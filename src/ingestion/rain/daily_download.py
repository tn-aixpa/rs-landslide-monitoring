'''
Throwaway script to investigate meteohub data
'''
import os
from dotenv import load_dotenv
import pandas as pd
import requests as r
import json

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


    


def download_trentino_daily():
    
    pass



