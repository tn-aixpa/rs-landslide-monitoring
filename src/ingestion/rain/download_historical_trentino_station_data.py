"""
Download historical data from Trentino Meteo storico website
This is used to build the average climatology datasets.
"""

import argparse
import csv
from pathlib import Path

import pandas as pd
from build_storico_trentino_session import build_storico_trentino_session
from parse_storico_trentino_html import parse_storico_trentino_html
from setup_logging import setup_logging

logger = setup_logging()

FIELD_NAMES = ["station_id", "datetime", "piogga(mm)", "qual"]

session = build_storico_trentino_session()

def main(data_directory: Path, historical_convention: bool):
    out_folder = data_directory / "rainfall_observations" / "trentino_observations"
    stations_path = data_directory / "stations_trentino.csv"
    df = pd.read_csv(stations_path)
    station_ids = list(df["station_id"])
    with open(out_folder / "observations.csv", "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELD_NAMES)
        writer.writeheader()
        for station_id in station_ids:
            logger.info(f"Downloading {station_id}...")            
            url_to_use = f"http://storico.meteotrentino.it/cgi/webhyd.pl?co={station_id}&v=10.00_10.00&vn=Pioggia%20(millimetri)%20&p=Tutti%20i%20dati,01/01/1800,01/01/1800,period,1&o=Tabella,data&i=Giornaliera,Day,1&cat=rs&1791295541093"
            if historical_convention:
                url_to_use = f"http://storico.meteotrentino.it/cgi/webhyd.pl?co={station_id}&v=10.50_10.50&vn=Pioggia (millimetri) Tot da Annale Idrologico&p=Tutti i dati,01/01/1800,01/01/1800,period,1&o=Tabella,data&i=Giornaliera,Day,1&cat=rs&1789398854164="    

            response = session.get(url_to_use)
            rows = parse_storico_trentino_html(response.content)
            writer.writerows(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
    ap.add_argument(
        "--convention",
        choices=["historical", "modern"],
        type=str,
        default="modern",
        help="Use historical or modern convention for meteorological measurements; historically stations did 9am-9am",
    )
    ap.add_argument("--out-file-name", default="observations2.csv")
    args = ap.parse_args()
    data_dir = Path(args.data_dir)
    convention = args.convention
    main(data_dir, convention == 'historical')
