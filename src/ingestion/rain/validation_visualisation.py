"""
Basic comparison between our results and those of Crespi by plotting both their observed and predicted values against each other.
TODO: Also visualise dry day comparison
"""
import argparse
from glob import glob
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from ingestion.rain.crespi_comparison import RunContext, read_observation_data
from parse_datetime import parse_datetime
from read_station_data import read_station_data

ap = argparse.ArgumentParser()

ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
args = ap.parse_args()
data_dir = Path(args.data_dir)

run_context = RunContext(data_dir)

stations = read_station_data(run_context.STATIONS_PATH)

observations = read_observation_data(
    [run_context.OBSERVATIONS_PATH, run_context.BOLZANO_OBSERVATIONS_PATH],
    run_context.reference_start,
    run_context.reference_end,
)

current_max_observed = 20
current_max_predicted = 20

all_crespi_files = glob(str(run_context.crespi_data_folder) + "/*.tif")

for crespi_dataset in all_crespi_files:
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

        plt.scatter(merged["precipitation"], merged["predicted"], c="red", alpha=1)


all_fleming_files = glob(str(run_context.OUTPUT_DIRECTORY) + "/*.tif")

for fleming_dataset in all_fleming_files:
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
        plt.scatter(merged["precipitation"], merged["predicted"], c="blue", alpha=0.5)


one_to_one_line = np.linspace(0, current_max_observed, 10)
plt.plot(one_to_one_line, one_to_one_line, label="y = x", color="black", linewidth=2)
plt.xlabel("observed")
plt.xlim(0, current_max_observed + 5)
plt.ylim(0, current_max_predicted + 5)
plt.ylabel("predicted")
plt.show()
