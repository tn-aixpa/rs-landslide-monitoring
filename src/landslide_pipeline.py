
from digitalhub_runtime_kfp.dsl import pipeline_context

def myhandler(startDate, endDate, geometry, outputName):
    with pipeline_context() as pc:
        
        s1_ascending = "s1_ascending_" + str(outputName)
        s1_descending = "s1_descending_"+ str(outputName) 
    
        string_dict_data_asc = """{"satelliteParams":{"satelliteType": "Sentinel1","processingLevel": "LEVEL1","sensorMode": "IW","productType": "SLC","orbitDirection": "ASCENDING","relativeOrbitNumber": "117"},"startDate": \"""" + str(startDate) + """\","endDate": \"""" + str(endDate) + """\","geometry": \"""" + str(geometry) + """\","area_sampling": "True","artifact_name": \"""" + str(s1_ascending) + """\"}"""
        string_dict_data_des = """{"satelliteParams":{"satelliteType": "Sentinel1","processingLevel": "LEVEL1","sensorMode": "IW","productType": "SLC","orbitDirection": "DESCENDING","relativeOrbitNumber": "168"},"startDate": \"""" + str(startDate) + """\","endDate": \"""" + str(endDate) + """\","geometry": \"""" + str(geometry) + """\","area_sampling": "True","artifact_name": \"""" + str(s1_descending) + """\"}"""
        
        s1 = pc.step(name="download-asc",
                     function="download_images_s1",
                     action="job",
                     secrets=["CDSETOOL_ESA_USER","CDSETOOL_ESA_PASSWORD"],
                     fs_group='8877',
                     args=["main.py", string_dict_data_asc],
                     volumes=[{
                        "volume_type": "persistent_volume_claim",
                        "name": "volume-land",
                        "mount_path": "/app/files",
                        "spec": { "size": "300Gi" }
                        }
                    ])

        s2 = pc.step(name="download-desc",
                     function="download_images_s1",
                     action="job",
                     secrets=["CDSETOOL_ESA_USER","CDSETOOL_ESA_PASSWORD"],
                     fs_group='8877',
                     args=["main.py", string_dict_data_des],
                     volumes=[{
                        "volume_type": "persistent_volume_claim",
                        "name": "volume-land",
                        "mount_path": "/app/files",
                        "spec": { "size": "300Gi" }
                        }
                    ]).after(s1)
        
        s3 = pc.step(name="elaborate",
                     function="elaborate",
                     action="job",
                     fs_group='8877',
                     resources={"cpu": {"requests": "6", "limits": "12"},"mem":{"requests": "32Gi", "limits": "64Gi"}},
                     volumes=[{
                        "volume_type": "persistent_volume_claim",
                        "name": "volume-land",
                        "mount_path": "/app/data",
                        "spec": { "size": "500Gi" }
                    }],
                     args=['/shared/launch.sh', str(s1_ascending), str(s1_descending), str(startDate), str(endDate), str(outputName), 'Shapes_TN', 'ammprv_v.shp', 'Map',  str(geometry)]
                     ).after(s2)
     
