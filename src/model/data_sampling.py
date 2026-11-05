from osgeo import gdal, ogr
import numpy as np
import digitalhub as dh
import os
import argparse
import zipfile
import random

def normalize_in_range(arr, feat_range=[0,1], min_value=-1, max_value=1):
    min_val = feat_range[0]
    max_val = feat_range[1]
    out = ((arr-min_val)/(max_val-min_val))*(max_value-min_value)+min_value
    return np.clip(out,min_value,max_value)

def main(parsed):
    maindir = "."
    data_folder = "data"
    output_folder = "output"
    input_folder = "input"

    proj_name = parsed.project
    patch_size = parsed.patch_size
    data_path = os.path.join(maindir, data_folder, input_folder)
    output_path = os.path.join(maindir, data_folder, output_folder)
    training_path = os.path.join(output_path,"training")
    val_path = os.path.join(output_path,"val")
    feature_folder = os.path.join(data_path, "features")
    rainfall_map_folder = os.path.join(data_path, "rainfall_map")
    historical_data_folder = os.path.join(rainfall_map_folder,"historical_data")

    for folder in (data_path,training_path,val_path,feature_folder,rainfall_map_folder,historical_data_folder):
        os.makedirs(folder,exist_ok=True)

    proj = dh.get_or_create_project(proj_name)
    feature_artifact = proj.get_artifact("03_features")
    feature_path = feature_artifact.download(feature_folder,overwrite=True)

    proj_rainfall = dh.get_or_create_project("geo")
    rainfall_map_artifact = proj_rainfall.get_artifact("historical_data.zip")
    rainfall_map_path = rainfall_map_artifact.download(os.path.join(rainfall_map_folder,"rainfall_map.zip"), overwrite=True)
    with zipfile.ZipFile(rainfall_map_path, 'r') as zip_ref:
        zip_ref.extractall(historical_data_folder)
    #historical_data_path = os.path.join(historical_data_folder,"historical_data","output","climatology")
    rainmaps_list = sorted([file for file in os.listdir(historical_data_folder)])
    ds = gdal.Open(os.path.join(historical_data_folder,rainmaps_list[0]),gdal.GA_ReadOnly)
    rows_rainmap = ds.RasterYSize
    cols_rainmap = ds.RasterXSize
    ds = None
    rainmaps= np.zeros(len(rainmaps_list),rows_rainmap,cols_rainmap)
    for i, rainmap_file in enumerate(sorted(rainmaps_list)):
        rm_file = os.path.join(historical_data_folder,rainmap_file)
        ds = gdal.Open(rm_file,gdal.GA_ReadOnly)
        rainmaps[i,] += ds.GetRasterBand(1).ReadAsArray()


    valid_area_map_artifact = proj.get_artifact("valid_area_map")
    valid_area_map_path = valid_area_map_artifact.download(os.path.join(data_path,"valid_area_map.gpkg"), overwrite=True)

    list_feature_path = sorted(os.listdir(feature_path))
    ds = gdal.Open(os.path.join(feature_path,list_feature_path[0],"somma_cumulata_spostamento_verticale.tif"),gdal.GA_ReadOnly)
    rows = ds.RasterYSize
    cols = ds.RasterXSize
    gt = ds.GetGeoTrasform()
    projection = ds.GetProjection()
    ds = None

    source_ds = ogr.Open(valid_area_map_path)
    source_layer = source_ds.GetLayer()

    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(data_path,"valid_area_map.tif"),
                                                     cols, rows, 1, gdal.GDT_Byte)
    target_ds.SetGeoTransform(gt)
    target_ds.SetProjection(projection)
    band = target_ds.GetRasterBand(1)
    band.SetNoDataValue(0)
    gdal.RasterizeLayer(target_ds, [1], source_layer, burn_values=[0])
    source_ds = None
    target_ds= None

    valid_area_map_ds = gdal.Open(os.path.join(data_path,"valid_area_map.tif"),gdal.GA_ReadOnly)
    valid_area_map = valid_area_map_ds.GetRasterBand(1).ReadAsArray()
    valid_area_map_ds = None

    imageTS = np.zeros((3,len(list_feature_path),rows,cols),np.float32)

    for i, path in enumerate(list_feature_path):
        f_path = os.path.join(feature_path,path)
        vertical_displ_sum_ds = gdal.Open(os.path.join(f_path,"somma_cumulata_spostamento_verticale.tif"), gdal.GA_ReadOnly)
        imageTS[0,i,:,:] = vertical_displ_sum_ds.GetRasterBand(1).ReadAsArray()
        vertical_displ_sum_ds = None

        horizontal_displ_sum_ds = gdal.Open(os.path.join(f_path,"somma_cumulata_spostamento_orizzontale.tif"), gdal.GA_ReadOnly)
        imageTS[1,i,:,:] = horizontal_displ_sum_ds.GetRasterBand(1).ReadAsArray()
        horizontal_displ_sum_ds = None
    imageTS[2,] = np.copy(rainmaps)

    #normalization
    imageTS[0,] = normalize_in_range(imageTS[0,],feat_range=[-0.55,0.55], min_value=-1, max_value=1)
    imageTS[1,] = normalize_in_range(imageTS[1,],feat_range=[-0.55,0.55], min_value=-1, max_value=1)
    imageTS[2,] = normalize_in_range(imageTS[2,],feat_range=[0,800], min_value=0, max_value=1)
    #sampling
    offset = patch_size
    n_split_rows = imageTS.shape[2]//offset
    n_split_cols = imageTS.shape[3]//offset
    dataset = []
    for i in range(n_split_rows):
        for j in range(n_split_cols):
            patch = imageTS[:,:,(i*offset):(i*offset)+offset,(j*offset):(j*offset)+offset]
            valid_patch = valid_area_map[(i*offset):(i*offset)+offset,(j*offset):(j*offset)+offset]
            if np.sum(valid_patch)>0 and not np.all(np.isnan(patch)):
                dataset.append(patch)

    dataset = np.asarray(dataset, np.float32)
    #gestione nan
    validation_size = int(dataset.shape[0]*0.1)
    index = random.sample(range(len(dataset)),validation_size)
    val = dataset[index]
    mask = np.ones(len(dataset),dtype=np.bool)
    mask[index] = False
    dataset = dataset[mask]
    #saving training set
    for i in range(len(dataset)):
        np.save(os.path.join(training_path,f"{i}.npy"),dataset[i])
    for i in range(len(val)):
            np.save(os.path.join(val_path,f"{i}.npy"),val[i])

    proj = dh.get_or_create_project(proj_name)
    proj.log_artifact("Dataset",kind="artifact",source=output_path)

if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument("-p","--project", type=str, help="The project name used to download and upload the artifacts")
    args.add_argument("--patch_size", type=str, help="The patch size used to sample the data")
    parsed = args.parse_args()
    main(parsed)