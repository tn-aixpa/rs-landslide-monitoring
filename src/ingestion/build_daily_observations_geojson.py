from pathlib import Path

import geopandas as gpd
import pandas as pd

from rain.constants import EPSG_CODE


def build_daily_observations_geojson(
    output_file_path: Path, daily_observations: pd.DataFrame, stations: pd.DataFrame
):
    """
    Produce a geojson output file of station observations on the day specified in daily_observations

    Args:
        output_file_path (Path): _description_
        daily_observations (pd.DataFrame): _description_
        stations (pd.DataFrame): _description_
    """
    obs_station_ids = daily_observations["station_id"].unique()
    stations = stations[stations["station_id"].isin(obs_station_ids)]
    merged = stations.merge(daily_observations, how="inner", on="station_id")
    gdf = gpd.GeoDataFrame(
        merged, geometry=gpd.points_from_xy(merged.x, merged.y), crs=f"EPSG:{EPSG_CODE}"
    )
    gdf = gdf.drop(["date", "provincia", "qual", "x", "y"], axis=1)
    gdf["precipitation"] = gdf["precipitation"].astype(int)
    json_str = gdf.to_json(indent=4)
    with open(output_file_path, "w") as f:
        f.write(json_str)
