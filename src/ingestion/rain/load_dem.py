'''
Load DEM into grid attributes information
'''
import numpy as np
import rasterio


def load_dem(path, smoothed = False) -> dict:
    """
    TODO: Return type for this could quite happily be turned into a class called GridAttributes or something
    Setup the grid based on either smoothed or regular DEM

    Args:
        path (_type_): _description_
        smoothed (bool, optional): _description_. Defaults to False.

    Returns:
        _type_: _description_
    """
    with rasterio.open(path) as src:
        elevation = src.read(1).astype(float)
        profile = src.profile.copy()
        src_nodata = src.nodata
        transform = src.transform
        crs = src.crs

    if src_nodata is not None:
        valid_mask = elevation != src_nodata
        elevation[~valid_mask] = np.nan
    else:
        valid_mask = np.isfinite(elevation)

    rows, cols = np.indices(elevation.shape)

    x, y = rasterio.transform.xy(
        transform,
        rows,
        cols,
        offset="center",
    )

    # rasterio may return flattened coordinate arrays.
    # Restore them to the same 2D shape as the DEM.
    x = np.asarray(x, dtype=float).reshape(elevation.shape)
    y = np.asarray(y, dtype=float).reshape(elevation.shape)

    temp = {
        "elevation_2d": elevation,
        "valid_mask_2d": valid_mask,
        "x_2d": x,
        "y_2d": y,
        # Flattened valid cells used by interpolation.
        "x": x[valid_mask],
        "y": y[valid_mask],
        "shape": elevation.shape,
        "transform": transform,
        "crs": crs,
        "profile": profile,
        "nodata": src_nodata,
    }

    if smoothed:
        temp['smoothed_elevation'] = elevation[valid_mask]
    else:
        temp["elevation"] = elevation[valid_mask]

    return temp
