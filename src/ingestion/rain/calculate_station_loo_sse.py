import numpy as np
import pandas as pd
from constants import EPSILON


def calculate_station_loo_sse(log_params_initial_guess: np.ndarray,sub_stations: pd.DataFrame,month_monthly_normals: pd.Series) -> float:
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
