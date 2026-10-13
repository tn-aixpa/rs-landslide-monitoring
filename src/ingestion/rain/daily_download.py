"""
Throwaway script to investigate meteohub data
"""

import io
from logging import Logger

import pandas as pd
import requests as r
from build_storico_trentino_session import build_resilient_session
from context import RunContext
from parse_datetime import parse_datetime

"""
Field name lookups taken from:
https://vocabulary-manager.eumetsat.int/vocabularies/BUFR/WMO/19/TABLE_B
"""
B01019 = "STATION_NAME"
B05001 = "LATITUDE"
B06001 = "LONGITUDE"
B13011 = "TOTAL_PRECIPITATION_TOTAL_WATER_EQUIVALENT"


date_time_format = "%d/%m/%Y"


def group_by_day(
    df: pd.DataFrame,
    date_column_name: str,
    value_column_name: str,
    group_by_extras: list[str] | None = None,
    historical_meterological_format=False,
):

    offset_amount = None
    label = "left"
    if historical_meterological_format:
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
    # date_from = date_from - pd.Timedelta(days=1) # subtract 1 to cover date_from day.
    # All times here are expressed in CEST, and are inclusive
    if historical_meterological_format:
        date_from = date_from.replace(hour=9)
        date_to = date_to.replace(hour=9)

    date_from_str = date_from.strftime("%Y%m%d%H%M")
    date_to_str = date_to.strftime("%Y%m%d%H%M")

    # Sensor code N = rain in mm
    url = f"https://geoservices.buergernetz.bz.it/services/meteo/v1/timeseries?station_code={station_id}&sensor_code=N&date_from={date_from_str}&date_to={date_to_str}"
    response = session.get(url)
    response.raise_for_status()

    response_json = response.json()
    if len(response_json) == 0:
        return None

    bolzano_daily_observations = pd.DataFrame(response.json())
    # Follows a non-standard timestamp format. Also use oppurtunity to strip off time + timezone which we don't need
    bolzano_daily_observations["DATE"] = parse_datetime(
        bolzano_daily_observations["DATE"].str[:10]
    )

    result = group_by_day(
        bolzano_daily_observations,
        "DATE",
        "VALUE",
        historical_meterological_format=historical_meterological_format,
    )

    result = result[:1]  # remove the day with 0 observations
    result["station_id"] = station_id
    result["qual"] = 1
    # Match column names from trentino
    result = result.rename(columns={"DATE": "date", "VALUE": "precipitation"})
    return result


def _download_trentino_archive(
    logger: Logger, date_from: pd.Timestamp, date_to: pd.Timestamp
):
    """
    Downloads data in parquet format. Gets updated daily

    Args:
        date_from (pd.Timestamp): _description_
        date_to (pd.Timestamp): _description_
    """

    '''
    annoyingly this API uses the Etc/GMT-1 timezone
    # meaning that first days of the month's data is split between files
    # if we use CET.
    '''
    date_from - pd.DateOffset(months = 1)

    periods = pd.period_range(
        start=date_from.to_period("M"), end=date_to.to_period("M"), freq="M"
    )
    to_loop_over = [(p.year, p.month) for p in periods]
    session = build_resilient_session()

    '''
    It would be more memory efficient to group first, then concat the groups.
    However, because month data is effectively split between months, list first, then
    group.
    '''
    df_list = []
    # TODO: Consider caching everything except current month
    for combo in to_loop_over:
        year = combo[0]
        month = combo[1]
        url = f"https://archivio.meteotrentino.it/share/bulk/year={year}/{year}-{month:02d}.parquet"
        response = session.get(url)
        response.raise_for_status()
        df = pd.read_parquet(io.BytesIO(response.content))

        df = df[df["code"] == "10.00"]  # Rain code
        df = df[df["quality"].isin([1, 2, 3, 145])] # 145 is teletransmission
        # Make days line up
        df["time"] = df["time"].dt.tz_convert("Europe/Rome")
        df = df[df["time"] >= date_from]
        df = df[df["time"] < date_to + pd.Timedelta(hours=24)]
        df_list.append(df)
    
    concatted: pd.DataFrame = pd.concat(df_list)
    grouped = group_by_day(concatted, "time", "value", group_by_extras=["station"])
    grouped["date"] = grouped["time"].dt.tz_localize(None)

    grouped = grouped.drop(["time"], axis=1)
    grouped = grouped.rename(
        columns={"value": "precipitation", "station": "station_id"}
    )
    grouped["qual"] = 1

    return grouped


def time_range_download(logger: Logger, context: RunContext, date_from: pd.Timestamp, date_to: pd.Timestamp) -> pd.DataFrame:
    """

    Download rainfall sensor data from alto-adige and trentino from between the specified dates

    Args:
        data_dir (Path): _description_
        date_from (pd.Timestamp): _description_
        date_to (pd.Timestamp): _description_

    Returns:
        pd.DataFrame: _description_
    """

    list_of_dfs = []

    trento_df = pd.DataFrame(_download_trentino_archive(logger, date_from, date_to))
    list_of_dfs.append(trento_df)
    # Uses special list
    bolzano_stations = pd.read_csv(context.bolzano_daily_stations_path)
    bolzano_session = build_resilient_session()

    for station_id in list(bolzano_stations["station_id"]):
        result = _download_bolzano_date_range(
            logger, bolzano_session, station_id, date_from, date_to
        )
        if result is None:
            logger.debug(f"No data recieved for {station_id}")
            continue
        list_of_dfs.append(result)

    return pd.concat(list_of_dfs, ignore_index=True)
