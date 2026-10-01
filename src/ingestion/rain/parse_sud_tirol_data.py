import argparse
import os
from pathlib import Path

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
args = ap.parse_args()
data_dir = Path(args.data_dir)

DATE_COLUMN_NAME = "Unnamed: 2"
RAIN_COLUMN_NAME = "sum"

RAIN_COLUMN_NAME_2 = "Niederschlag\nPrecipitazione\n[mm]\n09:00 - 09:00"
DATE_COLUMN_NAME_2 = "Datum\nData"

BASE_FOLDER = data_dir / "responses" / "sudtirol"

for file in os.listdir(BASE_FOLDER):
    print(file)
    df = pd.read_excel(BASE_FOLDER / file, skiprows=13, skipfooter=1)
    if RAIN_COLUMN_NAME in list(df):
        df = df[[DATE_COLUMN_NAME, RAIN_COLUMN_NAME]]
        df.rename(
            columns={DATE_COLUMN_NAME: "datetime", RAIN_COLUMN_NAME: "piogga(mm)"},
            inplace=True,
        )

    else:
        df = pd.read_excel(BASE_FOLDER / file, skiprows=12)
        if RAIN_COLUMN_NAME_2 not in df:
            raise AssertionError(list(df))

        df = df[[RAIN_COLUMN_NAME_2, DATE_COLUMN_NAME_2]]
        df.rename(
            columns={DATE_COLUMN_NAME_2: "datetime", RAIN_COLUMN_NAME_2: "piogga(mm)"},
            inplace=True,
        )

    df["datetime"] = pd.to_datetime(df["datetime"], format="%d.%m.%Y")
    df["datetime"] = df["datetime"].dt.strftime("%H:%M:%S %d/%m/%Y")
    df["qual"] = 1  # dato buono
    station_id = file.split("-")[0]
    df["station_id"] = station_id
    df = df[["station_id", "datetime", "piogga(mm)", "qual"]]
    df = df[df["piogga(mm)"] != "---"]

    df.to_csv(
        str(data_dir / "rainfall_observations" / "bolzano_observations.csv"),
        mode="a",
        index=False,
    )
