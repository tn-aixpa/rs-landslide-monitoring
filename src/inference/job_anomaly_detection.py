#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Dec  1 17:53:21 2023

@author: lbergamasco
"""

import os,sys
import torch
from data_loader.data_loaders import InSARDataLoader
from utae import UTAE
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import confusion_matrix, precision_score, recall_score, f1_score
import tifffile as tiff
from scipy.io import savemat
import digitalhub as dh
import glob
import json
from osgeo import gdal, ogr, osr
from data_sampling import reproject_and_clip,get_extent,resize_array,normalize_in_range
import logging
from typing import Optional, Sequence, Tuple
from utils.skd_handler import upload_artifact

gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

logger = logging.getLogger(__name__)

_DRIVER_BY_EXTENSION = {
    ".gpkg": "GPKG",
    ".shp": "ESRI Shapefile",
    ".geojson": "GeoJSON",
    ".json": "GeoJSON",
}


def _create_vector_datasource(path: str) -> ogr.DataSource:
    """Create a vector file, choosing the driver from the extension and replacing existing files."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in _DRIVER_BY_EXTENSION:
        raise ValueError(
            f"Unsupported extension '{ext}' for {path}. Use one of: {sorted(_DRIVER_BY_EXTENSION)}."
        )
    driver = ogr.GetDriverByName(_DRIVER_BY_EXTENSION[ext])
    if os.path.exists(path):
        driver.DeleteDataSource(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return driver.CreateDataSource(path)


def mask_to_vectors(
    mask: np.ndarray,
    geo_transform: Sequence[float],
    projection: Optional[str],
    polygon_path: str,
    centroid_path: str,
    connectedness: int = 4,
    min_area: Optional[float] = None,
    point_on_surface: bool = False,
) -> Tuple[str, str]:
    """
    Convert a binary mask (0/1) into a polygon vector file and a point vector file
    containing one point per polygon (at its centroid).

    Parameters
    ----------
    mask : np.ndarray
        2D array with values 0 and 1 (bool is also accepted). Pixels equal to 1
        are vectorized, pixels equal to 0 are background.
    geo_transform : sequence of 6 floats
        GDAL geotransform of the mask, e.g. from ds.GetGeoTransform().
    projection : str or None
        CRS of the mask (WKT, "EPSG:25832", PROJ string). If None, the output
        files have no CRS.
    polygon_path : str
        Output polygon file (.gpkg, .shp, .geojson).
    centroid_path : str
        Output point file (.gpkg, .shp, .geojson).
    connectedness : {4, 8}, optional
        Pixel connectivity used to group pixels into polygons (default 4:
        pixels touching only at a corner become separate polygons).
    min_area : float, optional
        Polygons with an area smaller than this value (in CRS units squared)
        are discarded from both outputs.
    point_on_surface : bool, optional
        If True, the point is guaranteed to lie inside the polygon
        (GEOS PointOnSurface) instead of being the true centroid. Useful for
        concave or ring-shaped polygons, whose centroid can fall outside.

    Returns
    -------
    (polygon_path, centroid_path)
        Both files have the fields 'id' (same value in the two files) and
        'area' (polygon area in CRS units squared).
    """
    if mask.ndim != 2:
        raise ValueError(f"Expected a 2D array, got {mask.ndim} dimensions.")
    if mask.size == 0:
        raise ValueError("The mask is empty.")
    if not np.isin(mask, (0, 1)).all():
        raise ValueError("The mask must contain only the values 0 and 1 (no NaN or other values).")
    if len(geo_transform) != 6:
        raise ValueError("geo_transform must contain 6 values.")
    if connectedness not in (4, 8):
        raise ValueError("connectedness must be 4 or 8.")

    height, width = mask.shape
    srs = None
    if projection:
        srs = osr.SpatialReference()
        srs.SetFromUserInput(projection)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    # In-memory raster holding the mask
    mem_raster = gdal.GetDriverByName("MEM").Create("", width, height, 1, gdal.GDT_Byte)
    mem_raster.SetGeoTransform(tuple(geo_transform))
    if srs is not None:
        mem_raster.SetProjection(srs.ExportToWkt())
    band = mem_raster.GetRasterBand(1)
    band.WriteArray(mask.astype(np.uint8))

    # Intermediate in-memory layer filled by Polygonize
    mem_driver = ogr.GetDriverByName("Memory") or ogr.GetDriverByName("MEM")
    mem_vector = mem_driver.CreateDataSource("")
    poly_ds = point_ds = None
    try:
        mem_layer = mem_vector.CreateLayer("tmp", srs=srs, geom_type=ogr.wkbPolygon)
        mem_layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))

        # The band is also used as mask: only pixels != 0 (i.e. the 1s) are vectorized
        options = ["8CONNECTED=8"] if connectedness == 8 else []
        gdal.Polygonize(band, band, mem_layer, 0, options)

        poly_ds = _create_vector_datasource(polygon_path)
        point_ds = _create_vector_datasource(centroid_path)
        poly_layer = poly_ds.CreateLayer("polygons", srs=srs, geom_type=ogr.wkbPolygon)
        point_layer = point_ds.CreateLayer("centroids", srs=srs, geom_type=ogr.wkbPoint)
        for lyr in (poly_layer, point_layer):
            lyr.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
            lyr.CreateField(ogr.FieldDefn("area", ogr.OFTReal))

        n_written = 0
        poly_layer.StartTransaction()
        point_layer.StartTransaction()
        for feat in mem_layer:
            geom = feat.GetGeometryRef()
            area = geom.GetArea()
            if min_area is not None and area < min_area:
                continue
            n_written += 1

            poly_feat = ogr.Feature(poly_layer.GetLayerDefn())
            poly_feat.SetGeometry(geom)
            poly_feat.SetField("id", n_written)
            poly_feat.SetField("area", area)
            poly_layer.CreateFeature(poly_feat)

            point_geom = geom.PointOnSurface() if point_on_surface else geom.Centroid()
            point_feat = ogr.Feature(point_layer.GetLayerDefn())
            point_feat.SetGeometry(point_geom)
            point_feat.SetField("id", n_written)
            point_feat.SetField("area", area)
            point_layer.CreateFeature(point_feat)
        poly_layer.CommitTransaction()
        point_layer.CommitTransaction()

        if n_written == 0:
            logger.warning("No polygons found in the mask: the output files are empty.")
            return
        else:
            logger.info("Written %d polygons to %s and %d points to %s.",
                        n_written, polygon_path, n_written, centroid_path)
    finally:
        # Close datasets to flush data to disk
        poly_ds = point_ds = None
        mem_vector = None
        mem_raster = None

    return polygon_path, centroid_path

def add_polygon_time_series_means(
    polygon_path: str,
    centroid_path: str,
    series: np.ndarray,
    geo_transform: Sequence[float],
    projection: Optional[str],
    output_path: Optional[str] = None,
    id_field: str = "id",
    field_names: Optional[Sequence[str]] = None,
    nodata: Optional[float] = None,
    all_touched: bool = False,
) -> str:
    """
    For each polygon, compute the mean of every image of a time series inside the
    polygon area, and store the values as fields of the matching centroid point.

    Parameters
    ----------
    polygon_path : str
        Polygon file generated by mask_to_vectors (fields 'id' and 'area').
    centroid_path : str
        Point file generated by mask_to_vectors (same 'id' values as the polygons).
    series : np.ndarray
        Time series with shape (T, H, W).
    geo_transform : sequence of 6 floats
        GDAL geotransform of the images (all images share the same grid).
    projection : str or None
        CRS of the images (WKT, "EPSG:25832", ...). If it differs from the CRS of
        the polygons, the polygons are reprojected in memory before the computation.
    output_path : str, optional
        If given, the centroid file is first copied here and the fields are added to
        the copy. If None, centroid_path is modified in place.
    id_field : str, optional
        Field linking polygons and centroids (default "id"). Values must be integers
        different from 0.
    field_names : sequence of str, optional
        Names of the T new fields, one per image. Default: "mean_0", "mean_1", ...
        (zero-padded). For Shapefile outputs the names must be at most 10 characters.
    nodata : float, optional
        Value to ignore in the images, in addition to NaN/inf.
    all_touched : bool, optional
        If True, a pixel is assigned to a polygon when it touches it; if False
        (default) only when its centre is inside. With the same grid used to create
        the polygons, the default selects exactly the original pixels.

    Returns
    -------
    str
        Path of the centroid file with the new fields. Polygons without valid
        pixels get NULL values.
    """
    # --- Input validation ----------------------------------------------------------
    if not isinstance(series, np.ndarray) or series.ndim != 3:
        raise ValueError("series must be a numpy array with shape (T, H, W).")
    n_t, height, width = series.shape
    if n_t == 0 or height == 0 or width == 0:
        raise ValueError("series is empty.")
    if len(geo_transform) != 6:
        raise ValueError("geo_transform must contain 6 values.")
    if geo_transform[2] != 0 or geo_transform[4] != 0:
        raise ValueError("Rotated geotransforms are not supported.")

    if field_names is None:
        pad = len(str(n_t - 1))
        field_names = [f"mean_{i:0{pad}d}" for i in range(n_t)]
    field_names = list(field_names)
    if len(field_names) != n_t:
        raise ValueError(f"field_names has {len(field_names)} items but the series has T={n_t} images.")
    if len(set(n.lower() for n in field_names)) != n_t or any(not n for n in field_names):
        raise ValueError("field_names must be non-empty and unique (case-insensitive).")

    # Checks on the centroid file before any heavy computation or file creation
    centroid_ds = gdal.OpenEx(centroid_path, gdal.OF_VECTOR | gdal.OF_READONLY)
    centroid_defn = centroid_ds.GetLayer(0).GetLayerDefn()
    existing_fields = {centroid_defn.GetFieldDefn(i).GetName().lower()
                       for i in range(centroid_defn.GetFieldCount())}
    source_driver = centroid_ds.GetDriver().ShortName
    centroid_ds = None

    if id_field.lower() not in existing_fields:
        raise ValueError(f"Field '{id_field}' not found in {centroid_path}.")
    clashes = [n for n in field_names if n.lower() in existing_fields]
    if clashes:
        raise ValueError(f"Field names already present in {centroid_path}: {clashes}.")

    in_place = output_path is None or os.path.abspath(output_path) == os.path.abspath(centroid_path)
    if in_place:
        target_path, target_driver = centroid_path, source_driver
    else:
        ext = os.path.splitext(output_path)[1].lower()
        if ext not in _DRIVER_BY_EXTENSION:
            raise ValueError(f"Unsupported extension '{ext}' for {output_path}.")
        target_path, target_driver = output_path, _DRIVER_BY_EXTENSION[ext]
    if target_driver == "ESRI Shapefile":
        too_long = [n for n in field_names if len(n) > 10]
        if too_long:
            raise ValueError(f"Shapefile field names must be at most 10 characters: {too_long}.")

    dst_srs = None
    if projection:
        dst_srs = osr.SpatialReference()
        dst_srs.SetFromUserInput(projection)
        dst_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    # --- Rasterize the polygon ids on the grid of the series ----------------------
    poly_ds = gdal.OpenEx(polygon_path, gdal.OF_VECTOR | gdal.OF_READONLY)
    source = poly_ds
    label_ds = None
    try:
        lyr = poly_ds.GetLayer(0)
        if lyr.GetLayerDefn().GetFieldIndex(id_field) < 0:
            raise ValueError(f"Field '{id_field}' not found in {polygon_path}.")

        poly_srs = lyr.GetSpatialRef()
        if dst_srs is not None and poly_srs is not None:
            if not poly_srs.IsSame(dst_srs):
                logger.info("Reprojecting polygons to the CRS of the time series.")
                source = gdal.VectorTranslate("", poly_ds, format="Memory", dstSRS=dst_srs.ExportToWkt())
                lyr = source.GetLayer(0)
        elif dst_srs is not None and poly_srs is None:
            logger.warning("Polygons have no CRS: assumed to be in the CRS of the time series.")

        polygon_ids = {int(f.GetField(id_field)) for f in lyr if f.GetField(id_field) is not None}
        lyr.ResetReading()

        label_ds = gdal.GetDriverByName("MEM").Create("", width, height, 1, gdal.GDT_Int32)
        label_ds.SetGeoTransform(tuple(geo_transform))
        if dst_srs is not None:
            label_ds.SetProjection(dst_srs.ExportToWkt())
        options = [f"ATTRIBUTE={id_field}"]
        if all_touched:
            options.append("ALL_TOUCHED=TRUE")
        gdal.RasterizeLayer(label_ds, [1], lyr, options=options)
        labels = label_ds.GetRasterBand(1).ReadAsArray().ravel()
    finally:
        label_ds = None
        source = None
        poly_ds = None

    # --- Mean per polygon and per time step (no per-polygon loops) -----------------
    pixel_idx = np.flatnonzero(labels)
    if pixel_idx.size == 0:
        raise ValueError(
            "No pixel of the series falls inside the polygons: check geo_transform and projection."
        )
    unique_ids, poly_idx = np.unique(labels[pixel_idx], return_inverse=True)
    poly_idx = poly_idx.ravel()
    n_poly = unique_ids.size
    col_of_id = {int(i): k for k, i in enumerate(unique_ids)}

    missing = polygon_ids - set(col_of_id)
    if missing:
        logger.warning(
            "%d polygon(s) contain no pixel of the series and will get NULL values "
            "(try all_touched=True or check the grid): ids %s",
            len(missing), sorted(missing)[:10],
        )

    means = np.full((n_t, n_poly), np.nan, dtype=np.float64)
    for t in range(n_t):
        values = series[t].ravel()[pixel_idx].astype(np.float64)
        valid = np.isfinite(values)
        if nodata is not None:
            valid &= values != nodata
        counts = np.bincount(poly_idx[valid], minlength=n_poly)
        sums = np.bincount(poly_idx[valid], weights=values[valid], minlength=n_poly)
        np.divide(sums, counts, out=means[t], where=counts > 0)
    mean_velocity = np.mean(means,axis=0,keepdims=True)
    means = np.concatenate([mean_velocity,means], axis=0)
    # --- Write the fields into the centroid file ----------------------------------
    if not in_place:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        if os.path.exists(output_path):
            gdal.GetDriverByName(target_driver).Delete(output_path)
        copy_ds = gdal.VectorTranslate(output_path, centroid_path, format=target_driver)
        copy_ds = None

    ds = gdal.OpenEx(target_path, gdal.OF_VECTOR | gdal.OF_UPDATE)
    try:
        lyr = ds.GetLayer(0)
        if not lyr.TestCapability(ogr.OLCCreateField):
            raise RuntimeError(
                f"The driver {target_driver} cannot add fields to an existing file: use .gpkg or .shp."
            )
        field_names.insert(0,"mean_velocity")
        for name in field_names:
            lyr.CreateField(ogr.FieldDefn(name, ogr.OFTReal))

        # Collect FIDs first: updating features while iterating can be unsafe on some drivers
        fids = [f.GetFID() for f in lyr]
        lyr.ResetReading()

        n_without_polygon = 0
        lyr.StartTransaction()
        for fid in fids:
            feat = lyr.GetFeature(fid)
            pid = feat.GetField(id_field)
            col = col_of_id.get(int(pid)) if pid is not None else None
            if col is None:
                n_without_polygon += 1
            for t, name in enumerate(field_names):
                value = means[t, col] if col is not None else np.nan
                if np.isnan(value):
                    feat.SetFieldNull(name)
                else:
                    feat.SetField(name, float(value))
            lyr.SetFeature(feat)
        lyr.CommitTransaction()
    finally:
        ds = None  # close the dataset to flush data to disk

    if n_without_polygon:
        logger.warning("%d centroid(s) have no matching polygon: fields set to NULL.", n_without_polygon)
    logger.info("Added %d fields to %d centroids in %s.", n_t, len(fids), target_path)
    return target_path

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

def dataset_from_image(image, patch_size, step=22):
    """
    image: (T, C, H, W)
    patch_size: size of each patch (square)
    step: step size for patching (default is equal to patch_size for non-overlapping patches)
    returns: (N, T, C, patch_size, patch_size) where N is the number of patches
    """
    n_step_h = ((image.shape[2]-patch_size)//step)+1
    n_step_w = ((image.shape[3]-patch_size)//step)+1
    print(n_step_h)
    print(n_step_w)
    output = np.zeros([n_step_h*n_step_w,image.shape[0],image.shape[1],patch_size,patch_size], dtype=np.float32)
    k=0
    for i in range(n_step_h):
        for j in range(n_step_w):
            output[k] = image[:,:,(i*step):(i*step)+patch_size,(j*step):(j*step)+patch_size]
            k+=1
    return output


def reconstruct_from_patches(patches, full_size=(770,770), patch_size=22):
    """
    patches: (N, T, C, ph, pw) where N = n_patches_h * n_patches_w
    full_size: (H, W)
    patch_size: size of each patch (square)
    returns: (T, C, H, W)
    """
    H, W = full_size
    ph = pw = patch_size
    n_patches_h = H // ph
    n_patches_w = W // pw
    C = patches.shape[2]
    T = patches.shape[1]

    image = np.zeros((T, C, H, W), dtype=patches.dtype)

    idx = 0
    for i in range(n_patches_h):
        for j in range(n_patches_w):
            image[:,:,i*ph:(i+1)*ph, j*pw:(j+1)*pw] = patches[idx]
            idx += 1
    return image

def main(config):

    model_name = _require(config,"model_name")
    batch_size = int(_require(config,"batch_size"))
    comp_thresh = bool(_require(config,"compute_threshold"))
    patch_size = int(_require(config,"patch_size"))
    th = float(config.get("th"))

    maindir = "."
    data_folder = "data"
    output_folder = "output"
    input_folder = "input"

    if "PROJECT_NAME" not in os.environ:
        raise EnvironmentError("Variabile d'ambiente 'PROJECT_NAME' non impostata.")
    proj_name = os.environ["PROJECT_NAME"]

    data_path = os.path.join(maindir, data_folder, input_folder)
    result_path = os.path.join(maindir, data_folder, output_folder)
    dataset_folder = os.path.join(data_path, "dataset")
    feature_folder = os.path.join(data_path, "features")
    rainfall_map_folder = os.path.join(data_path, "rainfall_map")
    checkpoint_model_folder = os.path.join(data_path,"model")

    for folder in (data_path, result_path, feature_folder, rainfall_map_folder,dataset_folder):
        os.makedirs(folder, exist_ok=True)

    logger.info("Scaricamento artefatti")

    proj = dh.get_or_create_project(proj_name)
    feature_artifact = proj.get_artifact("03_features")
    feature_path = feature_artifact.download(feature_folder, overwrite=True)
    rainfal_map_artifact = proj.get_artifact("rainfall_maps")
    rainfall_map_path = rainfal_map_artifact.download(rainfall_map_folder, overwrite=True)

    list_feature_path = sorted(os.listdir(feature_path))
    start_date = list_feature_path[0][:8]
    end_date = list_feature_path[-1][-8:]
    ds = gdal.Open(os.path.join(feature_path,list_feature_path[0],"somma_cumulata_spostamento_verticale.tif"),gdal.GA_ReadOnly)
    rows = ds.RasterYSize
    cols = ds.RasterXSize
    gt = ds.GetGeoTransform()
    projection = ds.GetProjection()
    ds = None

    print(os.path.join(feature_path,list_feature_path[0]))

    logger.info("Caricamento rainfall map")
    rainmaps_list = sorted([file for file in os.listdir(rainfall_map_path)])
    rainmaps= np.zeros([len(rainmaps_list),rows,cols],dtype=np.float32)
    for i, rainmap_file in enumerate(sorted(rainmaps_list)):
        rm_file = os.path.join(rainfall_map_path,rainmap_file)
        reproj_rm_file = reproject_and_clip(rm_file, os.path.join(rainfall_map_path,f"reproj_{rainmap_file}"), 
                                            target_resolution=(abs(gt[1]),abs(gt[5])),
                                            target_extent=get_extent(os.path.join(feature_path,list_feature_path[0],
                                                                                    "somma_cumulata_spostamento_verticale.tif")))
        ds = gdal.Open(reproj_rm_file,gdal.GA_ReadOnly)
        rainmaps[i,] += ds.GetRasterBand(1).ReadAsArray()
        ds = None

    logger.info("Merge dati")    
    imageTS = np.zeros([len(list_feature_path),3,rows,cols],np.float32)

    for i, path in enumerate(list_feature_path):
        f_path = os.path.join(feature_path,path)
        vertical_displ_sum_ds = gdal.Open(os.path.join(f_path,"somma_cumulata_spostamento_verticale.tif"), gdal.GA_ReadOnly)
        imageTS[i,0,:,:] = resize_array(vertical_displ_sum_ds.GetRasterBand(1).ReadAsArray(),(rows,cols))
        vertical_displ_sum_ds = None

        horizontal_displ_sum_ds = gdal.Open(os.path.join(f_path,"somma_cumulata_spostamento_orizzontale.tif"), gdal.GA_ReadOnly)
        imageTS[i,1,:,:] = resize_array(horizontal_displ_sum_ds.GetRasterBand(1).ReadAsArray(),(rows,cols))
        horizontal_displ_sum_ds = None
    imageTS[:,2,:,:] = (rainmaps)
    logger.info("Normalizzazione")
    #normalization
    imageTS[:,0,:,:] = normalize_in_range(imageTS[:,0,:,:],feat_range=[-0.55,0.55], min_value=-1, max_value=1)
    imageTS[:,1,:,:] = normalize_in_range(imageTS[:,1,:,:],feat_range=[-0.55,0.55], min_value=-1, max_value=1)
    imageTS[:,2,:,:] = normalize_in_range(imageTS[:,2,:,:],feat_range=[0,800], min_value=0, max_value=1)
    
    #recover in_channels
    in_channels = imageTS.shape[1]

    # build model architecture
    model = UTAE(in_channels=in_channels,out_conv=[32,in_channels],input_channel_first=True)

    logger.info('Loading checkpoint: {} ...'.format(model_name))

    # loading on CPU-only machine
    n_gpu = 1
    cp = proj.get_model("AD-model")
    #checkpoint.spec.parameters
    cp.download(checkpoint_model_folder, overwrite=True)
    checkpoint = torch.load(os.path.join(checkpoint_model_folder,model_name), map_location=torch.device('cpu'), weights_only=False)
    state_dict = checkpoint['state_dict']
    if n_gpu > 1:
        model = torch.nn.DataParallel(model)
    model.load_state_dict(state_dict)

    # prepare model for testing
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = model.to(device)
    model.eval()

    if comp_thresh:
        logger.info("Calcolo soglie per anomaly detection")
        dataset_artifact = proj.get_artifact("Dataset")
        dataset_path = dataset_artifact.download(dataset_folder,overwrite=True)
        data_loader = InSARDataLoader(os.path.join(dataset_path,"training"), batch_size=batch_size,
                                  shuffle=True, num_workers=8,augmentations=True,drop_last=True)
        predictions = []

        for im, _ in data_loader:
            im = im.to(non_blocking=True, device=device)
            with torch.no_grad():
                output = model(im)#.encoder_q(im_1,im_2)
                output = output.cpu().numpy()
                predictions.append(output)
        predictions = np.concatenate(predictions,axis=0)
        th = np.mean(predictions,axis=(0,2,3,4))+np.std(predictions,axis=(0,2,3,4))
        print('Threshold for normal data: {}'.format(th))
        #save on json file
        threshold_path = os.path.join(result_path, "threshold.json")
        thresh_dict = {"threshold":th}
        with open(threshold_path, "w") as f:
            json.dump(thresh_dict, f)
        proj.log_artifact(name=proj_name, kind="artifact", source=threshold_path)
    elif not comp_thresh:
        logger.info("Recupero soglie per anomaly detection")
        threshold_artifact = proj.get_artifact("threshdold")
        threshold_path = threshold_artifact.download(data_path,overwrite=True)
        with open(threshold_path, "r") as f:
            thresh_dict = json.load(f)
        th = thresh_dict["threshold"]

    logger.info("Processing image time series")
    to_add_first_rows = imageTS.shape[2]%patch_size
    to_add_first_cols = imageTS.shape[3]%patch_size
    buffer = patch_size//3
    mini_patch_size = patch_size-(buffer*2)
    imageTS_padded = np.pad(imageTS, ((0,0), (0,0), (0, to_add_first_rows), (0, to_add_first_cols)), 'reflect')
    imageTS_padded = np.pad(imageTS_padded, ((0,0), (0,0), (buffer,buffer), (buffer,buffer)), 'reflect')
    imageTS_reshaped = dataset_from_image(imageTS_padded,patch_size=patch_size,step=buffer)
    imageTS_reshaped = torch.from_numpy(imageTS_reshaped).to(device)
    test_dataset = torch.utils.data.TensorDataset(imageTS_reshaped) # (N,C,T,H,W)

    test_loader = torch.utils.data.DataLoader(
        test_dataset, batch_size=batch_size, shuffle=False # adjust batch_size to fit GPU
    )
    preds = []
    with torch.no_grad():
        for im in test_loader:
            im = im.to(device)  # unpack tuple
            out= model(im)
            preds.append(im.cpu())

        preds = torch.cat(preds).numpy()
        print('preds', preds.shape)

    results_unpadded = preds[:,buffer:(buffer+mini_patch_size),buffer:(buffer+mini_patch_size)]

    output_image = reconstruct_from_patches(results_unpadded, 
                                            full_size=(imageTS.shape[2]+to_add_first_rows,imageTS.shape[2]+to_add_first_rows), 
                                            patch_size=mini_patch_size)
    output_image = output_image[:,:,:imageTS.shape[2],:imageTS.shape[3]]

    # imageTS = np.zeros([len(list_feature_path),2,rows,cols],np.float32)
    # for i, path in enumerate(list_feature_path):
    #     f_path = os.path.join(feature_path,path)
    #     vertical_displ_sum_ds = gdal.Open(os.path.join(f_path,"somma_cumulata_scostamento_verticale_AOI.tif"), gdal.GA_ReadOnly)
    #     imageTS[i,0,:,:] = resize_array(vertical_displ_sum_ds.GetRasterBand(1).ReadAsArray(),(rows,cols))
    #     vertical_displ_sum_ds = None

    #     horizontal_displ_sum_ds = gdal.Open(os.path.join(f_path,"somma_cumulata_scostamento_orizzontale_AOI.tif"), gdal.GA_ReadOnly)
    #     imageTS[i,1,:,:] = resize_array(horizontal_displ_sum_ds.GetRasterBand(1).ReadAsArray(),(rows,cols))
    #     horizontal_displ_sum_ds = None


    logger.info("Anomaly detection")
    anomaly_map = np.all(output_image>th,axis=(0,1))
    # imageTS[:,0,:,:][np.logical_or(imageTS[:,0,:,:]>0.55,imageTS[:,0,:,:]<-0.55)]=0
    # imageTS[:,1,:,:][np.logical_or(imageTS[:,1,:,:]>0.55,imageTS[:,1,:,:]<-0.55)]=0
    # # control_vertical = np.logical_and(np.all(imageTS[:,0,:,:]<2,axis=0),np.all(imageTS[:,0,:,:]>-2,axis=0))
    # # control_horizontal = np.logical_and(np.all(imageTS[:,1,:,:]<2,axis=0),np.all(imageTS[:,1,:,:]>-2,axis=0))
    # anomaly_map = np.logical_and(np.any(imageTS[:,0,:,:]>th,axis=0),np.any(imageTS[:,1,:,:]>th,axis=0))

    logger.info("Creazione vettoriali")
    polygon_path, centroid_path = mask_to_vectors(anomaly_map.astype(np.uint8),
                                                  geo_transform=gt,
                                                  projection=projection,
                                                  polygon_path=os.path.join(result_path,f"anomaly_map_poly_{start_date}_{end_date}.geojson"),
                                                  centroid_path=os.path.join(result_path,f"anomaly_map_centroid_{start_date}_{end_date}.geojson"),
                                                  connectedness=8,
                                                  min_area=None,
                                                  point_on_surface=True
                                                  )
    if polygon_path is None:
        logger.warning("Exiting from the process since no anomaly area has been detected")
        return
    else:
        centroid_path_ver = add_polygon_time_series_means(
            polygon_path=polygon_path,
            centroid_path=centroid_path,
            series=imageTS[:,0,:,:],
            geo_transform=gt,
            projection=projection,
            output_path=os.path.join(result_path,f"anomaly_map_centroid_{start_date}_{end_date}_vertical.geojson"),
            field_names=list_feature_path,
            all_touched=False
        )
        centroid_path_ew = add_polygon_time_series_means(
                polygon_path=polygon_path,
                centroid_path=centroid_path,
                series=imageTS[:,1,:,:],
                geo_transform=gt,
                projection=projection,
                output_path=os.path.join(result_path,f"anomaly_map_centroid_{start_date}_{end_date}_ew.geojson"),
                field_names=list_feature_path,
                all_touched=False
            )
        logger.info("Salvataggio artefatto")
        upload_artifact(artifact_name="05_outputs", project_name=proj_name, src_path=result_path)

if __name__ == "__main__":
    _configure_logging()
    logger.info("Lettura parametri di input")
    if len(sys.argv) < 2:
        logger.error("Uso: python job_anomaly_detection.py '<json_input>'")
        sys.exit(1)
    try:
        parsed_input = _load_json_argument(sys.argv[1])
        main(parsed_input)
    except Exception:
        logger.exception("Il job è terminato con un errore non gestito.")
        sys.exit(1)
    