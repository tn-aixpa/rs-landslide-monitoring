# Workflow

<p align="justify">In this step we will create a workflow pipeline that establish a clear, repeatable process for handling the set of scenario tasks (download, elaborate). The DH platform pipeline ensures that tasks are completed in a sepcific order. It also provide the ease to fine tune the steps as per requirements of scenario imporving efficiency, consistency, aand traceability. For more detailed information about workflow and their management see the <a href="https://scc-digitalhub.github.io/docs/tasks/workflows">documentation</a>. Inside the project 'src' folder there exist a jypter notebook <a href="../../src/workflow.ipynb">workflow.ipynb</a> that depicts the creation and management of workflow.</p>

## 1. Initialize the project

Create the working context: data management project for scenario. Project is a placeholder for the code, data, and management of the data operations and workflows. To keep it reproducible, we use the git source type to store the definition and code.

```python
import digitalhub as dh
PROJECT_NAME = "landslide-monitoring" # here goes the project name that you are creating on the platform
proj = dh.get_or_create_project(PROJECT_NAME)
```

## 2. Log the Shape files artifact

<p align="justify">Log the shape file 'Shapes_TN' which can be downloaded from the [WebGIS Portal](https://webgis.provincia.tn.it/) from https://siatservices.provincia.tn.it/idt/vector/p_TN_377793f1-1094-4e81-810e-403897418b23.zip. Unzip the files in a folder named 'Shapes_TN' and then log it</p>

```python
artifact_name='Shapes_TN'
src_path='/Shapes_TN'
artifact_data = proj.log_artifact(name=artifact_name, kind="artifact", source=src_path)
```

Note that to invoke the operation on the platform, the data should be avaialble as an artifact on the platform datalake.

```python
artifact = proj.get_artifact("Shapes_TN")
artifact.key
```

Log the Map aritfact with three files (trentino_slope_map.tiff, trentino_aspect_map.tiff, and legend.qml). The files can be downloaded from the <a href="https://huggingface.co/datasets/lbergamasco/trentino-slope-map/tree/main">Huggingface repository</a>. Copy the three files inside a folder 'Map' and log it as project artifact

```python
artifact_name='Map'
src_path='Map'
artifact_data = proj.log_artifact(name=artifact_name, kind="artifact", source=src_path)
```

The resulting dataset will be registered as the project artifacts in the datalake under the name `Shapes_TN` and `Map`.

## 3. Register 'Download' operations for sentinel1 data

Register to the open data space copernicus(if not already) and get your credentials.

```
https://identity.dataspace.copernicus.eu/auth/realms/CDSE/login-actions/registration?client_id=cdse-public&tab_id=FIiRPJeoiX4
```

Log the credentials as project secret keys as shown below

```python
# THIS NEED TO BE EXECUTED JUST ONCE
secret0 = proj.new_secret(name="CDSETOOL_ESA_USER", secret_value="esa_username")
secret1 = proj.new_secret(name="CDSETOOL_ESA_PASSWORD", secret_value="esa_password")
```

<p align="justify">Register 'download_images_s1' operation in the project. The function is of kind container runtime that allows you to deploy deployments, jobs and services on Kubernetes. It uses the base image of sentinel-tools deploved in the context of project which is a wrapper for the Sentinel download and preprocessing routine for the integration with the AIxPA platform. For more details click <a href="https://github.com/tn-aixpa/sentinel-tools/">here</a>. The purpose of 'download_images_s1' function is to download sentinel-1 data (GRD image tiles)</p>

Register 'download_images_s1' operation in the project.

```python
function_s1 = proj.new_function(
    "download_images_s1",
    kind="container",
    image="ghcr.io/tn-aixpa/sentinel-tools:0.11.6",
    command="python")
```

The purpose of this function is to download sentinel1 data(GRD image tiles) based on input parameters for e.g. geometry, cloud cover percentage etc.

## 4. Register the `elaborate` operation in the project

```python
function_rs = proj.new_function(
    "elaborate",kind="container",
     image="ghcr.io/tn-aixpa/rs-landslide-monitoring:3.2",
     command="/bin/bash",
     code_src="launch.sh")
```

<p align="justify">The function represent a container runtime that allows you to deploy deployments, jobs and services on Kubernetes. It uses the base image of landslide-monitoring container deploved in the context of project that creates the runtime environment required for the execution. It invovles pulling the base image with gdal installed and installing all the required libraries and launch instructions specified by 'launch.sh' file.</p>

## 5. Create workflow pipeline

Workflows can be created and managed as entities similar to functions. From the console UI one can access them from the dashboard or the left menu. Run the following step to create 'workflow' python source file inside src directory. The workflow handler takes as input

- geometry (area of interest for e.g. POLYGON ((11.687737 46.134408, 11.773911 46.134408, 11.773911 46.174363, 11.687737 46.174363, 11.687737 46.134408)))
- outputName (output artifact name)
- startDate (Start date for the data elaboration in YYYY-MM-DD format)
- endDate (End date for the data elaboration in YYYY-MM-DD format)

<p align="justify">The inputs are sub organized inside to the workflow among different functions. The first four download steps perform sentinel downloads using the function created in previous step. The download function takes as input a list of arguments (args=["main.py", string_dict_data_s1Pre]) where the first argument is the python script file that will be launched inside to the container and the second argument is the json input string which includes all the necessary parameters of sentinel download operation like date, geometry, product type, cloud cover etc. For more details click <a href="https://github.com/tn-aixpa/sentinel-tools/">here</a>. The last step of workflow perform elaboration using the 'elaborate' function created in previous step. The elaboration function taks as input a list of arguments where the first argument is the bash script that will be launched on entry inside to the container while the following parameters contains both fixed and dynamic parameters. The fixed parameter includes both the project artifacts names (s1_ascending, s1_descending, 'Shapes_TN', 'ammprv_v.shp'). The workflow can be adopted as per context needs by changing/passing the different parametric values as depicted in 'Register workflow' section.</p>

```python
%%writefile "landslide_pipeline.py"

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
     

```

There is a committed version of this file on the repo.

## 6. Register workflow

Register workflow 'pipeline_landslide' in the project. In the following step, we register the workflow using the committed version of pipeline source code on project git repository. It is required to update the 'code_src' url with github username and personal access token in the code cell below

```python
workflow = proj.new_workflow(
name="pipeline_landslide",
kind="kfp",
code_src="git+https://<username>:<personal_access_token>@github.com/tn-aixpa/rs-landslide-monitoring",
handler="src.landslide_pipeline:myhandler")
```

<p align="justify">If you want to modify the pipeline source code, either update the existing version on github repo or register the pipeline with locally modified version of python source file for e.g. the value of parameter 'artifact_name' is set to 's1_ascending' in first step S1 of pipeline. If you want to log the artifact with different name inside to the DH platform project, create/update the pipeline code locally by replacing the value of 'artifact_name' key followed by the registration of pipeline using the locally modified file as shown below.</p>

```python
workflow = proj.new_workflow(name="pipeline_landslide", kind="kfp", code_src= "landslide_pipeline.py", handler = "myhandler")
```

## 7. Build workflow

```python
wfbuild = workflow.run(action="build", wait=True)
wfbuild.spec
```

## 8. Run workflow.

```python
workflow_run = workflow.run(action="pipeline", parameters={
    "startDate": "2020-11-01",
    "endDate": "2021-11-14",
    "geometry": "POLYGON ((10.595369 45.923394, 10.644894 45.923394, 10.644894 45.945838, 10.595369 45.945838, 10.595369 45.923394))",
    "outputName": "landslide_2020-11-01_2020-11-14"
    })
```

See the complete jypter notebook <a href="../../src/workflow.ipynb">here</a>. After the build, the pipeline specification and configuration is displayed as the result of this step(wfbuild.spec). The same can be achieved from the console UI dashboard or the left menu using the 'INSPECTOR' button which opens a dialog containing the resource in JSON format.

```python
{
    "task": "kfp+build://landslide-monitoring/45a57c99570d41868c9d210e0427c864",
    "workflow": "kfp://landslide-monitoring/pipeline_landslide:5c731db0bd7b4af6a2024627e4b9da66",
    ...
  }
```

<p align="justify">In order to integrate the pipeline with the front end UI 'rsde-pipeline-manger', the value of 'task' and 'workflow' keys are the two important configuration parameters that must be set in the in the configuration(config.yml) as taskId and workflowId. For more detailed information see <a href="https://github.com/tn-aixpa/rsde-pipeline-manager">rsde-pipeline-manger</a></p>
