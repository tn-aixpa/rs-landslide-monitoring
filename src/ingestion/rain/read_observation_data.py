from pathlib import Path

import numpy as np
import pandas as pd
from parse_datetime import parse_datetime

BAD_OBSERVATION_CODES = [
    90,  # Delayed because of snow
    140,  # Uncertain data
]


def read_observation_data(
    observation_files: list[Path], reference_start=None, reference_end=None
) -> pd.DataFrame:
    """
    Austrian + swiss observation data are kept in seperate files otherwise too big for MS Excel,
    so merge them in here instead.

    Also parse datetime fields, validate data etc.

    Args:
        observation_files (list[Path]): _description_
        reference_start (_type_, optional): _description_. Defaults to None.
        reference_end (_type_, optional): _description_. Defaults to None.

    Raises:
        Exception: _description_

    Returns:
        pd.DataFrame: _description_
    """

    df_list = []

    for observations_file in observation_files:
        observations = pd.read_csv(
            observations_file, dtype={"piogga(mm)": np.float32, "qual": np.int16}
        )

        observations["date"] = parse_datetime(observations["datetime"])

        if len(df_list) != 0 and set(observations) != set(df_list[0]):
            raise ValueError(
                f"Column mismatch; could not merge observations file at {observations_file}"
            )

        df_list.append(observations)

    observations = pd.concat(df_list)
    observations = observations.dropna(subset="piogga(mm)")

    observations = observations[
        ~observations["qual"].isin(BAD_OBSERVATION_CODES)
    ]  # drop bad data rows

    observations["precipitation"] = pd.to_numeric(
        observations["piogga(mm)"], errors="coerce"
    )

    if reference_start:
        observations = observations[observations["date"] >= reference_start]
    if reference_end:
        observations = observations[observations["date"] <= reference_end]

    observations["station_id"] = observations["station_id"].astype("str")
    return observations.drop(["piogga(mm)", "datetime"], axis=1)
