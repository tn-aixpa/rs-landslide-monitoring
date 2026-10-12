'''
Throwaway script to investigate meteohub data
'''
import argparse
import io
import json
import os
from logging import Logger
from pathlib import Path

import pandas as pd
import requests as r
from build_storico_trentino_session import build_resilient_session
from constants import TIME_ZONE
from context import RunContext
from dotenv import load_dotenv
from parse_datetime import parse_datetime
from parse_storico_trentino_html import parse_storico_trentino_html
from read_observation_data import post_process_trentino_observations
from setup_logging import setup_logging

'''
Field name lookups taken from:
https://vocabulary-manager.eumetsat.int/vocabularies/BUFR/WMO/19/TABLE_B
'''
B01019 = 'STATION_NAME'
B05001 = 'LATITUDE'
B06001 = 'LONGITUDE'
B13011 = 'TOTAL_PRECIPITATION_TOTAL_WATER_EQUIVALENT'


date_time_format = "%d/%m/%Y"

def group_by_day(df: pd.DataFrame, date_column_name:str, value_column_name: str, group_by_extras: list[str] | None = None, historical_meterological_format = False):

    offset_amount = None
    label = 'left'
    if historical_meterological_format:
        offset_amount = "9h"
        label = 'right'

    gg = [pd.Grouper(key=date_column_name,freq="1D",offset=offset_amount,closed="left", label=label)]
    if group_by_extras is not None:
        gg = gg + group_by_extras

    grouped = df.groupby(gg)[value_column_name].sum().reset_index()
    return grouped.sort_values(by = date_column_name)


def download_bolzano_date_range(logger: Logger, session: r.Session, station_id: str, date_from: pd.Timestamp, date_to: pd.Timestamp, historical_meterological_format = False) -> pd.DataFrame:
    '''
    This does both the download and the aggregation to keep it consistent with response from trentino's service
    '''

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
    bolzano_daily_observations["DATE"] = parse_datetime(bolzano_daily_observations["DATE"].str[:10])
    # bolzano_daily_observations["DATE"] = pd.to_datetime(bolzano_daily_observations["DATE"].str.replace(":00CEST", "", regex=False))

    result = group_by_day(bolzano_daily_observations, "DATE", "VALUE", historical_meterological_format=historical_meterological_format)
    
    result = result[:1] # remove the day with 0 observations
    result['station_id'] = station_id
    result['qual'] = 1
    # Match column names from trentino
    result = result.rename(columns={"DATE": "date", "VALUE": "precipitation"})
    return result


def _download_trentino_archive(logger: Logger, date_from:pd.Timestamp, date_to:pd.Timestamp):
    """
    Downloads data in parquet format. Gets updated daily

    Args:
        date_from (pd.Timestamp): _description_
        date_to (pd.Timestamp): _description_
    """
    periods = pd.period_range(start=date_from.to_period("M"), end=date_to.to_period("M"), freq="M")
    to_loop_over = [(p.year, p.month) for p in periods]
    session = build_resilient_session()
    grouped_list = []
    # TODO: Consider caching everything except current month
    for combo in to_loop_over:
        year = combo[0]
        month = combo[1]
        url = f"https://archivio.meteotrentino.it/share/bulk/year={year}/{year}-{month:02d}.parquet"
        response = session.get(url)
        response.raise_for_status()
        df = pd.read_parquet(io.BytesIO(response.content))

        df = df[df['code'] == '10.00'] # Rain code
        df = df[df['quality'].isin([1, 2, 3, 145])] # These are the only valid codes
        grouped = group_by_day(df, "time", "value", group_by_extras=['station'])
        grouped_list.append(grouped)

    concatted:pd.DataFrame = pd.concat(grouped_list)
    # Inclusive, think of singular day example
    concatted = concatted[concatted['time'] >= date_from]
    concatted = concatted[concatted['time'] <= date_to]

    concatted['date'] = concatted['time'].dt.tz_localize(None)

    concatted = concatted.drop(['time'], axis=1)
    concatted = concatted.rename(columns={'value':'precipitation', 'station': 'station_id'})
    concatted['qual'] = 1

    return concatted

def time_range_download(logger: Logger, context:RunContext, date_from: pd.Timestamp, date_to:pd.Timestamp) -> pd.DataFrame:
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

    for station_id in list(bolzano_stations['station_id']):
        result = download_bolzano_date_range(logger, bolzano_session, station_id, date_from, date_to)
        if result is None:
            logger.debug(f"No data recieved for {station_id}")
            continue
        list_of_dfs.append(result)

    return pd.concat(list_of_dfs)

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
    args = ap.parse_args()
    data_dir = Path(args.data_dir)
    context = RunContext(data_dir)
    date_to = pd.to_datetime("08/01/2026", format='%d/%m/%Y').tz_localize(TIME_ZONE)
    date_from = date_to# - pd.Timedelta(days = 1)
    logger = setup_logging()
    logger.info(time_range_download(logger, context, date_from, date_to))



def _download_meteohub_daily():
    """_summary_
    This function could be removed; 
    Raises:
        NotImplementedError: _description_
    """
    raise NotImplementedError("See README.md for implementation details")
    load_dotenv()
    response = r.post("https://meteohub.agenziaitaliameteo.it/auth/login", json={'username':os.environ['USERNAME'],'password':os.environ['PASSWORD']})
    print(response.status_code)
    print(response.json())

    raw_records = []

    with open("/home/jfleming/Downloads/data-20261005T142348Z-4fbbcbbc-57bb-447b-8559-476b4545066b(1).json",'r') as f:
        for line in f:
            raw_records.append(json.loads(line))


    records_to_parse = []

    for raw_record in raw_records:
        timestamp = pd.to_datetime(raw_record['date']) #ISO 8601
        for raw_record_data in raw_record['data']:
            if 'timerange' in raw_record_data:
                precipitation_value = raw_record_data['vars']['B13011']['v']


            if 'vars' in raw_record_data and 'B01019' in raw_record_data['vars']:
                station_raw = raw_record_data['vars']['B01019']['v']
                station_id = station_raw.split('-')[0].strip()
                # print(thing['vars'])
                # print(thing['B01019'])
        records_to_parse.append([timestamp, precipitation_value, station_id])

    df = pd.DataFrame(records_to_parse, columns=['timestamp', 'precipitation', 'station_id'])

    df.to_csv('hello_world.csv',index=False)



def download_trentino_daily_meteorlogical_date_hydstra(session:r.Session, station_id:str, date_from: pd.Timestamp, date_to: pd.Timestamp) -> pd.DataFrame:
    """

    WARNING - THIS API ONLY GETS ITS DATA UPDATED PERIODICALLY A COUPLE TIMES A YEAR.
    ONLY USE IT FOR CLIMATOLOGY CALCULATIONS, NOT DAILY OBSERVATIONS

    Uses meterological date system (9am-9am).
    Keep flexible date range in case of platform death/ outage requiring us to look back further in time.
    There is a bug with the trentino portal (which runs on the hydstra server software ); if you pass in 
    one single date (e.g. 17/01/2026), keeping the `date_from` and `date_to` the same, it will 400. Even
    though you just want the data for 17/01/2026, you must specify more than one day to constitute a range.


    Args:
        session (r.Session): _description_
        station_id (str): _description_
        date_from (pd.Timestamp): _description_
        date_to (pd.Timestamp): _description_
    """

    hydstra_bug_workaround_flag = False
    # Workaround for bug in hydstra server when you just want one day
    if date_from == date_to:
        date_from = date_from - pd.Timedelta(days = 1)
        hydstra_bug_workaround_flag = True

    date_from_str = date_from.strftime("%d/%m/%Y")
    date_to_str = date_to.strftime("%d/%m/%Y")
    
    daily_url = f"http://storico.meteotrentino.it/cgi/webhyd.pl?co={station_id}&v=10.50_10.50&vn=Pioggia%20(millimetri)%20Tot%20da%20Annale%20Idrologico&p=Altro,1,1,custom,1&o=Tabella,data&i=Giornaliera,Day,1&cat=rs&d1={date_from_str}&d2={date_to_str}&1791362644700"
    response = session.get(daily_url)
    response.raise_for_status()
    
    rows = pd.DataFrame(parse_storico_trentino_html(station_id, response.content))
    rows["date"] = parse_datetime(rows["datetime"])
    rows = post_process_trentino_observations(rows)

    if hydstra_bug_workaround_flag:
        rows = rows[rows['date'] == date_to]
    return rows
