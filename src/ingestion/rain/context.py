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
        self.reference_start = parse_datetime("01/01/1985")  # Not many station observations before here
        self.reference_end = parse_datetime("31/12/2025")  # bolzano values stop here

        # Include data in this range during daily interpolation calculation
        self.interpolation_start_date = parse_datetime("01/01/2017")
        self.interpolation_end_date = parse_datetime("31/12/2017")
        self.climatology_decay_parameters = {}
        self.data_dir = data_dir

        self.dem_path = data_dir / "dem.tif"
        self.smoothed_dem_path = data_dir / "smoothed_elevation.tif"

        self.historical_stations_path = (
            data_dir / "stations_reprojected" / "filtered_stations_9am.csv"
        )
        self.historical_trentino_observations_path = (
            data_dir
            / "rainfall_observations"
            / "trentino_observations"
            / "observations_9am.csv"
        )
        self.historical_au_observations_path = data_dir / "temp" / "austria_grouped_9am.csv"
        self.historical_bolzano_observations_path = (
            data_dir / "rainfall_observations" / "bolzano_observations.csv"
        )
        # CH_OBSERVATIONS_PATH = data_dir /  'rainfall_observations' / 'merged_swiss.csv'
        self.historical_observations_files = [
            self.historical_trentino_observations_path,
            self.historical_au_observations_path,
            self.historical_bolzano_observations_path,
        ]

        self.output_directory = data_dir / "output" / "interpolated_daily_output"

        self.write_climatologies = True
        self.climatology_output_dir = data_dir / "output" / "climatology"

        self.output_file_time_format = "%d_%m_%Y"

        self.crespi_data_folder = data_dir / "crespi_data"

        self.bolzano_daily_stations_path = data_dir / "daily_stations_alto_adige_filtered_reprojected.csv"

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

    def setup_boundary(self, province: str | None = None):
        self.historical_observations_files = [self.historical_trentino_observations_path]
        if province is None:
            boundary_dataset = self.data_dir / "region_boundary_reprojected" / "boundary_reprojected.shp"
            # Miss off bolzano and austria observations if just considering trentino.
            self.historical_observations_files = self.historical_observations_files + [self.historical_au_observations_path,self.historical_bolzano_observations_path]
        elif province == 'trentino':
            boundary_dataset = self.data_dir / "boundary_reprojected" / "boundary_reprojected.shp"
        else:
            raise ValueError(f"Province {province} was not a recognised option")
        
        self.boundary_polygon_shapes = read_boundary_dataset(boundary_dataset)

