# How to prepare data for elaboration

To prepare the geological data, it is required to log the data in the project context

## 1. Initialize the project

```python
import digitalhub as dh
PROJECT_NAME = "landslide-monitoring" # here goes the project name that you are creating on the platform
proj = dh.get_or_create_project(PROJECT_NAME)
```

## 2. Log the Shape artifact

Log the shape file 'Shapes_TN' which can be downloaded from the [WebGIS Portal](https://webgis.provincia.tn.it/) from https://siatservices.provincia.tn.it/idt/vector/p_TN_377793f1-1094-4e81-810e-403897418b23.zip. Unzip the files in a folder named 'Shapes_TN' and then log it

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

The resulting dataset will be registered as the project artifact in the datalake under the name `Shapes_TN`.

## 3. Download Sentinel Data in ascending and descending order.

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

```python
string_dict_data = """{
  'satelliteParams':{
      'satelliteType': 'Sentinel1',
      'processingLevel': 'LEVEL1',
      'sensorMode': 'IW',
      'productType': 'SLC',
      'orbitDirection': 'ASCENDING',
      'relativeOrbitNumber': '117'
  } ,
  'startDate': '2021-03-04',
  'endDate': '2021-03-10',
  'geometry': 'POLYGON((10.81295 45.895743, 10.813637 45.895743, 10.813637 45.89634, 10.81295 45.89634, 10.81295 45.895743))',
  'area_sampling': 'True',
  'tmp_path_same_folder_dwl':'True',
  'artifact_name': 's1_ascending'
  }"""
```

Register 'download_images_s1' operation in the project. The function if of kind container runtime that allows you to deploy deployments, jobs and services on Kubernetes. It uses the base image of sentinel-tools deploved in the context of project which is a wrapper for the Sentinel download and preprocessing routine for the integration with the AIxPA platform. For more details [Click here](https://github.com/tn-aixpa/sentinel-tools/). The parameters passed for sentinel downloads includes the starts and ends dates corresponding to period of two years of data. The ouput of this step will be logged inside to the platfrom project context as indicated by parameter 'artifact_name' ('s1_ascending').Several other paramters can be configures as per requirements for e.g. relativeOrbitNumber 117 is used for satellite images in ascending order.

```python
function_s1 = proj.new_function("download_images_s1",kind="container",image="ghcr.io/tn-aixpa/sentinel-tools:0.11.5",command="python")
```

### Run the function

```python
run = function_s1.run(
    action="job",
    secrets=["CDSETOOL_ESA_USER","CDSETOOL_ESA_PASSWORD"],
    fs_group='8877',
    args=["main.py", string_dict_data],
    resources={"cpu": {"requests": "3", "limits": "6"},"mem":{"requests": "32Gi", "limits": "64Gi"}},
    volumes=[{
        "volume_type": "persistent_volume_claim",
        "name": "volume-land",
        "mount_path": "/app/files",
        "spec": {
             "size": "300Gi"
        }
    }])
```

Check the status of function.

```python
run.refresh().status.state
```

Likewise, download the images in descending order using relative orbit number 163 and save artifact with name
's1_descening'

```python
string_dict_data = """{
  'satelliteParams':{
      'satelliteType': 'Sentinel1',
      'processingLevel': 'LEVEL1',
      'sensorMode': 'IW',
      'productType': 'SLC',
      'orbitDirection': 'DESCENDING',
      'relativeOrbitNumber': '168'
  } ,
  'startDate': '2021-03-01',
  'endDate': '2021-03-15',
  'geometry': 'POLYGON((10.81295 45.895743, 10.813637 45.895743, 10.813637 45.89634, 10.81295 45.89634, 10.81295 45.895743))',
  'area_sampling': 'True',
  'tmp_path_same_folder_dwl':'True',
  'artifact_name': 's1_descending'
  }"""
list_args =  ["main.py",string_dict_data]
```

```python
run = function_s1.run(
    action="job",
    secrets=["CDSETOOL_ESA_USER","CDSETOOL_ESA_PASSWORD"],
    fs_group='8877',
    args=["main.py", string_dict_data],
    resources={"cpu": {"requests": "3", "limits": "6"},"mem":{"requests": "32Gi", "limits": "64Gi"}},
    volumes=[{
        "volume_type": "persistent_volume_claim",
        "name": "volume-land",
        "mount_path": "/app/files",
        "spec": {
             "size": "300Gi"
        }
    }])
```
