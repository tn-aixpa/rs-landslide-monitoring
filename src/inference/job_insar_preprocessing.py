"""
Job di pre-processing InSAR (Sentinel-1): calcolo interferogrammi ascendenti/discendenti
e creazione dei mosaici di spostamento/coerenza.

Versione rifattorizzata: vedi CHANGELOG in fondo al file per l'elenco delle modifiche
rispetto alla versione originale.
"""

import os
import re
import sys
import json
import shutil
import zipfile
import logging
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
from osgeo import gdal
import snaphu
from snapista import Operator, Graph

import digitalhub as dh
from utils.skd_handler import upload_artifact

gdal.UseExceptions()

# XML da fonti esterne (zip scaricati da artifact store): usare un parser protetto
# da entity-expansion quando disponibile.
try:
    import defusedxml.ElementTree as ET
    _XML_PARSER_IS_SAFE = True
except ImportError:  # pragma: no cover - fallback se defusedxml non è installato
    import xml.etree.ElementTree as ET
    _XML_PARSER_IS_SAFE = False


logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configura un logger unico (console) invece di alternare print()/logging."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d [%(threadName)s] %(levelname)-5s %(name)s.%(funcName)s - %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    ))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if not _XML_PARSER_IS_SAFE:
        logger.warning(
            "defusedxml non installato: uso xml.etree.ElementTree per leggere i metadata "
            "dei prodotti Sentinel-1. Consigliato 'pip install defusedxml' per una maggiore "
            "sicurezza nel parsing di XML provenienti da fonti esterne."
        )


# ---------------------------------------------------------------------------
# Parametri di elaborazione: prima erano valori "magici" sparsi nel codice.
# Raccoglierli qui li rende visibili e configurabili in un unico punto.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProcessingConfig:
    dem_name: str = "SRTM 3Sec"
    first_burst_index: str = "1"
    last_burst_index: str = "9"
    coh_threshold: str = "0.15"
    coh_win_rg: str = "10"
    coh_win_az: str = "3"
    snaphu_init_method: str = "MCF"
    snaphu_stat_cost_mode: str = "DEFO"
    snaphu_tile_rows: str = "20"
    snaphu_tile_cols: str = "20"
    snaphu_nlooks: float = 23.8
    snaphu_tile_overlap: tuple = (200, 200)
    snaphu_min_region_size: int = 200
    pixel_spacing_m: str = "13.94028"
    pixel_spacing_deg: str = "1.2522766588905684E-4"
    map_projection_wkt: str = (
        "PROJCS[\"ETRS89 / UTM zone 32N\", GEOGCS[\"ETRS89\", "
        "DATUM[\"European Terrestrial Reference System 1989\", SPHEROID[\"GRS 1980\","
        "6378137.0, 298.257222101, AUTHORITY[\"EPSG\",\"7019\"]], "
        "TOWGS84[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], AUTHORITY[\"EPSG\",\"6258\"]], "
        "PRIMEM[\"Greenwich\", 0.0, AUTHORITY[\"EPSG\",\"8901\"]], "
        "UNIT[\"degree\", 0.017453292519943295], AXIS[\"Geodetic longitude\", EAST], "
        "AXIS[\"Geodetic latitude\", NORTH], AUTHORITY[\"EPSG\",\"4258\"]],"
        "PROJECTION[\"Transverse_Mercator\", AUTHORITY[\"EPSG\",\"9807\"]], "
        "PARAMETER[\"central_meridian\", 9.0], PARAMETER[\"latitude_of_origin\", 0.0], "
        "PARAMETER[\"scale_factor\", 0.9996], PARAMETER[\"false_easting\", 500000.0], "
        "PARAMETER[\"false_northing\", 0.0], UNIT[\"m\", 1.0], AXIS[\"Easting\", EAST], "
        "AXIS[\"Northing\", NORTH], AUTHORITY[\"EPSG\",\"25832\"]]"
    )
    cutline_layer: str = "ammprv_v"
    target_epsg: str = "EPSG:25832"
    subprocess_timeout_s: int = 1800


CONFIG = ProcessingConfig()

# Convenzione di naming standard dei prodotti Sentinel-1 (SAFE/zip):
# MMM_BB_TTTR_LFPP_YYYYMMDDTHHMMSS_YYYYMMDDTHHMMSS_OOOOOO_DDDDDD_CCCC.SAFE
# La data di acquisizione (prima occorrenza) si trova a partire dal carattere 17.
_S1_DATE_RE = re.compile(r"^(?P<mission>S1[AB])_.{2}_.{4}_.{4}_(?P<date>\d{8})T\d{6}_")

_MONTH_ABBR = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
    "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
    "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
}


class InterferometryError(Exception):
    """Errore nel calcolo dell'interferogramma per una specifica coppia di immagini."""


def extract_acquisition_date(filename: str) -> str:
    """
    Estrae la data di acquisizione (YYYYMMDD) da un nome file Sentinel-1 standard,
    validando il formato invece di affidarsi ciecamente a uno slicing per posizione fissa.
    """
    match = _S1_DATE_RE.match(os.path.basename(filename))
    if not match:
        raise ValueError(
            f"Il nome file '{filename}' non rispetta la convenzione di naming attesa "
            "per i prodotti Sentinel-1 (impossibile estrarre la data di acquisizione)."
        )
    return match.group("date")


def snap_date_label(date_yyyymmdd: str) -> str:
    """Converte 'YYYYMMDD' nel formato usato da SNAP per i nomi banda, es. '12Mar2023'."""
    year, month, day = date_yyyymmdd[:4], date_yyyymmdd[4:6], date_yyyymmdd[6:8]
    if month not in _MONTH_ABBR:
        raise ValueError(f"Mese non valido '{month}' nella data '{date_yyyymmdd}'.")
    return f"{day}{_MONTH_ABBR[month]}{year}"


def _read_platform_heading(zip_path: str, subswath: str) -> float:
    """
    Legge il platform heading angle dai metadata di annotazione VV del subswath
    richiesto, all'interno dell'archivio zip del prodotto Sentinel-1.

    Solleva InterferometryError se nessuna annotazione corrispondente viene trovata,
    invece di restituire silenziosamente 0.0 come nella versione precedente.
    """
    with zipfile.ZipFile(zip_path, "r") as archive:
        for name in archive.namelist():
            is_annotation = (
                "annotation" in name
                and "calibration" not in name
                and "rfi" not in name
                and f"-{subswath.lower()}-" in name.lower()
                and "vv" in name.lower()
            )
            if not is_annotation:
                continue
            logger.info("Lettura platform heading da: %s", name)
            with archive.open(name) as metadata_file:
                tree = ET.parse(metadata_file)
            root = tree.getroot()
            general_annotation = root.find("generalAnnotation")
            product_info = general_annotation.find("productInformation") if general_annotation is not None else None
            heading_node = product_info.find("platformHeading") if product_info is not None else None
            if heading_node is None or heading_node.text is None:
                continue
            return float(heading_node.text)

    raise InterferometryError(
        f"Impossibile trovare il platform heading per il subswath {subswath} in {zip_path}."
    )


def _reset_directory(path: str) -> None:
    """Svuota (o crea) una directory in modo idempotente."""
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def _run_raster_merge(inputs: Sequence[str], output_tif: str) -> None:
    """
    Esegue lo script esterno di merge raster senza passare per una shell,
    evitando l'injection di comandi tramite path costruiti da nomi file esterni.
    """
    script_path = os.path.join(os.path.dirname(__file__), "..", "core", "raster_utils.py")
    cmd = [
        sys.executable, script_path,
        "-o", output_tif,
        "-n", "0.0",
        "-ot", "Float32",
        "-of", "GTiff",
        *inputs,
    ]
    subprocess.run(cmd, check=True, timeout=CONFIG.subprocess_timeout_s)


def interferometry(
    input_path: str,
    filename1: str,
    filename2: str,
    output_path: str,
    unwrap_folder: str,
    subswath: str = "IW1",
    nproc: int = 4,
) -> Optional[float]:
    """
    Esegue l'interferometria tra due immagini Sentinel-1 per un dato subswath.

    Parameters
    ----------
    input_path : str
        Cartella contenente i file di input.
    filename1, filename2 : str
        Nomi dei due prodotti Sentinel-1 (zip) da processare.
    output_path : str
        Cartella base dove salvare i risultati (verrà creata una sottocartella per il subswath).
    unwrap_folder : str
        Cartella di lavoro temporanea per l'unwrapping di fase (dedicata a questa chiamata:
        il chiamante deve passare una cartella specifica per evitare che due subswath in
        elaborazione ravvicinata si sovrascrivano a vicenda).
    subswath : str, optional
        Subswath da processare (default "IW1").
    nproc : int, optional
        Numero di processi da usare per lo unwrapping (default 4).

    Returns
    -------
    Optional[float]
        Il platform heading angle (dalle metadata del primo prodotto) se il calcolo
        ha successo, altrimenti None (l'errore viene loggato e la cartella di output
        parziale viene ripulita).
    """
    output_path = os.path.join(output_path, subswath)
    os.makedirs(output_path, exist_ok=True)
    _reset_directory(unwrap_folder)

    file1 = os.path.join(input_path, filename1)
    file2 = os.path.join(input_path, filename2)

    try:
        date1 = extract_acquisition_date(filename1)
        date2 = extract_acquisition_date(filename2)
        data1 = snap_date_label(date1)
        data2 = snap_date_label(date2)
        theta = _read_platform_heading(file1, subswath)
    except (ValueError, InterferometryError, zipfile.BadZipFile) as exc:
        logger.error("Impossibile preparare l'interferometria per %s / %s: %s", filename1, filename2, exc)
        return None

    logger.info("Lettura: %s, %s", file1, file2)
    g1 = Graph()
    g1.add_node(Operator("Read", formatName="SENTINEL-1", file=file1), node_id="read1")
    g1.add_node(Operator("Read", formatName="SENTINEL-1", file=file2), node_id="read2")

    # TOPS Split
    logger.info("Coregistrazione")
    tops_split1 = Operator("TOPSAR-Split")
    tops_split1.subswath = subswath
    tops_split1.selectedPolarisations = "VV"
    tops_split1.firstBurstIndex = CONFIG.first_burst_index
    tops_split1.lastBurstIndex = CONFIG.last_burst_index

    tops_split2 = Operator("TOPSAR-Split")
    tops_split2.subswath = subswath
    tops_split2.selectedPolarisations = "VV"
    tops_split2.firstBurstIndex = CONFIG.first_burst_index
    tops_split2.lastBurstIndex = CONFIG.last_burst_index

    g1.add_node(tops_split1, node_id="TOPS-SPLIT1", source="read1")
    g1.add_node(tops_split2, node_id="TOPS-SPLIT2", source="read2")

    # Apply orbit: due istanze separate, una per branch, per evitare che lo stesso
    # oggetto Operator venga condiviso (e potenzialmente confuso) tra due nodi del grafo.
    file1orbit = filename1[:-9] + "_split_Orb"
    file2orbit = filename2[:-9] + "_split_Orb"
    orbit_kwargs = dict(orbitType="Sentinel Precise (Auto Download)", continueOnFail="true")
    orbit1 = Operator("Apply-Orbit-File", **orbit_kwargs)
    orbit2 = Operator("Apply-Orbit-File", **orbit_kwargs)
    g1.add_node(orbit1, node_id="orbit1", source="TOPS-SPLIT1")
    g1.add_node(orbit2, node_id="orbit2", source="TOPS-SPLIT2")
    g1.add_node(Operator("Write", file=os.path.join(output_path, file1orbit + ".dim")),
                node_id="writer1orbit", source="orbit1")
    g1.add_node(Operator("Write", file=os.path.join(output_path, file2orbit + ".dim")),
                node_id="writer2orbit", source="orbit2")
    g1.run()

    # Back-Geocoding
    g2 = Graph()
    filelist = "{},{}".format(
        os.path.join(output_path, file1orbit + ".dim"),
        os.path.join(output_path, file2orbit + ".dim"),
    )
    reader = Operator("ProductSet-Reader", fileList=filelist)
    g2.add_node(reader, node_id="Back-Geocoding_Reader")
    geocoding = Operator(
        "Back-Geocoding",
        demName=CONFIG.dem_name,
        demResamplingMethod="BILINEAR_INTERPOLATION",
        resamplingType="BILINEAR_INTERPOLATION",
        maskOutAreaWithoutElevation="true",
    )
    g2.add_node(geocoding, node_id="Back-Geocoding", source="Back-Geocoding_Reader")
    esd = Operator("Enhanced-Spectral-Diversity")
    esd.cohThreshold = CONFIG.coh_threshold
    g2.add_node(esd, node_id="Enhanced-Spectral-Diversity", source="Back-Geocoding")

    # Interferogramma
    logger.info("Calcolo interferogramma")
    interferogram = Operator("Interferogram")
    interferogram.subtractFlatEarthPhase = "true"
    interferogram.includeCoherence = "true"
    interferogram.cohWinRg = CONFIG.coh_win_rg
    interferogram.cohWinAz = CONFIG.coh_win_az
    interferogram.subtractTopographicPhase = "true"
    interferogram.demName = CONFIG.dem_name

    g2.add_node(interferogram, node_id="interferogram", source="Back-Geocoding")
    deburst = Operator("TOPSAR-Deburst", selectedPolarisations="VV")
    g2.add_node(deburst, node_id="deburst", source="interferogram")
    phase_filtering = Operator("GoldsteinPhaseFiltering")
    g2.add_node(phase_filtering, node_id="PhaseFiltering", source="deburst")
    g2.add_node(Operator("Write", file=os.path.join(output_path, "interferogram_deburst.dim")),
                node_id="writerInterferogram1", source="PhaseFiltering")
    g2.run()

    g3 = Graph()
    g3.add_node(Operator("Read", file=os.path.join(output_path, "interferogram_deburst.dim")), node_id="read")
    export = Operator("SnaphuExport", targetFolder=unwrap_folder)
    export.initMethod = CONFIG.snaphu_init_method
    export.statCostMode = CONFIG.snaphu_stat_cost_mode
    export.numberOfTileRows = CONFIG.snaphu_tile_rows
    export.numberOfTileCols = CONFIG.snaphu_tile_cols
    g3.add_node(export, node_id="export", source="read")
    g3.run()

    # Phase unwrapping
    logger.info("Phase unwrapping")
    try:
        wrapped_subfolders = os.listdir(unwrap_folder)
    except FileNotFoundError:
        wrapped_subfolders = []
    if len(wrapped_subfolders) == 0:
        logger.error("SnaphuExport non ha prodotto alcuna cartella in %s.", unwrap_folder)
        shutil.rmtree(output_path, ignore_errors=True)
        return None
    if len(wrapped_subfolders) > 1:
        logger.warning(
            "Trovate %d cartelle in %s, mi aspettavo una sola. Uso '%s'.",
            len(wrapped_subfolders), unwrap_folder, wrapped_subfolders[0],
        )
    wrapped_folder = wrapped_subfolders[0]
    wrapped_folder_path = os.path.join(unwrap_folder, wrapped_folder)

    phasefile = cohfile = unw_hdr_filename = unw_filename = None
    for f in os.listdir(wrapped_folder_path):
        if f.endswith(".img") and "Phase" in f:
            phasefile = f[:36] + ".snaphu.img"
        elif f.endswith(".img") and "coh" in f:
            cohfile = f
        elif "UnwPhase" in f and "masked" not in f:
            unw_hdr_filename = f[:-4] + ".hdr"
            unw_filename = f[:-4] + ".img"

    phasefile_hdr = phasefile[:-4] + ".hdr" if phasefile else None
    missing = [
        name for name, value in [
            ("file di fase (Phase .img)", phasefile),
            ("file di coerenza (coh .img)", cohfile),
            ("file di unwrapped phase (UnwPhase)", unw_hdr_filename),
        ] if value is None
    ]
    if missing:
        logger.error(
            "File attesi non trovati in %s dopo SnaphuExport: %s",
            wrapped_folder_path, ", ".join(missing),
        )
        shutil.rmtree(output_path, ignore_errors=True)
        return None

    width = height = None
    with open(os.path.join(wrapped_folder_path, phasefile_hdr), "r") as f:
        for line in f:
            if "samples" in line:
                width = int(line.split("=")[-1].strip())
            if "lines" in line:
                height = int(line.split("=")[-1].strip())
    if width is None or height is None:
        logger.error("Impossibile leggere width/height da %s.", phasefile_hdr)
        shutil.rmtree(output_path, ignore_errors=True)
        return None

    with open(os.path.join(wrapped_folder_path, phasefile), "rb") as f:
        phase = np.fromfile(f, dtype=np.float32).reshape((height, width))
    igram = np.exp(1j * phase)

    with open(os.path.join(wrapped_folder_path, cohfile), "rb") as f:
        coh = np.fromfile(f, dtype=np.float32).reshape((height, width))

    try:
        image_unwrapped, _ = snaphu.unwrap(
            igram, coh,
            nlooks=CONFIG.snaphu_nlooks,
            cost="defo",
            ntiles=(int(CONFIG.snaphu_tile_rows), int(CONFIG.snaphu_tile_cols)),
            init=CONFIG.snaphu_init_method.lower(),
            tile_overlap=CONFIG.snaphu_tile_overlap,
            nproc=nproc,
            min_region_size=CONFIG.snaphu_min_region_size,
            single_tile_reoptimize=False,
            regrow_conncomps=False,
        )
    except Exception as exc:
        logger.error(
            "Fallimento Snaphu unwrapping (%s). Cancellazione di %s e salto del subswath %s.",
            exc, output_path, subswath,
        )
        shutil.rmtree(output_path, ignore_errors=True)
        return None

    image_unwrapped.tofile(os.path.join(wrapped_folder_path, unw_filename))

    logger.info("Phase unwrapping completato. Importazione della fase unwrapped in SNAP.")
    logger.info("Calcolo dello spostamento e correzione geometrica.")
    g4 = Graph()
    g4.add_node(Operator("Read", file=os.path.join(output_path, "interferogram_deburst.dim")), node_id="read1")
    g4.add_node(Operator("Read", file=os.path.join(wrapped_folder_path, unw_hdr_filename)), node_id="read2")
    g4.add_node(Operator("SnaphuImport"), node_id="Import", source=["read1", "read2"])
    g4.add_node(Operator("Write", file=os.path.join(output_path, "interferogram_deburst_unw.dim")),
                node_id="writeImport", source="Import")
    g4.add_node(Operator("PhaseToDisplacement"), node_id="phasetodispl", source="Import")
    g4.add_node(Operator("BandMerge"), node_id="BandMerge", source=["Import", "phasetodispl"])

    tc = Operator("Terrain-Correction")
    tc.sourceBandNames = "displacement,coh_{}_VV_{}_{}".format(subswath, data1, data2)
    tc.pixelSpacingInMeter = CONFIG.pixel_spacing_m
    tc.pixelSpacingInDegree = CONFIG.pixel_spacing_deg
    tc.mapProjection = CONFIG.map_projection_wkt
    tc.saveIncidenceAngleFromEllipsoid = "true"
    g4.add_node(tc, node_id="terrain-correction", source="BandMerge")
    g4.add_node(Operator("Write", file=os.path.join(output_path, "interferogram_deburst_unw_disp_TC.dim")),
                node_id="writeTC", source="terrain-correction")

    tif_path = os.path.join(output_path, "interferogram_deburst_unw_disp_TC.tif")
    if os.path.exists(tif_path):
        tif_path = os.path.join(output_path, "interferogram_deburst_unw_disp_TC_2.tif")
    g4.add_node(Operator("Write", formatName="GeoTIFF-BigTIFF", file=tif_path),
                node_id="writeTCtif", source="terrain-correction")
    g4.run()

    logger.info("Interferometria per il subswath %s completata. File salvati in %s.", subswath, output_path)
    return theta


def mosaic(path: str, list_filenames: Sequence[str], trentino_boundary_path: str) -> None:
    """
    Crea i mosaici delle mappe di spostamento e coerenza a partire dai risultati
    dell'interferometria, per ogni coppia di immagini elaborata.

    Parameters
    ----------
    path : str
        Cartella contenente le sottocartelle (una per coppia di immagini) da processare.
    list_filenames : Sequence[str]
        Elenco delle sottocartelle da processare.
    trentino_boundary_path : str
        Path dello shapefile usato per il ritaglio (cutline) dei mosaici.

    Returns
    -------
    None
    """
    for f in list_filenames:
        logger.info("Creazione del mosaico per %s", f)
        file_path = os.path.join(path, f)
        for orientation in ("ascending", "descending"):
            orientation_path = os.path.join(file_path, orientation)
            iw1_dir = os.path.join(orientation_path, "IW1")
            iw2_dir = os.path.join(orientation_path, "IW2")

            if not (os.path.isdir(iw1_dir) and os.path.isdir(iw2_dir)):
                logger.warning(
                    "Salto il mosaico %s (%s): cartelle IW1/IW2 mancanti in %s.",
                    f, orientation, orientation_path,
                )
                continue

            iw1_tifs = [os.path.join(iw1_dir, fi) for fi in os.listdir(iw1_dir) if fi.endswith(".tif")]
            iw2_tifs = [os.path.join(iw2_dir, fi) for fi in os.listdir(iw2_dir) if fi.endswith(".tif")]
            if not iw1_tifs or not iw2_tifs:
                logger.warning(
                    "Salto il mosaico %s (%s): nessun .tif trovato in IW1 e/o IW2.",
                    f, orientation,
                )
                continue

            merged_tif = os.path.join(orientation_path, "m.tif")
            cutline_tif = os.path.join(orientation_path, "coherence_displacement.tif")
            try:
                _run_raster_merge([iw1_tifs[0], iw2_tifs[0]], merged_tif)
                gdal.Warp(
                    cutline_tif, merged_tif,
                    format="GTiff",
                    dstSRS=CONFIG.target_epsg,
                    cutlineDSName=trentino_boundary_path,
                    cutlineLayer=CONFIG.cutline_layer,
                    cropToCutline=True,
                )
            except (subprocess.SubprocessError, RuntimeError) as exc:
                logger.error("Fallita la creazione del mosaico %s (%s): %s", f, orientation, exc)
                continue
            finally:
                if os.path.exists(merged_tif):
                    os.remove(merged_tif)

            shutil.rmtree(iw1_dir, ignore_errors=True)
            shutil.rmtree(iw2_dir, ignore_errors=True)


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


def main(json_input: dict) -> None:
    maindir = "."
    data_folder = "data"
    temp_folder = "tmp"
    output_folder = "output"
    input_folder = "input"
    phase_wrapping_folder = "phase_unwrapping"

    logger.info("Lettura parametri di input")
    s1_a = _require(json_input, "s1_ascending")
    s1_d = _require(json_input, "s1_descending")
    shape_artifact = _require(json_input, "shapeArtifactName")
    shape_filename = _require(json_input, "shapeFileName")
    map_artifact = json_input.get("mapArtifactName")
    nproc = json_input.get("nproc") or 4

    if "PROJECT_NAME" not in os.environ:
        raise EnvironmentError("Variabile d'ambiente 'PROJECT_NAME' non impostata.")
    project_name = os.environ["PROJECT_NAME"]

    logger.info("Definizione dei path")
    data_path = os.path.join(maindir, data_folder, input_folder)
    result_path = os.path.join(maindir, data_folder, output_folder)
    data_ascending_folder = os.path.join(data_path, "ascending")
    data_descending_folder = os.path.join(data_path, "descending")
    temp_dir = os.path.join(data_path, temp_folder)
    unwrap_folder = os.path.join(temp_dir, phase_wrapping_folder)
    trentino_boundary_folder = os.path.join(data_path, "shape")
    input_map_folder = os.path.join(data_path, "maps")
    previous_artifact_folder = os.path.join(data_path, "previous_artifact")

    logger.info("Creazione delle cartelle di lavoro")
    for folder in (
        data_path, data_ascending_folder, data_descending_folder, temp_dir,
        result_path, trentino_boundary_folder, input_map_folder, previous_artifact_folder,
    ):
        os.makedirs(folder, exist_ok=True)

    logger.info(
        "Parametri in input: s1_ascending=%s, s1_descending=%s, shapeArtifact=%s, shapeFileName=%s",
        s1_a, s1_d, shape_artifact, shape_filename,
    )

    project = dh.get_or_create_project(project_name)
    logger.info("Scaricamento degli artefatti per il progetto: %s", project_name)

    data_s1a = project.get_artifact(s1_a)
    input_path_ascending = data_s1a.download(data_ascending_folder, overwrite=True)

    data_s1d = project.get_artifact(s1_d)
    input_path_descending = data_s1d.download(data_descending_folder, overwrite=True)

    shape = project.get_artifact(shape_artifact)
    trentino_boundary_folder = shape.download(trentino_boundary_folder, overwrite=True)
    trentino_boundary_path = os.path.join(trentino_boundary_folder, shape_filename)

    previous_artifact_path = ""
    input_json_path = ""
    if "02_pre_processed" in project.list_artifacts():
        logger.info("Scaricamento artefatto precedente '02_pre_processed'")
        previous_artifact = project.get_artifact("02_pre_processed")
        previous_artifact_path = previous_artifact.download(previous_artifact_folder, overwrite=True)
        candidate_json_path = os.path.join(previous_artifact_path, "sensor_angles.json")
        if os.path.isfile(candidate_json_path):
            input_json_path = candidate_json_path

    logger.info("Dati scaricati con successo.")
    logger.info("input_path_ascending = %s", input_path_ascending)
    logger.info("input_path_descending = %s", input_path_descending)
    logger.info("unwrap_folder = %s", unwrap_folder)
    logger.info("trentino_boundary_path = %s", trentino_boundary_path)

    logger.info("Step 1: Calcolo dell'interferometria")
    list_files_ascending = sorted(f for f in os.listdir(input_path_ascending) if f.endswith(".zip"))
    list_files_descending = sorted(f for f in os.listdir(input_path_descending) if f.endswith(".zip"))
    logger.info("list_files_ascending: %s", list_files_ascending)
    logger.info("list_files_descending: %s", list_files_descending)

    try:
        list_dates_ascending = [extract_acquisition_date(f) for f in list_files_ascending]
        list_dates_descending = [extract_acquisition_date(f) for f in list_files_descending]
    except ValueError as exc:
        raise ValueError(f"Errore nel formato dei nomi dei file Sentinel-1 in input: {exc}") from exc

    sorted_indices_ascending = sorted(range(len(list_dates_ascending)), key=list_dates_ascending.__getitem__)
    sorted_indices_descending = sorted(range(len(list_dates_descending)), key=list_dates_descending.__getitem__)

    n_ascending, n_descending = len(list_files_ascending), len(list_files_descending)
    if n_ascending != n_descending and abs(n_ascending - n_descending) < 2:
        logger.warning(
            "Il numero di immagini ascendenti (%d) e discendenti (%d) è diverso. "
            "Verrà utilizzato il numero minimo di immagini.", n_ascending, n_descending,
        )
    elif abs(n_ascending - n_descending) >= 2:
        logger.warning(
            "Il numero di immagini ascendenti (%d) e discendenti (%d) è molto diverso. "
            "Questo potrebbe influire negativamente sull'interferometria: controllare i dati di input.",
            n_ascending, n_descending,
        )
    n_images = min(n_ascending, n_descending)

    list_theta_ascending, list_theta_descending = [], []

    for i in range(1, n_images):
        filename_ascending1 = list_files_ascending[sorted_indices_ascending[i - 1]]
        filename_ascending2 = list_files_ascending[sorted_indices_ascending[i]]
        filename_descending1 = list_files_descending[sorted_indices_descending[i - 1]]
        filename_descending2 = list_files_descending[sorted_indices_descending[i]]
        date_descending1 = list_dates_descending[sorted_indices_descending[i - 1]]
        date_descending2 = list_dates_descending[sorted_indices_descending[i]]
        date_ascending1 = list_dates_ascending[sorted_indices_ascending[i - 1]]
        date_ascending2 = list_dates_ascending[sorted_indices_ascending[i]]

        if i + 1 < n_images:
            if date_descending1 == date_descending2 or date_descending2 == list_dates_descending[sorted_indices_descending[i + 1]]:
                logger.warning(
                    "Le immagini discendenti %s e %s hanno la stessa data o non appartengono "
                    "ad aree corrispondenti. Prendo la data successiva.",
                    filename_descending1, filename_descending2,
                )
                date_descending2 = list_dates_descending[sorted_indices_descending[i + 1]]
                filename_descending2 = list_files_descending[sorted_indices_descending[i + 1]]
            if date_ascending1 == date_ascending2 or date_ascending2 == list_dates_ascending[sorted_indices_ascending[i + 1]]:
                logger.warning(
                    "Le immagini ascendenti %s e %s hanno la stessa data o non appartengono "
                    "ad aree corrispondenti. Prendo la data successiva.",
                    filename_ascending1, filename_ascending2,
                )
                date_ascending2 = list_dates_ascending[sorted_indices_ascending[i + 1]]
                filename_ascending2 = list_files_ascending[sorted_indices_ascending[i + 1]]
        else:
            if date_descending1 == date_descending2:
                logger.warning(
                    "Le immagini discendenti %s e %s hanno la stessa data e non ci sono ulteriori "
                    "immagini da analizzare. Esco dal ciclo.", filename_descending1, filename_descending2,
                )
                break
            if date_ascending1 == date_ascending2:
                logger.warning(
                    "Le immagini ascendenti %s e %s hanno la stessa data e non ci sono ulteriori "
                    "immagini da analizzare. Esco dal ciclo.", filename_ascending1, filename_ascending2,
                )
                break

        if date_descending1 < date_ascending1:
            output_label = f"{date_descending1}-{date_ascending2}"
        elif date_ascending1 < date_descending1:
            output_label = f"{date_ascending1}-{date_descending2}"
        else:
            logger.warning(
                "Data ascendente e discendente coincidenti (%s): impossibile determinare "
                "l'ordine cronologico per questa coppia. Salto l'iterazione.", date_ascending1,
            )
            continue

        output_path_ascending = os.path.join(result_path, output_label, "ascending")
        output_path_descending = os.path.join(result_path, output_label, "descending")

        pairs_to_check = [
            (input_path_ascending, filename_ascending1),
            (input_path_ascending, filename_ascending2),
            (input_path_descending, filename_descending1),
            (input_path_descending, filename_descending2),
        ]
        zip_is_valid = True
        for folder, filename in pairs_to_check:
            try:
                with zipfile.ZipFile(os.path.join(folder, filename), "r"):
                    pass
            except zipfile.BadZipFile:
                logger.warning("%s è un file zip danneggiato. Iterazione saltata.", filename)
                zip_is_valid = False
                break
        if not zip_is_valid:
            continue

        logger.info("output_path = %s", output_label)
        logger.info("output_path_ascending = %s", output_path_ascending)
        logger.info("output_path_descending = %s", output_path_descending)
        os.makedirs(output_path_ascending, exist_ok=True)
        os.makedirs(output_path_descending, exist_ok=True)

        logger.info("Calcolo interferometria tra %s e %s", filename_descending1, filename_descending2)
        unwrap_iw1 = os.path.join(unwrap_folder, "descending_iw1")
        unwrap_iw2 = os.path.join(unwrap_folder, "descending_iw2")
        theta_descending_iw1 = interferometry(
            input_path_descending, filename_descending1, filename_descending2,
            output_path_descending, unwrap_iw1, subswath="IW1", nproc=nproc,
        )
        theta_descending_iw2 = interferometry(
            input_path_descending, filename_descending1, filename_descending2,
            output_path_descending, unwrap_iw2, subswath="IW2", nproc=nproc,
        )
        theta_descending = theta_descending_iw1 if theta_descending_iw1 is not None else theta_descending_iw2
        if theta_descending is not None:
            list_theta_descending.append(theta_descending)
            logger.info("Platform heading angle descending: %s", theta_descending)

        logger.info("Calcolo interferometria tra %s e %s", filename_ascending1, filename_ascending2)
        # Nota: come nella logica originale, l'elaborazione ascending IW1/IW2 viene
        # eseguita solo se la corrispondente discending IW2/IW1 ha avuto successo,
        # per coerenza tra le coperture est/ovest dei due orbit ascending/descending.
        if theta_descending_iw2 is not None:
            unwrap_asc_iw1 = os.path.join(unwrap_folder, "ascending_iw1")
            theta_ascending_iw1 = interferometry(
                input_path_ascending, filename_ascending1, filename_ascending2,
                output_path_ascending, unwrap_asc_iw1, subswath="IW1", nproc=nproc,
            )
        else:
            logger.warning("Salto interferometria ascending IW1: fallita la discending IW2.")
            theta_ascending_iw1 = None

        if theta_descending_iw1 is not None:
            unwrap_asc_iw2 = os.path.join(unwrap_folder, "ascending_iw2")
            theta_ascending_iw2 = interferometry(
                input_path_ascending, filename_ascending1, filename_ascending2,
                output_path_ascending, unwrap_asc_iw2, subswath="IW2", nproc=nproc,
            )
        else:
            logger.warning("Salto interferometria ascending IW2: fallita la discending IW1.")
            theta_ascending_iw2 = None

        theta_ascending = theta_ascending_iw1 if theta_ascending_iw1 is not None else theta_ascending_iw2
        if theta_ascending is not None:
            list_theta_ascending.append(theta_ascending)
            logger.info("Platform heading angle ascending: %s", theta_ascending)

    # Salvataggio dei theta ascending/descending in JSON
    sensor_angles_path = os.path.join(result_path, "sensor_angles.json")
    if not input_json_path:
        theta_dict = {"ascending": list_theta_ascending, "descending": list_theta_descending}
    else:
        with open(input_json_path, "r") as f:
            theta_dict = json.load(f)
        theta_dict.setdefault("ascending", []).extend(list_theta_ascending)
        theta_dict.setdefault("descending", []).extend(list_theta_descending)
    with open(sensor_angles_path, "w") as f:
        json.dump(theta_dict, f)

    logger.info("Interferometria completata per tutte le coppie di immagini. Calcolo dei mosaici.")
    logger.info("Step 2: Creazione dei mosaici di spostamento e coerenza")
    list_filenames = [f for f in os.listdir(result_path) if os.path.isdir(os.path.join(result_path, f))]
    logger.info("Trovate %d sottocartelle in %s", len(list_filenames), result_path)

    mosaic(result_path, list_filenames, trentino_boundary_path)
    logger.info("Mosaici creati con successo per tutte le coppie di immagini.")

    if not previous_artifact_path:
        upload_artifact(artifact_name="02_pre_processed", project_name=project_name, src_path=result_path)
    else:
        logger.info(
            "Artifact '02_pre_processed' già esistente nel progetto '%s'. Aggiornamento con i nuovi dati.",
            project_name,
        )
        shutil.copytree(previous_artifact_path, result_path, dirs_exist_ok=True)
        upload_artifact(artifact_name="02_pre_processed", project_name=project_name, src_path=result_path)

    logger.info("Mosaici caricati con successo come artifact '02_pre_processed'.")


if __name__ == "__main__":
    _configure_logging()
    logger.info("Lettura parametri di input")
    if len(sys.argv) < 2:
        logger.error("Uso: python job_insar_preprocessing.py '<json_input>'")
        sys.exit(1)
    try:
        parsed_input = _load_json_argument(sys.argv[1])
        main(parsed_input)
    except Exception:
        logger.exception("Il job è terminato con un errore non gestito.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CHANGELOG rispetto alla versione originale
# ---------------------------------------------------------------------------
# Sicurezza:
#  - subprocess: rimosso shell=True e la concatenazione di stringhe; ora si usa
#    subprocess.run con lista di argomenti + timeout (niente command injection).
#  - XML: uso di defusedxml.ElementTree quando disponibile, per proteggere il
#    parsing dei metadata Sentinel-1 da attacchi di entity-expansion.
#  - Argomento JSON da CLI: si prova prima json.loads diretto; il replace ' -> "
#    è un fallback esplicito e loggato, non il comportamento di default.
#
# Bug corretti:
#  - unwrap_folder ora è un parametro esplicito di interferometry() (niente più
#    variabile globale implicita impostata solo nel blocco __main__).
#  - Apply-Orbit-File: due istanze Operator distinte invece di una condivisa.
#  - Estrazione data da nome file: validata con regex (extract_acquisition_date)
#    invece di uno slicing posizionale silenzioso.
#  - Sostituita la sentinella magica 9999.0 con Optional[float] (None = errore)
#    e con l'eccezione InterferometryError.
#  - Gestione esplicita del caso "data ascending == data descending" nel calcolo
#    di output_path (prima mancava il branch else).
#  - Validazione delle variabili phasefile/cohfile/unw_hdr_filename prima
#    dell'uso, con messaggio di errore chiaro invece di UnboundLocalError.
#  - Verifica che SnaphuExport produca esattamente una cartella di output.
#  - nproc con default (4) quando non specificato in input, invece di None.
#  - Validazione dei parametri obbligatori nel JSON di input (_require).
#  - Rimosso codice morto (riga "tempfile.tempdir" isolata, doppio controllo
#    sulla pulizia di unwrap_folder).
#
# Qualità del codice:
#  - Un solo sistema di logging (niente più print()+logging duplicati).
#  - Parametri di elaborazione centralizzati in ProcessingConfig invece di
#    valori hardcoded sparsi nel codice.
#  - os.makedirs(..., exist_ok=True) al posto del pattern non atomico
#    "if not os.path.isdir: os.makedirs".
#  - zipfile.ZipFile usato sempre come context manager.
#  - Corretto il type hint di mosaic() (-> None invece di -> np.float32).
#  - cartelle di unwrap dedicate per ogni combinazione orbita/subswath, per
#    evitare che chiamate successive a interferometry() si sovrascrivano.
