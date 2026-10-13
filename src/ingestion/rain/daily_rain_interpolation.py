'''
Hello
'''
import argparse
import sys
from pathlib import Path

import pandas as pd
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


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
    ap.add_argument("--date", help="Todays date, dd/mm/yyyy format. Defaults to yesterday's date in Italy")
    args = ap.parse_args()
    data_dir = Path(args.data_dir)
    
    if args.date is None:
        today = pd.Timestamp.now(tz=TIME_ZONE).normalize()
    else:
        today = parse_datetime(args.date)
        today = today.tz_localize(TIME_ZONE)

    # No point considering today as data won't be complete
    yesterday = today - pd.Timedelta(days=1)
    day_before_yesterday = yesterday - pd.Timedelta(days = 1)
    logger.info(f"Considering {day_before_yesterday} to {yesterday}")
    run_context = RunContext(data_dir)
    run_context.setup_boundary()
    
    daily_observations_df = time_range_download(logger, run_context, yesterday, yesterday)
    # Historical observations are used to calculate daily anomaly. Meterological concept used for this model.
    # Unfortunately this means mixing time formats; unlikely to result in inaccuracy.
    historical_observations = read_observation_data(run_context.historical_observations_files)

    stations_df = read_station_data(run_context.historical_stations_path, run_context.smoothed_dem_path)
    
    grid = load_dem(run_context.smoothed_dem_path, smoothed=True)
    monthly_normals = calculate_monthly_normals(historical_observations)
    monthly_climatology = build_or_load_precipitation_climatology(run_context, stations=stations_df, monthly_normals=monthly_normals, grid=grid)
    yesterday = yesterday.tz_localize(None).normalize()
    unique_dates = pd.date_range(yesterday, yesterday, freq='D')
    # unique_dates = daily_observations_df['date'].unique()
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
