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
#from skimage.restoration import unwrap_phase
import xml.etree.ElementTree as ET
from PIL import Image
import warnings

tempfile.tempdir

def interferometry(input_path,filename1,filename2,output_path,subswath="IW1"):
    iw = subswath
    # unwrap_folder = "phase_unwrapping/"
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
        if (not 'calibration' in name) and 'annotation' in name and iw in name and 'vv' in name:
            metadata1 = archive1.open(name)
            tree = ET.parse(metadata1)
            root = tree.getroot()
            ga = root.find('generalAnnotation')
            prodInfo = ga.find('productInformation')
            platHeading = np.float32(prodInfo.find('platformHeading').text)
    archive1.close()
    tetha = 90 - platHeading
    alpha = 180 - platHeading
    
    print("Lettura:\n{}\n{}".format(file1,file2))
    g1 = Graph()
    g1.add_node(Operator("Read",formatName="SENTINEL-1",file=file1), node_id="read1")
    g1.add_node(Operator("Read",formatName="SENTINEL-1",file=file2), node_id="read2")
    
    #TOPS Split
    print("Coregistrazione...")
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

    # expression = f"(coh_"+iw+"_VV_"+data1+"_"+data2+" > 0.2) ? Phase_ifg_"+iw+"_VV_"+data1+"_"+data2+" : NaN"
    # bandmaths = Operator("BandMaths")
    # mask_phase = TargetBand(name="Phase_ifg_{}_VV_{}_{}_masked".format(iw,data1,data2),expression=expression,
    #                         unit="phase",description="Phase from complex data")
    # bandmaths.targetBandDescriptors = TargetBandDescriptors([mask_phase])
    # g2.add_node(bandmaths,node_id="mask_phase",source="PhaseFiltering")
    # merge = Operator("BandMerge", sourceBandNames="i_ifg_"+iw+"_VV_"+data1+"_"+data2+",q_ifg_"+iw+"_VV_"+data1+"_"+data2+",Intensity_ifg_"+iw+"_VV_"+data1+"_"+data2+"_db,Phase_ifg_"+iw+"_VV_"+data1+"_"+data2+",coh_"+iw+"_VV_"+data1+"_"+data2,
    #                  source=["PhaseFiltering","mask_phase"])
    # g2.add_node(merge,node_id="BandMerge",source=["PhaseFiltering","mask_phase"])
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
    wrapped_folder = os.listdir(unwrap_folder)[0]
    conf_file_path = os.path.join(unwrap_folder,wrapped_folder,'snaphu.conf')

    with open(conf_file_path,'r') as f:
        for l in f.readlines():
            if 'snaphu -f' in l:
                linewidth = l[-6:-1]

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
    # target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(output_path,"phase.tif"), 
    #                                 phase.shape[1], phase.shape[0], 1, gdal.GDT_Float32,
    #                                 options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    # target_ds.GetRasterBand(1).WriteArray(phase)
    # target_ds = None
    # gc.collect()
    igram = np.exp(1j * phase)
    
    with open(os.path.join(unwrap_folder,wrapped_folder,cohfile),'rb') as f:
        data_coh = np.fromfile(f, dtype=np.float32)
    coh = data_coh.reshape((height,width))
    
    image_unwrapped,_ = snaphu.unwrap(igram, coh, nlooks=23.8, cost="defo", ntiles=(20,20), init='mcf',#23.8
                                      tile_overlap=(200,200), nproc=4, min_region_size=200, single_tile_reoptimize=False,
                                      regrow_conncomps=False)

    # target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(output_path,"unw_phase.tif"), 
    #                                 image_unwrapped.shape[1], image_unwrapped.shape[0], 1, gdal.GDT_Float32,
    #                                 options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    # target_ds.GetRasterBand(1).WriteArray(image_unwrapped)
    # target_ds = None

    image_unwrapped.tofile(os.path.join(unwrap_folder,wrapped_folder,unw_filename))

    
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
    g4.add_node(Operator("Write", formatName="GeoTIFF-BigTIFF", file=os.path.join(output_path,"interferogram_deburst_unw_disp_TC.tif")),
                node_id="writeTCtif",source="terrain-correction")
    g4.run()
    return tetha, alpha

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
        #filename_iw2 = [os.path.join(asc_file_path,"IW2",fi) for fi in os.listdir(os.path.join(asc_file_path,"IW2")) if ".tif" in fi][0]
        list_files = " ".join([filename_iw1])#,filename_iw2])
        subprocess.check_output("python merge.py -o "+os.path.join(asc_file_path,"m.tif")+" -n 0.0 -ot Float32 -of GTiff "+list_files, shell=True)
        gdal.Warp(os.path.join(asc_file_path,"mosaic.tif"),os.path.join(asc_file_path,"m.tif"),format='GTiff',
                  dstSRS='EPSG:25832', cutlineDSName=trentino_boundary_path,cutlineLayer='ammprv_v',cropToCutline=True)
        os.remove(os.path.join(asc_file_path,"m.tif"))
        #filename_iw1 = [os.path.join(desc_file_path,"IW1",fi) for fi in os.listdir(os.path.join(desc_file_path,"IW1")) if ".tif" in fi][0]
        filename_iw2 = [os.path.join(desc_file_path,"IW2",fi) for fi in os.listdir(os.path.join(desc_file_path,"IW2")) if ".tif" in fi][0]
        list_files = " ".join([filename_iw2])#filename_iw1,
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
        
        #reading ascending and descending images
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
            inc_angle_asc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            inc_angle_desc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            
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
    temp_folder = 'tmp'
    output_folder = 'output'
    input_folder = 'input'
    phase_wrapping_folder = 'phase_unwrapping'

    # read input parameters
    s1_a = json_input['s1_ascending'] # sentinel-1 ascending data artifact name (e.g., 's1_ascending')
    s1_d = json_input['s1_descending'] # sentinel-1 descending data artifact name (e.g., 's1_descending')
    startDate = json_input['startDate'] # start date (e.g., '2021-03-01')
    endDate = json_input['endDate'] # end date (e.g., '2021-03-30')
    output_artifact_name=json_input['outputArtifactName'] #output artifact name (e.g., 'deforestation_output')
    shapeArtifact = json_input.get('shapeArtifactName') 
    shapeFileName = json_input.get('shapeFileName')
    mapArtifact = json_input.get('mapArtifactName')
    geo_wkt = json_input['geomWKT'] # AOI geometry in WKT format
    
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

    print(f"Input parameters: s1_ascending={s1_a}, s1_descending={s1_d}, startDate={startDate}, endDate={endDate}, output_artifact_name={output_artifact_name}, shapeArtifact={shapeArtifact}, shapeFileName={shapeFileName}, mapArtifact={mapArtifact}, geo_wkt={geo_wkt}")
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
    # download map files if provided
    print(f"Downloading map artifact: {mapArtifact} inside {input_map_folder}")
    map_data = project.get_artifact(mapArtifact)
    input_map_folder = map_data.download(input_map_folder, overwrite=True)    
    trentino_slope_map_path = os.path.join(input_map_folder,'trentino_slope_map.tif')
    trentino_aspect_map_path = os.path.join(input_map_folder,'trentino_aspect_map.tif')
    legend_path = os.path.join(input_map_folder,'legend.qml')
    print("Data downloaded successfully.")   

    print(f"input_path_ascending = {data_ascending_folder}")
    print(f"input_path_descending = {data_descending_folder}")
    print(f"tempfile.tempdir = {tempfile.tempdir}")
    print(f"unwrap_folder = {unwrap_folder}")
    print(f"trentino_boundary_path = {trentino_boundary_path}")
    print(f"trentino_slope_map_path = {trentino_slope_map_path}")
    print(f"trentino_aspect_map_path = {trentino_aspect_map_path}")
    print(f"legend_path = {legend_path}")
    
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
    list_theta_ascending = []
    list_alpha_ascending = []
    list_theta_descending = []
    list_alpha_descending = []
    if len(list_files_ascending) != len(list_files_descending) and abs(len(list_files_ascending) - len(list_files_descending)) < 2:
        warnings.warn("The number of ascending and descending images is different. The minimum number of images will be used.")
    elif abs(len(list_files_ascending) - len(list_files_descending)) >= 2:
        warnings.warn("The number of images in the ascending and descending image time series is very different. This could badly affect the interferometry. Please check the input data.")
    n_images = min(len(list_files_ascending),len(list_files_descending))
    for i in range(1,n_images,1):
        filename_ascending1 = list_files_ascending[sorted_indeces_ascending[i-1]]
        filename_ascending2 = list_files_ascending[sorted_indeces_ascending[i]]
        filename_descending1 = list_files_descending[sorted_indeces_descending[i-1]]
        filename_descending2 = list_files_descending[sorted_indeces_descending[i]]
        if filename_descending1<filename_ascending1:
            output_path = "{}-{}".format(list_dates_descending[sorted_indeces_descending[i-1]],
                                         list_dates_ascending[sorted_indeces_ascending[i]])
        elif filename_ascending1<filename_descending1:
            output_path = "{}-{}".format(list_dates_ascending[sorted_indeces_ascending[i-1]],
                                         list_dates_descending[sorted_indeces_descending[i]])
        output_path_ascending = os.path.join(result_path, output_path, "ascending")
        output_path_descending = os.path.join(result_path, output_path, "descending")
        output_path_folder = os.path.join(maindir, result_path, output_path)
    
        print(f"output_path = {output_path}")
        print(f"output_path_ascending = {output_path_ascending}")
        print(f"output_path_descending = {output_path_descending}")
        if not os.path.isdir(output_path_ascending):
            os.makedirs(output_path_ascending)
        if not os.path.isdir(output_path_descending):
            os.makedirs(output_path_descending)
        print("Calcolo interferometria tra {} e {}".format(filename_descending1,filename_descending2))
        # tetha, alpha = interferometry(input_path_descending, filename_descending1, filename_descending2, 
        #                               output_path_descending,subswath='IW1')#east
        tetha, alpha = interferometry(input_path_descending, filename_descending1, filename_descending2, 
                             output_path_descending,subswath='IW2')#west
        list_theta_descending.append(tetha)
        list_alpha_descending.append(alpha)
        print("Calcolo interferometria tra {} e {}".format(filename_ascending1,filename_ascending2))
        tetha, alpha = interferometry(input_path_ascending, filename_ascending1, filename_ascending2,
                                      output_path_ascending,subswath='IW1')#west
        # _,_ = interferometry(input_path_ascending, filename_ascending1, filename_ascending2, 
        #                      output_path_ascending,subswath='IW2')#east
        list_theta_ascending.append(tetha)
        list_alpha_ascending.append(alpha)

    # Upload the result artifact
    # print(f"Uploading Interferometric results to DigitalHub artifact")
    # (artifact_name='interferometry',project_name=project_name,src_path=output_path_folder)
    
    # Step 2. // To calculate the vertical and east-west displacements from the interferometric data
    # The vertical and east-west displacements are calculated from the interferometric data,
    # and the results are stored in the output_path directory.
    print("Step 2: Calculating vertical and east-west displacements...")
    list_filenames = [f for f in os.listdir(result_path) if os.path.isdir(os.path.join(result_path, f))] # which list is this??

    print(f"Found {len(list_filenames)} subdirectories in {result_path}")
    #calculate the vertical and east-west displacements
    v_displ_maps, ew_displ_maps, coh_maps, asc, desc, coh_asc, coh_desc, proj, geoT, inc_angle_asc, inc_angle_desc= v_ew_displ(result_path, list_filenames)
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
    keep_list_filenames = [list_filenames[i] for i in range(len(list_filenames)) if keep_img_mask[i]]
    keep_list_tetha_ascending = [list_theta_ascending[i] for i in range(len(list_theta_ascending)) if keep_img_mask[i]]
    keep_list_alpha_ascending = [list_alpha_ascending[i] for i in range(len(list_alpha_ascending)) if keep_img_mask[i]]
    keep_list_tetha_descending = [list_theta_descending[i] for i in range(len(list_theta_descending)) if keep_img_mask[i]]
    keep_list_alpha_descending = [list_alpha_descending[i] for i in range(len(list_alpha_descending)) if keep_img_mask[i]]

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

    geometry = loads(geo_wkt)
    aoi = gpd.GeoDataFrame(geometry=[geometry],crs="EPSG:4326")
    aoi = aoi.to_crs(25832)
    bounds = aoi.total_bounds
    window = (bounds[0], bounds[3], bounds[2], bounds[1])
    ds_trans = gdal.Translate(trentino_slope_map_path[:-4]+'_clip.tif', 
                                trentino_slope_map_path, width = inc_angle_asc[:,:,0].shape[1],
                                height = inc_angle_asc[:,:,0].shape[0], resampleAlg = 'bilinear',
                                projWin = window, projWinSRS = "EPSG:25832")
    slope_map = ds_trans.GetRasterBand(1).ReadAsArray()
    ds_trans = None
    ds_trans = gdal.Translate(trentino_aspect_map_path[:-4]+'_clip.tif', 
                                trentino_aspect_map_path, width = inc_angle_asc[:,:,0].shape[1],
                                height = inc_angle_asc[:,:,0].shape[0], resampleAlg = 'bilinear',
                                projWin = window, projWinSRS = "EPSG:25832")
    aspect_map = ds_trans.GetRasterBand(1).ReadAsArray()
    ds_trans = None
    #compute the c coefficient in ascending and descending
    c_ascending_time_series = np.zeros(inc_angle_asc.shape,dtype=np.float32)
    for i_c in range(c_ascending_time_series.shape[2]):
        N = np.cos(np.deg2rad(90-inc_angle_asc[:,:,i_c]))*np.cos(np.deg2rad(list_theta_ascending[i_c]))
        E = np.cos(np.deg2rad(90-inc_angle_asc[:,:,i_c]))*np.cos(np.deg2rad(list_alpha_ascending[i_c]))
        H = np.sin(np.deg2rad(inc_angle_asc[:,:,i_c]))
        c = np.divide(1,(np.cos(np.deg2rad(slope_map))*np.sin(np.deg2rad(aspect_map-90))*N)+((-np.cos(np.deg2rad(slope_map))*np.cos(np.deg2rad(aspect_map-90)))*E)+(np.cos(np.deg2rad(slope_map)*H)))
        c_ascending_time_series[:,:,i_c] = np.copy(c)
    
    c_descending_time_series = np.zeros(inc_angle_desc.shape,dtype=np.float32)
    for i_c in range(c_descending_time_series.shape[2]):
        N = np.cos(np.deg2rad(90-inc_angle_desc[:,:,i_c]))*np.cos(np.deg2rad(list_theta_descending[i_c]))
        E = np.cos(np.deg2rad(90-inc_angle_desc[:,:,i_c]))*np.cos(np.deg2rad(list_alpha_descending[i_c]))
        H = np.sin(np.deg2rad(inc_angle_desc[:,:,i_c]))
        c = np.divide(1,(np.cos(np.deg2rad(slope_map))*np.sin(np.deg2rad(aspect_map-90))*N)+((-np.cos(np.deg2rad(slope_map))*np.cos(np.deg2rad(aspect_map-90)))*E)+(np.cos(np.deg2rad(slope_map)*H)))
        c_descending_time_series[:,:,i_c] = np.copy(c)

    #save the stacked masked vertical displacement maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'serie_temporale_scostamento_verticale.tif'), 
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
        target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
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
        target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
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
        target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
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
        target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
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
        target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
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
        target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
        target_ds.GetRasterBand(i+1).WriteArray(coh_desc[:,:,i])
    target_ds = None
    gc.collect()

    #save the areas of interest cumulative east-west displacement map
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'somma_cumulata_scostamento_orizzontale_AOI.tif'), 
                                    cum_sum_ew_displ_map_AOI.shape[1], cum_sum_ew_displ_map_AOI.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(cum_sum_ew_displ_map_AOI)
    target_ds = None
    gc.collect()

    #save the areas of interest cumulative vertical displacement map
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'somma_cumulata_scostamento_verticale_AOI.tif'), 
                                    cum_sum_v_displ_map_AOI.shape[1], cum_sum_v_displ_map_AOI.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(cum_sum_v_displ_map_AOI)
    target_ds = None
    gc.collect()

    #save the 1/c coefficient ascending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'serie_temporale_coefficiente_c_ascendente.tif'), 
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
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(result_path,'serie_temporale_coefficiente_c_discendente.tif'), 
                                    c_descending_time_series.shape[1], c_descending_time_series.shape[0], c_descending_time_series.shape[2], 
                                    gdal.GDT_Float32,options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(c_descending_time_series.shape[2]):
        target_ds.GetRasterBand(i+1).SetDescription(keep_list_filenames[i])
        target_ds.GetRasterBand(i+1).WriteArray(c_descending_time_series[:,:,i])
    target_ds = None
    gc.collect()

    shutil.copy(legend_path,os.path.join(result_path,'legend.qml'))

    print("Processing completed.")
        
#upload output artifact
print(f"Uploading artifact: {output_artifact_name}, {output_artifact_name}")
zip_file = os.path.join(result_path, output_artifact_name + '.zip')
print(f"Creating zip file: {zip_file}")
zf = zipfile.ZipFile(zip_file, "w")
for dirname, subdirs, files in os.walk(result_path):
    # if (dirname != "./output"):
    #     continue
    print(f"Processing directory: {dirname}")
    for filename in files:
        if(filename.endswith('.tif') or filename.endswith('.tiff') or filename.endswith('.qml')):
            print(f"Adding {filename} to the zip file")
            zf.write(os.path.join(dirname, filename), arcname=filename)
zf.close()
   
upload_artifact(artifact_name=output_artifact_name,project_name=project_name,src_path=zip_file)