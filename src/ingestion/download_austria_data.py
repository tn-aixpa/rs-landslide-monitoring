import os

import pandas as pd
import requests as r

from rain.setup_logging import setup_logging

logger = setup_logging()

START_DATE = "1980-01-01"
# START_DATE = '2025-12-25'
END_DATE = "2025-12-31"

output_csv_path = "/home/jfleming/Documents/rain-temp/data/temp/grouped.csv"
os.unlink(output_csv_path)  # clear contents

write_header = True

good_stations = []
# All stations near the border that have hourly records
stations_to_try = [
    14631,
    17701,
    19505,
    14513,
    14912,
    14403,
    17102,
    15210,
    14825,
    17005,
    17901,
    14701,
]
# https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h?parameters=TL&station_ids=14610&parameters=rr&start=1970-01-01&end=2026-12-31
for station_id in stations_to_try:
    # https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h?parameters=TL&station_ids=17003&parameters=rr&start=2026-01-01&end=2026-12-31
    response = r.get(
        f"https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-1h?parameters=TL&station_ids={station_id}&parameters=rr&start={START_DATE}&end={END_DATE}"
    )
    if not response.ok:
        # TODO: 404 indicates no historical info for this station between these ranges, so just continue. Check this explicitly in future
        # logger.info(f"No data for station with ID: {station_id}")
        continue

    body = response.json()
    rain_data = body["features"][0]["properties"]["parameters"]["rr"]["data"]
    count = len([x for x in rain_data if x is not None])

    if count == 0:
        # print(f"No data for station with ID: {station_id}")
        continue

    print(station_id)
    good_stations.append(station_id)

    timestamp_array = body["timestamps"]
    time_series = pd.Series(timestamp_array, name="datetime")

    rain_series = pd.Series(rain_data, name="piogga(mm)")

    austria = pd.concat([time_series, rain_series], axis=1)
    austria["au_timestamp"] = pd.to_datetime(
        austria["datetime"], utc=True
    ).dt.tz_convert("Europe/Vienna")
    austria = austria.drop(["datetime"], axis=1)
    austria = austria.dropna()  # drop any missing timestep (None in JSON response)

    austria.to_csv("/home/jfleming/Documents/rain-temp/data/temp/raw.csv", index=False)

    local_time = austria["au_timestamp"].dt.tz_convert("Europe/Vienna")
    meteorological_day = (
        local_time - pd.Timedelta(hours=9)
    ).dt.date  # runs from 9:00 to 9:00 the next day

    austria_daily_rain = (
        austria.assign(meteorological_day=meteorological_day)
        .groupby("meteorological_day")["piogga(mm)"]
        .sum()
        .reset_index()
    )

    # Could do this in groupby but this helps for readability IMO
    austria_daily_rain["station_id"] = station_id
    austria_daily_rain["qual"] = 1

    austria_daily_rain = austria_daily_rain.sort_values(
        by="meteorological_day", ascending=True
    )
    austria_daily_rain = austria_daily_rain.iloc[
        1:-1
    ]  # Don't have full set of records for very first and last days.
    austria_daily_rain = austria_daily_rain.rename(
        columns={"meteorological_day": "datetime"}
    )
    austria_daily_rain.to_csv(
        output_csv_path, index=False, mode="a", header=write_header
    )
    write_header = False

print(good_stations)
