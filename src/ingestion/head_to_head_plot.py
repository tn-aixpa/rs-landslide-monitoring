"""
WIP
"""
import argparse
from glob import glob
from pathlib import Path

from rain.build_rain_training_dataset import RunContext, read_observation_data
from rain.read_station_data import read_station_data

ap = argparse.ArgumentParser()

ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")

data_dir = Path(ap.data_dir)

output_path = Path(data_dir / "crespi_data")

run_context = RunContext(data_dir)

stations = read_station_data(run_context.STATIONS_PATH)

observations = read_observation_data(
    [run_context.OBSERVATIONS_PATH, run_context.BOLZANO_OBSERVATIONS_PATH],
    run_context.reference_start,
    run_context.reference_end,
)

all_crespi_files = glob(str(run_context.crespi_data_folder) + "/*.tif")
crespi_paths = [Path(file) for file in all_crespi_files]

for crespi_path in crespi_paths:
    crespi_date = crespi_path.stem[7:]
    fleming_file_path = run_context.OUTPUT_DIRECTORY / f"fleming_{crespi_date}.tif"

    # TODO: Also check 0 predictions
    if not fleming_file_path.exists():
        continue
