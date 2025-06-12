import sys
import json
from snapista import Operator, OperatorParams
from snapista import Graph
from snapista import TargetBand, TargetBandDescriptors
import os
import snaphu
import rasterio
import tempfile
import numpy as np
import shutil
import digitalhub as dh
from utils.skd_handler import upload_artifact

tempfile.tempdir = "/data/disk1/lbergamasco/AIxPA/tmp/"

def interferometry(input_path,filename1,filename2,output_path,subswath="IW1"):
    iw = subswath
    unwrap_folder = "phase_unwrapping/"
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
    tops_split1.firstBurstIndex = 3
    tops_split1.lastBurstIndex = 5
    tops_split2 = Operator("TOPSAR-Split")
    tops_split2.subswath = iw
    tops_split2.selectedPolarisations = "VV"
    tops_split2.firstBurstIndex = 3
    tops_split2.lastBurstIndex = 5
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
    filelist = ",".join(output_path+f for f in os.listdir(output_path) if "split_Orb.dim" in f)
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
    export.numberOfTileRows = 10
    export.numberOfTileCols = 10
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

    snaphu.unwrap(igram, coh, nlooks=23.8, cost="defo", ntiles=(10,10), init='mcf',
                  tile_overlap=(200,200), nproc=4, min_region_size=200, single_tile_reoptimize=False,
                  regrow_conncomps=False,unw=unw, conncomp=conncomp)
    
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
    tc.sourceBandNames = ["displacement_VV","coh_{}_VV_{}_{}".format(iw,data1,data2)]
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

# python main.py "{'s1_ascending':'s1_ascending', 's1_descending': 's1_descending', 'start':'2021-03-01', 'end':'2021-03-30','outputArtifactName': 'landslide_output'}"

if __name__ == "__main__":
    
    global output_path

    args = sys.argv[1].replace("'","\"")
    json_input = json.loads(args)
    maindir = '.'
    datapath = 'data'
    output_path = 'output'
    
    s1_a = json_input['s1_ascending'] # sentinel-1 ascending data artifact name (e.g., 's1_ascending')
    s1_d = json_input['s1_descending'] # sentinel-1 descending data artifact name (e.g., 's1_descending')
    project_name=os.environ["PROJECT_NAME"] #project name (e.g., 'landslide-monitoring')
    startDate = json_input['start'] # start date (e.g., '2021-03-01')
    endDate = json_input['end'] # end date (e.g., '2021-03-30')
    output_artifact_name=json_input['outputArtifactName'] #output artifact name (e.g., 'deforestation_output')
    data_ascending_folder = os.path.join(datapath, 'ascending')
    data_descending_folder = os.path.join(datapath, 'descending')
    output_path = os.path.join(maindir, output_path)

    # create data folders
    data_path = os.path.join(maindir, datapath)
    if not os.path.exists(data_path):
        os.makedirs(data_path)  
    # create ascending and descending data folders
    if not os.path.exists(data_ascending_folder):
        os.makedirs(data_ascending_folder)   
    if not os.path.exists(data_descending_folder):
        os.makedirs(data_descending_folder)
    # create output directory
    output_path = os.path.join(maindir, output_path)  
    if not os.path.exists(output_path):
        os.makedirs(output_path)    

    print(f"Input parameters: s1_ascending={s1_a}, s1_descending={s1_d}, startDate={startDate}, endDate={endDate}, output_artifact_name={output_artifact_name}")
    # download data
    project = dh.get_or_create_project(project_name)
    # print(f"Downloading artifacts for project: {project_name}")
    # download s1 ascending data
    # print(f"Downloading artifact: {s1_a} inside {data_ascending_folder}")  
    # data_s1a = project.get_artifact(s1_a)
    # input_path_ascending = data_s1a.download(data_ascending_folder, overwrite=True)
    # download s1 descending data
    # print(f"Downloading artifact: {s1_d} inside {data_descending_folder}")
    # data_s1d = project.get_artifact(s1_d)
    # input_path_descending = data_s1d.download(data_ascending_folder, overwrite=True)
    print(f"input_path_ascending = {data_ascending_folder}")
    print(f"input_path_descending = {data_descending_folder}")

    input_path_ascending = data_ascending_folder
    input_path_descending = data_descending_folder
        
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
        output_path_ascending = "{}/ascending/".format(output_path)
        output_path_descending = "{}/descending/".format(output_path)
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
        
    #upload output artifact
    print(f"Upoading artifact: {output_artifact_name}, {output_artifact_name}")
    #upload_artifact(artifact_name=output_artifact_name,project_name=project_name,src_path=output_path)