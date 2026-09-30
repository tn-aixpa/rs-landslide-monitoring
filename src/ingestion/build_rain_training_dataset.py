"""
PRISM-like anomaly interpolation for daily precipitation
Questo script viene usato per calculare 1. il climatology iniziale per ogni mese che costruire
il set di dati di addestramento; 2. i set di dati quotidiano

This will use all CPUs available through joblib to parallelize the process.

Se non c'e' piove per un giorno in particolare, non produciamo output per quell giorno (100% mask)


Roba da fare:
- Verifica che il estenzione dell'DEM copre tutti le stazione durante runtime as the one passed may be different
- Switch to logging library rather than printing
- Argument help to italian
- Add interpolation start and end date arguments
- Convert to conda
- README
- Download daily data
- Rework `grid` variable

"""

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from joblib import Parallel, delayed
from scipy.optimize import minimize
from scipy.spatial import cKDTree

from rain.build_daily_observations_geojson import build_daily_observations_geojson
from rain.delete_all_from_folder import delete_all_from_folder
from rain.is_debugging import is_debugging
from rain.parse_datetime import parse_datetime
from rain.read_observation_data import read_observation_data
from rain.read_station_data import read_station_data
from rain.context import RunContext
from rain.setup_logging import setup_logging

logger = setup_logging()

EPSILON = 1e-12

SMOOTHING_RADIUS = 10_000
SMOOTHING_HALF_DISTANCE = 2_000.0
N_JOBS = 4

if is_debugging():
    logger.info("Debugging detected, switching to single threading mode")
    N_JOBS = 1

THREADING_PREFERENCE = "processes"


def calculate_station_loo_sse(
    log_params_initial_guess: np.ndarray,
    sub_stations: pd.DataFrame,
    month_monthly_normals: pd.Series,
) -> float:
    """
    Performs leave one out (LOO) analysis to calculate sum-squared-error (sse)
    log_params: [log10(c_horizontal), log10(c_elevation)] for smooth optimizer stepping.
    """
    c_horiz = 10 ** log_params_initial_guess[0]
    c_elev = 10 ** log_params_initial_guess[1]

    station_xs = sub_stations["x"].to_numpy(dtype=float)
    station_ys = sub_stations["y"].to_numpy(dtype=float)
    station_zs = sub_stations["elevation"].to_numpy(dtype=float)
    obs = sub_stations["station_id"].map(month_monthly_normals).to_numpy(dtype=float)

    station_count = len(station_xs)
    if station_count < 3:
        return np.inf

    dx = station_xs[:, None] - station_xs[None, :]
    dy = station_ys[:, None] - station_ys[None, :]
    dz = station_zs[:, None] - station_zs[None, :]

    dist_sq = dx**2 + dy**2
    dz_sq = dz**2

    W = np.exp(-dist_sq / c_horiz) * np.exp(-dz_sq / c_elev)
    np.fill_diagonal(W, 0.0)  # Exclude LOO station
    A11 = W.sum(axis=1)
    A12 = (W * station_zs[None, :]).sum(axis=1)
    A22 = (W * (station_zs[None, :] ** 2)).sum(axis=1)

    b1 = (W * obs[None, :]).sum(axis=1)
    b2 = (W * station_zs[None, :] * obs[None, :]).sum(axis=1)

    det = A11 * A22 - (A12**2)
    valid_det = det > 1e-10

    alpha = np.zeros(
        station_count, dtype=float
    )  # Cramer's rule for WLS coefficients alpha & beta
    beta = np.zeros(station_count, dtype=float)

    alpha[valid_det] = (
        A22[valid_det] * b1[valid_det] - A12[valid_det] * b2[valid_det]
    ) / det[valid_det]
    beta[valid_det] = (
        A11[valid_det] * b2[valid_det] - A12[valid_det] * b1[valid_det]
    ) / det[valid_det]
    pred = (
        alpha + beta * station_zs
    )  # Predict value at target station i using its elevation

    fallback = ~valid_det & (A11 > EPSILON)  # Fallback if ill-conditioned
    pred[fallback] = b1[fallback] / A11[fallback]
    pred = np.maximum(0.0, pred)
    sse = float(np.sum((obs - pred) ** 2))

    return sse


def optimize_decay_params_for_month_worker(
    human_month: int,
    stations: pd.DataFrame,
    monthly_normals: pd.DataFrame,
    initial_c_horiz: float = 25_000.0**2,
    initial_c_elev: float = 500.0**2,
) -> dict:
    logger = setup_logging()
    """
    Optimizes decay parameters for a single month in <1 second.
    """
    first_parameter_guess = np.log10([initial_c_horiz, initial_c_elev])

    month_month_normals = monthly_normals[
        monthly_normals["month"] == human_month
    ].set_index("station_id")["normal"]
    sub_stations = stations[
        stations["station_id"].isin(month_month_normals.index)
    ].copy()

    res = minimize(
        fun=calculate_station_loo_sse,
        x0=first_parameter_guess,
        args=(sub_stations, month_month_normals),
        method="Nelder-Mead",
    )

    if "precision loss" in res.message.lower():
        logger.info(
            f"Optimisation error message: {res.message} after {res.nit} iterations"
        )

    best_c_horiz = 10 ** res.x[0]
    best_c_elev = 10 ** res.x[1]

    logger.info(
        f"Decay params for month {human_month:02d} complete | Best SSE: {res.fun:.2f} | c_horiz: {best_c_horiz:.1f}, c_elev: {best_c_elev:.1f}"
    )

    return {
        "month": human_month,
        "horizontal": best_c_horiz,
        "elevation": best_c_elev,
        "sse": res.fun,
    }


def optimize_daily_decay(
    day: pd.Timestamp,
    stations: pd.DataFrame,
    daily_observations: pd.DataFrame,
    initial_c_horiz: float = 412458716,
    initial_c_elev: float = 2.380205848486982e21,
):
    """
    TODO: combine with optimize_decay_params_for_month
    """
    first_parameter_guess = np.log10([initial_c_horiz, initial_c_elev])
    daily_precip_series = daily_observations.set_index("station_id")["precipitation"]
    sub_stations = stations[
        stations["station_id"].isin(daily_precip_series.index)
    ].copy()

    minimized_result = minimize(
        fun=calculate_station_loo_sse,
        x0=first_parameter_guess,
        args=(sub_stations, daily_precip_series),
        method="Nelder-Mead",
    )

    best_c_horiz = 10 ** minimized_result.x[0]
    best_c_elev = 10 ** minimized_result.x[1]

    return {"day": day, "horizontal": best_c_horiz, "elevation": best_c_elev}


def fast_parallel_parameter_search(
    stations: pd.DataFrame, monthly_normals: pd.DataFrame
) -> dict:
    """
    Given stations and monthly normals, calculate the best climatology parameters.
    This is generally pretty quick, taking a few seconds.
    This does NOT write out the climatology grid files, only determines the best parameters.

    """
    logger.info("Starting fast parameter optimization across 12 months...")

    results = Parallel(n_jobs=N_JOBS, prefer=THREADING_PREFERENCE)(
        delayed(optimize_decay_params_for_month_worker)(
            human_month=month,
            stations=stations,
            monthly_normals=monthly_normals,
        )
        for month in list(monthly_normals["month"].unique())
    )

    optimized_decay_params = {
        res["month"]: {
            "horizontal": res["horizontal"],
            "elevation": res["elevation"],
        }
        for res in results
    }

    return optimized_decay_params


def load_dem(path):
    with rasterio.open(path) as src:
        elevation = src.read(1).astype(float)
        profile = src.profile.copy()
        nodata = src.nodata
        transform = src.transform
        crs = src.crs

    if nodata is not None:
        valid_mask = elevation != nodata
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

    return {
        "elevation_2d": elevation,
        "valid_mask_2d": valid_mask,
        "x_2d": x,
        "y_2d": y,
        # Flattened valid cells used by interpolation.
        "x": x[valid_mask],
        "y": y[valid_mask],
        "elevation": elevation[valid_mask],
        "shape": elevation.shape,
        "transform": transform,
        "crs": crs,
        "profile": profile,
        "nodata": nodata,
    }


def smooth_elevation(
    rc: RunContext, grid, radius=SMOOTHING_RADIUS, half_distance=SMOOTHING_HALF_DISTANCE
):
    """
    Cacky implementation of smoothing a DEM - don't use a kernel, use brush-like smoothing using
    inefficient tree-structure.
    Use parameters from Crespi paper for smoothing
    """
    x = grid["x"]
    y = grid["y"]
    elevation = grid["elevation"]

    def save_smooth():
        smoothed_elevation_2d = np.full(grid["shape"], 0, dtype=np.float32)
        smoothed_elevation_2d[grid["valid_mask_2d"]] = grid["smoothed_elevation"]
        # Copy the spatial metadata from the original DEM.
        profile = grid["profile"].copy()

        profile.update(
            dtype=rasterio.float32, count=1, nodata=0, compress="deflate", predictor=3
        )
        logger.info("SAVING SMOOTHED")

        # Do not mask here; stations in Austria need their elevation too
        # masked_smoothed_elevation_2d = rc.apply_mask_to_np_array(smoothed_elevation_2d, profile['transform'])
        with rasterio.open(rc.SMOOTHED_DEM_PATH, "w", **profile) as dst:
            dst.write(smoothed_elevation_2d, 1)

    def reload_smoothed():
        with rasterio.open(rc.SMOOTHED_DEM_PATH) as src:
            smoothed_elevation_2d = src.read(1)
            smoothed_nodata = src.nodata
            if smoothed_nodata is not None:
                smoothed_elevation_2d[smoothed_elevation_2d == smoothed_nodata] = np.nan
        # Convert back to the same flattened valid-cell structure used by the interpolation code.
        grid["smoothed_elevation"] = smoothed_elevation_2d[grid["valid_mask_2d"]]

    if os.path.exists(rc.SMOOTHED_DEM_PATH):
        logger.info("Smoothed DEM found, reloading...")
        return reload_smoothed()

    logger.info("Smoothed DEM not found, creating from scratch...")
    coordinates = np.column_stack([x, y])
    tree = cKDTree(coordinates)

    smoothed = np.empty_like(elevation, dtype=float)

    for i, point in enumerate(coordinates):
        neighbours = tree.query_ball_point(point, radius)

        neighbours = np.asarray(neighbours)

        dx = x[neighbours] - x[i]
        dy = y[neighbours] - y[i]

        distance = np.hypot(dx, dy)

        weights = 0.5 ** (distance / half_distance)

        smoothed[i] = np.average(elevation[neighbours], weights=weights)

    grid["smoothed_elevation"] = smoothed
    save_smooth()


def calculate_monthly_normals(observations: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate mean monthly precipitation totals over the
    reference period.
    """

    observations = observations.copy()

    reference = observations.copy()

    reference["year"] = reference["date"].dt.year
    reference["month"] = reference["date"].dt.month

    monthly_precip_totals = reference.groupby(
        [
            "station_id",
            "year",
            "month",
        ],
        as_index=False,
    )["precipitation"].sum()

    normals = (
        monthly_precip_totals.groupby(
            [
                "station_id",
                "month",
            ],
            as_index=False,
        )["precipitation"]
        .mean()
        .rename(columns={"precipitation": "normal"})
    )

    return normals


def build_precipitation_climatology(
    rc: RunContext,
    stations: pd.DataFrame,
    monthly_normals: pd.DataFrame,
    grid: dict,
    clean=False,
) -> np.ndarray:
    """
    Vectorized PRISM-like climatology interpolation for all grid cells at once.
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

    with rasterio.open(
        rc.CLIMATOLOGY_OUTPUT_DIR / "summed_climatology.tif", "w", **profile
    ) as dst:
        dst.write(summed_climatology, 1)

    return climatology


def calculate_precipitation_anomalies(
    daily_observations: pd.DataFrame, station_monthly_normals: pd.DataFrame
):
    """
    What were the precipitation anomalies on this day compared with the average climatology?
    """

    day = daily_observations.copy()
    month = pd.Timestamp(day["date"].iloc[0]).month

    normals = station_monthly_normals[station_monthly_normals["month"] == month][
        [
            "station_id",
            "normal",
        ]
    ]

    day = day.merge(normals, on="station_id", how="inner")
    day = day[day["normal"] > EPSILON].copy()
    day["anomaly"] = day["precipitation"] / day["normal"]

    return day


def interpolate_daily_precipitation_vectorized(
    daily_observations: pd.DataFrame,
    stations: pd.DataFrame,
    monthly_normals: pd.DataFrame,
    monthly_climatology: np.ndarray,
    grid: dict,
    daily_decay_parameters: dict,
) -> np.ndarray:
    """
    Calcula precipitazione per un giorno in particulare
    Calculate precipitation on a particular day
    """
    anomalies = calculate_precipitation_anomalies(daily_observations, monthly_normals)
    if len(anomalies) == 0:
        return np.full(len(grid["x"]), np.nan, dtype=np.float32)

    station_metadata = stations[
        stations["station_id"].isin(anomalies["station_id"])
    ].copy()
    anomalies = (
        anomalies.set_index("station_id")
        .loc[station_metadata["station_id"]]
        .reset_index()
    )

    n_stations = len(station_metadata)

    sx = station_metadata["x"].to_numpy(dtype=float)[:, None]
    sy = station_metadata["y"].to_numpy(dtype=float)[:, None]
    sz = station_metadata["elevation"].to_numpy(dtype=float)[:, None]

    gx = grid["x"][None, :]
    gy = grid["y"][None, :]
    gz = grid["smoothed_elevation"][None, :]

    dist_sq = (sx - gx) ** 2 + (sy - gy) ** 2
    dz_sq = (sz - gz) ** 2

    c_horiz = daily_decay_parameters["horizontal"]
    c_elev = daily_decay_parameters["elevation"]

    weights = np.exp(-dist_sq / c_horiz) * np.exp(-dz_sq / c_elev)

    total_weights = weights.sum(axis=0)
    station_anomalies = anomalies["anomaly"].to_numpy(dtype=float)  # (S,)

    anomaly_grid = np.where(
        total_weights > EPSILON, (weights.T @ station_anomalies) / total_weights, np.nan
    )

    # Final daily estimate multiplication
    date = pd.Timestamp(daily_observations["date"].iloc[0])
    climatology = monthly_climatology[date.month - 1]

    estimate = anomaly_grid * climatology

    # dry-day constraint (3 nearest stations check)
    obs_precip = anomalies["precipitation"].to_numpy(dtype=float)  # (S,)
    if n_stations >= 3:
        # kth=2 partitions the array so the 3 smallest elements are in positions 0, 1, 2
        nearest_3_indices = np.argpartition(dist_sq, 2, axis=0)[:3, :]
        nearest_3_precip = obs_precip[nearest_3_indices]
        all_dry = np.all(nearest_3_precip == 0.0, axis=0)
        estimate[all_dry] = 0.0

    return np.maximum(0.0, estimate).astype(np.float32)


def main(
    rc: RunContext,
    single_day=None,
    climatology_only=False,
    climatology_single_month: str | None = None,
    clean=False,
):
    os.makedirs(rc.OUTPUT_DIRECTORY, exist_ok=True)

    logger.info("Loading DEM...")
    grid = load_dem(rc.DEM_PATH)

    smooth_elevation(rc, grid)

    logger.info("Loading station data...")
    stations = read_station_data(rc.STATIONS_PATH, run_context.SMOOTHED_DEM_PATH)
    observations = read_observation_data(
        rc.observations_files, rc.reference_start, rc.reference_end
    )
    logger.info("Calculating monthly normals...")

    monthly_normals = calculate_monthly_normals(observations)
    
    monthly_normals.to_csv(
        str(data_dir / 'temp' / 'monthly_normals.csv'), index=False
    )

    run_context.climatology_decay_parameters = fast_parallel_parameter_search(
        stations, monthly_normals
    )

    if climatology_single_month is not None:
        if not climatology_single_month.isdigit():
            raise ValueError("climatology_single_month must be an integer")
        monthly_normals = monthly_normals[
            monthly_normals["month"] == int(climatology_single_month)
        ]

    logger.info("Building monthly precipitation climatology...")

    # monthly_climatology looks like [12, [grid_x * grid_y]] array; one entry per month
    monthly_climatology = build_precipitation_climatology(
        rc, stations=stations, monthly_normals=monthly_normals, grid=grid, clean=clean
    )

    if climatology_single_month is not None:
        logger.info("climatology_single_month was set so exiting")
        return

    if climatology_only:
        logger.info("Climatology only, exiting")
        return

    def interpolate_single_day_worker(
        date1: np.datetime64,
        observations: pd.DataFrame,
        stations: pd.DataFrame,
        monthly_normals: pd.DataFrame,
        monthly_climatology: np.ndarray,
        grid: dict,
    ):
        logger = setup_logging()
        date = pd.Timestamp(date1)
        date_str = f"{date:%d/%m/%Y}"
        logger.info(f"Interpolating {date_str}")

        # Keep all station observations for the date (including 0 mm precip)
        daily_observations = observations[observations["date"] == date]

        # TODO: Could check this against Crespi data
        if (
            len(daily_observations) == 0
            or (daily_observations["precipitation"] == 0).all()
        ):
            logger.info(
                f"Skipping output for {date_str} as day was observed completely dry"
            )
            return

        daily_decay_parameters = optimize_daily_decay(
            date, stations, daily_observations
        )
        precipitation_valid_cells = interpolate_daily_precipitation_vectorized(
            daily_observations=daily_observations,
            stations=stations,
            monthly_normals=monthly_normals,
            monthly_climatology=monthly_climatology,
            grid=grid,
            daily_decay_parameters=daily_decay_parameters,
        )

        def valid_cells_to_raster(values: np.ndarray, grid, nodata=np.nan):
            """
            Convert a 1D array of interpolated valid cells back into
            the original 2D DEM raster shape. Kinda rubbish that we have to do this
            TODO: get rid of this
            """
            raster = np.full(grid["shape"], nodata, dtype=np.float32)
            raster[grid["valid_mask_2d"]] = values
            return raster

        precipitation_raster = valid_cells_to_raster(
            values=precipitation_valid_cells, grid=grid
        )
        date_str = date.strftime(rc.output_file_time_format)
        output_path = rc.OUTPUT_DIRECTORY / f"fleming_{date_str}.tif"

        if np.all(np.isnan(precipitation_raster) | (precipitation_raster == 0)):
            logger.info(
                f"Skipping output for {date_str} as day evaluated to dry across grid"
            )
        else:
            masked_precipitation_raster = rc.apply_mask_to_np_array(
                precipitation_raster, grid["profile"]["transform"]
            )

            profile = grid["profile"].copy()
            profile.update(
                dtype=rasterio.float32, count=1, nodata=np.nan, compress="deflate"
            )
            with rasterio.open(
                output_path,
                "w",
                **profile,
            ) as dst:
                dst.write(masked_precipitation_raster.astype(np.float32), 1)

            logger.info(f"Saved: {output_path}")

    observations = observations[
        observations["date"] >= run_context.interpolation_start_date
    ]
    observations = observations[
        observations["date"] <= run_context.interpolation_end_date
    ]
    unique_dates = np.sort(observations["date"].unique())
    if single_day is None:
        logger.info(
            f"Interpolating for {len(unique_dates)} dates between {run_context.interpolation_start_date} and {run_context.interpolation_end_date}"
        )
    else:
        single_day = parse_datetime(single_day)
        if single_day not in unique_dates:
            raise AssertionError(f"{single_day} not found in unique_dates")
        unique_dates = [single_day]
        daily_observations = observations[observations["date"] == single_day]
        single_day_date_str = single_day.strftime(rc.output_file_time_format)
        geojson_output_path = (
            rc.OUTPUT_DIRECTORY / f"fleming_{single_day_date_str}.geojson"
        )
        build_daily_observations_geojson(
            geojson_output_path, daily_observations, stations
        )

    Parallel(n_jobs=N_JOBS, prefer=THREADING_PREFERENCE)(
        delayed(interpolate_single_day_worker)(
            date1=date,
            observations=observations,
            stations=stations,
            monthly_normals=monthly_normals,
            monthly_climatology=monthly_climatology,
            grid=grid,
        )
        for date in unique_dates
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()

    normal = ap.add_argument_group("options", "Options used in production.")

    normal.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
    normal.add_argument(
        "--clean",
        action=argparse.BooleanOptionalAction,
        help="Se specificato, elimnina tutti output dalle esecuzione precedente",
    )
    normal.add_argument(
        "--interpolation-start-date",
        default="01/01/2017",
        help="Filtra osservazione da questa data",
    )
    normal.add_argument(
        "--interpolation-end-date",
        default="31/12/2017",
        help="Filtra osservazione a questa data",
    )

    debug = ap.add_argument_group(
        "debug options", "Options useful when during developement/ debugging."
    )

    # Debugging options
    debug.add_argument(
        "--climatology-only",
        action=argparse.BooleanOptionalAction,
        help="Debug option. Calculate the climatology and then exit without interpolating",
    )
    debug.add_argument(
        "--single-day",
        help="Debug option. Use this if you want to interpolate only a single day of output",
    )
    debug.add_argument(
        "--climatology-single-month",
        help="Debug option. Calculate climatology for a single month and then exit. 1 indexed",
    )

    args = ap.parse_args()
    data_dir = Path(args.data_dir)

    if not data_dir.exists:
        raise FileNotFoundError(f"{data_dir} does not exist!")

    run_context = RunContext(data_dir)

    run_context.interpolation_start_date = parse_datetime(args.interpolation_start_date)
    run_context.interpolation_end_date = parse_datetime(args.interpolation_end_date)

    main(
        run_context,
        single_day=args.single_day,
        climatology_only=args.climatology_only,
        climatology_single_month=args.climatology_single_month,
        clean=args.clean,
    )
