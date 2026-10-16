from pathlib import Path

import numpy as np
from parse_datetime import parse_datetime
from rasterio.features import geometry_mask
from read_boundary_dataset import read_boundary_dataset


class RunContext:
    """
    Holds variables determined at program start e.g. by user argument.
    """

    def __init__(self, data_dir: Path):

        # Include data in this range during calculation of climatology
        # These are both _inclusive_
        # Not many station observations before 1985
        self.reference_start = parse_datetime("01/01/1985")
        self.reference_end = parse_datetime("31/12/2025")  # bolzano values stop here

        # Include data in this range during daily interpolation calculation
        self.interpolation_start_date = parse_datetime("01/01/2017")
        self.interpolation_end_date = parse_datetime("31/12/2017")
        self.climatology_decay_parameters = {}
        self.data_dir = data_dir

        self.dem_path = data_dir / "dem.tif"
        self.smoothed_dem_path = data_dir / "smoothed_elevation.tif"

        self.historical_stations_path = (
            data_dir / "stations_reprojected" / "trentino_stations.csv"
        )
        self.historical_trentino_observations_path = (
            data_dir / "historical_rainfall_observations" / "trentino_observations.csv"
        )
        # We check if this exists before reading. Not compulsary.
        self.historical_austria_observations_path = (
            data_dir / "historical_rainfall_observations" / "austria_grouped_9am.csv"
        )
        self.historical_bolzano_observations_path = (
            data_dir / "historical_rainfall_observations" / "bolzano_observations.csv"
        )
        self.historical_observations_files = None

        self.daily_rainfall_observations_dir = data_dir / "daily_rainfall_observations"

        self.output_directory = data_dir / "output" / "interpolated_daily_output"

        self.write_climatologies = True
        self.climatology_output_dir = data_dir / "output" / "climatology"

        self.output_file_time_format = "%d_%m_%Y"

        self.crespi_data_folder = data_dir / "crespi_data"

        self.bolzano_daily_stations_path = (
            data_dir / "stations_reprojected" / "alto_adige_stations.csv"
        )

    def apply_mask_to_np_array(self, np_array, transform):
        """
        TODO: code smell, move elsewhere.
        """
        mask_climatology_2d = geometry_mask(
            self.boundary_polygon_shapes,
            out_shape=np_array.shape,
            transform=transform,
            invert=False,
        )
        return np.ma.MaskedArray(np_array, mask_climatology_2d)

    def setup(self, province: str | None = None):
        """
        Args:
            province (str | None, optional): Set this only during comparison of results when cutting out alto-adige data. Defaults to None.

        Raises:
            ValueError: _description_
        """
        self.historical_observations_files = [
            self.historical_trentino_observations_path
        ]
        if province is None:
            boundary_dataset = (
                self.data_dir
                / "region_boundary_reprojected"
                / "boundary_reprojected.shp"
            )
            # Miss off bolzano and austria observations if just considering trentino.
            self.historical_observations_files = self.historical_observations_files + [
                self.historical_bolzano_observations_path,
            ]
        elif province == "trentino":
            boundary_dataset = (
                self.data_dir / "boundary_reprojected" / "boundary_reprojected.shp"
            )
        else:
            raise ValueError(f"Province {province} was not a recognised option")

        if self.historical_austria_observations_path.exists():
            self.historical_observations_files.append(
                self.historical_austria_observations_path
            )

        self.boundary_polygon_shapes = read_boundary_dataset(boundary_dataset)
