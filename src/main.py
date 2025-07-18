import sys
import json
from snapista import Operator, OperatorParams
from snapista import Graph
from snapista import TargetBand, TargetBandDescriptors
import os,gc
import snaphu
import rasterio
import tempfile
import numpy as np
import shutil
import digitalhub as dh
from utils.skd_handler import upload_artifact
from osgeo import gdal
gdal.UseExceptions()
from shapely.wkt import loads
import geopandas as gpd
import subprocess
import zipfile

tempfile.tempdir

def interferometry(input_path,filename1,filename2,output_path,subswath="IW1"):
    iw = subswath
    # unwrap_folder = "phase_unwrapping/"
    output_path = "{}{}/".format(output_path,subswath)
    if not os.path.isdir(output_path):
        os.makedirs(output_path)
    if os.path.isdir(unwrap_folder):
        shutil.rmtree(unwrap_folder)
    if not os.path.isdir(unwrap_folder):
        os.makedirs(unwrap_folder)
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
    
    print("Lettura:\n{}\n{}".format(file1,file2))
    g1 = Graph()
    g1.add_node(Operator("Read",formatName="SENTINEL-1",file=file1), node_id="read1")
    g1.add_node(Operator("Read",formatName="SENTINEL-1",file=file2), node_id="read2")
    
    #TOPS Split
    print("Coregistrazione...")
    tops_split1 = Operator("TOPSAR-Split")
    tops_split1.subswath = iw
    tops_split1.selectedPolarisations = "VV"
    tops_split1.firstBurstIndex = 1
    tops_split1.lastBurstIndex = 9
    tops_split2 = Operator("TOPSAR-Split")
    tops_split2.subswath = iw
    tops_split2.selectedPolarisations = "VV"
    tops_split2.firstBurstIndex = 1
    tops_split2.lastBurstIndex = 9
    g1.add_node(tops_split1,node_id="TOPS-SPLIT1",source="read1")
    g1.add_node(tops_split2, node_id="TOPS-SPLIT2",source="read2")
    
    #Apply orbit
    file1orbit = filename1[:-9]+"_split_Orb"
    file2orbit = filename2[:-9]+"_split_Orb"
    orbit = Operator("Apply-Orbit-File",orbitType="Sentinel Precise (Auto Download)",continueOnFail="true")
    g1.add_node(orbit,node_id="orbit1",source="TOPS-SPLIT1")
    g1.add_node(orbit,node_id="orbit2",source="TOPS-SPLIT2")
    g1.add_node(Operator("Write", file=output_path+file1orbit+".dim"),
               node_id="writer1orbit",source="orbit1")
    g1.add_node(Operator("Write", file=output_path+file2orbit+".dim"),
               node_id="writer2orbit",source="orbit2")
    g1.run()
    #BackGeocoding
    g2 = Graph()
    filelist = "{},{}".format(output_path+file1orbit+".dim",output_path+file2orbit+".dim")#",".join(output_path+f for f in 
    reader = Operator("ProductSet-Reader", fileList=filelist)
    g2.add_node(reader,node_id="Back-Geocoding_Reader")#,source="writer1orbit,writer1orbit")
    geocoding = Operator("Back-Geocoding", demName="SRTM 3Sec",#"SRTM 1Sec HGT (Auto Download)",
                         demResamplingMethod="BILINEAR_INTERPOLATION",resamplingType="BILINEAR_INTERPOLATION",
                         maskOutAreaWithoutElevation="true")
    g2.add_node(geocoding, node_id="Back-Geocoding",source="Back-Geocoding_Reader")
    # esd = Operator("Enhanced-Spectral-Diversity")
    # esd.cohThreshold = "0.15"
    # g.add_node(esd, node_id="Enhanced-Spectral-Diversity",source="Back-Geocoding")
    
    #Interferometry
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
    g2.add_node(Operator("Write", file=output_path+"interferogram_deburst.dim"),
               node_id="writerInterferogram1",source="PhaseFiltering")
    g2.run()
    
    g3 = Graph()
    g3.add_node(Operator("Read",file=output_path+"interferogram_deburst.dim"), node_id="read")
    export = Operator("SnaphuExport",targetFolder=unwrap_folder)
    export.initMethod = 'MCF'
    export.statCostMode = 'DEFO'
    export.numberOfTileRows = 15
    export.numberOfTileCols = 5
    g3.add_node(export, node_id='export',source="read")
    g3.run()
    
    #phase unwrapping
    wrapped_folder = os.listdir(unwrap_folder)[0]
    for f in os.listdir(os.path.join(unwrap_folder,wrapped_folder)):
        if ('.img' in f) and ('Phase' in f):
            phasefile = f
        if ('.img' in f) and ('coh' in f):
            cohfile = f
        if 'UnwPhase' in f:
            unw_hdr_filename = f[:-4]
            unw_hdr_filename+= '.hdr'
            unw_filename = f[:-4]
            unw_filename += '.img'
            
    phase = np.array(snaphu.io.Raster(os.path.join(unwrap_folder,wrapped_folder,phasefile)))
    igram = np.exp(1j * (phase))
    coh = snaphu.io.Raster(os.path.join(unwrap_folder,wrapped_folder,cohfile)) 
    mask = np.logical_not(np.logical_or(np.isnan(phase),phase==0))
    
    unw = snaphu.io.Raster.create(os.path.join(unwrap_folder,wrapped_folder,unw_filename),
                                  width = igram.shape[1], height = igram.shape[0], dtype="f4")
    conncomp = snaphu.io.Raster.create(os.path.join(unwrap_folder,wrapped_folder,"conncomp.tif"),
                                       width = igram.shape[1], height = igram.shape[0], dtype="u4")

    snaphu.unwrap(igram, coh, nlooks=50, cost="defo", ntiles=(15,5), init='mcf',#23.8
                  tile_overlap=(200,200), nproc=16, min_region_size=200, single_tile_reoptimize=False,
                  regrow_conncomps=False,mask=mask,unw=unw, conncomp=conncomp)
    
    g4 = Graph()
    g4.add_node(Operator("Read",file=output_path+"interferogram_deburst.dim"), node_id="read1")
    g4.add_node(Operator("Read",file=os.path.join(unwrap_folder,wrapped_folder,unw_hdr_filename)), 
                node_id="read2")
    g4.add_node(Operator("SnaphuImport"), node_id='Import',source=["read1","read2"])
    g4.add_node(Operator("Write", file=output_path+"interferogram_deburst_unw.dim" ),
                node_id="writeImport",source="Import")
    g4.add_node(Operator("PhaseToDisplacement"), node_id="phasetodispl",source="Import")
    g4.add_node(Operator("BandMerge"), node_id="BandMerge",source=["Import","phasetodispl"])
    tc = Operator("Terrain-Correction")
    tc.sourceBandNames = "displacement,coh_{}_VV_{}_{}".format(iw,data1,data2)
    tc.pixelSpacingInMeter = 13.94028
    tc.pixelSpacingInDegree = 1.2522766588905684E-4
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
    g4.add_node(Operator("Write", file=output_path+"interferogram_deburst_unw_disp_TC.dim" ),
                node_id="writeTC",source="terrain-correction")
    g4.add_node(Operator("Write", formatName="GeoTIFF-BigTIFF", file=output_path+"interferogram_deburst_unw_disp_TC.tif" ),
                node_id="writeTCtif",source="terrain-correction")
    g4.run()

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
    #trentino_boundary_path = r"D:\AIxPA\Interferometria\ammprv_v.shp"
    #get geotrasformation and projection
    geometry = loads(geo_wkt)
    aoi = gpd.GeoDataFrame(geometry=[geometry],crs="EPSG:4326")
    aoi = aoi.to_crs(25832)
    bounds = aoi.total_bounds
    window = (bounds[0], bounds[3], bounds[2], bounds[1])
    for i,f in enumerate(list_filenames):
        file_path = os.path.join(path,f)
        asc_file_path = os.path.join(file_path,"ascending")
        desc_file_path = os.path.join(file_path,"descending")
        filename_iw1 = [os.path.join(asc_file_path,"IW1",fi) for fi in os.listdir(os.path.join(asc_file_path,"IW1")) if ".tif" in fi][0]
        filename_iw2 = [os.path.join(asc_file_path,"IW2",fi) for fi in os.listdir(os.path.join(asc_file_path,"IW2")) if ".tif" in fi][0]
        list_files = " ".join([filename_iw1,filename_iw2])
        subprocess.check_output("python merge.py -o "+os.path.join(asc_file_path,"m.tif")+" -n 0.0 -ot Float32 -of GTiff "+list_files, shell=True)
        gdal.Warp(os.path.join(asc_file_path,"mosaic.tif"),os.path.join(asc_file_path,"m.tif"),format='GTiff',
                  dstSRS='EPSG:25832', cutlineDSName=trentino_boundary_path,cutlineLayer='ammprv_v',cropToCutline=True)
        os.remove(os.path.join(asc_file_path,"m.tif"))
        filename_iw1 = [os.path.join(desc_file_path,"IW1",fi) for fi in os.listdir(os.path.join(desc_file_path,"IW1")) if ".tif" in fi][0]
        filename_iw2 = [os.path.join(desc_file_path,"IW2",fi) for fi in os.listdir(os.path.join(desc_file_path,"IW2")) if ".tif" in fi][0]
        list_files = " ".join([filename_iw1,filename_iw2])
        subprocess.check_output("python merge.py -o "+os.path.join(desc_file_path,"m.tif")+" -n 0.0 -ot Float32 -of GTiff "+list_files, shell=True)
        gdal.Warp(os.path.join(desc_file_path,"mosaic.tif"),os.path.join(desc_file_path,"m.tif"),format='GTiff',
                  dstSRS='EPSG:25832', cutlineDSName=trentino_boundary_path,cutlineLayer='ammprv_v',cropToCutline=True)
        os.remove(os.path.join(desc_file_path,"m.tif"))
        #end of the part that we can process without request

        #the following part can be on demand
        #clipping for ascending images
        filename_ascending = [fi for fi in os.listdir(asc_file_path) if ".tif" in fi][0]
        output_filename_ascending = filename_ascending[:-4]+"_clip.tif"
        ds_trans = gdal.Translate(os.path.join(asc_file_path,output_filename_ascending), 
                                os.path.join(asc_file_path,filename_ascending), projWin = window,
                                projWinSRS = "EPSG:25832")
        proj = ds_trans.GetProjection()
        geoT = ds_trans.GetGeoTransform()
        ds_trans = None
        filename_ascending = output_filename_ascending
        
        #clipping for descending images
        filename_descending = [fi for fi in os.listdir(desc_file_path) if ".tif" in fi][0]
        output_filename_descending = filename_descending[:-4]+"_clip.tif"
        gdal.Translate(os.path.join(desc_file_path,output_filename_descending), 
                        os.path.join(desc_file_path,filename_descending), projWin = window,
                        projWinSRS = "EPSG:25832")
        filename_descending = output_filename_descending
        #else:
            #filename_ascending = [fi for fi in os.listdir(asc_file_path) if "mosaic.tif" in fi][0]
            #filename_descending = [fi for fi in os.listdir(desc_file_path) if "mosaic.tif" in fi][0]
        
        #reading acending and descending images
        print(r"Reading: {}".format(os.path.join(asc_file_path,filename_ascending)))
        ds = gdal.Open(os.path.join(asc_file_path,filename_ascending),gdal.GA_ReadOnly)
        if i==0:
            v_displ_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            ew_displ_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            coh_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            asc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            desc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            coh_asc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            coh_desc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            
        asc = ds.GetRasterBand(1).ReadAsArray()
        coh_asc = ds.GetRasterBand(2).ReadAsArray()
        inc_angle_asc = ds.GetRasterBand(3).ReadAsArray()
        ds = None
        print(r"Reading: {}".format(os.path.join(desc_file_path,filename_descending)))
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
        v_displ_time_series[:,:,i] = np.mean(np.array([v_asc,v_desc]),axis=0)
        ew_displ_time_series[:,:,i] = (ew_asc-ew_desc)/2
        coh_time_series[:,:,i] = np.mean(np.array([coh_asc,coh_desc]),axis=0)
        asc_time_series[:,:,i] = np.copy(asc)
        desc_time_series[:,:,i] = np.copy(desc)
        coh_asc_time_series[:,:,i] = np.copy(coh_asc)
        coh_desc_time_series[:,:,i] = np.copy(coh_desc)
    return v_displ_time_series, ew_displ_time_series, coh_time_series, asc_time_series, desc_time_series, coh_asc_time_series, coh_desc_time_series, proj, geoT


# python main.py "{'s1_ascending':'s1_ascending', 's1_descending': 's1_descending', 'startDate':'2021-03-01', 'endDate':'2021-03-30','outputArtifactName': 'landslide_output', 'shapeArtifactName': 'trentino_boundary', 'shapeFileName': 'ammprv_v.shp', 'geomWKT': 'POLYGON ((11.687737 46.134408, 11.773911 46.134408, 11.773911 46.174363, 11.687737 46.174363, 11.687737 46.134408))'}"

if __name__ == "__main__":

    global output_path, unwrap_folder,trentino_boundary_path,geo_wkt

    args = sys.argv[1].replace("'","\"")
    json_input = json.loads(args)
    maindir = '.'
    data_folder = 'data'
    temp_folder = 'tmp'
    result_folder = 'result'
    phase_wrapping_folder = 'phase_unwrapping'

    # read input parameters
    s1_a = json_input['s1_ascending'] # sentinel-1 ascending data artifact name (e.g., 's1_ascending')
    s1_d = json_input['s1_descending'] # sentinel-1 descending data artifact name (e.g., 's1_descending')
    startDate = json_input['startDate'] # start date (e.g., '2021-03-01')
    endDate = json_input['endDate'] # end date (e.g., '2021-03-30')
    output_artifact_name=json_input['outputArtifactName'] #output artifact name (e.g., 'deforestation_output')
    shapeArtifact = json_input.get('shapeArtifactName') # optional shape file for clipping
    shapeFileName = json_input.get('shapeFileName') # optional shape file name for clipping
    geo_wkt = json_input['geomWKT'] # AOI geometry in WKT format
    
    project_name=os.environ["PROJECT_NAME"] #project name (e.g., 'landslide-monitoring')
    
    # define paths
    data_path = os.path.join(maindir, data_folder)
    result_path = os.path.join(maindir, result_folder)
    data_ascending_folder = os.path.join(data_path, 'ascending')
    data_descending_folder = os.path.join(data_path, 'descending')
    tempfile.tempdir = os.path.join(data_path, temp_folder)
    unwrap_folder = os.path.join(tempfile.tempdir, phase_wrapping_folder)
    trentino_boundary_folder = os.path.join(data_path, 'shape')
    
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

    print(f"Input parameters: s1_ascending={s1_a}, s1_descending={s1_d}, startDate={startDate}, endDate={endDate}, output_artifact_name={output_artifact_name}")
    # download data
    project = dh.get_or_create_project(project_name)
    print(f"Downloading artifacts for project: {project_name}")
    # download s1 ascending data
    print(f"Downloading artifact: {s1_a} inside {data_ascending_folder}")  
    data_s1a = project.get_artifact(s1_a)
    input_path_ascending = data_s1a.download(data_ascending_folder, overwrite=True)
    # download s1 descending data
    print(f"Downloading artifact: {s1_d} inside {data_descending_folder}")
    data_s1d = project.get_artifact(s1_d)
    input_path_descending = data_s1d.download(data_descending_folder, overwrite=True)
    # download shape file if provided
    print(f"Downloading shape artifact: {shapeArtifact} inside {trentino_boundary_folder}")
    shape = project.get_artifact(shapeArtifact)
    trentino_boundary_folder = shape.download(trentino_boundary_folder, overwrite=True)
    trentino_boundary_path = os.path.join(trentino_boundary_folder, shapeFileName)

    print(f"input_path_ascending = {data_ascending_folder}")
    print(f"input_path_descending = {data_descending_folder}")
    print(f"tempfile.tempdir = {tempfile.tempdir}")
    print(f"unwrap_folder = {unwrap_folder}")
    print(f"trentino_boundary_path = {trentino_boundary_path}")
    
    # Step 1. // To calculate the interferometric data between the ascending and descending images
    # The interferometric data is calculated between the ascending and descending images, 
    # and the results are stored in the output_path directory.
    print("Step 1: Calculating interferometric data...")

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
    for i in range(1,len(sorted_indeces_descending),1):
        filename_ascending1 = list_files_ascending[sorted_indeces_ascending[i-1]]
        filename_ascending2 = list_files_ascending[sorted_indeces_ascending[i]]
        filename_descending1 = list_files_descending[sorted_indeces_descending[i-1]]
        filename_descending2 = list_files_descending[sorted_indeces_descending[i]]
        output_path = "{}-{}".format(list_dates_descending[sorted_indeces_descending[i-1]],
                                     list_dates_ascending[sorted_indeces_ascending[i]])
        output_path_ascending = os.path.join(maindir, result_path, "{}/ascending/".format(output_path))
        output_path_descending = os.path.join(maindir, result_path, "{}/descending/".format(output_path))
        output_path_folder = os.path.join(maindir, result_path, output_path)
    
        print(f"output_path = {output_path}")
        print(f"output_path_ascending = {output_path_ascending}")
        print(f"output_path_descending = {output_path_descending}")
        if not os.path.isdir(output_path_ascending):
            os.makedirs(output_path_ascending)
        if not os.path.isdir(output_path_descending):
            os.makedirs(output_path_descending)
        print("Calcolo interferometria tra {} e {}".format(filename_descending1,filename_descending2))
        interferometry(input_path_descending, filename_descending1, filename_descending2, 
                       output_path_descending,subswath='IW1')
        interferometry(input_path_descending, filename_descending1, filename_descending2, 
                       output_path_descending,subswath='IW2')
        print("Calcolo interferometria tra {} e {}".format(filename_ascending1,filename_ascending2))
        interferometry(input_path_ascending, filename_ascending1, filename_ascending2, 
                       output_path_ascending,subswath='IW1')
        interferometry(input_path_ascending, filename_ascending1, filename_ascending2, 
                       output_path_ascending,subswath='IW2')

    # Upload the result artifact
    # print(f"Uploading Interferometric results to DigitalHub artifact: {output_artifact_name}")
    # upload_artifact(artifact_name='interferometry',project_name=project_name,src_path=[output_path_ascending, output_path_descending],)
    
    # Step 2. // To calculate the vertical and east-west displacements from the interferometric data
    # The vertical and east-west displacements are calculated from the interferometric data,
    # and the results are stored in the output_path directory.
    print("Step 2: Calculating vertical and east-west displacements...")
    list_filenames = [f for f in os.listdir(result_path) if os.path.isdir(os.path.join(result_path, f))] # which list is this??

    print(f"Found {len(list_filenames)} subdirectories in {result_path}")
    #calculate the vertical and east-west displacements
    v_displ_maps, ew_displ_maps, coh_maps, asc, desc, coh_asc, coh_desc, proj, geoT = v_ew_displ(result_path, list_filenames)
    #keep only the interferometry maps with a mean coherence value higher than 0.3
    mean_coh = np.average(coh_maps,axis=(0,1))
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
    keep_img_mask = np.logical_and(np.max(ew_displ_maps,axis=(0,1))<1,
                                  np.min(ew_displ_maps,axis=(0,1))>-1)#mean_coh>=th

    v_displ_maps = v_displ_maps[:,:,keep_img_mask]
    ew_displ_maps = ew_displ_maps[:,:,keep_img_mask]
    coh_maps = coh_maps[:,:,keep_img_mask]
    asc = asc[:,:,keep_img_mask]
    desc = desc[:,:,keep_img_mask]
    coh_asc = coh_asc[:,:,keep_img_mask]
    coh_desc = coh_desc[:,:,keep_img_mask]

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
    
    #save the stacked masked vertical displacement maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'serie_temporale_scostamento_verticale.tif'), 
                                    masked_v_displ_maps.shape[1], masked_v_displ_maps.shape[0], masked_v_displ_maps.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(masked_v_displ_maps.shape[2]):
        masked_v_displ_maps[:,:,i][coh_maps[:,:,i]<0.6] = np.nan
        target_ds.GetRasterBand(i+1).WriteArray(masked_v_displ_maps[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the masked cumulative vertical displacement maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'somma_cumulata_scostamento_verticale.tif'), 
                                    masked_cum_sum_v_displ_map.shape[1], masked_cum_sum_v_displ_map.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_v_displ_map)
    target_ds = None
    gc.collect()
    
    #save the stacked masked east-west displacement maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'serie_temporale_scostamento_orizzontale.tif'), 
                                    masked_ew_displ_maps.shape[1], masked_ew_displ_maps.shape[0], masked_ew_displ_maps.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(masked_ew_displ_maps.shape[2]):
        masked_ew_displ_maps[:,:,i][coh_maps[:,:,i]<0.6] = np.nan
        target_ds.GetRasterBand(i+1).WriteArray(masked_ew_displ_maps[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the masked cumulative east-west displacement map
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'somma_cumulata_scostamento_orizzontale.tif'), 
                                    masked_cum_sum_ew_displ_map.shape[1], masked_cum_sum_ew_displ_map.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_ew_displ_map)
    target_ds = None
    gc.collect()
    
    #save the stacked masked total displacement maps ascending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'serie_temporale_scostamento_totale_ascendente.tif'), 
                                    asc.shape[1], asc.shape[0], asc.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(asc.shape[2]):
        asc[:,:,i][coh_asc[:,:,i]<0.6] = np.nan
        target_ds.GetRasterBand(i+1).WriteArray(asc[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the masked cumulative total displacement map ascending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'somma_cumulata_scostamento_totale_ascendente.tif'), 
                                    masked_cum_sum_asc.shape[1], masked_cum_sum_asc.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_asc)
    target_ds = None
    gc.collect()
    
    #save the stacked masked total displacement maps descending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'serie_temporale_scostamento_totale_discendente.tif'), 
                                    desc.shape[1], desc.shape[0], desc.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(desc.shape[2]):
        desc[:,:,i][coh_desc[:,:,i]<0.6] = np.nan
        target_ds.GetRasterBand(i+1).WriteArray(desc[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the masked cumulative total displacement map ascending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'somma_cumulata_scostamento_totale_discendente.tif'), 
                                    masked_cum_sum_desc.shape[1], masked_cum_sum_desc.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_desc)
    target_ds = None
    gc.collect()
    
    #save the average coherence map
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'mappa_coerenza_media.tif'), 
                                    avg_coh_map.shape[1], avg_coh_map.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(avg_coh_map)
    target_ds = None
    gc.collect()
    
    #save the stacked coherence maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'serie_temporale_mappe_coerenza.tif'), 
                                    avg_coh_map.shape[1], avg_coh_map.shape[0], coh_maps.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(coh_maps.shape[2]):
        target_ds.GetRasterBand(i+1).WriteArray(coh_maps[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the average coherence map ascending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'mappa_coerenza_media_ascendente.tif'), 
                                    avg_coh_asc.shape[1], avg_coh_asc.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(avg_coh_asc)
    target_ds = None
    gc.collect()
    
    #save the stacked coherence maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'serie_temporale_mappe_coerenza_ascendente.tif'), 
                                    coh_asc.shape[1], coh_asc.shape[0], coh_asc.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(coh_asc.shape[2]):
        target_ds.GetRasterBand(i+1).WriteArray(coh_asc[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the average coherence map descending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'mappa_coerenza_media_dscendente.tif'), 
                                    avg_coh_desc.shape[1], avg_coh_desc.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(avg_coh_desc)
    target_ds = None
    gc.collect()
    
    #save the stacked coherence maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'serie_temporale_mappe_coerenza_discendente.tif'), 
                                    coh_desc.shape[1], coh_desc.shape[0], coh_desc.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(coh_desc.shape[2]):
        target_ds.GetRasterBand(i+1).WriteArray(coh_desc[:,:,i])
    target_ds = None
    gc.collect()
        
    #upload output artifact
    print(f"Uploading artifact: {output_artifact_name}, {output_artifact_name}")
    zip_file = os.path.join(result_path, output_artifact_name + '.zip')
    print(f"Creating zip file: {zip_file}")
    zf = zipfile.ZipFile(zip_file, "w")
    for dirname, subdirs, files in os.walk(result_path):
        if (dirname != "./result"):
            continue
        print(f"Processing directory: {dirname}")
        for filename in files:
            if(filename.endswith('.tif') or filename.endswith('.tiff')):
                print(f"Adding {filename} to the zip file")
                zf.write(os.path.join(dirname, filename), arcname=filename)
    zf.close()
    
    upload_artifact(artifact_name=output_artifact_name,project_name=project_name,src_path=zip_file)