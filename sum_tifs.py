from pathlib import Path

import numpy as np
import rasterio

input_dir = Path("/home/jfleming/Documents/rs-landslide-monitoring/data2/output/interpolated_daily_output")
output_path = input_dir / "sum.tif"

tiff_files = sorted(input_dir.glob("*.tif"))

if not tiff_files:
    raise ValueError(f"No TIFF files found in {input_dir}")

with rasterio.open(tiff_files[0]) as src:
    profile = src.profile.copy()
    total = src.read(1, masked=True).filled(0).astype(np.float64)

    for path in tiff_files[1:]:
        with rasterio.open(path) as src:
            total += src.read(1, masked=True).filled(0)

    profile.update(dtype="float64", nodata=None)

with rasterio.open(output_path, "w", **profile) as dst:
    dst.write(total, 1)

print(f"Saved sum of {len(tiff_files)} TIFFs to {output_path}")