# RS-Landslide-Monitoring

## Usage Scenario

The main purpose of the tool is to provide perform the landslide-detection elaboration over the period of time (for e.g 6 months). The project implements a pipeline that downloads an image time series of Sentinel-1 Single Look Complex (SLC) images acquired in ascending and descending orbit directions. It processes couples of raw .SAFE or .zip Sentinel-1 images to compute the interferometry and coherence between them. The method calculates the total soil displacement for both ascending and descending directions, computes the horizontal and vertical displacement components, and outputs the cumulative sum of these components by filtering out areas with low coherence.

## Input

- **Sentinel-2 Data** of ascending and desceding order in `.SAFE` folders or `.zip` format using specific relative orbits.
- **Shape Mask** in `.shp` or raster format.
  - Can be downloaded from the [WebGIS Portal](https://webgis.provincia.tn.it/) from https://siatservices.provincia.tn.it/idt/vector/p_TN_377793f1-1094-4e81-810e-403897418b23.zip.

## Output

Multiple GeoTIFF files containing:

- Cumulative sum and temporal variation of the horizontal displacement ;
- Cumulative sum and temporal variation of the vertical displacement;
- Cumulative sum and temporal variation of the total displacement of ascending and descending Sentinel-1 images;
- Mean and temporal variation of the coherence maps;
- Mean and temporal variation of the coherence maps of ascending and descending Sentinel-1 image;

The output is logged as artifact in the project context.
