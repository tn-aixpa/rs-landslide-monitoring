"""
Exports time_range_download
"""

import io
from logging import Logger

import pandas as pd
import requests as r
from build_storico_trentino_session import build_resilient_session
from constants import TIME_ZONE
from context import RunContext
from parse_datetime import parse_datetime


def _group_by_day(
    df: pd.DataFrame,
    date_column_name: str,
    value_column_name: str,
    group_by_extras: list[str] | None = None,
    historical_meteorological_format=False,
):

    offset_amount = None
    label = "left"
    if historical_meteorological_format:
        offset_amount = "9h"
        label = "right"

    gg = [
        pd.Grouper(
            key=date_column_name,
            freq="1D",
            offset=offset_amount,
            closed="left",
            label=label,
        )
    ]
    if group_by_extras is not None:
        gg = gg + group_by_extras

    grouped = df.groupby(gg)[value_column_name].sum().reset_index()
    return grouped.sort_values(by=date_column_name)


def _download_bolzano_date_range(
    logger: Logger,
    session: r.Session,
    station_id: str,
    date_from: pd.Timestamp,
    date_to: pd.Timestamp,
    historical_meterological_format=False,
) -> pd.DataFrame:
    """
    This does both the download and the aggregation to keep it consistent with response from trentino's service
    """

    date_to = date_to + pd.Timedelta(days=1)
    # All times here are expressed in CEST, and are inclusive
    if historical_meterological_format:
        raise NotImplementedError("Not implemented")
        date_from = date_from.replace(hour=9)
        date_to = date_to.replace(hour=9)

    date_from_str = date_from.strftime("%Y%m%d%H%M")
    date_to_str = date_to.strftime("%Y%m%d%H%M")

    # Sensor code N = rain in mm
    url = f"https://geoservices.buergernetz.bz.it/services/meteo/v1/timeseries?station_code={station_id}&sensor_code=N&date_from={date_from_str}&date_to={date_to_str}"
    logger.info(f"Downloading {url}")
    response = session.get(url)
    response.raise_for_status()

    response_json = response.json()
    if len(response_json) == 0:
        return None

    bolzano_daily_observations = pd.DataFrame(response.json())
    # Follows a non-standard timestamp format. Also use opportunity to strip off time + timezone which we don't need
    bolzano_daily_observations["DATE"] = parse_datetime(
        bolzano_daily_observations["DATE"].str[:10]
    )

    result = _group_by_day(
        bolzano_daily_observations,
        "DATE",
        "VALUE",
        historical_meteorological_format=historical_meterological_format,
    )
    result["temp_date"] = result["DATE"].dt.tz_localize(TIME_ZONE)
    result = result[result["temp_date"] >= date_from]
    result = result[result["temp_date"] < date_to]
    result = result.drop(["temp_date"], axis=1)
    result["station_id"] = station_id
    result["qual"] = 1
    # Match column names from Trentino
    result = result.rename(columns={"DATE": "date", "VALUE": "precipitation"})
    return result


def _download_trentino_archive(
    logger: Logger, session: r.Session, date_from: pd.Timestamp, date_to: pd.Timestamp
):
    """
    Downloads data in parquet format. Gets updated daily

    Args:
        date_from (pd.Timestamp): _description_
        date_to (pd.Timestamp): _description_
    """

    """
    annoyingly this API uses the Etc/GMT-1 timezone
    # meaning that first days of the month's data is split between files
    # if we use CET.
    """
    download_from = date_from
    if date_from.day == 1:
        download_from = date_from - pd.DateOffset(months=1)

    periods = pd.period_range(
        start=download_from.to_period("M"), end=date_to.to_period("M"), freq="M"
    )
    to_loop_over = [(p.year, p.month) for p in periods]

    """
    It would be more memory efficient to group first, then concat the groups.
    However, because month data is effectively split between months, list first, then
    group.
    """
    df_list = []
    # TODO: Consider caching everything except current month
    for combo in to_loop_over:
        year = combo[0]
        month = combo[1]
        url = f"https://archivio.meteotrentino.it/share/bulk/year={year}/{year}-{month:02d}.parquet"
        logger.info(f"Downloading {url}")
        response = session.get(url)
        response.raise_for_status()
        df = pd.read_parquet(io.BytesIO(response.content))

        df = df[df["code"] == "10.00"]  # Rain code
        df = df[df["quality"].isin([1, 2, 3, 145])]  # 145 is teletransmission
        # Make days line up
        df["time"] = df["time"].dt.tz_convert("Europe/Rome")
        df = df[df["time"] >= date_from]
        df = df[df["time"] < date_to + pd.Timedelta(days=1)]
        df_list.append(df)

    concatted: pd.DataFrame = pd.concat(df_list)
    grouped = _group_by_day(concatted, "time", "value", group_by_extras=["station"])
    grouped["date"] = grouped["time"].dt.tz_localize(None)

    grouped = grouped.drop(["time"], axis=1)
    grouped = grouped.rename(
        columns={"value": "precipitation", "station": "station_id"}
    )
    grouped["qual"] = 1

    return grouped


def time_range_download(
    logger: Logger, context: RunContext, date_from: pd.Timestamp, date_to: pd.Timestamp
) -> pd.DataFrame:
    """

    Download rainfall sensor data from alto-adige and trentino from between the specified dates.

    Manipulate both datasets to match up with each other.

    Args:
        logger (Logger): _description_
        context (RunContext): _description_
        date_from (pd.Timestamp): _description_
        date_to (pd.Timestamp): _description_

    Returns:
        pd.DataFrame: _description_
    """

    list_of_dfs = []
    session = build_resilient_session()
    trento_df = pd.DataFrame(
        _download_trentino_archive(logger, session, date_from, date_to)
    )
    list_of_dfs.append(trento_df)
    # Uses special list
    bolzano_stations = pd.read_csv(context.bolzano_daily_stations_path)

    for station_id in list(bolzano_stations["station_id"]):
        result = _download_bolzano_date_range(
            logger, session, station_id, date_from, date_to
        )
        if result is None:
            logger.debug(f"No data received for {station_id}")
            continue
        list_of_dfs.append(result)

    return pd.concat(list_of_dfs, ignore_index=True)
