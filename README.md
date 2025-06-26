# RS-Landslide-Monitoring

This project implements a pipeline for Landslides detection to detect and monitor ground deformation associated with landslides using Sentinel-1 Level-2A imagery. Given an area of interest and starting and ending dates, the project pipeline downloads the Sentinel-1 SLC images for that period that include the area of interest and divides the images acquired in the ascending direction from those in the descending direction into two folders. The time gap between two images acquired in a given direction has to be six days to improve the coherence between the two images.

The project pipeline computes, for both ascending and descending directions, the interferometry between couples of images acquired every six days and derives the total displacement, coherence map, and local incident angle. It derives the horizontal and vertical displacement components from these products and merges them to obtain their cumulative sum and the displacement between each couple of images. The coherence maps are averaged, and the results are used to filter out the areas with the lowest coherence.

The project pipeline output GeoTiff Raster files containing:

- Cumulative sum and temporal variation of the horizontal displacement ;
- Cumulative sum and temporal variation of the vertical displacement;
- Cumulative sum and temporal variation of the total displacement of ascending and descending Sentinel-1 images;
- Mean and temporal variation of the coherence maps;
- Mean and temporal variation of the coherence maps of ascending and descending Sentinel-1 image;

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

## Requirements

### Hardware Requirements

The pipelines takes several days to complete with 16 CPUs and 64GB Ram for 6 months data which is the default period. It consists of two steps (download, elaboration). The download step is dependant on Sentinel Hub dataspace. It could happen that data download takes more time than usual due to various factors, including technical issues, data processing delays, and limitations in the data access infrastructure. The second step 'elaboration' consists of interferometry step which is a remote sensing technique that uses radar data to detect and monitor ground deformation associated with landslides and post processing steps which are computationally heavy since it is pixel based analysis.The amount of sentinal data is huge that is whay a volume of 600Gi of type 'persistent_volume_claim' is specified to ensure significant data space.

### General Requirements

- Register to the open data space copenicus(if not already) and get your credentials.

```
https://identity.dataspace.copernicus.eu/auth/realms/CDSE/login-actions/registration?client_id=cdse-public&tab_id=FIiRPJeoiX4
```

- Shape file can be downloaded from the [WebGIS Portal](https://webgis.provincia.tn.it/) from https://siatservices.provincia.tn.it/idt/vector/p_TN_377793f1-1094-4e81-810e-403897418b23.zip. More details in download [step](./docs/howto/download.md)

## Usage

Tool usage documentation [here](./docs/usage.md).

## How To

- [Download and preprocess sentinel geological data](./docs/howto/download.md)
- [Run Elaboration and log output ](./docs/howto/elaborate.md)

## License

[Apache License 2.0](./LICENSE)
