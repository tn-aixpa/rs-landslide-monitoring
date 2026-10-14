import pandas as pd


def calculate_monthly_normals(observations: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate mean monthly precipitation totals over the reference period.
    Make sure you pass the HISTORICAL observations rather than the most recent daily observations.
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
