"""
Used to create daily interpolated data which can then be aggregated.
"""

import argparse
from pathlib import Path
import rasterio
import numpy as np
import pandas as pd
from build_daily_observations_geojson import build_daily_observations_geojson
from build_or_load_precipitation_climatology import (
    build_or_load_precipitation_climatology,
)
from calculate_monthly_normals import calculate_monthly_normals
from constants import THREADING_PREFERENCE
from context import RunContext
from interpolate_single_day_worker import interpolate_single_day_worker
from is_debugging import is_debugging
from joblib import Parallel, delayed
from load_dem import load_dem
from parse_datetime import parse_datetime
from read_observation_data import read_observation_data
from read_station_data import read_station_data
from setup_logging import setup_logging


def main():
    logger = setup_logging()
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--data-dir",
        required=True,
        help="Folder containing observation data, station data and DEM",
    )
    ap.add_argument("--observations-file", required=True, help="CSV output file of daily_observations_download.py")

    ap.add_argument(
        "--n-jobs",
        type=int,
        default=4,
        help="Number of parallel jobs used to generate outputs",
    )

    debug_group = ap.add_argument_group("debug", "debug options")
    debug_group.add_argument(
        "--geojson",
        action="store_true",
        help="Output geojson of daily observations for help in debugging",
    )

    args = ap.parse_args()
    data_dir = Path(args.data_dir)

    daily_observations_file = Path(args.observations_file)
    daily_observations_df = pd.read_csv(daily_observations_file)
    
    daily_observations_df["date"] = parse_datetime(daily_observations_df["date"])
    date_from = daily_observations_df["date"].min()
    date_to = daily_observations_df["date"].max()
    time_delta = date_to - date_from
    logger.info(
        f"Considering {time_delta.days + 1} days between {date_from:%d/%m/%Y} and {date_to:%d/%m/%Y}"
    )
    run_context = RunContext(data_dir)
    run_context.setup()

    # Historical observations are used to calculate daily anomaly. Meterological concept used for this model.
    # Unfortunately this means mixing time formats; unlikely to result in inaccuracy.
    historical_observations = read_observation_data(
        run_context.historical_observations_files
    )

    stations_df = read_station_data(
        run_context.historical_stations_path, run_context.smoothed_dem_path
    )

    grid = load_dem(run_context.smoothed_dem_path, smoothed=True)
    monthly_normals = calculate_monthly_normals(historical_observations)
    monthly_climatology = build_or_load_precipitation_climatology(
        run_context, stations=stations_df, monthly_normals=monthly_normals, grid=grid
    )
    date_to = date_to.tz_localize(None).normalize()
    date_from = date_from.tz_localize(None).normalize()
    unique_dates = pd.date_range(date_from, date_to, freq="D")

    n_jobs = args.n_jobs

    if is_debugging():
        # There are some weird C library shenanigans that cause the debug session to crash when debugging in vscode debugger
        logger.info("Debugging detected, switching to single threading mode")
        n_jobs = 1

    results = Parallel(n_jobs=n_jobs, prefer=THREADING_PREFERENCE)(
        delayed(interpolate_single_day_worker)(
            run_context=run_context,
            date1=date,
            observations=daily_observations_df,
            stations=stations_df,
            monthly_normals=monthly_normals,
            monthly_climatology=monthly_climatology,
            grid=grid,
            write_output_file=True
        )
        for date in unique_dates
    )
    # Filter out dry days, fill in occasional nodata regions
    filtered_results = [result for result in results if result is not None]
    
    final_sum = np.nansum(filtered_results, axis=0)
    '''
    Some interpolations with very small amounts of rainfall can fail to solve,
    resulting in small regions of nodata within the valid geometry area.
    Treat them as 0, then mask the raster by border geometry again.
    '''
    masked_precipitation_raster = run_context.apply_mask_to_np_array(
        final_sum, grid["profile"]["transform"]
    )

    profile = grid["profile"].copy()
    profile.update(
        dtype=rasterio.float32, count=1, nodata=np.nan, compress="deflate"
    )

    with rasterio.open(run_context.output_directory / "summed_aggregate.tif", "w", **profile) as dst:
        dst.write(masked_precipitation_raster.astype(np.float32), 1)

    # Output geojson of observations for visual debugging and verification
    if args.geojson:
        for date in unique_dates:
            date_str = date.strftime(run_context.output_file_time_format)
            output_path = (
                run_context.output_directory / f"observations_{date_str}.geojson"
            )
            daily_observations = daily_observations_df[
                daily_observations_df["date"] == date
            ]
            build_daily_observations_geojson(
                output_path, daily_observations, stations_df
            )


if __name__ == "__main__":
    main()
