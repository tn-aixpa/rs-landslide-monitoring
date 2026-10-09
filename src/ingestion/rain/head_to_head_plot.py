"""
WIP
"""
import argparse
import random
from glob import glob
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from crespi_comparison import RunContext
from parse_datetime import parse_datetime
from read_station_data import read_station_data

ap = argparse.ArgumentParser()
ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
args = ap.parse_args()
data_dir = Path(args.data_dir)


output_path = Path(data_dir / "crespi_data")

run_context = RunContext(data_dir)

# Use stations as comparison points, need to pick abitrary points
stations = read_station_data(run_context.historical_stations_path)

all_crespi_files = glob(str(run_context.crespi_data_folder) + "/*.tif")
crespi_paths = [Path(file) for file in all_crespi_files]

markers = ["o", "s", "^", "v", "D", "*", "P", "X", "<", ">", "p", "h"]

coords = list(zip(stations.x, stations.y))

big_crespi_series = pd.Series()
big_fleming_series = pd.Series()

for crespi_dataset in crespi_paths:
    crespi_date = crespi_dataset.stem[7:]
    crespi_stem = Path(crespi_dataset).stem
    date_str = crespi_stem[7:].replace("_", "/")
    time_stamp = parse_datetime(date_str)
    fleming_file_path = run_context.output_directory / f"fleming_{crespi_date}.tif"

    fleming_series = []
    if not fleming_file_path.exists():
        # Then all the fleming values are 0, plot em
        fleming_series = pd.Series([0 for _ in range(len(stations))])
    else:
        with rasterio.open(fleming_file_path) as fleming_src:
            result = fleming_src.sample(coords)

            new_series_list = []
            for r in result:
                new_series_list.append(r[0])

            fleming_series = pd.Series(new_series_list)
            fleming_series = fleming_series.replace(fleming_src.nodata, 0) # nodata means no rain
        
    with rasterio.open(crespi_dataset) as crespi_src:
        result = crespi_src.sample(coords)
        new_series_list = []
        for r in result:
            new_series_list.append(r[0])
        if len(new_series_list) != len(stations):
            raise AssertionError("Could not join on result")

        crespi_series = pd.Series(new_series_list)
        crespi_series = crespi_series.replace(crespi_src.nodata, 0) # nodata means no rain
    color = (random.random(), random.random(), random.random())
    marker = random.choice(markers)
    plt.scatter(crespi_series, fleming_series, marker=marker, color=color, alpha=0.5)

    if big_crespi_series is None:
        big_crespi_series = crespi_series
        big_fleming_series = fleming_series
    else:
        big_crespi_series = pd.concat([big_crespi_series, crespi_series])
        big_fleming_series = pd.concat([big_fleming_series, fleming_series])


correlation = big_crespi_series.corr(big_fleming_series)
print(f"Corr is: {correlation}")


one_to_one_line = np.linspace(0, 100, 10)
plt.plot(one_to_one_line, one_to_one_line, label="y = x", color="black", linewidth=2)
plt.xlabel("crespi (mm)")
plt.xlim(0, 100)
plt.ylim(0, 100)
plt.ylabel("fleming (mm)")
plt.legend()
plt.show()
