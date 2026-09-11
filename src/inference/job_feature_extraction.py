"""
Job di feature extraction InSAR: calcolo delle mappe di spostamento verticale/est-ovest,
delle serie temporali e dei relativi prodotti derivati a partire dagli interferogrammi
pre-processati.

Versione rifattorizzata: vedi CHANGELOG in fondo al file per l'elenco delle modifiche
rispetto alla versione originale.
"""

import os
import gc
import re
import sys
import json
import shutil
import logging
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
from osgeo import gdal

import digitalhub as dh
from core.skd_handler import upload_artifact

gdal.UseExceptions()

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configura un logger unico (console) invece di alternare print()/logging.

    Stessa funzione usata in job_insar_preprocessing.py, per avere un formato di log
    coerente in tutta la pipeline.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(threadName)s] %(levelname)-5s %(name)s.%(funcName)s - %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    ))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# Parametri di elaborazione centralizzati (prima erano soglie "magiche" sparse
# nel codice: 0.3, 0.9, 0.4, 0.6, n_months=4, ...).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FeatureConfig:
    n_months: int = 4
    # soglia di coerenza media minima per tenere un'interferogramma nella serie storica
    min_mean_coherence: float = 0.3
    # soglia di coerenza per selezionare i punti "molto coerenti" usati per il calcolo dell'offset
    high_coherence_threshold: float = 0.9
    # soglia di coerenza media (sulle mappe cumulate) sotto la quale si maschera con NaN
    cumulative_coherence_threshold: float = 0.4
    # soglia di coerenza per-banda sotto la quale si maschera con NaN le mappe della serie storica
    band_coherence_threshold: float = 0.6
    default_output_artifact_name: str = "03_features"


CONFIG = FeatureConfig()


class FeatureExtractionError(Exception):
    """Errore nel calcolo delle feature InSAR (dati mancanti, incoerenti o corrotti)."""


def _load_json_argument(raw_arg: str) -> dict:
    """
    Effettua il parsing del parametro JSON passato da linea di comando.

    Prova prima un parsing diretto (JSON valido con virgolette doppie); solo se
    fallisce ricorre alla sostituzione ' -> " usata dal chiamante legacy, loggando
    un warning perché questa sostituzione può corrompere valori contenenti apostrofi.
    """
    try:
        return json.loads(raw_arg)
    except json.JSONDecodeError:
        logger.warning(
            "Argomento JSON non valido con virgolette standard: applico fallback "
            "sostituendo apici singoli con doppi (rischio di corruzione se un valore "
            "contiene un apostrofo)."
        )
        return json.loads(raw_arg.replace("'", "\""))


def _require(json_input: dict, key: str) -> str:
    value = json_input.get(key)
    if not value:
        raise ValueError(f"Parametro obbligatorio mancante o vuoto nell'input JSON: '{key}'.")
    return value


def get_folders_last_months(base_path: str, n_months: int) -> list[str]:
    """
    Seleziona le cartelle degli ultimi n mesi rispetto alla cartella
    con la data più recente, basandosi sul formato YYYYMMDD_YYYYMMDD.

    Args:
        base_path: Percorso della directory contenente le cartelle
        n_months: Numero di mesi da considerare

    Returns:
        Lista ordinata delle cartelle degli ultimi n mesi
    """
    pattern = re.compile(r'^\d{8}_\d{8}$')
    base = Path(base_path)

    valid_folders: list[tuple[str, datetime, datetime]] = []
    for folder in base.iterdir():
        if not folder.is_dir():
            continue
        if not pattern.match(folder.name):
            continue

        parts = folder.name.split('_')
        try:
            date_start = datetime.strptime(parts[0], '%Y%m%d')
            date_end = datetime.strptime(parts[1], '%Y%m%d')
        except ValueError:
            continue

        valid_folders.append((folder.name, date_start, date_end))

    if not valid_folders:
        logger.warning("Nessuna cartella nel formato YYYYMMDD_YYYYMMDD trovata in %s.", base_path)
        return []

    most_recent_date = max(date_end for _, _, date_end in valid_folders)

    month = most_recent_date.month - n_months
    year = most_recent_date.year
    if month <= 0:
        month += 12
        year -= 1
    cutoff_date = most_recent_date.replace(year=year, month=month)

    logger.info("Data più recente trovata: %s", most_recent_date.strftime('%d/%m/%Y'))
    logger.info("Cutoff (%d mesi prima): %s", n_months, cutoff_date.strftime('%d/%m/%Y'))

    selected = [name for name, _, date_end in valid_folders if date_end >= cutoff_date]
    return sorted(selected)


def _safe_trig_divide(numerator: np.ndarray, angle_deg: np.ndarray, func) -> np.ndarray:
    """
    Calcola numerator / func(deg2rad(angle_deg)) (func = np.cos o np.sin),
    restituendo NaN (invece di +/-inf silenziosi) dove il denominatore è ~0.
    """
    denom = func(np.deg2rad(angle_deg))
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.divide(numerator, denom)
    result[np.isclose(denom, 0.0)] = np.nan
    return result


def _mask_by_coherence(data: np.ndarray, coherence: np.ndarray, threshold: float) -> np.ndarray:
    """Restituisce una copia di 'data' con NaN dove 'coherence' < threshold (banda per banda se 3D)."""
    masked = np.copy(data)
    if masked.ndim == 3:
        for i in range(masked.shape[2]):
            masked[:, :, i][coherence[:, :, i] < threshold] = np.nan
    else:
        masked[coherence < threshold] = np.nan
    return masked


def _write_geotiff(
    path: str,
    array: np.ndarray,
    geo_transform,
    projection: str,
    band_names: Optional[Sequence[str]] = None,
) -> None:
    """
    Scrive un array 2D (singola banda) o 3D (righe, colonne, bande) come GeoTIFF,
    centralizzando il pattern ripetuto ~15 volte nella versione originale.
    """
    if array.ndim == 2:
        array = array[:, :, np.newaxis]
    height, width, n_bands = array.shape

    if band_names is not None and len(band_names) != n_bands:
        raise ValueError(
            f"Numero di band_names ({len(band_names)}) diverso dal numero di bande ({n_bands}) per {path}."
        )

    os.makedirs(os.path.dirname(path), exist_ok=True)
    target_ds = gdal.GetDriverByName("GTiff").Create(
        path, width, height, n_bands, gdal.GDT_Float32,
        options=["COMPRESS=DEFLATE", "BIGTIFF=YES"],
    )
    try:
        target_ds.SetGeoTransform(geo_transform)
        target_ds.SetProjection(projection)
        for i in range(n_bands):
            band = target_ds.GetRasterBand(i + 1)
            if band_names is not None:
                band.SetDescription(band_names[i])
            band.WriteArray(array[:, :, i])
    finally:
        target_ds = None
        gc.collect()


def _find_mosaic_file(folder: str, orientation_folder: str, folder_label: str, orientation: str) -> str:
    """Trova l'unico file '*mosaic.tif' in orientation_folder, con un errore chiaro se manca."""
    if not os.path.isdir(orientation_folder):
        raise FeatureExtractionError(
            f"Cartella '{orientation}' mancante per '{folder_label}' (attesa in {orientation_folder})."
        )
    candidates = [fi for fi in os.listdir(orientation_folder) if "mosaic.tif" in fi]
    if not candidates:
        raise FeatureExtractionError(
            f"Nessun file '*mosaic.tif' trovato in {orientation_folder} (coppia '{folder_label}', {orientation})."
        )
    if len(candidates) > 1:
        logger.warning(
            "Trovati più file mosaic.tif in %s: uso '%s'.", orientation_folder, sorted(candidates)[0],
        )
    return sorted(candidates)[0]


def v_ew_displ(path: str, list_filenames: Sequence[str]):
    """
    Calcola le mappe di spostamento verticale ed est-ovest, e le relative serie temporali,
    a partire dai mosaici di spostamento/coerenza ascending e descending.

    Parameters
    ----------
    path : str
        Cartella contenente le sottocartelle (una per coppia di immagini) da processare.
    list_filenames : Sequence[str]
        Elenco delle sottocartelle da processare.

    Returns
    -------
    v_displ_time_series, ew_displ_time_series, coh_time_series, asc_time_series,
    desc_time_series, coh_asc_time_series, coh_desc_time_series : np.ndarray (float32)
        Serie temporali di spostamento verticale, est-ovest, coerenza media, spostamento
        totale ascending/descending e relative coerenze.
    proj : str
        Proiezione dei file di output.
    geoT : tuple
        Geo-trasformazione dei file di output.
    inc_angle_asc_time_series, inc_angle_desc_time_series : np.ndarray (float32)
        Serie temporali degli angoli di incidenza ascending/descending.

    Raises
    ------
    FeatureExtractionError
        Se manca il file mosaic.tif atteso per una coppia, o se un raster non ha
        almeno 3 bande (spostamento, coerenza, angolo di incidenza).
    """
    n_time = len(list_filenames)
    v_displ_time_series = ew_displ_time_series = coh_time_series = None
    asc_time_series = desc_time_series = coh_asc_time_series = coh_desc_time_series = None
    inc_angle_asc_time_series = inc_angle_desc_time_series = None
    proj = geoT = None

    for i, f in enumerate(list_filenames):
        file_path = os.path.join(path, f)
        asc_file_path = os.path.join(file_path, "ascending")
        desc_file_path = os.path.join(file_path, "descending")

        filename_ascending = _find_mosaic_file(path, asc_file_path, f, "ascending")
        filename_descending = _find_mosaic_file(path, desc_file_path, f, "descending")

        asc_full_path = os.path.join(asc_file_path, filename_ascending)
        desc_full_path = os.path.join(desc_file_path, filename_descending)

        logger.info("Lettura: %s", asc_full_path)
        ds = gdal.Open(asc_full_path, gdal.GA_ReadOnly)
        if ds.RasterCount < 3:
            raise FeatureExtractionError(
                f"{asc_full_path} ha solo {ds.RasterCount} bande, ne sono attese almeno 3 "
                "(spostamento, coerenza, angolo di incidenza)."
            )
        if i == 0:
            shape = [ds.RasterYSize, ds.RasterXSize, n_time]
            v_displ_time_series = np.zeros(shape, dtype=np.float32)
            ew_displ_time_series = np.zeros(shape, dtype=np.float32)
            coh_time_series = np.zeros(shape, dtype=np.float32)
            asc_time_series = np.zeros(shape, dtype=np.float32)
            desc_time_series = np.zeros(shape, dtype=np.float32)
            coh_asc_time_series = np.zeros(shape, dtype=np.float32)
            coh_desc_time_series = np.zeros(shape, dtype=np.float32)
            inc_angle_asc_time_series = np.zeros(shape, dtype=np.float32)
            inc_angle_desc_time_series = np.zeros(shape, dtype=np.float32)
            proj = ds.GetProjection()
            geoT = ds.GetGeoTransform()

        asc = ds.GetRasterBand(1).ReadAsArray()
        coh_asc = ds.GetRasterBand(2).ReadAsArray()
        inc_angle_asc = ds.GetRasterBand(3).ReadAsArray()
        ds = None

        logger.info("Lettura: %s", desc_full_path)
        ds = gdal.Open(desc_full_path, gdal.GA_ReadOnly)
        if ds.RasterCount < 3:
            raise FeatureExtractionError(
                f"{desc_full_path} ha solo {ds.RasterCount} bande, ne sono attese almeno 3 "
                "(spostamento, coerenza, angolo di incidenza)."
            )
        desc = ds.GetRasterBand(1).ReadAsArray()
        coh_desc = ds.GetRasterBand(2).ReadAsArray()
        inc_angle_desc = ds.GetRasterBand(3).ReadAsArray()
        ds = None

        # calcolo dello spostamento verticale ed est-ovest
        v_asc = _safe_trig_divide(asc, inc_angle_asc, np.cos)
        ew_asc = _safe_trig_divide(asc, inc_angle_asc, np.sin)
        v_desc = _safe_trig_divide(desc, inc_angle_desc, np.cos)
        ew_desc = _safe_trig_divide(desc, inc_angle_desc, np.sin)

        v_displ_time_series[:, :, i] = -np.nanmean(np.array([v_asc, v_desc]), axis=0)
        ew_displ_time_series[:, :, i] = (ew_asc - ew_desc) / 2
        coh_time_series[:, :, i] = np.mean(np.array([coh_asc, coh_desc]), axis=0)
        asc_time_series[:, :, i] = asc
        desc_time_series[:, :, i] = desc
        coh_asc_time_series[:, :, i] = coh_asc
        coh_desc_time_series[:, :, i] = coh_desc
        inc_angle_asc_time_series[:, :, i] = inc_angle_asc
        inc_angle_desc_time_series[:, :, i] = inc_angle_desc

    return (
        v_displ_time_series, ew_displ_time_series, coh_time_series,
        asc_time_series, desc_time_series, coh_asc_time_series, coh_desc_time_series,
        proj, geoT, inc_angle_asc_time_series, inc_angle_desc_time_series,
    )


def _compute_c_coefficient(inc_angle: np.ndarray, theta_list: Sequence[float],
                            slope_map: np.ndarray, aspect_map: np.ndarray, label: str) -> np.ndarray:
    """
    Calcola il coefficiente di proiezione 'c' per ogni step temporale, dato l'angolo di
    incidenza, il platform heading (theta) e le mappe di pendenza/esposizione.

    NOTA correzione rispetto all'originale: l'ultimo termine della formula era
    'sin(deg2rad(slope_map) * H)' invece di 'sin(deg2rad(slope_map)) * H' (il fattore H
    veniva moltiplicato PRIMA di applicare il seno, invece che dopo, rompendo la struttura
    della formula rispetto agli altri due termini che seguono lo stesso pattern
    "funzione trigonometrica dell'angolo, poi moltiplicata per la componente"). Da
    verificare con chi ha definito la formula originale se il fix è corretto per il
    caso d'uso specifico.
    """
    c_time_series = np.zeros(inc_angle.shape, dtype=np.float32)
    for i_c in range(c_time_series.shape[2]):
        logger.info("Platform heading angle %s per lo step temporale %d: %s", label, i_c, theta_list[i_c])
        N = -np.sin(np.deg2rad(inc_angle[:, :, i_c])) * np.cos(np.deg2rad(theta_list[i_c])) - (3 * np.pi / 2)
        E = -np.sin(np.deg2rad(inc_angle[:, :, i_c])) * np.sin(np.deg2rad(theta_list[i_c])) - (3 * np.pi / 2)
        H = np.cos(np.deg2rad(inc_angle[:, :, i_c]))
        c = (
            (np.cos(np.deg2rad(slope_map)) * np.sin(np.deg2rad(aspect_map - 90)) * N)
            + ((-np.cos(np.deg2rad(slope_map)) * np.sin(np.deg2rad(aspect_map - 90))) * E)
            + (np.sin(np.deg2rad(slope_map)) * H)
        )
        c_time_series[:, :, i_c] = c
    return c_time_series


def run(json_input: dict) -> None:
    maindir = "."
    data_folder = "data"
    preprocessed_folder = "02_pre_processed"
    output_folder = "output"
    input_folder = "input"

    logger.info("Lettura parametri di input")
    preprocessed_artifact = _require(json_input, "preprocessedArtifactName")
    map_artifact = _require(json_input, "mapArtifactName")
    output_artifact_name = json_input.get("outputArtifactName") or CONFIG.default_output_artifact_name

    if "PROJECT_NAME" not in os.environ:
        raise EnvironmentError("Variabile d'ambiente 'PROJECT_NAME' non impostata.")
    project_name = os.environ["PROJECT_NAME"]

    data_path = os.path.join(maindir, data_folder, input_folder)
    preprocessed_path = os.path.join(data_path, preprocessed_folder)
    previous_feature_download_folder = os.path.join(data_path, "previous_feature_artifact")
    result_path = os.path.join(maindir, data_folder, output_folder)
    input_map_folder = os.path.join(data_path, "maps")

    logger.info("Creazione delle cartelle di lavoro")
    for folder in (data_path, result_path, input_map_folder, preprocessed_path, previous_feature_download_folder):
        os.makedirs(folder, exist_ok=True)

    logger.info(
        "Parametri in input: preprocessed_artifact=%s, output_artifact_name=%s, mapArtifact=%s",
        preprocessed_artifact, output_artifact_name, map_artifact,
    )

    project = dh.get_or_create_project(project_name)
    logger.info("Scaricamento degli artefatti per il progetto: %s", project_name)

    logger.info("Scaricamento artifact: %s in %s", preprocessed_artifact, preprocessed_path)
    preprocessed_data = project.get_artifact(preprocessed_artifact)
    input_path = preprocessed_data.download(preprocessed_path, overwrite=True)

    logger.info("Scaricamento map artifact: %s in %s", map_artifact, input_map_folder)
    map_data = project.get_artifact(map_artifact)
    input_map_folder = map_data.download(input_map_folder, overwrite=True)
    trentino_slope_map_path = os.path.join(input_map_folder, "trentino_slope_map.tif")
    trentino_aspect_map_path = os.path.join(input_map_folder, "trentino_aspect_map.tif")
    legend_path = os.path.join(input_map_folder, "legend.qml")
    input_json_path = os.path.join(input_path, "sensor_angles.json")

    # Path dell'artifact "precedente" vuoto finché non viene effettivamente trovato e
    # scaricato: usato più avanti per decidere se creare un nuovo artifact o aggiornarlo.
    previous_feature_artifact_path = ""
    if output_artifact_name in project.list_artifacts():
        logger.info(
            "Scaricamento del precedente artifact '%s' in %s",
            output_artifact_name, previous_feature_download_folder,
        )
        previous_feature_artifact = project.get_artifact(output_artifact_name)
        previous_feature_artifact_path = previous_feature_artifact.download(
            previous_feature_download_folder, overwrite=True
        )

    logger.info("Dati scaricati con successo.")
    logger.info("preprocessed_path = %s", preprocessed_path)
    logger.info("trentino_slope_map_path = %s", trentino_slope_map_path)
    logger.info("trentino_aspect_map_path = %s", trentino_aspect_map_path)
    logger.info("legend_path = %s", legend_path)

    if not os.path.isfile(input_json_path):
        raise FeatureExtractionError(
            f"File degli angoli sensore non trovato: {input_json_path}. "
            "Verificare che l'artifact di pre-processing sia completo."
        )
    with open(input_json_path, "r") as f:
        theta_dict = json.load(f)
    if "ascending" not in theta_dict or "descending" not in theta_dict:
        raise FeatureExtractionError(f"{input_json_path} non contiene le chiavi 'ascending'/'descending' attese.")
    list_theta_ascending = theta_dict["ascending"]
    list_theta_descending = theta_dict["descending"]

    logger.info("Calcolo degli spostamenti verticali ed est-ovest...")
    list_filenames = get_folders_last_months(input_path, n_months=CONFIG.n_months)
    if not list_filenames:
        raise FeatureExtractionError(
            f"Nessuna cartella nel formato YYYYMMDD_YYYYMMDD trovata in {input_path} "
            f"negli ultimi {CONFIG.n_months} mesi."
        )
    if len(list_theta_ascending) < len(list_filenames) or len(list_theta_descending) < len(list_filenames):
        raise FeatureExtractionError(
            f"sensor_angles.json contiene {len(list_theta_ascending)} angoli ascending / "
            f"{len(list_theta_descending)} descending, ma sono state selezionate "
            f"{len(list_filenames)} coppie di immagini: gli angoli non sono sufficienti "
            "per garantire un allineamento corretto con le mappe."
        )
    list_theta_ascending = list_theta_ascending[-len(list_filenames):]
    list_theta_descending = list_theta_descending[-len(list_filenames):]
    starting_date = list_filenames[0].split("_")[0]
    ending_date = list_filenames[-1].split("_")[1]

    logger.info("Trovate %d sottocartelle in %s", len(list_filenames), input_path)

    (
        v_displ_maps, ew_displ_maps, coh_maps, asc, desc, coh_asc, coh_desc,
        proj, geoT, inc_angle_asc, inc_angle_desc,
    ) = v_ew_displ(input_path, list_filenames)

    # Tiene solo gli interferogrammi con coerenza media superiore alla soglia
    mean_coh = np.average(coh_maps, axis=(0, 1))
    n_time = ew_displ_maps.shape[2]
    offset_ew_displ_maps = np.zeros(n_time, dtype=np.float32)
    offset_v_displ_maps = np.zeros(n_time, dtype=np.float32)
    offset_asc = np.zeros(n_time, dtype=np.float32)
    offset_desc = np.zeros(n_time, dtype=np.float32)
    for i in range(n_time):
        most_coh_points = coh_maps[:, :, i] > CONFIG.high_coherence_threshold
        offset_ew_displ_maps[i] = np.nanmean(ew_displ_maps[:, :, i][most_coh_points])
        offset_v_displ_maps[i] = np.nanmean(v_displ_maps[:, :, i][most_coh_points])
        offset_asc[i] = np.nanmean(asc[:, :, i][most_coh_points])
        offset_desc[i] = np.nanmean(desc[:, :, i][most_coh_points])

    ew_displ_maps -= offset_ew_displ_maps
    v_displ_maps -= offset_v_displ_maps
    asc -= offset_asc
    desc -= offset_desc

    # Bug corretto: in origine np.logical_and() veniva chiamato con un solo argomento,
    # cosa che solleva TypeError (è una ufunc binaria). La condizione da applicare è
    # semplicemente il confronto con la soglia di coerenza media.
    keep_img_mask = mean_coh >= CONFIG.min_mean_coherence

    if np.sum(keep_img_mask) == 0:
        message = (
            f"Nessun interferogramma con coerenza media superiore a {CONFIG.min_mean_coherence}. "
            "Salto la generazione dei file TIFF per insufficienza di dati."
        )
        warnings.warn(message)
        logger.warning(message)
        logger.info("Elaborazione completata (nessun output generato).")
        return

    keep_list_filenames = [n for n, keep in zip(list_filenames, keep_img_mask) if keep]
    keep_list_theta_ascending = [n for n, keep in zip(list_theta_ascending, keep_img_mask) if keep]
    keep_list_theta_descending = [n for n, keep in zip(list_theta_descending, keep_img_mask) if keep]

    v_displ_maps = v_displ_maps[:, :, keep_img_mask]
    ew_displ_maps = ew_displ_maps[:, :, keep_img_mask]
    coh_maps = coh_maps[:, :, keep_img_mask]
    asc = asc[:, :, keep_img_mask]
    desc = desc[:, :, keep_img_mask]
    coh_asc = coh_asc[:, :, keep_img_mask]
    coh_desc = coh_desc[:, :, keep_img_mask]
    inc_angle_asc = inc_angle_asc[:, :, keep_img_mask]
    inc_angle_desc = inc_angle_desc[:, :, keep_img_mask]

    avg_coh_map = np.average(coh_maps, axis=-1)

    cum_sum_ew_displ_map = np.sum(ew_displ_maps, axis=-1)
    masked_cum_sum_ew_displ_map = _mask_by_coherence(cum_sum_ew_displ_map, avg_coh_map, CONFIG.cumulative_coherence_threshold)

    cum_sum_v_displ_map = np.sum(v_displ_maps, axis=-1)
    masked_cum_sum_v_displ_map = _mask_by_coherence(cum_sum_v_displ_map, avg_coh_map, CONFIG.cumulative_coherence_threshold)

    cum_sum_asc = np.sum(asc, axis=-1)
    cum_sum_desc = np.sum(desc, axis=-1)
    avg_coh_asc = np.average(coh_asc, axis=-1)
    avg_coh_desc = np.average(coh_desc, axis=-1)
    masked_cum_sum_asc = _mask_by_coherence(cum_sum_asc, avg_coh_asc, CONFIG.cumulative_coherence_threshold)
    masked_cum_sum_desc = _mask_by_coherence(cum_sum_desc, avg_coh_desc, CONFIG.cumulative_coherence_threshold)

    mask_AOI = np.logical_or(
        np.logical_and(masked_cum_sum_asc > 0, masked_cum_sum_desc < 0),
        np.logical_and(masked_cum_sum_asc < 0, masked_cum_sum_desc > 0),
    )
    cum_sum_ew_displ_map_AOI = np.copy(cum_sum_ew_displ_map)
    cum_sum_ew_displ_map_AOI[np.logical_not(mask_AOI)] = np.nan
    cum_sum_v_displ_map_AOI = np.copy(cum_sum_v_displ_map)
    cum_sum_v_displ_map_AOI[np.logical_not(mask_AOI)] = np.nan

    ds_trans = gdal.Open(trentino_slope_map_path, gdal.GA_ReadOnly)
    slope_map = ds_trans.GetRasterBand(1).ReadAsArray()
    ds_trans = None
    ds_trans = gdal.Open(trentino_aspect_map_path, gdal.GA_ReadOnly)
    aspect_map = ds_trans.GetRasterBand(1).ReadAsArray()
    ds_trans = None

    c_ascending_time_series = _compute_c_coefficient(
        inc_angle_asc, keep_list_theta_ascending, slope_map, aspect_map, "ascending"
    )
    c_descending_time_series = _compute_c_coefficient(
        inc_angle_desc, keep_list_theta_descending, slope_map, aspect_map, "descending"
    )

    out_dir = os.path.join(result_path, f"{starting_date}_{ending_date}")
    os.makedirs(out_dir, exist_ok=True)

    logger.info("Scrittura dei prodotti raster in %s", out_dir)

    masked_v_displ_maps = _mask_by_coherence(v_displ_maps, coh_maps, CONFIG.band_coherence_threshold)
    _write_geotiff(os.path.join(out_dir, "serie_temporale_scostamento_verticale.tif"),
                    masked_v_displ_maps, geoT, proj, keep_list_filenames)
    _write_geotiff(os.path.join(out_dir, "somma_cumulata_spostamento_verticale.tif"),
                    masked_cum_sum_v_displ_map, geoT, proj)

    masked_ew_displ_maps = _mask_by_coherence(ew_displ_maps, coh_maps, CONFIG.band_coherence_threshold)
    _write_geotiff(os.path.join(out_dir, "serie_temporale_scostamento_orizzontale.tif"),
                    masked_ew_displ_maps, geoT, proj, keep_list_filenames)
    _write_geotiff(os.path.join(out_dir, "somma_cumulata_spostamento_orizzontale.tif"),
                    masked_cum_sum_ew_displ_map, geoT, proj)

    masked_asc = _mask_by_coherence(asc, coh_asc, CONFIG.band_coherence_threshold)
    _write_geotiff(os.path.join(out_dir, "serie_temporale_scostamento_totale_ascendente.tif"),
                    masked_asc, geoT, proj, keep_list_filenames)
    _write_geotiff(os.path.join(out_dir, "somma_cumulata_scostamento_totale_ascendente.tif"),
                    masked_cum_sum_asc, geoT, proj)

    masked_desc = _mask_by_coherence(desc, coh_desc, CONFIG.band_coherence_threshold)
    _write_geotiff(os.path.join(out_dir, "serie_temporale_scostamento_totale_discendente.tif"),
                    masked_desc, geoT, proj, keep_list_filenames)
    _write_geotiff(os.path.join(out_dir, "somma_cumulata_scostamento_totale_discendente.tif"),
                    masked_cum_sum_desc, geoT, proj)

    _write_geotiff(os.path.join(out_dir, "mappa_coerenza_media.tif"), avg_coh_map, geoT, proj)
    _write_geotiff(os.path.join(out_dir, "serie_temporale_mappe_coerenza.tif"),
                    coh_maps, geoT, proj, keep_list_filenames)

    _write_geotiff(os.path.join(out_dir, "mappa_coerenza_media_ascendente.tif"), avg_coh_asc, geoT, proj)
    _write_geotiff(os.path.join(out_dir, "serie_temporale_mappe_coerenza_ascendente.tif"),
                    coh_asc, geoT, proj, keep_list_filenames)

    _write_geotiff(os.path.join(out_dir, "mappa_coerenza_media_discendente.tif"), avg_coh_desc, geoT, proj)
    _write_geotiff(os.path.join(out_dir, "serie_temporale_mappe_coerenza_discendente.tif"),
                    coh_desc, geoT, proj, keep_list_filenames)

    _write_geotiff(os.path.join(out_dir, "somma_cumulata_scostamento_orizzontale_AOI.tif"),
                    cum_sum_ew_displ_map_AOI, geoT, proj)
    _write_geotiff(os.path.join(out_dir, "somma_cumulata_scostamento_verticale_AOI.tif"),
                    cum_sum_v_displ_map_AOI, geoT, proj)

    _write_geotiff(os.path.join(out_dir, "serie_temporale_coefficiente_c_ascendente.tif"),
                    c_ascending_time_series, geoT, proj, keep_list_filenames)
    _write_geotiff(os.path.join(out_dir, "serie_temporale_coefficiente_c_discendente.tif"),
                    c_descending_time_series, geoT, proj, keep_list_filenames)

    shutil.copy(legend_path, os.path.join(out_dir, "legend.qml"))

    if not previous_feature_artifact_path:
        upload_artifact(artifact_name=output_artifact_name, project_name=project_name, src_path=result_path)
    else:
        logger.info(
            "Artifact '%s' già esistente nel progetto '%s'. Aggiornamento con i nuovi dati.",
            output_artifact_name, project_name,
        )
        shutil.copytree(previous_feature_artifact_path, result_path, dirs_exist_ok=True)
        upload_artifact(artifact_name=output_artifact_name, project_name=project_name, src_path=result_path)

    logger.info("Elaborazione completata.")


# python job_feature_extraction.py "{\"preprocessedArtifactName\": \"02_pre_processed\", \"outputArtifactName\": \"03_features\", \"mapArtifactName\": \"Map\"}"
if __name__ == "__main__":
    _configure_logging()
    logger.info("Lettura parametri di input")
    if len(sys.argv) < 2:
        logger.error("Uso: python job_feature_extraction.py '<json_input>'")
        sys.exit(1)
    try:
        parsed_input = _load_json_argument(sys.argv[1])
        run(parsed_input)
    except Exception:
        logger.exception("Il job è terminato con un errore non gestito.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CHANGELOG rispetto alla versione originale
# ---------------------------------------------------------------------------
# Bug corretti:
#  - np.logical_and(mean_coh>=th) chiamato con un solo argomento (TypeError certo,
#    è una ufunc binaria): sostituito con keep_img_mask = mean_coh >= th.
#  - Formula del coefficiente 'c': l'ultimo termine era sin(deg2rad(slope_map) * H)
#    invece di sin(deg2rad(slope_map)) * H (fattore H moltiplicato dentro il seno
#    invece che dopo, non coerente con la struttura degli altri due termini).
#    Isolata in _compute_c_coefficient() con un commento esplicito: da validare
#    con chi ha definito la formula originale.
#  - Flag "esiste un artifact di feature precedente": nella versione originale si
#    controllava len(previous_feature_artifact_path) == 0, ma quella variabile era
#    sempre una path string non vuota (bug: era sempre False). Ora
#    previous_feature_artifact_path parte vuoto e viene valorizzato solo se
#    l'artifact esiste davvero nel progetto ed è stato scaricato.
#  - output_artifact_name veniva letto dall'input JSON ma non veniva mai usato
#    (l'artifact era sempre caricato con il nome hardcoded "03_features"). Ora
#    viene usato per l'upload/il controllo di esistenza, con default
#    "03_features" se non specificato.
#  - global output_path, unwrap_folder, trentino_boundary_path, geo_wkt: era
#    codice morto copiato da job_insar_preprocessing.py (nessuna di queste
#    variabili è usata in questo file). Rimosso.
#  - Validazioni aggiunte prima di indicizzare liste potenzialmente vuote/corte:
#    list_filenames vuoto, sensor_angles.json con meno angoli delle coppie
#    selezionate (evita disallineamenti silenziosi), file mosaic.tif mancante,
#    numero di bande insufficiente in un raster (_find_mosaic_file, FeatureExtractionError).
#  - Divisioni per coseno/seno dell'angolo di incidenza: ora _safe_trig_divide
#    restituisce NaN invece di +/-inf silenziosi quando il denominatore è ~0, e
#    v_displ_time_series usa nanmean invece di mean per non perdere l'intero
#    pixel quando solo un orientamento (asc/desc) ha un denominatore nullo.
#
# Sicurezza / robustezza:
#  - Parsing dell'argomento JSON da CLI: json.loads diretto con fallback esplicito
#    e loggato al replace ' -> ", invece del replace sistematico.
#  - Rimossi gli import inutilizzati (shapely.wkt.loads, geopandas).
#  - Parametri obbligatori dell'input JSON validati esplicitamente (_require)
#    invece di essere passati anche se None a project.get_artifact(...).
#
# Qualità del codice:
#  - Un solo sistema di logging centralizzato (_configure_logging, identico a
#    job_insar_preprocessing.py) invece di logging.basicConfig() a livello di
#    modulo e print()+logging duplicati ovunque.
#  - Soglie di coerenza centralizzate in FeatureConfig invece di valori
#    hardcoded sparsi nel codice (0.3, 0.9, 0.4, 0.6).
#  - _write_geotiff() centralizza il pattern di scrittura GeoTIFF ripetuto
#    ~15 volte nella versione originale (crea driver, imposta geotransform/
#    proiezione, scrive le bande, libera la memoria).
#  - _mask_by_coherence() centralizza il pattern di mascheramento con NaN
#    in base a una soglia di coerenza (per array 2D e 3D).
#  - os.makedirs(..., exist_ok=True) usato in modo consistente ovunque.
