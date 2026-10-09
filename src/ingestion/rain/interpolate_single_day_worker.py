import numpy as np
import pandas as pd
import rasterio
from calculate_station_loo_sse import calculate_station_loo_sse
from constants import EPSILON
from context import RunContext
from scipy.optimize import minimize
from setup_logging import setup_logging


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



def calculate_precipitation_anomalies(daily_observations: pd.DataFrame, station_monthly_normals: pd.DataFrame):
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

    station_metadata = stations[stations["station_id"].isin(anomalies["station_id"])].copy()
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


def interpolate_single_day_worker(
    run_context: RunContext,
    date1: np.datetime64,
    observations: pd.DataFrame,
    stations: pd.DataFrame,
    monthly_normals: pd.DataFrame,
    monthly_climatology: np.ndarray,
    grid: dict,
):
    logger = setup_logging() # Do this inside worker function too as it sets up its own context
    date = pd.Timestamp(date1)
    date_str = f"{date:%d/%m/%Y}"
    logger.info(f"Interpolating {date_str}")

    # Keep all station observations for the date (including 0 mm precip)
    daily_observations = observations[observations["date"] == date]

    if len(daily_observations) == 0 or (daily_observations["precipitation"] == 0).all():
        logger.info(f"Skipping output for {date_str} as day was observed completely dry")
        return

    daily_decay_parameters = optimize_daily_decay(date, stations, daily_observations)
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
    date_str = date.strftime(run_context.output_file_time_format)
    output_path = run_context.OUTPUT_DIRECTORY / f"fleming_{date_str}.tif"

    if np.all(np.isnan(precipitation_raster) | (precipitation_raster == 0)):
        logger.info(f"Skipping output for {date_str} as day evaluated to dry across grid")
    else:
        masked_precipitation_raster = run_context.apply_mask_to_np_array(
            precipitation_raster, grid["profile"]["transform"]
        )

        profile = grid["profile"].copy()
        profile.update(dtype=rasterio.float32, count=1, nodata=np.nan, compress="deflate")
        with rasterio.open(output_path,"w",**profile) as dst:
            dst.write(masked_precipitation_raster.astype(np.float32), 1)

        logger.info(f"Saved: {output_path}")
