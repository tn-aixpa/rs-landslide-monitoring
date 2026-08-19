import os
import sys
import json
from snapista import Operator
from snapista import Graph
import snaphu
import tempfile
import numpy as np
import shutil
import digitalhub as dh
from utils.skd_handler import upload_artifact
from osgeo import gdal
gdal.UseExceptions()
import subprocess
import zipfile
import xml.etree.ElementTree as ET
import warnings
import logging

tempfile.tempdir

logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d [%(threadName)s] %(levelname)-5s %(name)s.%(funcName)s - %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S",
    )

def interferometry(input_path,filename1,filename2,output_path,subswath="IW1"):
    """
    Esegue l'interferometria tra immagini Sentinel-1
    Parameters    ----------
    input_path : str
        The path to the directory containing the input files.
    filename1 : str
        The name of the first input file.
    filename2 : str
        The name of the second input file.
    output_path : str
        The path to the directory where the output files will be saved.
    subswath : str, optional
        The subswath to process (default is "IW1").
    
    Returns
    -------
    tetha : np.float32
        The platform heading angle extracted from the metadata of the first input file.
    """
    iw = subswath
    output_path = os.path.join(output_path,subswath)
    if not os.path.isdir(output_path):
        os.makedirs(output_path)
    if os.path.isdir(unwrap_folder):
       shutil.rmtree(unwrap_folder)
    if not os.path.isdir(unwrap_folder):
       os.makedirs(unwrap_folder)
    if len(os.listdir(unwrap_folder))>0:
        for f in os.listdir(unwrap_folder):
            file_path = os.path.join(unwrap_folder,f)
            shutil.rmtree(file_path)
    convert_month = {'01':'Jan',
                     '02':'Feb',
                     '03':'Mar',
                     '04':'Apr',
                     '05':'May',
                     '06':'Jun',
                     '07':'Jul',
                     '08':'Aug',
                     '09':'Sep',
                     '10':'Oct',
                     '11':'Nov',
                     '12':'Dec'}
    file1 = os.path.join(input_path, filename1)
    file2 = os.path.join(input_path, filename2)
    d1 = filename1[17:25]
    d2 = filename2[17:25]
    data1 = d1[-2:]+convert_month[d1[4:6]]+d1[:4]
    data2 = d2[-2:]+convert_month[d2[4:6]]+d2[:4]

    archive1 = zipfile.ZipFile(file1,'r')
    platHeading = 0
    for name in archive1.namelist():
        if (not 'calibration' in name) and (not 'rfi' in name) and ('annotation' in name) and (iw.lower() in name) and ('vv' in name):
            print("Reading platform heading from: {}".format(name))
            metadata1 = archive1.open(name)
            tree = ET.parse(metadata1)
            root = tree.getroot()
            ga = root.find('generalAnnotation')
            prodInfo = ga.find('productInformation')
            platHeading = np.float32(prodInfo.find('platformHeading').text)
    archive1.close()
    tetha = np.copy(platHeading)
    
    print("Lettura:\n{}\n{}".format(file1,file2))
    logging.info("Reading files: {} and {}".format(file1,file2))
    g1 = Graph()
    g1.add_node(Operator("Read",formatName="SENTINEL-1",file=file1), node_id="read1")
    g1.add_node(Operator("Read",formatName="SENTINEL-1",file=file2), node_id="read2")
    
    #TOPS Split
    print("Coregistrazione")
    logging.info("Coregistrazione")
    tops_split1 = Operator("TOPSAR-Split")
    tops_split1.subswath = iw
    tops_split1.selectedPolarisations = "VV"
    tops_split1.firstBurstIndex = '1'
    tops_split1.lastBurstIndex = '9'
    tops_split2 = Operator("TOPSAR-Split")
    tops_split2.subswath = iw
    tops_split2.selectedPolarisations = "VV"
    tops_split2.firstBurstIndex = '1'
    tops_split2.lastBurstIndex = '9'
    g1.add_node(tops_split1,node_id="TOPS-SPLIT1",source="read1")
    g1.add_node(tops_split2, node_id="TOPS-SPLIT2",source="read2")
    
    # #Apply orbit
    file1orbit = filename1[:-9]+"_split_Orb"
    file2orbit = filename2[:-9]+"_split_Orb"
    orbit = Operator("Apply-Orbit-File",orbitType="Sentinel Precise (Auto Download)",continueOnFail="true")
    g1.add_node(orbit,node_id="orbit1",source="TOPS-SPLIT1")
    g1.add_node(orbit,node_id="orbit2",source="TOPS-SPLIT2")
    g1.add_node(Operator("Write", file=os.path.join(output_path,file1orbit+".dim")),
               node_id="writer1orbit",source="orbit1")
    g1.add_node(Operator("Write", file=os.path.join(output_path,file2orbit+".dim")),
               node_id="writer2orbit",source="orbit2")
    g1.run()
    #BackGeocoding
    g2 = Graph()
    filelist = "{},{}".format(os.path.join(output_path,file1orbit+".dim"),os.path.join(output_path,file2orbit+".dim"))#",".join(output_path+f for f in 
    reader = Operator("ProductSet-Reader", fileList=filelist)
    g2.add_node(reader,node_id="Back-Geocoding_Reader")#,source="writer1orbit,writer1orbit")
    geocoding = Operator("Back-Geocoding", demName="SRTM 3Sec",#"SRTM 1Sec HGT (Auto Download)",
                         demResamplingMethod="BILINEAR_INTERPOLATION",resamplingType="BILINEAR_INTERPOLATION",
                         maskOutAreaWithoutElevation="true")
    g2.add_node(geocoding, node_id="Back-Geocoding",source="Back-Geocoding_Reader")
    esd = Operator("Enhanced-Spectral-Diversity")
    esd.cohThreshold = "0.15"
    g2.add_node(esd, node_id="Enhanced-Spectral-Diversity",source="Back-Geocoding")
    
    #Interferometry
    print("Calcolo interferogramma")
    logging.info("Calcolo interferogramma")
    interferogram = Operator("Interferogram")
    interferogram.subtractFlatEarthPhase="true"
    interferogram.includeCoherence="true"
    interferogram.cohWinRg="10"
    interferogram.cohWinAz="3"
    interferogram.subtractTopographicPhase="true"
    if interferogram.subtractTopographicPhase == "true":
        interferogram.demName = "SRTM 3Sec"#"SRTM 1Sec HGT (Auto Download)"
    
    g2.add_node(interferogram, node_id="interferogram",source="Back-Geocoding")
    deburst = Operator("TOPSAR-Deburst", selectedPolarisations="VV")
    g2.add_node(deburst, node_id="deburst",source="interferogram")
    phase_filtering = Operator("GoldsteinPhaseFiltering")
    g2.add_node(phase_filtering, node_id="PhaseFiltering",source="deburst")
    g2.add_node(Operator("Write", file=os.path.join(output_path,"interferogram_deburst.dim")),
               node_id="writerInterferogram1",source="PhaseFiltering")
    g2.run()

    g3 = Graph()
    g3.add_node(Operator("Read",file=os.path.join(output_path,"interferogram_deburst.dim")), node_id="read")
    export = Operator("SnaphuExport",targetFolder=unwrap_folder)
    export.initMethod = 'MCF'
    export.statCostMode = 'DEFO'
    export.numberOfTileRows = '20'
    export.numberOfTileCols = '20'
    g3.add_node(export, node_id='export',source="read")
    g3.run()
    
    #phase unwrapping
    print("Phase unwrapping")
    logging.info("Phase unwrapping")
    wrapped_folder = os.listdir(unwrap_folder)[0]

    for f in os.listdir(os.path.join(unwrap_folder,wrapped_folder)):
        if ('.img' in f) and ('Phase' in f):
            phasefile_hdr = phasefile = f[:36]+".snaphu.hdr"
            phasefile = f[:36]+".snaphu.img"
        if ('.img' in f) and ('coh' in f):
            cohfile = f
        if ('.hdr' in f) and ('coh' in f):
            cohfile_hdr = f
        if 'UnwPhase' in f and (not 'masked' in f):
            unw_hdr_filename = f[:-4]
            unw_hdr_filename+= '.hdr'
            unw_filename = f[:-4]
            unw_filename += '.img'

    with open(os.path.join(unwrap_folder,wrapped_folder,phasefile_hdr),'r') as f:
        for l in f.readlines():
            if 'samples' in l:
                width = int(l[10:])
            if 'lines' in l:
                height = int(l[8:])
        
    with open(os.path.join(unwrap_folder,wrapped_folder,phasefile),'rb') as f:
        data = np.fromfile(f, dtype=np.float32)
    phase = data.reshape((height,width))
    igram = np.exp(1j * phase)
    
    with open(os.path.join(unwrap_folder,wrapped_folder,cohfile),'rb') as f:
        data_coh = np.fromfile(f, dtype=np.float32)
    coh = data_coh.reshape((height,width))
    try:
        image_unwrapped,_ = snaphu.unwrap(igram, coh, nlooks=23.8, cost="defo", ntiles=(20,20), init='mcf',#23.8
                                        tile_overlap=(200,200), nproc=4, min_region_size=200, single_tile_reoptimize=False,
                                        regrow_conncomps=False)
    except Exception as e:
        message = "Fallimento Snaphu unwrapping con errore: {}. Cancellazione della cartella {} e salto del calcolo dell'interferogramma per il subswath {}.".format(e, output_path, iw)
        print(message)
        logging.error(message)
        shutil.rmtree(output_path)
        return 9999.0

    image_unwrapped.tofile(os.path.join(unwrap_folder,wrapped_folder,unw_filename))

    print("Phase unwrapping completato con successo. Importazione della fase unwrapped in SNAP")
    logging.info("Phase unwrapping completato con successo. Importazione della fase unwrapped in SNAP")
    print("Calcolo dello spostamento partendo dalla fase unwrapped e applicazione della correzione geometrica")
    logging.info("Calcolo dello spostamento partendo dalla fase unwrapped e applicazione della correzione geometrica")
    g4 = Graph()
    g4.add_node(Operator("Read",file=os.path.join(output_path,"interferogram_deburst.dim")), node_id="read1")
    g4.add_node(Operator("Read",file=os.path.join(unwrap_folder,wrapped_folder,unw_hdr_filename)), 
                node_id="read2")
    g4.add_node(Operator("SnaphuImport"), node_id='Import',source=["read1","read2"])
    g4.add_node(Operator("Write", file=os.path.join(output_path,"interferogram_deburst_unw.dim")),
                node_id="writeImport",source="Import")
    g4.add_node(Operator("PhaseToDisplacement"), node_id="phasetodispl",source="Import")
    g4.add_node(Operator("BandMerge"), node_id="BandMerge",source=["Import","phasetodispl"])
    tc = Operator("Terrain-Correction")
    tc.sourceBandNames = "displacement,coh_{}_VV_{}_{}".format(iw,data1,data2)
    tc.pixelSpacingInMeter = '13.94028'
    tc.pixelSpacingInDegree = '1.2522766588905684E-4'
    tc.mapProjection = "PROJCS[\"ETRS89 / UTM zone 32N\", GEOGCS[\"ETRS89\", \
DATUM[\"European Terrestrial Reference System 1989\", SPHEROID[\"GRS 1980\",6378137.0, 298.257222101, \
AUTHORITY[\"EPSG\",\"7019\"]], TOWGS84[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], \
AUTHORITY[\"EPSG\",\"6258\"]], PRIMEM[\"Greenwich\", 0.0, AUTHORITY[\"EPSG\",\"8901\"]], \
UNIT[\"degree\", 0.017453292519943295], AXIS[\"Geodetic longitude\", EAST], AXIS[\"Geodetic latitude\", NORTH], \
AUTHORITY[\"EPSG\",\"4258\"]],PROJECTION[\"Transverse_Mercator\", AUTHORITY[\"EPSG","9807\"]], \
\PARAMETER[\"central_meridian\", 9.0], PARAMETER[\"latitude_of_origin\", 0.0], PARAMETER[\"scale_factor\", 0.9996], \
PARAMETER[\"false_easting\", 500000.0], PARAMETER[\"false_northing\", 0.0], \
UNIT[\"m\", 1.0], AXIS[\"Easting\", EAST], AXIS[\"Northing\", NORTH], AUTHORITY[\"EPSG\",\"25832\"]]"
    tc.saveIncidenceAngleFromEllipsoid = "true"
    g4.add_node(tc, node_id="terrain-correction",source='BandMerge')
    g4.add_node(Operator("Write", file=os.path.join(output_path,"interferogram_deburst_unw_disp_TC.dim")),
                node_id="writeTC",source="terrain-correction")
    if not 'interferogram_deburst_unw_disp_TC.tif' in os.listdir(output_path):
        g4.add_node(Operator("Write", formatName="GeoTIFF-BigTIFF", file=os.path.join(output_path,"interferogram_deburst_unw_disp_TC.tif")),
                    node_id="writeTCtif",source="terrain-correction")
    else:
        g4.add_node(Operator("Write", formatName="GeoTIFF-BigTIFF", file=os.path.join(output_path,"interferogram_deburst_unw_disp_TC_2.tif")),
                    node_id="writeTCtif",source="terrain-correction")
    g4.run()
    print("Processo di calcolo dell'interferometria per il subswath {} completato con successo. File salvati in {}".format(iw, output_path))
    logging.info("Processo di calcolo dell'interferometria per il subswath {} completato con successo. File salvati in {}".format(iw, output_path))
    return tetha

def mosaic(path :str,list_filenames: list) -> np.float32:
    """
    Crea mosaici delle mappe di spostamento e coerenza a partire dal risultato dell'interferometria
    Parameters
    ----------
    path : str
        path of the folder containing the files to process.
    list_filenames : list
        the list of the files to process.

    Returns
    -------
    None
    """
    for f in list_filenames:
        print("Creazione del mosaico per {}".format(f))
        logging.info("Creazione del mosaico per {}".format(f))
        file_path = os.path.join(path,f)
        asc_file_path = os.path.join(file_path,"ascending")
        desc_file_path = os.path.join(file_path,"descending")
        filename_iw1 = [os.path.join(asc_file_path,"IW1",fi) for fi in os.listdir(os.path.join(asc_file_path,"IW1")) if ".tif" in fi][0]
        filename_iw2 = [os.path.join(asc_file_path,"IW2",fi) for fi in os.listdir(os.path.join(asc_file_path,"IW2")) if ".tif" in fi][0]
        list_files = " ".join([filename_iw1, filename_iw2])
        subprocess.check_output("python ../core/raster_utils.py -o "+os.path.join(asc_file_path,"m.tif")+" -n 0.0 -ot Float32 -of GTiff "+list_files, shell=True)
        gdal.Warp(os.path.join(asc_file_path,"coherence_displacement.tif"),os.path.join(asc_file_path,"m.tif"),format='GTiff',
                  dstSRS='EPSG:25832', cutlineDSName=trentino_boundary_path,cutlineLayer='ammprv_v',cropToCutline=True)
        os.remove(os.path.join(asc_file_path,"m.tif"))
        shutil.rmtree(os.path.join(asc_file_path,"IW1"))
        shutil.rmtree(os.path.join(asc_file_path,"IW2"))

        filename_iw1 = [os.path.join(desc_file_path,"IW1",fi) for fi in os.listdir(os.path.join(desc_file_path,"IW1")) if ".tif" in fi][0]
        filename_iw2 = [os.path.join(desc_file_path,"IW2",fi) for fi in os.listdir(os.path.join(desc_file_path,"IW2")) if ".tif" in fi][0]
        list_files = " ".join([filename_iw1, filename_iw2])
        subprocess.check_output("python ../core/raster_utils.py -o "+os.path.join(desc_file_path,"m.tif")+" -n 0.0 -ot Float32 -of GTiff "+list_files, shell=True)
        gdal.Warp(os.path.join(desc_file_path,"coherence_displacement.tif"),os.path.join(desc_file_path,"m.tif"),format='GTiff',
                  dstSRS='EPSG:25832', cutlineDSName=trentino_boundary_path,cutlineLayer='ammprv_v',cropToCutline=True)
        os.remove(os.path.join(desc_file_path,"m.tif"))
        shutil.rmtree(os.path.join(desc_file_path,"IW1"))
        shutil.rmtree(os.path.join(desc_file_path,"IW2"))

if __name__ == "__main__":

    global output_path, unwrap_folder,trentino_boundary_path,geo_wkt

    args = sys.argv[1].replace("'","\"")
    json_input = json.loads(args)
    maindir = '.'
    data_folder = 'data'
    temp_folder = 'tmp'
    output_folder = 'output'
    input_folder = 'input'
    phase_wrapping_folder = 'phase_unwrapping'

    # read input parameters
    s1_a = json_input['s1_ascending'] # sentinel-1 ascending data artifact name (e.g., 's1_ascending')
    s1_d = json_input['s1_descending'] # sentinel-1 descending data artifact name (e.g., 's1_descending')
    shapeArtifact = json_input.get('shapeArtifactName') 
    shapeFileName = json_input.get('shapeFileName')
    mapArtifact = json_input.get('mapArtifactName')
    
    project_name=os.environ["PROJECT_NAME"] #project name (e.g., 'landslide-monitoring')
    
    # define paths
    data_path = os.path.join(maindir, data_folder, input_folder)
    result_path = os.path.join(maindir, data_folder, output_folder)
    data_ascending_folder = os.path.join(data_path, 'ascending')
    data_descending_folder = os.path.join(data_path, 'descending')
    tempfile.tempdir = os.path.join(data_path, temp_folder)
    unwrap_folder = os.path.join(tempfile.tempdir, phase_wrapping_folder)
    trentino_boundary_folder = os.path.join(data_path, 'shape')
    input_map_folder = os.path.join(data_path,'maps')
    previous_artifact_folder = os.path.join(data_path, 'previous_artifact')
    
    # create data folders
    if not os.path.exists(data_path):
        os.makedirs(data_path)  
    # create ascending and descending data folders
    if not os.path.exists(data_ascending_folder):
        os.makedirs(data_ascending_folder)   
    if not os.path.exists(data_descending_folder):
        os.makedirs(data_descending_folder)
    # create temp directory
    if (not os.path.exists(tempfile.tempdir)):
        os.makedirs(tempfile.tempdir)
    # create result folder
    if not os.path.exists(result_path):
        os.makedirs(result_path)
    # create shape folder
    if not os.path.exists(trentino_boundary_folder):
        os.makedirs(trentino_boundary_folder)
    # create input map folder
    if not os.path.exists(input_map_folder):
        os.makedirs(input_map_folder)
    if not os.path.exists(previous_artifact_folder):
        os.makedirs(previous_artifact_folder)

    print(f"Parametri in input: s1_ascending={s1_a}, s1_descending={s1_d}, shapeArtifact={shapeArtifact}, shapeFileName={shapeFileName}")
    logging.info(f"Parametri in input: s1_ascending={s1_a}, s1_descending={s1_d}, shapeArtifact={shapeArtifact}, shapeFileName={shapeFileName}")
    # download data
    project = dh.get_or_create_project(project_name)
    print(f"Scaricamento degli artifact per il progetto: {project_name}")
    logging.info(f"Scaricamento degli artefatti per il progetto: {project_name}")
    # download s1 ascending data
    print(f"Scaricamento artefatto: {s1_a} dentro {data_ascending_folder}")  
    logging.info(f"Scaricamento artefatto: {s1_a} dentro {data_ascending_folder}")
    data_s1a = project.get_artifact(s1_a)
    input_path_ascending = data_s1a.download(data_ascending_folder, overwrite=True)
    # download s1 descending data
    print(f"Scaricamento artefatto: {s1_d} dentro {data_descending_folder}")
    logging.info(f"Scaricamento artefatto: {s1_d} dentro {data_descending_folder}")
    data_s1d = project.get_artifact(s1_d)
    input_path_descending = data_s1d.download(data_descending_folder, overwrite=True)
    # download shape file if provided
    print(f"Scaricamento artefatto shapefile: {shapeArtifact} dentro {trentino_boundary_folder}")
    logging.info(f"Scaricamento artefatto shapefile: {shapeArtifact} dentro {trentino_boundary_folder}")
    shape = project.get_artifact(shapeArtifact)
    trentino_boundary_folder = shape.download(trentino_boundary_folder, overwrite=True)
    trentino_boundary_path = os.path.join(trentino_boundary_folder, shapeFileName)
    previous_artifact_path = ""
    input_json_path = ""
    if len(project.list_artifacts(artifact_name="02_pre_processed")) > 0:
        print(f"Scaricamento artefatto 02_pre_processed precedente dentro {previous_artifact_folder}")
        logging.info(f"Scaricamento artefatto 02_pre_processed precedente dentro {previous_artifact_folder}")
        previous_artifact = project.get_artifact("02_pre_processed")
        previous_artifact_path = previous_artifact.download(previous_artifact_folder, overwrite=True)
        input_json_path = os.path.join(previous_artifact_path, "sensor_angles.json")

    print("Dati scaricati con successo.")   
    logging.info("Dati scaricati con successo.")

    print(f"input_path_ascending = {data_ascending_folder}")
    logging.info(f"input_path_ascending = {data_ascending_folder}")
    print(f"input_path_descending = {data_descending_folder}")
    logging.info(f"input_path_descending = {data_descending_folder}")
    print(f"tempfile.tempdir = {tempfile.tempdir}")
    logging.info(f"tempfile.tempdir = {tempfile.tempdir}")
    print(f"unwrap_folder = {unwrap_folder}")
    logging.info(f"unwrap_folder = {unwrap_folder}")
    print(f"trentino_boundary_path = {trentino_boundary_path}")
    logging.info(f"trentino_boundary_path = {trentino_boundary_path}")

    # Step 1. // To calculate the interferometric data between the ascending and descending images
    # The interferometric data is calculated between the ascending and descending images, 
    # and the results are stored in the output_path directory.
    print("Step 1: Calcolo dell'interferometria")
    logging.info("Step 1: Calcolo dell'interferometria")

    # input_path_ascending = data_ascending_folder
    # input_path_descending = data_descending_folder
        
    list_files_ascending = [f for f in os.listdir(input_path_ascending) if ".zip" in f]
    print(f"list_files_ascending: {list_files_ascending}")
    list_files_descending = [f for f in os.listdir(input_path_descending) if ".zip" in f]
    print(f"list_files_descending: {list_files_descending}")
    list_dates_ascending = [f[17:25] for f in list_files_ascending]
    list_dates_descending = [f[17:25] for f in list_files_descending]
    sorted_indeces_ascending = sorted(range(len(list_dates_ascending)), key=list_dates_ascending.__getitem__)
    sorted_indeces_descending = sorted(range(len(list_dates_descending)), key=list_dates_descending.__getitem__)
    list_theta_ascending = []
    list_theta_descending = []
    if len(list_files_ascending) != len(list_files_descending) and abs(len(list_files_ascending) - len(list_files_descending)) < 2:
        message = "Il numero di immagini ascendenti e discendenti è diverso. Verrà utilizzato il numero minimo di immagini."
        warnings.warn(message)
        logging.warning(message)
    elif abs(len(list_files_ascending) - len(list_files_descending)) >= 2:
        message = "Il numero di immagini nella serie temporale delle immagini ascendenti e discendenti è molto diverso. Questo potrebbe influire negativamente sull'interferometria. Si prega di controllare i dati di input."
        warnings.warn(message)
        logging.warning(message)
    n_images = min(len(list_files_ascending),len(list_files_descending))
    for i in range(1,n_images,1):
        filename_ascending1 = list_files_ascending[sorted_indeces_ascending[i-1]]
        filename_ascending2 = list_files_ascending[sorted_indeces_ascending[i]]
        filename_descending1 = list_files_descending[sorted_indeces_descending[i-1]]
        filename_descending2 = list_files_descending[sorted_indeces_descending[i]]
        date_descending1 = list_dates_descending[sorted_indeces_descending[i-1]]
        date_descending2 = list_dates_descending[sorted_indeces_descending[i]]
        if date_descending1 == date_descending2 or date_descending2 == list_dates_descending[sorted_indeces_descending[i+1]]:
            print(f"Warning: Le immagini discendenti {filename_descending1} e {filename_descending2} hanno la stessa data o non appartengono ad aree corrispondenti. Prendo data successiva.")
            logging.warning(f"Le immagini discendenti {filename_descending1} e {filename_descending2} hanno la stessa data o non appartengono ad aree corrispondenti. Prendo data successiva.")
            date_descending2 = list_dates_descending[sorted_indeces_descending[i+1]]
            filename_descending2 = list_files_descending[sorted_indeces_descending[i+1]]
        date_ascending1 = list_dates_ascending[sorted_indeces_ascending[i-1]]
        date_ascending2 = list_dates_ascending[sorted_indeces_ascending[i]]
        if date_ascending1 == date_ascending2 or date_ascending2 == list_dates_ascending[sorted_indeces_ascending[i+1]]:
            print(f"Warning: Le immagini ascendenti {filename_ascending1} e {filename_ascending2} hanno la stessa data o non appartengono ad aree corrispondenti. Prendo data successiva.")
            logging.warning(f"Le immagini ascendenti {filename_ascending1} e {filename_ascending2} hanno la stessa data o non appartengono ad aree corrispondenti. Prendo data successiva.")
            date_ascending2 = list_dates_ascending[sorted_indeces_ascending[i+1]]
            filename_ascending2 = list_files_ascending[sorted_indeces_ascending[i+1]]
        if date_descending1<date_ascending1:
            output_path = "{}-{}".format(date_descending1,
                                         date_ascending2)
        elif date_ascending1<date_descending1:
            output_path = "{}-{}".format(date_ascending1,
                                         date_descending2)
        output_path_ascending = os.path.join(result_path, output_path, "ascending")
        output_path_descending = os.path.join(result_path, output_path, "descending")
     
        # Check if the zip files are valid
        try:
            archive1 = zipfile.ZipFile(os.path.join(input_path_ascending, filename_ascending1), 'r')
        except zipfile.BadZipFile:
            print(f"Warning: {filename_ascending1} è un file zip danneggiato. Iterazione saltata.")
            logging.warning(f"{filename_ascending1} è un file zip danneggiato. Iterazione saltata.")
            continue
        archive1.close()
        try:
            archive1 = zipfile.ZipFile(os.path.join(input_path_ascending, filename_ascending2), 'r')
        except zipfile.BadZipFile:
            print(f"Warning: {filename_ascending2} e' un file zip danneggiato. Iterazione saltata.")
            logging.warning(f"{filename_ascending2} e' un file zip danneggiato. Iterazione saltata.")
            continue
        archive1.close()
        try:
            archive1 = zipfile.ZipFile(os.path.join(input_path_descending, filename_descending1), 'r')
        except zipfile.BadZipFile:
            print(f"Warning: {filename_descending1} è un file zip danneggiato. Iterazione saltata.")
            logging.warning(f"{filename_descending1} è un file zip danneggiato. Iterazione saltata.")
            continue
        archive1.close()
        try:
            archive1 = zipfile.ZipFile(os.path.join(input_path_descending, filename_descending2), 'r')
        except zipfile.BadZipFile:
            print(f"Warning: {filename_descending2} è un file zip danneggiato. Iterazione saltata.")
            logging.warning(f"{filename_descending2} è un file zip danneggiato. Iterazione saltata.")
            continue
        archive1.close()
    
        print(f"output_path = {output_path}")
        logging.info(f"output_path = {output_path}")
        print(f"output_path_ascending = {output_path_ascending}")
        logging.info(f"output_path_ascending = {output_path_ascending}")
        print(f"output_path_descending = {output_path_descending}")
        logging.info(f"output_path_descending = {output_path_descending}")

        if not os.path.isdir(output_path_ascending):
            os.makedirs(output_path_ascending)
        if not os.path.isdir(output_path_descending):
            os.makedirs(output_path_descending)
        
        print("Calcolo interferometria tra {} e {}".format(filename_descending1,filename_descending2))
        logging.info("Calcolo interferometria tra {} e {}".format(filename_descending1,filename_descending2))
        tetha_descending_iw1 = interferometry(input_path_descending, filename_descending1, filename_descending2, 
                                      output_path_descending,subswath='IW1')#east
        tetha_descending_iw2 = interferometry(input_path_descending, filename_descending1, filename_descending2, 
                             output_path_descending,subswath='IW2')#west
        if tetha_descending_iw1!=9999.0:
            tetha_descending = tetha_descending_iw1
        elif tetha_descending_iw2!=9999.0:
            tetha_descending = tetha_descending_iw2
        else:
            tetha_descending = 9999.0

        if tetha_descending!=9999.0:
            list_theta_descending.append(tetha_descending)
            print("Platform heading angle descending: {}".format(tetha_descending))
        print("Calcolo interferometria tra {} e {}".format(filename_ascending1,filename_ascending2))
        logging.info("Calcolo interferometria tra {} e {}".format(filename_ascending1,filename_ascending2))
        if tetha_descending_iw2!=9999.0:
            tetha_ascending_iw1 = interferometry(input_path_ascending, filename_ascending1, filename_ascending2,
                                        output_path_ascending,subswath='IW1')#west
        else:
            print("Skipping ascending IW1 interferometry computation due to failure in descending IW2 interferometry.")
            logging.warning("Skipping ascending IW1 interferometry computation due to failure in descending IW2 interferometry.")
            tetha_ascending_iw1 = 9999.0
        if tetha_descending_iw1!=9999.0:
            tetha_ascending_iw2 = interferometry(input_path_ascending, filename_ascending1, filename_ascending2, 
                                 output_path_ascending,subswath='IW2')#east
        else:
            print("Skipping ascending IW2 interferometry computation due to failure in descending IW1 interferometry.")
            logging.warning("Skipping ascending IW2 interferometry computation due to failure in descending IW1 interferometry.")
            tetha_ascending_iw2 = 9999.0
        
        if tetha_ascending_iw1!=9999.0:
            tetha_ascending = tetha_ascending_iw1
        elif tetha_ascending_iw2!=9999.0:
            tetha_ascending = tetha_ascending_iw2
        else:
            tetha_ascending = 9999.0
        
        if tetha_ascending!=9999.0:
            list_theta_ascending.append(tetha_ascending)
            print("Platform heading angle ascending: {}".format(tetha_ascending))
    
    #salvataggio dei tetha ascending e descending in un file di JSON
    if input_json_path == "":
        theta_dict = {"ascending": list_theta_ascending, "descending": list_theta_descending}
        with open(f"{result_path}/sensor_angles.json", "w") as f:
            json.dump(theta_dict, f)
    else:
        with open(input_json_path, "r") as f:
            existing_theta_dict = json.load(f)
        existing_theta_dict["ascending"].extend(list_theta_ascending)
        existing_theta_dict["descending"].extend(list_theta_descending)
        with open(input_json_path, "w") as f:
            json.dump(existing_theta_dict, f)
    # #salvataggio file JSON come artifact
    # upload_artifact(artifact_name="sensor_angles",project_name=project_name,src_path=f"{result_path}/sensor_angles.json")
    print("Interferometria completata per tutte le coppie di immagini. Calcolo dei mosaici.")
    logging.info("Interferometria completata per tutte le coppie di immagini. Calcolo dei mosaici.")
    # Step 2. // To create mosaics of the displacement and coherence maps starting from the interferometric results
    # Mosaics of the displacement and coherence maps are created starting from the interferometric results, and the results are stored in the same output_path directory.
    print("Step 2: Creazione dei mosaici di spostamento e coerenza")
    logging.info("Step 2: Creazione dei mosaici di spostamento e coerenza")
    list_filenames = [f for f in os.listdir(result_path) if os.path.isdir(os.path.join(result_path, f))]

    print(f"Found {len(list_filenames)} subdirectories in {result_path}")
    logging.info(f"Found {len(list_filenames)} subdirectories in {result_path}")
    mosaic(result_path, list_filenames)
    print("Mosaici creati con successo per tutte le coppie di immagini.")
    logging.info("Mosaici creati con successo per tutte le coppie di immagini.")
    if len(os.listdir(previous_artifact_path)) == 0:
        upload_artifact(artifact_name = "02_pre_processed", project_name = project_name, src_path = result_path, output_path = f"s3://{project_name}")
    else:
        print(f"Artifact '02_pre_processed' already exists in project '{project_name}'. Updating the artifact with new data.")
        logging.info(f"Artifact '02_pre_processed' already exists in project '{project_name}'. Updating the artifact with new data.")
        shutil.copytree(previous_artifact_path, result_path, dirs_exist_ok=True)
        upload_artifact(artifact_name = "02_pre_processed", project_name = project_name, src_path = result_path, output_path = f"s3://{project_name}")
    print(f"Mosaics uploaded successfully as artifact: mosaics")
    logging.info(f"Mosaics uploaded successfully as artifact: mosaics")