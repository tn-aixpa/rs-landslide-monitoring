"""
Parses number format from netcdf file output of Crespi, also flips raster upside-down
to fix weird R conventions which don't match those of GDAL
"""
import argparse
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import rasterio

band_count = 14245

# TODO: Come back and remove noqa: DTZ007 entry
date1 = datetime.strptime("01/01/1970", "%d/%m/%Y")  # noqa: DTZ007

d_2017 = 17167 - 3652

ap = argparse.ArgumentParser()

ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
args = ap.parse_args()
data_dir = Path(args.data_dir)
output_path = Path(data_dir / "crespi_data")

for band in range(d_2017, d_2017 + 366):
    current_date = date1 + timedelta(days=band + 3651)
    current_date_str = current_date.strftime("%d_%m_%Y")

    tmp_out_path = output_path / f"crespi_{current_date_str}_tmp.tif"
    dst_path = output_path / f"crespi_{current_date_str}.tif"
    if dst_path.exists():
        continue

    print(current_date_str)
    tmp_out_path_str = str(tmp_out_path)
    subprocess.run(
        [
            "gdal_translate",
            "-b",
            f"{band}",
            str(data_dir/ "DailySeries_1980_2018_Prec.nc"),
            tmp_out_path_str,
            "-co",
            "-a_srs",
            "EPSG:32632",
            "COMPRESS=DEFLATE",
            "-co",
            "PREDICTOR=3",
        ],
        check=False,
    )

    # Flip the tif upside down because of weird R conventions
    with rasterio.open(tmp_out_path_str) as src:
        data = src.read()
        profile = src.profile.copy()

        # Flip rows vertically
        flipped = data[:, ::-1, :]

        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(flipped)

    os.unlink(tmp_out_path)
