from pathlib import Path

import numpy as np
from rasterio.features import geometry_mask

from rain.parse_datetime import parse_datetime
from rain.read_boundary_dataset import read_boundary_dataset


class RunContext:
    """
    Holds variables determined at program start e.g. by user argument.
    """

    def __init__(self, data_dir: Path):

        # Include data in this range during calculation of climatology
        # TODO: Inclusive?
        self.reference_start = parse_datetime(
            "01/01/1985"
        )  # Not many station observations before here
        self.reference_end = parse_datetime("31/12/2025")  # bolzano values stop here

        # Include data in this range during daily interpolation calculation
        self.interpolation_start_date = parse_datetime("01/01/2017")
        self.interpolation_end_date = parse_datetime("31/12/2017")
        self.climatology_decay_parameters = {}
        self.data_dir = data_dir

        self.DEM_PATH = data_dir / "dem.tif"
        self.SMOOTHED_DEM_PATH = data_dir / "smoothed_elevation.tif"

        self.STATIONS_PATH = (
            data_dir / "stations_reprojected" / "filtered_stations_9am.csv"
        )
        self.OBSERVATIONS_PATH = (
            data_dir
            / "rainfall_observations"
            / "trentino_observations"
            / "observations_9am.csv"
        )
        self.AU_OBSERVATIONS_PATH = data_dir / "temp" / "austria_grouped_9am.csv"
        self.BOLZANO_OBSERVATIONS_PATH = (
            data_dir / "rainfall_observations" / "bolzano_observations.csv"
        )
        # CH_OBSERVATIONS_PATH = data_dir /  'rainfall_observations' / 'merged_swiss.csv'
        self.observations_files = [
            self.OBSERVATIONS_PATH,
            self.AU_OBSERVATIONS_PATH,
            self.BOLZANO_OBSERVATIONS_PATH,
        ]

        self.OUTPUT_DIRECTORY = data_dir / "output" / "interpolated_daily_output"

        self.WRITE_CLIMATOLOGIES = True
        self.CLIMATOLOGY_OUTPUT_DIR = data_dir / "output" / "climatology"

        self.BOUNDARY_DATASET = (
            data_dir / "boundary_reprojected" / "boundary_reprojected.shp"
        )

        # TODO: move to static constructor
        self.boundary_polygon_shapes = read_boundary_dataset(self.BOUNDARY_DATASET)

        self.output_file_time_format = "%d_%m_%Y"

        self.crespi_data_folder = data_dir / "crespi_data"

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
