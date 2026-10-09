'''
Hello
'''

import argparse
from pathlib import Path

import pandas as pd
from build_or_load_precipitation_climatology import (
    build_or_load_precipitation_climatology,
)
from calculate_monthly_normals import calculate_monthly_normals
from constants import THREADING_PREFERENCE
from context import RunContext
from daily_download import time_range_download
from interpolate_single_day_worker import interpolate_single_day_worker
from is_debugging import is_debugging
from joblib import Parallel, delayed
from parse_datetime import parse_datetime
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
    ap.add_argument("--date", help="Todays date, dd/mm/yyyy format. Defaults to today's date in Italy")
    args = ap.parse_args()
    data_dir = Path(args.data_dir)

    if args.date is None:
        today = pd.Timestamp.now(tz='Europe/Rome').normalize()
    else:        
        today = parse_datetime(args.date)
    
    yesterday = today - pd.Timedelta(days=1)


    observations_df = time_range_download(data_dir, yesterday, today)
    run_context = RunContext(data_dir)
    stations_df = read_station_data(run_context.historical_stations_path, run_context.smoothed_dem_path)
    stations_df = stations_df[stations_df['provincia'] == 'tn']
    bolzano_stations = read_station_data(run_context.bolzano_daily_stations_path, run_context.smoothed_dem_path)
    # TODO: Merge stations_df and bolzano_stations

    monthly_normals = calculate_monthly_normals(observations_df)
    monthly_climatology = build_or_load_precipitation_climatology(run_context, stations=stations_df, monthly_normals=monthly_normals, grid=grid)

    Parallel(n_jobs=N_JOBS, prefer=THREADING_PREFERENCE)(
        delayed(interpolate_single_day_worker)(
            run_context=run_context,
            date1=date,
            observations=observations_df,
            stations=stations_df,
            monthly_normals=monthly_normals,
            monthly_climatology=monthly_climatology,
            grid=grid,
        )
        for date in unique_dates
    )