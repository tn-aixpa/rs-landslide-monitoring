import os

import numpy as np
import pandas as pd
import rasterio
from constants import EPSILON
from context import RunContext
from delete_all_from_folder import delete_all_from_folder
from setup_logging import setup_logging

logger = setup_logging()

def build_or_load_precipitation_climatology(
    rc: RunContext,
    stations: pd.DataFrame,
    monthly_normals: pd.DataFrame,
    grid: dict,
    clean=False
) -> np.ndarray:
    """
    Vectorized PRISM-like climatology interpolation for all grid cells at once.

    If the climatology doesn't exist, create it, otherwise just load it from tif files
    """
    n_cells = len(grid["x"])

    climatology = np.empty((12, n_cells), dtype=np.float32)

    climatology_paths = [
        rc.CLIMATOLOGY_OUTPUT_DIR / f"precipitation_climatology_month_{month:02d}.tif"
        for month in range(1, 13)
    ]

    if clean:
        logger.info("Cleaning old precipitation climatology")
        delete_all_from_folder(str(rc.CLIMATOLOGY_OUTPUT_DIR))

    if all(os.path.exists(path) for path in climatology_paths):
        logger.info("Loading existing monthly climatology grids...")
        for month, path in enumerate(climatology_paths):
            with rasterio.open(path) as src:
                climatology_2d = src.read(1).astype(float)
                if src.nodata is not None:
                    climatology_2d[climatology_2d == src.nodata] = np.nan
            climatology[month] = climatology_2d[grid["valid_mask_2d"]]
        return climatology

    gx = grid["x"][None, :]
    gy = grid["y"][None, :]
    gz = grid["smoothed_elevation"][None, :]

    for month in range(1, 13):
        month_normals = monthly_normals[monthly_normals["month"] == month].set_index(
            "station_id"
        )["normal"]

        available_mask = stations["station_id"].isin(month_normals.index)
        sub_stations = stations[available_mask].copy()
        sx = sub_stations["x"].to_numpy(dtype=float)[:, None]
        sy = sub_stations["y"].to_numpy(dtype=float)[:, None]
        sz = sub_stations["elevation"].to_numpy(dtype=float)[:, None]
        normals = (
            sub_stations["station_id"].map(month_normals).to_numpy(dtype=float)[:, None]
        )

        dist_sq = (sx - gx) ** 2 + (sy - gy) ** 2
        dz_sq = (sz - gz) ** 2

        month_decay_params = rc.climatology_decay_parameters[month]
        c_horiz = month_decay_params["horizontal"]
        c_elev = month_decay_params["elevation"]
        W = np.exp(-dist_sq / c_horiz) * np.exp(
            -dz_sq / c_elev
        )  # Gaussian weight matrix W: shape (S, C)

        # Cramer's Rule
        # System: [A11  A12] [alpha] = [b1]
        #         [A12  A22] [beta ]   [b2]

        A11 = W.sum(axis=0)
        A12 = (W * sz).sum(axis=0)
        A22 = (W * (sz**2)).sum(axis=0)

        b1 = (W * normals).sum(axis=0)
        b2 = (W * sz * normals).sum(axis=0)

        det = A11 * A22 - (A12**2)

        valid_det = det > 1e-10  # Mask singular or ill-conditioned matrices

        alpha = np.zeros(n_cells, dtype=float)
        beta = np.zeros(n_cells, dtype=float)

        alpha[valid_det] = (
            A22[valid_det] * b1[valid_det] - A12[valid_det] * b2[valid_det]
        ) / det[valid_det]
        beta[valid_det] = (
            A11[valid_det] * b2[valid_det] - A12[valid_det] * b1[valid_det]
        ) / det[valid_det]

        pred = alpha + beta * gz[0, :]
        fallback_mask = ~valid_det & (
            A11 > EPSILON
        )  # Fallback to simple weighted mean for ill-conditioned matrices
        pred[fallback_mask] = b1[fallback_mask] / A11[fallback_mask]

        climatology[month - 1] = np.maximum(0.0, pred).astype(np.float32)

    os.makedirs(rc.CLIMATOLOGY_OUTPUT_DIR, exist_ok=True)
    profile = grid["profile"].copy()
    profile.update(
        dtype=rasterio.float32,
        count=1,
        nodata=np.nan,
        compress="deflate",
        blockxsize=256,
        blockysize=256,
        tiled=True,
    )  # TODO: nodata value  change this to 0

    summed_climatology = None
    for month in range(12):
        climatology_2d = np.full(grid["shape"], np.nan, dtype=np.float32)
        climatology_2d[grid["valid_mask_2d"]] = climatology[month]
        # TODO: Don't hard code
        output_path = (
            rc.CLIMATOLOGY_OUTPUT_DIR
            / f"precipitation_climatology_month_{month + 1:02d}.tif"
        )

        rc.apply_mask_to_np_array(climatology_2d, profile["transform"])
        
        masked_climatology_2d = rc.apply_mask_to_np_array(
            climatology_2d, profile["transform"]
        )
        if summed_climatology is None:
            summed_climatology = masked_climatology_2d
        else:
            summed_climatology = summed_climatology + masked_climatology_2d

        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(masked_climatology_2d, 1)

    # TODO: Move this filename to some constant
    with rasterio.open(
        rc.CLIMATOLOGY_OUTPUT_DIR / "summed_climatology.tif", "w", **profile
    ) as dst:
        dst.write(summed_climatology, 1)

    return climatology
