"""
Basic comparison between our results and those of Crespi by plotting both their observed and predicted values against each other.
Problem with this plot is that 0mm predictions don't show up very well. Probably needs a bar plot or something
"""
import argparse
from glob import glob
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from crespi_comparison import RunContext, read_observation_data
from parse_datetime import parse_datetime
from read_station_data import read_station_data

ap = argparse.ArgumentParser()

ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
args = ap.parse_args()
data_dir = Path(args.data_dir)

run_context = RunContext(data_dir)

stations = read_station_data(run_context.historical_stations_path)

observations = read_observation_data(
    [run_context.historical_trentino_observations_path, run_context.historical_bolzano_observations_path],
    run_context.reference_start,
    run_context.reference_end,
)

current_max_observed = 20
current_max_predicted = 20

all_crespi_files = glob(str(run_context.crespi_data_folder) + "/*.tif")

for i,crespi_dataset in enumerate(all_crespi_files):
    with rasterio.open(crespi_dataset) as crespi_src:
        crespi_stem = Path(crespi_dataset).stem
        date_str = crespi_stem[7:].replace("_", "/")
        time_stamp = parse_datetime(date_str)
        daily_observations = observations[observations["date"] == time_stamp]
        merged = stations.merge(daily_observations, how="inner", on="station_id")
        coords = list(zip(merged.x, merged.y))
        result = crespi_src.sample(coords)
        new_series = []
        for r in result:
            new_series.append(r[0])
        if len(new_series) != len(merged):
            raise AssertionError("Could not join on result")
        if any(x == crespi_src.nodata for x in new_series):
            raise AssertionError("Retreived nodata from crespi")

        merged["predicted"] = new_series

        current_max_observed = max(current_max_observed, merged["precipitation"].max())

        current_max_predicted = max(current_max_predicted, merged["predicted"].max())

        plt.scatter(merged["precipitation"], merged["predicted"], c="red", alpha=1, label="crespi" if i == 0 else None)


all_fleming_files = glob(str(run_context.output_directory) + "/*.tif")

for i,fleming_dataset in enumerate(all_fleming_files):
    with rasterio.open(fleming_dataset) as crespi_src:
        crespi_stem = Path(fleming_dataset).stem
        date_str = crespi_stem[8:].replace("_", "/")
        time_stamp = parse_datetime(date_str)
        daily_observations = observations[observations["date"] == time_stamp]
        merged = stations.merge(daily_observations, how="inner", on="station_id")
        coords = list(zip(merged.x, merged.y))
        result = crespi_src.sample(coords)
        new_series = []
        for r in result:
            new_series.append(r[0])
        if len(new_series) != len(merged):
            raise AssertionError("Could not join on result")
        if any(x == crespi_src.nodata for x in new_series):
            raise AssertionError("Retreived nodata from crespi")

        merged["predicted"] = new_series

        current_max_observed = max(current_max_observed, merged["precipitation"].max())

        current_max_predicted = max(current_max_predicted, merged["predicted"].max())

        # TODO: Also check 0 predictions
        plt.scatter(merged["precipitation"], merged["predicted"], c="blue", alpha=0.5, label="fleming" if i == 0 else None)


one_to_one_line = np.linspace(0, current_max_observed, 10)
plt.plot(one_to_one_line, one_to_one_line, label="y = x", color="black", linewidth=2)
plt.xlabel("observed (mm)")
plt.xlim(0, current_max_observed + 5)
plt.ylim(0, current_max_predicted + 5)
plt.ylabel("predicted (mm)")
plt.legend()
plt.show()
