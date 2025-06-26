# Elaboration

## 1. Register the `elaborate` operation in the project

```python
function_rs = proj.new_function(
    "elaborate",
    kind="container",
    image="ghcr.io/tn-aixpa/rs-landslide-monitoring:2.7_b6",
    command="/bin/bash",
    code_src="launch.sh")
```

The function represent a container runtime that allows you to deploy deployments, jobs and services on Kubernetes. It uses the base image of rs-landslide-moinitoring container deploved in the context of project create the environment required for the execution. It invovles pulling the base image with gdal installed and installing all the required libraries and launch instructions specified by 'launch.sh' file.

## 2. Run

The function aims at downloading all the geological inputs(s1_ascending, s1_descending, Shapes_TN) from project context and perform the complex task of geological elaboration.

```python
run_el = function_rs.run(
    action="job",
    fs_group='8877',
    resources={"cpu": {"requests": "6", "limits": "12"},"mem":{"requests": "32Gi", "limits": "64Gi"}},
    volumes=[{
        "volume_type": "persistent_volume_claim",
        "name": "volume-land",
        "mount_path": "/app/files",
        "spec": { "size": "600Gi" }
    }],
    args=['/shared/launch.sh', 's1_ascending', 's1_descending', '2021-03-01', '2021-07-30', 'landslide_2021-03-04_2021-07-30', 'Shapes_TN', 'ammprv_v.shp','POLYGON((10.81295 45.895743, 10.813637 45.895743, 10.813637 45.89634, 10.81295 45.89634, 10.81295 45.895743))']
)
```

As indicated in the project documentation, the pixel based analysis performed in the elaboration steps are computation heavy. The best possible performance matrix is more or less around the configuration indicated in the step above. The amount of sentinal data can vary. A safe limit volume of 250Gi is specified as persistent volume claim to ensure significant data space. The function takes around 8-9 hours to complete with 16 CPUs and 64GB Ram for six months of data which is the default period. The multiple GeoTIFF raster files as output are saved in the project context as an artifact (landslide_2021-03-04_2021-07-30).
