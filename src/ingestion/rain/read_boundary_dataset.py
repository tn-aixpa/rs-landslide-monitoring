from pathlib import Path

import fiona


def read_boundary_dataset(boundary_dataset_path: Path):
    """
    Don't think Trentino has exclaves/ enclaves but play it safe
    """
    with fiona.open(boundary_dataset_path, "r") as shapefile:
        shapes = [feature["geometry"] for feature in shapefile]
    return shapes
