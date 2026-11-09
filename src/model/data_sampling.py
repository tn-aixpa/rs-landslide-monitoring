from osgeo import gdal, ogr, osr
import numpy as np
import digitalhub as dh
import os
import argparse
import zipfile
import random
from typing import Optional, Tuple, Union, Sequence

gdal.UseExceptions()
osr.UseExceptions()

def get_extent(
    image: Union[str, gdal.Dataset],
    target_srs: Optional[str] = None,
    densify_points: int = 21,
) -> Tuple[float, float, float, float]:
    """
    Compute the extent of a raster as (min_x, min_y, max_x, max_y).

    Parameters
    ----------
    image : str or gdal.Dataset
        Path of the raster or an already opened GDAL dataset.
    target_srs : str, optional
        If given (e.g. "EPSG:4326", WKT, PROJ string), the extent is returned in this
        CRS instead of the raster's own CRS.
    densify_points : int, optional
        Number of points sampled along each edge when reprojecting the extent
        (default 21). Reprojecting only the 4 corners can underestimate the
        extent, because straight edges become curves in another CRS.

    Returns
    -------
    (min_x, min_y, max_x, max_y)
        Extent in the raster CRS, or in target_srs if provided.
    """
    if isinstance(image, str):
        if not os.path.isfile(image):
            raise FileNotFoundError(f"Raster not found: {image}")
        ds = gdal.Open(image, gdal.GA_ReadOnly)
        close_ds = True
    else:
        ds = image
        close_ds = False

    try:
        gt = ds.GetGeoTransform()
        n_cols, n_rows = ds.RasterXSize, ds.RasterYSize
        src_wkt = ds.GetProjection()
    finally:
        if close_ds:
            ds = None

    def pixel_to_geo(col: float, row: float) -> Tuple[float, float]:
        # Full affine transform: also correct for rotated/skewed rasters
        x = gt[0] + col * gt[1] + row * gt[2]
        y = gt[3] + col * gt[4] + row * gt[5]
        return x, y

    if target_srs is None:
        corners = [pixel_to_geo(c, r) for c, r in
                   ((0, 0), (n_cols, 0), (0, n_rows), (n_cols, n_rows))]
        xs, ys = zip(*corners)
        return min(xs), min(ys), max(xs), max(ys)

    if not src_wkt:
        raise ValueError("The raster has no CRS: cannot reproject the extent.")

    src = osr.SpatialReference()
    src.ImportFromWkt(src_wkt)
    dst = osr.SpatialReference()
    dst.SetFromUserInput(target_srs)
    # Keep (x=easting/lon, y=northing/lat) order regardless of the CRS definition (GDAL >= 3)
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(src, dst)

    # Sample points along the 4 edges of the raster
    n = max(2, int(densify_points))
    steps = [i / (n - 1) for i in range(n)]
    edge_pixels = (
        [(s * n_cols, 0) for s in steps]
        + [(s * n_cols, n_rows) for s in steps]
        + [(0, s * n_rows) for s in steps]
        + [(n_cols, s * n_rows) for s in steps]
    )
    points = [transform.TransformPoint(*pixel_to_geo(c, r))[:2] for c, r in edge_pixels]
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)

def reproject_and_clip(
    input_path: str,
    output_path: str,
    target_resolution: Union[float, Sequence[float]],
    target_extent: Sequence[float],
    target_srs: Optional[str] = None,
    extent_srs: Optional[str] = None,
    resample_alg: str = "bilinear",
    dst_nodata: Optional[float] = None,
    output_format: str = "GTiff",
) -> str:
    """
    Reproject a raster to a target resolution and clip it to a target extent.

    Parameters
    ----------
    input_path : str
        Path of the input raster.
    output_path : str
        Path of the output raster.
    target_resolution : float or (xres, yres)
        Pixel size in the units of the target SRS (e.g. metres for EPSG:25832,
        degrees for EPSG:4326). A single value is used for both axes.
    target_extent : (min_x, min_y, max_x, max_y)
        Extent used to clip the output.
    target_srs : str, optional
        Target CRS (e.g. "EPSG:25832", WKT, PROJ string). If None, the CRS of the
        input raster is kept (resolution and extent are then interpreted in it).
    extent_srs : str, optional
        CRS in which target_extent is expressed. If None, it is assumed to be
        target_srs (or the input CRS when target_srs is None).
    resample_alg : str, optional
        Resampling algorithm: "near", "bilinear", "cubic", "cubicspline",
        "lanczos", "average", "mode", ... Use "near" for categorical data.
    dst_nodata : float, optional
        NoData value of the output. If None, the input NoData value is kept.
    output_format : str, optional
        GDAL driver name (default "GTiff").

    Returns
    -------
    str
        Path of the output raster.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input raster not found: {input_path}")

    if isinstance(target_resolution, (int, float)):
        x_res = y_res = float(target_resolution)
    else:
        if len(target_resolution) != 2:
            raise ValueError("target_resolution must be a number or an (xres, yres) pair.")
        x_res, y_res = (float(v) for v in target_resolution)
    if x_res <= 0 or y_res <= 0:
        raise ValueError("target_resolution values must be positive.")

    if len(target_extent) != 4:
        raise ValueError("target_extent must be (min_x, min_y, max_x, max_y).")
    min_x, min_y, max_x, max_y = (float(v) for v in target_extent)
    if min_x >= max_x or min_y >= max_y:
        raise ValueError(f"Invalid target_extent: {tuple(target_extent)}.")

    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)

    options = gdal.WarpOptions(
        format=output_format,
        dstSRS=target_srs,
        xRes=x_res,
        yRes=y_res,
        outputBounds=(min_x, min_y, max_x, max_y),
        outputBoundsSRS=extent_srs,
        resampleAlg=resample_alg,
        dstNodata=dst_nodata,
        multithread=True,
        creationOptions=["COMPRESS=DEFLATE", "TILED=YES"] if output_format == "GTiff" else None,
    )

    ds = gdal.Warp(output_path, input_path, options=options)
    if ds is None:
        raise RuntimeError(f"gdal.Warp failed for {input_path}")
    ds = None  # close the dataset to flush data to disk
    return output_path

def normalize_in_range(arr, feat_range=[0,1], min_value=-1, max_value=1):
    min_val = feat_range[0]
    max_val = feat_range[1]
    out = ((arr-min_val)/(max_val-min_val))*(max_value-min_value)+min_value
    return np.clip(out,min_value,max_value)

def resize_array(arr: np.ndarray, target_shape: tuple[int, int],
                 fill_value=0, anchor: str = "top-left") -> np.ndarray:
    """
    Adatta un array 2D a target_shape tramite crop (se troppo grande) e/o
    padding (se troppo piccolo), indipendentemente per righe e colonne.

    Parameters
    ----------
    arr : np.ndarray
        Array bidimensionale di input (non viene modificato).
    target_shape : tuple[int, int]
        Dimensioni desiderate (righe, colonne).
    fill_value : scalar, optional
        Valore usato per il padding (default 0). Con np.nan e array di tipo
        intero, il risultato viene promosso automaticamente a float.
    anchor : {"top-left", "center"}, optional
        "top-left": il contenuto resta ancorato in alto a sinistra
        (crop/padding sul lato destro e in basso).
        "center": crop/padding distribuiti in modo simmetrico.

    Returns
    -------
    np.ndarray
        Nuovo array di forma target_shape.
    """
    if arr.ndim != 2:
        raise ValueError(f"Atteso un array 2D, ricevuto con {arr1.ndim} dimensioni.")
    if len(target_shape) != 2 or any(int(d) != d or d <= 0 for d in target_shape):
        raise ValueError(f"target_shape deve contenere due interi positivi, ricevuto {target_shape}.")
    if anchor not in ("top-left", "center"):
        raise ValueError("anchor deve essere 'top-left' oppure 'center'.")

    def _offsets(src: int, dst: int):
        n = min(src, dst)  # numero di elementi da copiare lungo l'asse
        if anchor == "center":
            return (src - n) // 2, (dst - n) // 2, n
        return 0, 0, n

    s_r, d_r, n_r = _offsets(arr.shape[0], target_shape[0])
    s_c, d_c, n_c = _offsets(arr.shape[1], target_shape[1])

    out_dtype = np.result_type(arr.dtype, np.min_scalar_type(fill_value))
    out = np.full(target_shape, fill_value, dtype=out_dtype)
    out[d_r:d_r + n_r, d_c:d_c + n_c] = arr[s_r:s_r + n_r, s_c:s_c + n_c]
    return out

def main(parsed):
    maindir = "."
    data_folder = "data"
    output_folder = "output"
    input_folder = "input"

    proj_name = parsed.project
    patch_size = int(parsed.patch_size)
    offset_scale = int(parsed.offset_scale)
    non_valid_perc = float(parsed.non_valid_perc)
    data_path = os.path.join(maindir, data_folder, input_folder)
    output_path = os.path.join(maindir, data_folder, output_folder)
    training_path = os.path.join(output_path,"training")
    val_path = os.path.join(output_path,"val")
    feature_folder = os.path.join(data_path, "features")
    rainfall_map_folder = os.path.join(data_path, "rainfall_map")
    # historical_data_folder = os.path.join(rainfall_map_folder,"historical_data")
    print("Creazione cartelle")
    for folder in (data_path,training_path,val_path,feature_folder,rainfall_map_folder):
        os.makedirs(folder,exist_ok=True)
    print("Scaricamento artefatti")
    proj = dh.get_or_create_project(proj_name)
    feature_artifact = proj.get_artifact("03_features")
    feature_path = feature_artifact.download(feature_folder,overwrite=True)

    #proj_rainfall = dh.get_or_create_project("geo")
    rainfall_map_artifact = proj.get_artifact("rainfall_maps")
    rainfall_map_path = rainfall_map_artifact.download(rainfall_map_folder, overwrite=True)
    # with zipfile.ZipFile(rainfall_map_path, 'r') as zip_ref:
    #     zip_ref.extractall(historical_data_folder)
    #historical_data_path = os.path.join(historical_data_folder,"historical_data","output","climatology")
    valid_area_map_artifact = proj.get_artifact("valid_area_map")
    valid_area_map_path = valid_area_map_artifact.download(os.path.join(data_path,"valid_area_map.tif"), overwrite=True)

    print("Caricamento valid area map")
    list_feature_path = sorted(os.listdir(feature_path))
    ds = gdal.Open(os.path.join(feature_path,list_feature_path[0],"somma_cumulata_spostamento_verticale.tif"),gdal.GA_ReadOnly)
    rows = ds.RasterYSize
    cols = ds.RasterXSize
    gt = ds.GetGeoTransform()
    projection = ds.GetProjection()
    ds = None

    ds = gdal.Open(valid_area_map_path,gdal.GA_ReadOnly)
    valid_area_map = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    valid_area_map = resize_array(valid_area_map,(rows,cols))

    print("Caricamento rainfall map")
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
        ds=None

    print("Merge dati")    
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
    print("Normalizzazione")
    #normalization
    imageTS[:,0,:,:] = normalize_in_range(imageTS[:,0,:,:],feat_range=[-0.55,0.55], min_value=-1, max_value=1)
    imageTS[:,1,:,:] = normalize_in_range(imageTS[:,1,:,:],feat_range=[-0.55,0.55], min_value=-1, max_value=1)
    imageTS[:,2,:,:] = normalize_in_range(imageTS[:,2,:,:],feat_range=[0,800], min_value=0, max_value=1)
    print("Sampling")
    #sampling
    offset = patch_size//offset_scale
    n_split_rows = imageTS.shape[2]//offset
    n_split_cols = imageTS.shape[3]//offset
    dataset = []
    for i in range(n_split_rows):
        for j in range(n_split_cols):
            patch = imageTS[:,:,(i*offset):(i*offset)+patch_size,(j*offset):(j*offset)+patch_size]
            valid_patch = valid_area_map[(i*offset):(i*offset)+patch_size,(j*offset):(j*offset)+patch_size]
            if np.sum(valid_patch)>0 and not np.all(np.isnan(patch[:,:2,:,:])):
                dataset.append(patch)

    dataset = np.asarray(dataset, np.float32)
    #gestione nan
    dataset[np.isnan(dataset)] = 0
    #split dataset
    print("Divisione dataset")
    validation_size = int(dataset.shape[0]*0.1)
    index = random.sample(range(len(dataset)),validation_size)
    val = dataset[index]
    mask = np.ones(len(dataset),dtype=bool)
    mask[index] = False
    dataset = dataset[mask]
    #saving training set
    print("Salvataggio dataset")
    for i in range(len(dataset)):
        np.save(os.path.join(training_path,f"{i}.npy"),dataset[i])
    for i in range(len(val)):
            np.save(os.path.join(val_path,f"{i}.npy"),val[i])

    proj = dh.get_or_create_project(proj_name)
    proj.log_artifact("Dataset",kind="artifact",source=output_path)

if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument("-p","--project", type=str, help="The project name used to download and upload the artifacts")
    args.add_argument("--patch_size", type=int, default=128, help="The patch size used to sample the data. (default 128)")
    args.add_argument("--offset_scale", type=int, default=1, help="Value to scale the patch size and compute the sampling offset. (default 1)")
    args.add_argument("--non_valid_perc", type=float, default=0.0, help="Percentage of non stable areas allowed during the sampling. (default 0.0)")
    parsed = args.parse_args()
    main(parsed)