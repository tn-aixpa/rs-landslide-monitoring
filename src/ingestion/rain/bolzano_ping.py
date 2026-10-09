import json

import pandas as pd
import requests as r
from build_storico_trentino_session import build_buergernetz_session

ok_ids = []
session = build_buergernetz_session()
stations = pd.read_csv("/home/jfleming/Documents/rs-landslide-monitoring/data/alto_adige_daily_stations_reprojected.csv")
for station_id in list(stations['SCODE']):
    print(station_id)
    url = f"https://geoservices.buergernetz.bz.it/services/meteo/v1/timeseries?station_code={station_id}&sensor_code=N&date_from=202610081600"
    response = session.get(url)
    result = response.json()
    print(result)
    if len(result) != 0:
        ok_ids.append(station_id)

with open("data.json", "w") as f:
    json.dump(ok_ids,f)
