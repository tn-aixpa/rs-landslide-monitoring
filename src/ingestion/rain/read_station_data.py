from pathlib import Path

import pandas as pd
import rasterio


def read_station_data(stations_data_path: Path, smoothed_dem_path: Path | None = None):
    """

    Read station data and optionally lookup their elevation information from the DEM

    Args:
        stations_data_path (Path): _description_
        smoothed_dem_path (Path | None, optional): _description_. Defaults to None.

    Raises:
        AssertionError: _description_

    Returns:
        _type_: _description_
    """
    stations = pd.read_csv(stations_data_path)
    if smoothed_dem_path is not None:
        with rasterio.open(smoothed_dem_path) as src:
            coords = list(zip(stations["x"], stations["y"]))
            stations["elevation"] = [vals[0] for vals in src.sample(coords)]
            no_data_series = stations["elevation"] == src.nodata
            if no_data_series.any():
                raise AssertionError("Some station(s) did not have an elevation")
    return stations
