# Rainfall interpolation

## Quickstart

There are two main scripts for this project.

```sh
python daily_download.py --data-dir=/project/data  --date-from=29/06/2026 --date-to=10/07/2026 --output-file=/tmp/rain_29_06_2026_to_10_07_2026.csv
```

The second is `daily_rain_interpolation.py` which builds .tif files of rainfall over the province, one .tif per day over the specified range.
An example of usage:
```sh
python daily_rain_interpolation.py --data-dir=/project/data --date-from=29/06/2026 --date-to=10/07/2026 --observations-file=/tmp/rain_29_06_2026_to_10_07_2026.csv
```

The following datasets are required and placed in the project data directory specified by the `--data-dir` argument.

| Name    | Where to put | Notes | Source
| -------- | ------- | ------- | -------
| trentino_observations.csv and bolzano_observations.csv  |  historical_rainfall_observations   |   Contains historical rainfall observations for anomaly and climatology creation | 
| daily_stations_alto_adige_filtered_reprojected.csv | stations_reprojected | Locations and station id for alto adige stations that have a rain sensor. Reprojected to EPSG:32632 | 
| filtered_stations_9am.csv | stations_reprojected | Locations and station id for Trentino stations that have a rain sensor. Reprojected to EPSG:32632 |
| smoothed_elevation.tif | data_dir  | 30m DEM smoothed as per method in Crespi | 
| boundary_reprojected.shp | region_boundary_reprojected | Boundary of province, downloaded from trentino data portal. Reprojected to EPSG:32632 |
| boundary_reprojected.shp | region_boundary_reprojected | Boundary of region | 


Daily datasets for alto-adige are downloaded from `https://geoservices.buergernetz.bz.it` and `https://archivio.meteotrentino.it`

The process is run in parallel, controlled by the `-n_jobs` argument, defaulting to 4. Each process uses ~2 GB of RAM and 100% of the CPU it is assigned to. To download the observations + produce their outputs for an entire year takes about 10 minutes.

In terms of storage space, each daily output is roughly 500Kb. In order to save space and speed up the script, if a day was completely dry then no output gets written. The output for the 1 year period from 13/10/2025 to 13/10/2026 for example is 126.4 MB.

Other scripts in this repo are for running + visualising comparisons with Crespi's results to make sure we get similar results.



## RuntimeWarning: invalid value encountered in divide
RuntimeWarning: invalid value encountered in divide
  total_weights > EPSILON, (weights.T @ station_anomalies) / total_weights, np.nan

This warning happens at runtime if there are only 1 or 2 stations with observed rainfall. It can be safely ignored, the interpolated results still match the observed values well in these cases.

## Methodology of Crespi

This script is based on this article: https://essd.copernicus.org/articles/13/2801/2021/essd-13-2801-2021.pdf which is available for free.

A very brief summary of this paper is that rainfall for a particular day is calculated based on several factors:

```sh
rain on day x (mm) = function(climatology, altitude, station observation for day)
```

This follows a standard meterological framework called PRISM. 
The advantages of this approach are:

1. The results are more realistic considering elevation; much better than a simple linear interpolation would achieve.
2. Local rain shadows, lake effects are (supposedly) accounted for using climatology. Spiky station data are smoothed out.
3. Results in high resolution from meteorological point of view (250m) over traditional approaches (usually 2.5km).

The disadvantages are that it:
1. Legitimately spiky results get smoothed out.
2. Performs poorly in high rainfall events (see paper for more detail). Legitamate changes in climate due to global warming are smoothed out.
3. Requires a large, consistent record of historical data, including data from regions outside of the study area.

Bear in mind that all rain datasets have two time period formats; a historical form that runs from 9am of day 1 to 9am of day 2, and another which runs from UTC midnight day 1 to UTC midnight day 2. For the Crespi comparison and the average climatology calculation, we use the 9am time convention, whereas for the daily interpolation we use the midnight-midnight convention. This means that we mix conventions; this should be ok given that we consider climatology over several decades when calculting daily anomalies.
