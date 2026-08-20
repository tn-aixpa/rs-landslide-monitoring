import sys
import json
import os,gc
import tempfile
import numpy as np
import shutil
import digitalhub as dh
from core.skd_handler import upload_artifact
from osgeo import gdal
gdal.UseExceptions()
from shapely.wkt import loads
import geopandas as gpd
import zipfile
import warnings
import logging
import re
from pathlib import Path
from datetime import datetime

tempfile.tempdir

logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d [%(threadName)s] %(levelname)-5s %(name)s.%(funcName)s - %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    )


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

    # --- 1. Raccogli tutte le cartelle valide con le loro date ---
    valid_folders: list[tuple[str, datetime, datetime]] = []

    for folder in base.iterdir():
        if not folder.is_dir():
            continue
        if not pattern.match(folder.name):
            continue

        parts = folder.name.split('_')
        try:
            date_start = datetime.strptime(parts[0], '%Y%m%d')
            date_end   = datetime.strptime(parts[1], '%Y%m%d')
        except ValueError:
            continue

        valid_folders.append((folder.name, date_start, date_end))

    if not valid_folders:
        print("Nessuna cartella nel formato YYYYMMDD_YYYYMMDD trovata.")
        return []

    # --- 2. Trova la data più recente tra tutte le cartelle ---
    most_recent_date = max(date_end for _, _, date_end in valid_folders)

    # --- 3. Calcola la cutoff: n mesi prima della data più recente ---
    month = most_recent_date.month - n_months
    year  = most_recent_date.year
    if month <= 0:
        month += 12
        year  -= 1
    cutoff_date = most_recent_date.replace(year=year, month=month)

    print(f"Data più recente trovata: {most_recent_date.strftime('%d/%m/%Y')}")
    print(f"Cutoff ({n_months} mesi prima): {cutoff_date.strftime('%d/%m/%Y')}\n")

    # --- 4. Filtra le cartelle con data di fine >= cutoff ---
    selected = [
        name
        for name, _, date_end in valid_folders
        if date_end >= cutoff_date
    ]

    return sorted(selected)

def v_ew_displ(path :str,list_filenames: list) -> np.float32:
    """
    Parameters
    ----------
    path : str
        path of the folder containing the files to process.
    list_filenames : list
        the list of the files to process.

    Returns
    -------
    v_displ_time_series: np.float32
        an array containing all the vetical displacement maps in the time series.
    ew_displ_time_series: np.float32
        an array containing all the east-west displacement maps in the time series.
    coh_time_series: np.float32
        an array containing all the coherence maps in the time series.
    asc_time_series: np.float32
        an array containing the total displacement in the time series acquired in the ascending direction
    desc_time_series: np.float32
        an array containing the total displacement in the time series acquired in the descending direction
    coh_asc_time_series: np.float32
        an array containing the coherence map time series acquired in ascending direction
    coh_desc_time_series: np.float32
        an array containing the coherence map time series acquired in descending direction
    proj: string
        projection of the output files
    geoT: list
        the geo transformation of the output files
    """
    n_time = len(list_filenames)
    for i,f in enumerate(list_filenames):
        file_path = os.path.join(path,f)
        asc_file_path = os.path.join(file_path,"ascending")
        desc_file_path = os.path.join(file_path,"descending")

        filename_ascending = [fi for fi in os.listdir(asc_file_path) if "mosaic.tif" in fi][0]
        filename_descending = [fi for fi in os.listdir(desc_file_path) if "mosaic.tif" in fi][0]
        
        #reading ascending and descending images
        print(r"Reading: {}".format(os.path.join(asc_file_path,filename_ascending)))
        logging.info(f"Reading: {os.path.join(asc_file_path,filename_ascending)}")
        ds = gdal.Open(os.path.join(asc_file_path,filename_ascending),gdal.GA_ReadOnly)
        if i==0:
            v_displ_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            ew_displ_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            coh_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            asc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            desc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            coh_asc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            coh_desc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            inc_angle_asc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            inc_angle_desc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            
        asc = ds.GetRasterBand(1).ReadAsArray()
        coh_asc = ds.GetRasterBand(2).ReadAsArray()
        inc_angle_asc = ds.GetRasterBand(3).ReadAsArray()
        ds = None
        print(r"Reading: {}".format(os.path.join(desc_file_path,filename_descending)))
        logging.info(f"Reading: {os.path.join(desc_file_path,filename_descending)}")
        ds = gdal.Open(os.path.join(desc_file_path,filename_descending),gdal.GA_ReadOnly)
        desc = ds.GetRasterBand(1).ReadAsArray()
        coh_desc = ds.GetRasterBand(2).ReadAsArray()
        inc_angle_desc = ds.GetRasterBand(3).ReadAsArray()
        ds = None
        #vertical and east-west displacement calculation
        v_asc = np.divide(asc,np.cos(inc_angle_asc*(np.pi/180)))
        ew_asc = np.divide(asc,np.sin(inc_angle_asc*(np.pi/180)))
        v_desc = np.divide(desc,np.cos(inc_angle_desc*(np.pi/180)))
        ew_desc = np.divide(desc,np.sin(inc_angle_desc*(np.pi/180)))
        v_displ_time_series[:,:,i] = -np.mean(np.array([v_asc,v_desc]),axis=0)
        ew_displ_time_series[:,:,i] = (ew_asc-ew_desc)/2
        coh_time_series[:,:,i] = np.mean(np.array([coh_asc,coh_desc]),axis=0)
        asc_time_series[:,:,i] = np.copy(asc)
        desc_time_series[:,:,i] = np.copy(desc)
        coh_asc_time_series[:,:,i] = np.copy(coh_asc)
        coh_desc_time_series[:,:,i] = np.copy(coh_desc)
        inc_angle_asc_time_series[:,:,i] = np.copy(inc_angle_asc)
        inc_angle_desc_time_series[:,:,i] = np.copy(inc_angle_desc)
    return v_displ_time_series, ew_displ_time_series, coh_time_series, asc_time_series, desc_time_series,coh_asc_time_series, coh_desc_time_series, proj, geoT, inc_angle_asc_time_series, inc_angle_desc_time_series


# python main.py "{'s1_ascending':'s1_ascending', 's1_descending': 's1_descending', 'startDate':'2020-11-01', 'endDate':'2021-02-28','outputArtifactName': 'landslide_output', 'shapeArtifactName': 'Shapes_TN', 'shapeFileName': 'ammprv_v.shp', 'mapArtifactName': 'Map', 'geomWKT': 'POLYGON ((11.687737 46.134408, 11.773911 46.134408, 11.773911 46.174363, 11.687737 46.174363, 11.687737 46.134408))'}"

if __name__ == "__main__":

    global output_path, unwrap_folder,trentino_boundary_path,geo_wkt

    args = sys.argv[1].replace("'","\"")
    json_input = json.loads(args)
    maindir = '.'
    data_folder = 'data'
    preprocessed_folder = '02_pre_processed'
    temp_folder = 'tmp'
    output_folder = 'output'
    input_folder = 'input'
    phase_wrapping_folder = 'phase_unwrapping'

    # read input parameters
    preprocessed_artifact = json_input.get('preprocessedArtifactName') #preprocessed artifact name (e.g., '02_pre_processed')
    output_artifact_name=json_input['outputArtifactName'] #output artifact name (e.g., 'deforestation_output')
    mapArtifact = json_input.get('mapArtifactName')
    
    project_name=os.environ["PROJECT_NAME"] #project name (e.g., 'landslide-monitoring')
    
    # define paths
    data_path = os.path.join(maindir, data_folder, input_folder)
    preprocessed_path = os.path.join(data_path, preprocessed_folder)
    previous_feature_artifact_path = os.path.join(data_path, 'previous_feature_artifact')
    result_path = os.path.join(maindir, data_folder, output_folder)
    input_map_folder = os.path.join(data_path,'maps')
    
    # create data folders
    if not os.path.exists(data_path):
        os.makedirs(data_path)  
    # create result folder
    if not os.path.exists(result_path):
        os.makedirs(result_path)
    # create input map folder
    if not os.path.exists(input_map_folder):
        os.makedirs(input_map_folder)
    os.makedirs(preprocessed_path, exist_ok=True)
    os.makedirs(previous_feature_artifact_path, exist_ok=True)

    print(f"Input parameters: preprocessed_artifact={preprocessed_artifact}, output_artifact_name={output_artifact_name}, mapArtifact={mapArtifact}")
    logging.info(f"Input parameters: preprocessed_artifact={preprocessed_artifact}, output_artifact_name={output_artifact_name}, mapArtifact={mapArtifact}")
    # download data
    project = dh.get_or_create_project(project_name)
    print(f"Downloading artifacts for project: {project_name}")
    logging.info(f"Downloading artifacts for project: {project_name}")
    # download s1 ascending data
    print(f"Downloading artifact: {preprocessed_artifact} inside {preprocessed_path}")  
    logging.info(f"Downloading artifact: {preprocessed_artifact} inside {preprocessed_path}")
    preprocessed_data = project.get_artifact(preprocessed_artifact)
    input_path = preprocessed_data.download(preprocessed_path, overwrite=True)
    # download map files if provided
    print(f"Downloading map artifact: {mapArtifact} inside {input_map_folder}")
    logging.info(f"Downloading map artifact: {mapArtifact} inside {input_map_folder}")
    map_data = project.get_artifact(mapArtifact)
    input_map_folder = map_data.download(input_map_folder, overwrite=True)    
    trentino_slope_map_path = os.path.join(input_map_folder,'trentino_slope_map.tif')
    trentino_aspect_map_path = os.path.join(input_map_folder,'trentino_aspect_map.tif')
    legend_path = os.path.join(input_map_folder,'legend.qml')
    input_json_path = os.path.join(input_path,'sensor_angles.json')
    if "03_features" in project.list_artifacts():
        print(f"Downloading previous feature artifact 03_features inside {previous_feature_artifact_path}")
        logging.info(f"Downloading previous feature artifact 03_features inside {previous_feature_artifact_path}")
        previous_feature_artifact = project.get_artifact("03_features")
        previous_feature_path = previous_feature_artifact.download(previous_feature_artifact_path, overwrite=True)

    print("Data downloaded successfully.")   
    logging.info("Data downloaded successfully.")

    print(f"preprocessed_path = {preprocessed_path}")
    print(f"trentino_slope_map_path = {trentino_slope_map_path}")
    print(f"trentino_aspect_map_path = {trentino_aspect_map_path}")
    print(f"legend_path = {legend_path}")

    with open(input_json_path, "r") as f:
        theta_dict = json.load(f)
    list_theta_ascending = theta_dict["ascending"]
    list_theta_descending = theta_dict["descending"]
    
    # Step 2. // To calculate the vertical and east-west displacements from the interferometric data
    # The vertical and east-west displacements are calculated from the interferometric data,
    # and the results are stored in the output_path directory.
    print("Calculating vertical and east-west displacements...")
    logging.info("Calculating vertical and east-west displacements...")
    #come prendere solo i nomi dei file acquisisti gli ultimi 4 mesi?
    list_filenames = get_folders_last_months(input_path,n_months=4)
    list_theta_ascending = list_theta_ascending[-len(list_filenames):]
    list_theta_descending = list_theta_descending[-len(list_filenames):]
    starting_date = list_filenames[0].split("_")[0]
    ending_date = list_filenames[-1].split("_")[1]

    print(f"Found {len(list_filenames)} subdirectories in {input_path}")
    logging.info(f"Found {len(list_filenames)} subdirectories in {input_path}")
    #calculate the vertical and east-west displacements
    v_displ_maps, ew_displ_maps, coh_maps, asc, desc, coh_asc, coh_desc, proj, geoT, inc_angle_asc, inc_angle_desc= v_ew_displ(input_path, list_filenames)
    #keep only the interferometry maps with a mean coherence value higher than 0.3
    mean_coh = np.average(coh_maps,axis=(0,1))
    th = 0.3
    n_time = ew_displ_maps.shape[2]
    offset_ew_displ_maps = np.zeros(n_time,dtype=np.float32)
    offset_v_displ_maps = np.zeros(n_time,dtype=np.float32)
    offset_asc = np.zeros(n_time,dtype=np.float32)
    offset_desc = np.zeros(n_time,dtype=np.float32)
    for i in range(n_time):
        most_coh_points = coh_maps[:,:,i]>0.9
        offset_ew_displ_maps[i] = np.mean(ew_displ_maps[:,:,i][most_coh_points])
        offset_v_displ_maps[i] = np.mean(v_displ_maps[:,:,i][most_coh_points])
        offset_asc[i] = np.mean(asc[:,:,i][most_coh_points])
        offset_desc[i] = np.mean(desc[:,:,i][most_coh_points])
    ew_displ_maps -= offset_ew_displ_maps
    v_displ_maps -= offset_v_displ_maps
    asc -= offset_asc
    desc -= offset_desc
    keep_img_mask = np.logical_and(mean_coh>=th)#(np.logical_and(np.max(ew_displ_maps,axis=(0,1))<1,
                                  #np.min(ew_displ_maps,axis=(0,1))>-1),mean_coh>=th)
    if np.sum(keep_img_mask)==0:
        warnings.warn("No interferogram with mean coherence higher than {}. Skipping generation of tiff files for data insufficiency.".format(th))
        logging.warning("No interferogram with mean coherence higher than {}. Skipping generation of tiff files for data insufficiency.".format(th))
    else:
        keep_list_filenames = [list_filenames[i] for i in range(len(list_filenames)) if keep_img_mask[i]]
        keep_list_tetha_ascending = [list_theta_ascending[i] for i in range(len(list_theta_ascending)) if keep_img_mask[i]]
        keep_list_tetha_descending = [list_theta_descending[i] for i in range(len(list_theta_descending)) if keep_img_mask[i]]

        v_displ_maps = v_displ_maps[:,:,keep_img_mask]
        ew_displ_maps = ew_displ_maps[:,:,keep_img_mask]
        coh_maps = coh_maps[:,:,keep_img_mask]
        asc = asc[:,:,keep_img_mask]
        desc = desc[:,:,keep_img_mask]
        coh_asc = coh_asc[:,:,keep_img_mask]
        coh_desc = coh_desc[:,:,keep_img_mask]
        inc_angle_asc = inc_angle_asc[:,:,keep_img_mask]
        inc_angle_desc = inc_angle_desc[:,:,keep_img_mask]

        #compute the average over time
        avg_coh_map = np.average(coh_maps,axis=-1)
        masked_v_displ_maps = np.copy(v_displ_maps)
        masked_ew_displ_maps = np.copy(ew_displ_maps)

        cum_sum_ew_displ_map = np.sum(ew_displ_maps,axis=-1)
        masked_cum_sum_ew_displ_map = np.copy(cum_sum_ew_displ_map)
        masked_cum_sum_ew_displ_map[avg_coh_map<0.4] = np.nan
        
        cum_sum_v_displ_map = np.sum(v_displ_maps,axis=-1)
        masked_cum_sum_v_displ_map = np.copy(cum_sum_v_displ_map)
        masked_cum_sum_v_displ_map[avg_coh_map<0.4] = np.nan
        
        cum_sum_asc = np.sum(asc,axis=-1)
        cum_sum_desc = np.sum(desc,axis=-1)
        avg_coh_asc = np.average(coh_asc,axis=-1)
        avg_coh_desc = np.average(coh_desc, axis=-1)
        masked_cum_sum_asc = np.copy(cum_sum_asc)
        masked_cum_sum_asc[avg_coh_asc<0.4] = np.nan
        masked_cum_sum_desc = np.copy(cum_sum_desc)
        masked_cum_sum_desc[avg_coh_desc<0.4] = np.nan

        mask_AOI = np.logical_or(np.logical_and(masked_cum_sum_asc>0,masked_cum_sum_desc<0),
                                np.logical_and(masked_cum_sum_asc<0,masked_cum_sum_desc>0))
        cum_sum_ew_displ_map_AOI = np.copy(cum_sum_ew_displ_map)
        cum_sum_ew_displ_map_AOI[np.logical_not(mask_AOI)] = np.nan
        cum_sum_v_displ_map_AOI = np.copy(cum_sum_v_displ_map)
        cum_sum_v_displ_map_AOI[np.logical_not(mask_AOI)] = np.nan

        ds_trans = gdal.Open(trentino_slope_map_path,gdal.GA_ReadOnly)
        slope_map = ds_trans.GetRasterBand(1).ReadAsArray()
        ds_trans = None
        ds_trans = gdal.Open(trentino_aspect_map_path,gdal.GA_ReadOnly)
        aspect_map = ds_trans.GetRasterBand(1).ReadAsArray()
        ds_trans = None
        #compute the c coefficient in ascending and descending
        c_ascending_time_series = np.zeros(inc_angle_asc.shape,dtype=np.float32)
        for i_c in range(c_ascending_time_series.shape[2]):
            print("Platform heading angle ascending for time step {}: {}".format(i_c,keep_list_tetha_ascending[i_c]))
            N = -np.sin(np.deg2rad(inc_angle_asc[:,:,i_c]))*np.cos(np.deg2rad(keep_list_tetha_ascending[i_c]))-(3*np.pi/2)
            E = -np.sin(np.deg2rad(inc_angle_asc[:,:,i_c]))*np.sin(np.deg2rad(keep_list_tetha_ascending[i_c]))-(3*np.pi/2)
            H = np.cos(np.deg2rad(inc_angle_asc[:,:,i_c]))
            c = (np.cos(np.deg2rad(slope_map))*np.sin(np.deg2rad(aspect_map-90))*N)+((-np.cos(np.deg2rad(slope_map))*np.sin(np.deg2rad(aspect_map-90)))*E)+(np.sin(np.deg2rad(slope_map)*H))
            c_ascending_time_series[:,:,i_c] = np.copy(c)
        
        c_descending_time_series = np.zeros(inc_angle_desc.shape,dtype=np.float32)
        for i_c in range(c_descending_time_series.shape[2]):
            print("Platform heading angle descending for time step {}: {}".format(i_c,keep_list_tetha_descending[i_c]))
            N = -np.sin(np.deg2rad(inc_angle_desc[:,:,i_c]))*np.cos(np.deg2rad(keep_list_tetha_descending[i_c]))-(3*np.pi/2)
            E = -np.sin(np.deg2rad(inc_angle_desc[:,:,i_c]))*np.sin(np.deg2rad(keep_list_tetha_descending[i_c]))-(3*np.pi/2)
            H = np.cos(np.deg2rad(inc_angle_desc[:,:,i_c]))
            c = (np.cos(np.deg2rad(slope_map))*np.sin(np.deg2rad(aspect_map-90))*N)+((-np.cos(np.deg2rad(slope_map))*np.sin(np.deg2rad(aspect_map-90)))*E)+(np.sin(np.deg2rad(slope_map)*H))
            c_descending_time_series[:,:,i_c] = np.copy(c)

        #save the stacked masked vertical displacement maps
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,f'{starting_date}_{ending_date}', 'serie_temporale_scostamento_verticale.tif'), 
                                        masked_v_displ_maps.shape[1], masked_v_displ_maps.shape[0], masked_v_displ_maps.shape[2], gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        for i in range(masked_v_displ_maps.shape[2]):
            masked_v_displ_maps[:,:,i][coh_maps[:,:,i]<0.6] = np.nan
            target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
            target_ds.GetRasterBand(i+1).WriteArray(masked_v_displ_maps[:,:,i])
        target_ds = None
        gc.collect()
        
        #save the masked cumulative vertical displacement maps
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,f'{starting_date}_{ending_date}', 'somma_cumulata_spostamento_verticale.tif'), 
                                        masked_cum_sum_v_displ_map.shape[1], masked_cum_sum_v_displ_map.shape[0], 1, gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_v_displ_map)
        target_ds = None
        gc.collect()
        
        #save the stacked masked east-west displacement maps
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,f'{starting_date}_{ending_date}', 'serie_temporale_scostamento_orizzontale.tif'), 
                                        masked_ew_displ_maps.shape[1], masked_ew_displ_maps.shape[0], masked_ew_displ_maps.shape[2], gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        for i in range(masked_ew_displ_maps.shape[2]):
            masked_ew_displ_maps[:,:,i][coh_maps[:,:,i]<0.6] = np.nan
            target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
            target_ds.GetRasterBand(i+1).WriteArray(masked_ew_displ_maps[:,:,i])
        target_ds = None
        gc.collect()

        #save the masked cumulative east-west displacement map
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,f'{starting_date}_{ending_date}', 'somma_cumulata_spostamento_orizzontale.tif'), 
                                        masked_cum_sum_ew_displ_map.shape[1], masked_cum_sum_ew_displ_map.shape[0], 1, gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_ew_displ_map)
        target_ds = None
        gc.collect()
        
        #save the stacked masked total displacement maps ascending
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,f'{starting_date}_{ending_date}', 'serie_temporale_scostamento_totale_ascendente.tif'), 
                                        asc.shape[1], asc.shape[0], asc.shape[2], gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        for i in range(asc.shape[2]):
            asc[:,:,i][coh_asc[:,:,i]<0.6] = np.nan
            target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
            target_ds.GetRasterBand(i+1).WriteArray(asc[:,:,i])
        target_ds = None
        gc.collect()
        
        #save the masked cumulative total displacement map ascending
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,f'{starting_date}_{ending_date}', 'somma_cumulata_scostamento_totale_ascendente.tif'), 
                                        masked_cum_sum_asc.shape[1], masked_cum_sum_asc.shape[0], 1, gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_asc)
        target_ds = None
        gc.collect()
        
        #save the stacked masked total displacement maps descending
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,f'{starting_date}_{ending_date}', 'serie_temporale_scostamento_totale_discendente.tif'), 
                                        desc.shape[1], desc.shape[0], desc.shape[2], gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        for i in range(desc.shape[2]):
            desc[:,:,i][coh_desc[:,:,i]<0.6] = np.nan
            target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
            target_ds.GetRasterBand(i+1).WriteArray(desc[:,:,i])
        target_ds = None
        gc.collect()
        
        #save the masked cumulative total displacement map ascending
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,f'{starting_date}_{ending_date}', 'somma_cumulata_scostamento_totale_discendente.tif'), 
                                        masked_cum_sum_desc.shape[1], masked_cum_sum_desc.shape[0], 1, gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_desc)
        target_ds = None
        gc.collect()
        
        #save the average coherence map
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,f'{starting_date}_{ending_date}', 'mappa_coerenza_media.tif'), 
                                        avg_coh_map.shape[1], avg_coh_map.shape[0], 1, gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        target_ds.GetRasterBand(1).WriteArray(avg_coh_map)
        target_ds = None
        gc.collect()
        
        #save the stacked coherence maps
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path, f'{starting_date}_{ending_date}', 'serie_temporale_mappe_coerenza.tif'), 
                                        avg_coh_map.shape[1], avg_coh_map.shape[0], coh_maps.shape[2], gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        for i in range(coh_maps.shape[2]):
            target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
            target_ds.GetRasterBand(i+1).WriteArray(coh_maps[:,:,i])
        target_ds = None
        gc.collect()
        
        #save the average coherence map ascending
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path, f'{starting_date}_{ending_date}', 'mappa_coerenza_media_ascendente.tif'), 
                                        avg_coh_asc.shape[1], avg_coh_asc.shape[0], 1, gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        target_ds.GetRasterBand(1).WriteArray(avg_coh_asc)
        target_ds = None
        gc.collect()
        
        #save the stacked coherence maps
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path, f'{starting_date}_{ending_date}', 'serie_temporale_mappe_coerenza_ascendente.tif'), 
                                        coh_asc.shape[1], coh_asc.shape[0], coh_asc.shape[2], gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        for i in range(coh_asc.shape[2]):
            target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
            target_ds.GetRasterBand(i+1).WriteArray(coh_asc[:,:,i])
        target_ds = None
        gc.collect()
        
        #save the average coherence map descending
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path, f'{starting_date}_{ending_date}', 'mappa_coerenza_media_discendente.tif'), 
                                        avg_coh_desc.shape[1], avg_coh_desc.shape[0], 1, gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        target_ds.GetRasterBand(1).WriteArray(avg_coh_desc)
        target_ds = None
        gc.collect()
        
        #save the stacked coherence maps
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path, f'{starting_date}_{ending_date}', 'serie_temporale_mappe_coerenza_discendente.tif'), 
                                        coh_desc.shape[1], coh_desc.shape[0], coh_desc.shape[2], gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        for i in range(coh_desc.shape[2]):
            target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
            target_ds.GetRasterBand(i+1).WriteArray(coh_desc[:,:,i])
        target_ds = None
        gc.collect()

        #save the areas of interest cumulative east-west displacement map
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path, f'{starting_date}_{ending_date}', 'somma_cumulata_scostamento_orizzontale_AOI.tif'), 
                                        cum_sum_ew_displ_map_AOI.shape[1], cum_sum_ew_displ_map_AOI.shape[0], 1, gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        target_ds.GetRasterBand(1).WriteArray(cum_sum_ew_displ_map_AOI)
        target_ds = None
        gc.collect()

        #save the areas of interest cumulative vertical displacement map
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path, f'{starting_date}_{ending_date}', 'somma_cumulata_scostamento_verticale_AOI.tif'), 
                                        cum_sum_v_displ_map_AOI.shape[1], cum_sum_v_displ_map_AOI.shape[0], 1, gdal.GDT_Float32,
                                        options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        target_ds.GetRasterBand(1).WriteArray(cum_sum_v_displ_map_AOI)
        target_ds = None
        gc.collect()

        #save the 1/c coefficient ascending
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path, f'{starting_date}_{ending_date}', 'serie_temporale_coefficiente_c_ascendente.tif'), 
                                        c_ascending_time_series.shape[1], c_ascending_time_series.shape[0], c_ascending_time_series.shape[2], 
                                        gdal.GDT_Float32,options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        for i in range(c_ascending_time_series.shape[2]):
            target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
            target_ds.GetRasterBand(i+1).WriteArray(c_ascending_time_series[:,:,i])
        target_ds = None
        gc.collect()

        #save the 1/c coefficient descending
        target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path, f'{starting_date}_{ending_date}', 'serie_temporale_coefficiente_c_discendente.tif'), 
                                        c_descending_time_series.shape[1], c_descending_time_series.shape[0], c_descending_time_series.shape[2], 
                                        gdal.GDT_Float32,options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        target_ds.SetGeoTransform(geoT)
        target_ds.SetProjection(proj)
        for i in range(c_descending_time_series.shape[2]):
            target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
            target_ds.GetRasterBand(i+1).WriteArray(c_descending_time_series[:,:,i])
        target_ds = None
        gc.collect()

        shutil.copy(legend_path,os.path.join(result_path, f'{starting_date}_{ending_date}', 'legend.qml'))

        if len(previous_feature_artifact_path) == 0:
            upload_artifact(artifact_name = "03_features", project_name = project_name, src_path = result_path)
        else:
            print(f"Artifact 03_features already exists in project {project_name}. Updating the artifact with new data.")
            logging.info(f"Artifact 03_features already exists in project {project_name}. Updating the artifact with new data.")
            shutil.copytree(previous_feature_artifact_path, result_path, dirs_exist_ok=True)
            upload_artifact(artifact_name = "03_features", project_name = project_name, src_path = result_path)

    print("Processing completed.")