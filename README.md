# RS-Landslide-Monitoring

<p align="justify">This project implements a pipeline for Landslides detection to detect and monitor ground deformation associated with landslides using Sentinel-1 Level-2A imagery. Given an area of interest and starting and ending dates, the project pipeline downloads the Sentinel-1 SLC images for that period that include the area of interest and divides the images acquired in the ascending direction from those in the descending direction into two folders. The time gap between two images acquired in a given direction has to be six days to improve the coherence between the two images.</p>

<p align="justify">The project pipeline computes, for both ascending and descending directions, the interferometry between couples of images acquired every six days and derives the total displacement, coherence map, and local incident angle. It derives the horizontal and vertical displacement components from these products and merges them to obtain their cumulative sum and the displacement between each couple of images. The coherence maps are averaged, and the results are used to filter out the areas with the lowest coherence.</p>

The project pipeline output GeoTiff Raster files containing:

- Cumulative sum and temporal variation of the horizontal displacement ;
- Cumulative sum and temporal variation of the vertical displacement;
- Cumulative sum and temporal variation of the total displacement of ascending and descending Sentinel-1 images;
- Cumulative sum of the horizontal displacement of the areas where the cumulative sum of the ascending and descending displacements has an opposite sign;
- Cumulative sum of the vertical displacement of the areas where the cumulative sum of the ascending and descending displacements has an opposite sign;
- Mean and temporal variation of the coherence maps;
- Mean and temporal variation of the coherence maps of ascending and descending Sentinel-1 images;
- Temporal variation of the C coefficient map representing the ratio of effective displacement computed in ascending and descending orbits;

#### AIxPA

- `kind`: product-template
- `ai`: remote sensing
- `domain`: PA

The product contains operations for

- Download Sentinel-1 data using tile-specific metadata (containing only two years).
- Perform elaboration that includes
  - Computation of interferometry for both ascending and descending directions of images.
  - Computation of coherence map, local incident angle.
  - Computation of comulative sum based on horizontal and vertical displacement components between each couple of  
    images.
  - Filteration of lowest coherence areas after average operation.
- Log results as GeoTIFF raster files.

The file "legend.qml", provided together with the output GeoTiff Raster files, allows for visualizing the latter with a colormap that depends on the displacement. This file is a QGIS style file intended for use with GeoTiff Raster files that display displacement information. When a GeoTiff Raster file displaying displacement information is loaded in QGIS, the user can click on the file layer and navigate to "Style-> Load Style" in the bottom left part of the window to load "legend.qml".

## Requirements

### Hardware Requirements

<p align="justify">The pipeline duration depends amount the amount of sentinel data. The data in turns depends on two factors, the timeline window and geometry. The pipeline consists of two steps (download, elaboration). The download step is dependant on Sentinel Hub dataspace. Due to sentinel server performance issues, downloads may take longer than expected. The second step 'elaboration' consists of interferometry step which is a remote sensing technique that uses radar data to detect and monitor ground deformation associated with landslides and post processing steps which are computationally heavy since it is pixel based analysis. In some cases, during the 'download' step large ZIP archives might become corrupted during transfer and the subsequent 'elaboration' step will end up with empty results and insufficient elaboration data warning. If you encounter such issue, please rerun the 'download' step followed by 'elaboration'. The amount of sentinal data is huge that is whay a default volume of 300Gi of type 'persistent_volume_claim' is specified in example to ensure significant data space. This configuration must be change according to scenario requirement. In the example given in documentation <a href="./docs/howto/workflow.md">workflow.ipynb</a>, an elaboration on two weeks data is performed which takes ~5 hours to complete with 16 CPUs and 64GB Ram.</p>

### General Requirements

- Register to the open data space copenicus(if not already) and get your credentials.

```
https://identity.dataspace.copernicus.eu/auth/realms/CDSE/login-actions/registration?client_id=cdse-public&tab_id=FIiRPJeoiX4
```

- <p align="justify">Shape file can be downloaded from the <a href="https://webgis.provincia.tn.it/">WebGIS Portal</a> or using direct <a href="https://siatservices.provincia.tn.it/idt/vector/p_TN_377793f1-1094-4e81-810e-403897418b23.zip">link</a> to zip archive. More details in download <a href="./docs/howto/download.md">step</a></p>

## Usage

Tool usage documentation [here](./docs/usage.md).

## How To

- [Download and preprocess sentinel geological data](./docs/howto/download.md)
- [Run Elaboration and log output ](./docs/howto/elaborate.md)
- [Workflow](./docs/howto/workflow.md)

## License

[Apache License 2.0](./LICENSE)
