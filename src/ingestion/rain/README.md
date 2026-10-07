# Precipitazione

Lavoro in corso; questo progetto ha 3 stagine:
1. Fare il confronto contro nostro codice e quella di Crespi et al. (Fatto, vedi `crespi_comparison.py` per documentazione e informazione sull'utilizzo)
2. Produrre set di dati per il training del modello (non fatto)
3. Scaricare set di dati del tempo giornaliero per previsione (non fatto)

Bear in mind that all rain datasets have two time period formats; a historical form that runs from 9am of day 1 to 9am of day 2, and another which runs from UTC midnight day 1 to UTC midnight day 2. For the Crespi comparison, we use the 9am


## Creare set di dati input

### Stazione 

Primo di tutto, dobbiamo scaricare i set di dati delle stazioni meteorologiche. 

#### Trentino

Meteo trentino - http://storico.meteotrentino.it/

#### Bolzano

Dati sono disponibile fino a 31/12/2025; [scarica qui](https://meteo.provincia.bz.it/it/download-dati)

Forse anche:
https://meteobrowser.eurac.edu/app_direct/meteobrowser/

#### Austria

Austria reports measurements in both daily and hourly intervals. The hourly interval data has less coverage in terms of stations and dates than the daily intervals. So we instead download the hourly rate and then aggregate using that, taking account of daylight saving times and the like.


### DEM

Abbiamo usato quella di Copernicus con risoluzione di 30m.


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
