'''
Throwaway script to investigate meteohub data
'''
from typing import TYPE_CHECKING
import os
from dotenv import load_dotenv
import pandas as pd

import json

from build_storico_trentino_session import build_storico_trentino_session

if __name__ == TYPE_CHECKING:
    import requests as r

'''
Field name lookups taken from:
https://vocabulary-manager.eumetsat.int/vocabularies/BUFR/WMO/19/TABLE_B
'''
B01019 = 'STATION_NAME'
B05001 = 'LATITUDE'
B06001 = 'LONGITUDE'
B13011 = 'TOTAL_PRECIPITATION_TOTAL_WATER_EQUIVALENT'





def _download_meteohub_daily():
    """_summary_

    Raises:
        NotImplementedError: _description_
    """
    raise NotImplementedError("See README.md for implementation details")
    load_dotenv()
    response = r.post("https://meteohub.agenziaitaliameteo.it/auth/login", json={'username':'jfleming@fbk.eu','password':os.environ['PASSWORD']})
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

def download_bolzano_daily():
    # https://geoservices.buergernetz.bz.it/services/meteo/v1/timeseries?station_code=19850PG&sensor_code=Q&date_from=202501010000&date_to=202501010000
    pass
    


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
    
    daily_url = f"http://storico.meteotrentino.it/cgi/webhyd.pl?co={station_id}&v=10.50_10.50&vn=Pioggia%20(millimetri)%20Tot%20da%20Annale%20Idrologico&p=Altro,1,1,custom,1&o=Tabella,data&i=Giornaliera,Day,1&cat=rs&d1={date_from}&d2={date_to}&1791362644700"
    response = session.get(daily_url)
    response.raise_for_status()

    
    


if __name__ == '__main__':
    session = build_storico_trentino_session()
    today = pd.Timestamp.now().normalize()
    yesterday = today - pd.Timedelta(days=2) # To include yesterday's date from historical API, substract 2. Not a typo.
    
    download_trentino_daily_meteorlogical_date(session, 't0179', yesterday, today)
    
