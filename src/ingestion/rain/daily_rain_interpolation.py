"""
Used to create daily interpolated data which can then be aggregated.
"""

import argparse
from pathlib import Path

import pandas as pd
from build_daily_observations_geojson import build_daily_observations_geojson
from build_or_load_precipitation_climatology import (
    build_or_load_precipitation_climatology,
)
from calculate_monthly_normals import calculate_monthly_normals
from constants import THREADING_PREFERENCE, TIME_ZONE
from context import RunContext
from daily_download import time_range_download
from interpolate_single_day_worker import interpolate_single_day_worker
from is_debugging import is_debugging
from joblib import Parallel, delayed
from load_dem import load_dem
from parse_datetime import parse_datetime
from read_observation_data import read_observation_data
from read_station_data import read_station_data
from setup_logging import setup_logging

N_JOBS = 4

logger = setup_logging()

if is_debugging():
    # There are some weird C library shenanigans that cause the debug session to crash when debugging in vscode debugger
    logger.info("Debugging detected, switching to single threading mode")
    N_JOBS = 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()

    ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
    ap.add_argument(
        "--date-from",
        help="Date range to, dd/mm/yyyy format. Defaults to yesterday's date in Italy",
    )
    ap.add_argument(
        "--date-to",
        help="Date range to, dd/mm/yyyy format. Defaults to yesterday's date in Italy",
    )

    debug_group = ap.add_argument_group("debug", "debug options")
    debug_group.add_argument(
        "--geojson",
        action="store_true",
        help="Output geojson of daily observations for help in debugging",
    )

    args = ap.parse_args()
    data_dir = Path(args.data_dir)

    if (args.date_from is None and args.date_to is not None) or (
        args.date_from is not None and args.date_to is None
    ):
        raise AssertionError("Invalid date range")

    if args.date_from is None and args.date_to is None:
        # No point considering today as data won't be complete,
        today = pd.Timestamp.now(tz=TIME_ZONE).normalize()
        yesterday = today - pd.Timedelta(days=1)
        date_from = yesterday
        date_to = yesterday
    else:
        date_from = parse_datetime(args.date_from)
        date_from = date_from.tz_localize(TIME_ZONE)

        date_to = parse_datetime(args.date_to)
        date_to = date_to.tz_localize(TIME_ZONE)

    if date_to < date_from:
        raise AssertionError(f"{date_from} must be before {date_to}")
    time_delta = date_to - date_from
    logger.info(f"Considering {time_delta.days} days between {date_from:%d/%m/%Y} to {date_to:%d/%m/%Y}")
    run_context = RunContext(data_dir)
    run_context.setup()

    daily_observations_df = time_range_download(logger, run_context, date_from, date_to)

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

    Parallel(n_jobs=N_JOBS, prefer=THREADING_PREFERENCE)(
        delayed(interpolate_single_day_worker)(
            run_context=run_context,
            date1=date,
            observations=daily_observations_df,
            stations=stations_df,
            monthly_normals=monthly_normals,
            monthly_climatology=monthly_climatology,
            grid=grid,
        )
        for date in unique_dates
    )

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
