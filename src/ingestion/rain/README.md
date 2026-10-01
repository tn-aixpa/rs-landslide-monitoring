# Precipitazione

Lavoro in corso; questo progetto ha 3 stagine:
1. Fare il confronto contro nostro codice e quella di Crespi et al. (Fatto, vedi `build_rain_training_dataset.py` per documentazione e informazione sull'utilizzo)
2. Produrre set di dati per il training del modello (non fatto)
3. Scaricare set di dati del tempo giornaliero per previsione (non fatto)

## Creare set di dati input

### Stazione 

Primo di tutto, dobbiamo scaricare i set di dati delle stazioni meteorologiche. 

#### Trentino

Meteo trentino - http://storico.meteotrentino.it/

#### Bolzano

Dati sono disponibile fino a 31/12/2025; [scarica qui](https://meteo.provincia.bz.it/it/download-dati)

#### Austria

Austria reports measurements in both daily and hourly intervals. The hourly interval data has less coverage in terms of stations and dates than the daily intervals. So we instead download the hourly rate and then aggregate using that, taking account of daylight saving times and the like.


### DEM

Abbiamo usato quella di Copernicus con risoluzione di 30m.
