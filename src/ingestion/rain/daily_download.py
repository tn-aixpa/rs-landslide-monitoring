'''
Throwaway script to investigate meteohub data
'''
import argparse
import json
import os
from pathlib import Path

import pandas as pd
import requests as r
from build_storico_trentino_session import (
    build_buergernetz_session,
    build_storico_trentino_session,
)
from context import RunContext
from dotenv import load_dotenv
from parse_storico_trentino_html import parse_storico_trentino_html
from read_station_data import read_station_data

'''
Field name lookups taken from:
https://vocabulary-manager.eumetsat.int/vocabularies/BUFR/WMO/19/TABLE_B
'''
B01019 = 'STATION_NAME'
B05001 = 'LATITUDE'
B06001 = 'LONGITUDE'
B13011 = 'TOTAL_PRECIPITATION_TOTAL_WATER_EQUIVALENT'


date_time_format = "%d/%m/%Y"


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

def download_bolzano_date_range(session: r.Session, station_id: str, date_from: pd.Timestamp, date_to: pd.Timestamp):
    '''
    This does both the download and the aggregation to keep it consistent with response from trentino's service
    '''
    # All times here are expressed in CET, and are inclusive?
    date_from_str = date_from.replace(hour=9).strftime("%Y%m%d%H%M")
    date_to_str = date_to.replace(hour=9).strftime("%Y%m%d%H%M")

    # Sensor code N = rain in mm
    url = f"https://geoservices.buergernetz.bz.it/services/meteo/v1/timeseries?station_code={station_id}&sensor_code=N&date_from={date_from_str}&date_to={date_to_str}"
    response = session.get(url)
    response.raise_for_status()
    bolzano_daily_observations = pd.DataFrame(response.json())
    # bolzano_daily_observations = pd.read_json('/home/jfleming/Documents/rs-landslide-monitoring/test.json',convert_dates=False)

    bolzano_daily_observations["DATE"] = pd.to_datetime(bolzano_daily_observations["DATE"].str.replace(":00CEST", "", regex=False))
    
    result = (
        bolzano_daily_observations.groupby(
            pd.Grouper(
                key="DATE",
                freq="1D",
                offset="9h",
                closed="left",  # Includes 9am 06/01, excludes 9am 07/01
                label="right",  # Labels the period with 07/01
            )
        )["VALUE"]
        .sum()
        .reset_index()
    )

    result = result[:-1]
    result['DATE'] = result['DATE'].dt.normalize() # Strip off time, not used in meterological time format
    result['station_id'] = station_id
    # Match column names from trentino
    result = result.rename(columns={"DATE": "timestamp", "VALUE": "piogga(mm)"})
    return result


def download_trentino_daily_meteorlogical_date(session:r.Session, station_id:str, date_from: pd.Timestamp, date_to: pd.Timestamp):
    """
    Uses meterological date system (9am-9am).
    Keep flexible date range in case of platform death/ outage requiring us to look back further in time.
    
    Args:
        session (r.Session): _description_
        station_id (str): _description_
        date_from (pd.Timestamp): _description_
        date_to (pd.Timestamp): _description_
    """

    date_from_str = date_from.strftime("%d/%m/%Y")
    date_to_str = date_to.strftime("%d/%m/%Y")
    
    daily_url = f"http://storico.meteotrentino.it/cgi/webhyd.pl?co={station_id}&v=10.50_10.50&vn=Pioggia%20(millimetri)%20Tot%20da%20Annale%20Idrologico&p=Altro,1,1,custom,1&o=Tabella,data&i=Giornaliera,Day,1&cat=rs&d1={date_from_str}&d2={date_to_str}&1791362644700"
    response = session.get(daily_url)
    response.raise_for_status()
    print(response.content)
    rows = parse_storico_trentino_html(station_id, response.content)
    return rows
    


def download_trentino_most_recent_meteorlogical_date(session, station_id):
    '''
    If time is 07/01/2025 00:01, then the data that we get will be for the 06/01/2025 09:00 record. 
    So make sure to schedule this to run _after_ 9:00 of each day
    '''
    today = pd.to_datetime("07/01/2025", format="%d/%m/%Y")
    # today = pd.Timestamp.now().normalize()
    yesterday = today - pd.Timedelta(days=2) # To include yesterday's date from historical API, substract 2. Not a typo.
    
    x = download_trentino_daily_meteorlogical_date(session, station_id, yesterday, today)
    df = pd.DataFrame(x)
    
    to_match = f"09:00:00 {today.strftime('%d/%m/%Y')}"
    df = df[df['datetime'] == to_match]
    return df.iloc[0].to_dict()


def time_range_download(data_dir:Path, date_from: pd.Timestamp, date_to:pd.Timestamp) -> pd.DataFrame:
    context = RunContext(data_dir)
    
    stations = read_station_data(context.historical_stations_path)
    trentino_stations = stations[stations['provincia'] == 'tn']
    session = build_storico_trentino_session()
    for station_id in list(trentino_stations['station_id']):
        today = pd.DataFrame(download_trentino_most_recent_meteorlogical_date(session,station_id))
    
    # Uses special list
    bolzano_stations = pd.read_csv(context.bolzano_daily_stations_path)
    bolzano_session = build_buergernetz_session()

    # TODO: change to using argument.
    today = pd.to_datetime("01/07/2025", format="%d/%m/%Y")
    yesterday = today - pd.Timedelta(days=1)
    for station_id in list(bolzano_stations['station_id']):
        result = download_bolzano_date_range(bolzano_session, station_id, yesterday, today)


    raise NotImplementedError("Implement rest of this")
# if __name__ == '__main__':
#     ap = argparse.ArgumentParser()
#     ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
#     ap.add_argument("--data-dir", required=True, help="Cartella per i file di dati")
#     args = ap.parse_args()
#     data_dir = Path(args.data_dir)
#     time_range_download(data_dir)
