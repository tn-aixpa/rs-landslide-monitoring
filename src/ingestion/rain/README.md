# Rainfall interpolation

## Methodology of Crespi

This script is based on this article: https://essd.copernicus.org/articles/13/2801/2021/essd-13-2801-2021.pdf

A very brief summary of this paper is that rainfall for a particular day is calculated based on several factors:

```
rain on day x (mm) = function(climatology, altitude, station observation for day)
```
This follows a standard meterological framework called PRISM. 
The advantages of this approach are:

1. The results look smoother and more realistic considering elevation; much better than a simple linear interpolation would achieve.
2. Spiky or erroneous station data get smoothed out due to climatology factor
3. Results in high resolution from meteorological point of view (250m) over traditional approaches (usually 2.5km).

The disadvantages are that it:
1. Legitimately spiky results get smoothed out and it.
2. Performs poorly in high rainfall events (see paper for more detail). Legitamate changes in climate due to global warming are smoothed out.
3. Requires a large, consistent record of historical data, including data from regions outside of the study area.




Lavoro in corso; questo progetto ha 3 stagine:
1. Fare il confronto contro nostro codice e quella di Crespi et al. (Fatto, vedi `crespi_comparison.py` per documentazione e informazione sull'utilizzo)
2. Produrre set di dati per il training del modello (non fatto)
3. Scaricare set di dati del tempo giornaliero per previsione (non fatto)

Bear in mind that all rain datasets have two time period formats; a historical form that runs from 9am of day 1 to 9am of day 2, and another which runs from UTC midnight day 1 to UTC midnight day 2. For the Crespi comparison, we use the 9am.

Unfortunately, 



## Creare set di dati input

### Why not Meteohub?

(See also the How to download Meteohub data section.) Meteohub, available at https://meteobrowser.eurac.edu/app_direct/meteobrowser/ returns precipitation values
that _do not match_ those from meteotrentino. The units are different, being returned in `kg m**-2`, but luckily this corresponds 1 -> 1 to `mm`. 

Take station T0009 on 29/01/2026 for example; on meteo trentino it returns 35mm (so, a decent amount). On Meteohub for the same station + date, its 0. On the same day, a different station (T0380) meteotrentino returns 0.2, yet on meteohub its 12.6. Its not clear what causes this difference!

An example of an independent system where the observations *DO* match is buergernetz vs https://weather.province.bz.it/en/download-data. Thank goodness!

### Stazione 

Primo di tutto, dobbiamo scaricare i set di dati delle stazioni meteorologiche. 

#### Trentino

Meteo trentino - http://storico.meteotrentino.it/

#### Bolzano

Historical data is available up until 31/12/2025; [download here in excel format](https://meteo.provincia.bz.it/it/download-dati)

For daily data, aggregate these:
https://geoservices.buergernetz.bz.it/services/meteo/v1/timeseries?station_code=19850PG&sensor_code=Q&date_from=202501010000&date_to=202501011200

#### Austria

For the Crespi comparison, you must also download Autrian station data. *This isn't necessary for the daily interpolation.*

Austria reports measurements in both daily and hourly intervals. The hourly interval data has less coverage in terms of stations and dates than the daily intervals. So we instead download the hourly rate and then aggregate using that, taking account of daylight saving times and the like.


### DEM

We used the 30m resolution DEM downloaded from Copernicus over the study area.

### How to download Meteohub data

The main URL is the faith inspiring: https://meteohub.agenziaitaliameteo.it:7777/#/
POST this to /api/data 
```json
{
  "request_name": "you_want_what_now",
  "reftime": {
    "from": "2026-01-29T00:01:00.000Z",
    "to": "2026-01-29T23:59:00.000Z"
  },
  "dataset_names": [
    "open-trentino"
  ],
  "filters": {
    "product": [
      {
        "code": "B13011",
        "desc": "TOTAL PRECIPITATION / TOTAL WATER EQUIVALENT",
        "active": true
      }
    ]
  },
  "output_format": "json",
  "only_reliable": true,
  "postprocessors": [
    
  ],
  "force_obs_download": true
}
```
which responds with:
```json
{
  "request_id": 5374222,
  "task_id": "1afd8edb-64cf-425c-b8ec-6026282d4b30"
}
```

/api/requests

```json
[
  {
    "id": 5374222,
    "name": "you_want_what_now",
    "args": {
      "filters": {
        "product": [
          {
            "code": "B13011",
            "desc": "TOTAL PRECIPITATION / TOTAL WATER EQUIVALENT",
            "active": true
          }
        ]
      },
      "reftime": {
        "to": "2026-01-29T23:59:00.000000Z",
        "from": "2026-01-29T00:01:00.000000Z"
      },
      "only_reliable": true,
      "output_format": "json",
      "postprocessors": [],
      "dataset_names": [
        "open-trentino"
      ]
    },
    "submission_date": "2026-10-05T15:06:05.674482",
    "status": "PENDING",
    "task_id": "1afd8edb-64cf-425c-b8ec-6026282d4b30",
    "opendata": false
  },
  {
    "id": 5373508,
    "name": "testjson",
    "args": {
      "filters": {
        "product": [
          {
            "code": "B13011",
            "desc": "TOTAL PRECIPITATION / TOTAL WATER EQUIVALENT",
            "active": true
          }
        ]
      },
      "reftime": {
        "to": "2026-10-04T00:00:00.000000Z",
        "from": "2026-10-03T00:00:00.000000Z"
      },
      "only_reliable": true,
      "output_format": "json",
      "dataset_names": [
        "open-trentino"
      ]
    },
    "submission_date": "2026-10-05T13:28:10.915629",
    "status": "SUCCESS",
    "task_id": "e853d976-6d4c-4bcd-b78f-1f304353a499",
    "opendata": false,
    "end_date": "2026-10-05T13:28:13.412641",
    "fileoutput": "data-20261005T132812Z-e853d976-6d4c-4bcd-b78f-1f304353a499.json",
    "filesize": 4586416
  }
]
```

then after file download call
DELETE /api/requests/{request_id}

... Maybe check the list of requests and loop through them to bin off all of em in case of script death.

Could also check that `/api/usage` doesn't exceed maximum.
