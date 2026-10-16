from unittest.mock import MagicMock

from constants import TIME_ZONE
from ingestion.rain.daily_observations_download import _download_bolzano_date_range, _download_trentino_archive
from parse_datetime import parse_datetime


def test_basic_bolzano():
    logger = MagicMock()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_json_content = [
        {"DATE": "2022-01-02T00:00:00CET", "VALUE": -9999.999},
        {"DATE": "2022-01-01T00:00:00CET", "VALUE": 10.0},
        {"DATE": "2022-01-01T01:00:00CET", "VALUE": 20.0},
    ]
    mock_response.json.return_value = mock_json_content
    mock_response.raise_for_status.return_value = None

    # Mock the requests session object
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response
    date1 = parse_datetime("01/01/2022").tz_localize(TIME_ZONE)
    df = _download_bolzano_date_range(logger, mock_session, "abc123", date1, date1)

    assert len(df) == 1  # Single row, cutting off date that is not relevant
    row = df.iloc[0]
    assert df.iloc[0]["precipitation"] == 30.0
    assert row["date"].tz_localize(TIME_ZONE) == date1


def test_range_bolzano():
    logger = MagicMock()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_json_content = [
        {"DATE": "2022-01-04T00:00:00CET", "VALUE": -9999.999},
        {"DATE": "2022-01-03T23:59:00CET", "VALUE": 40},
        {"DATE": "2022-01-03T01:00:00CET", "VALUE": 20},
        {"DATE": "2022-01-02T00:00:00CET", "VALUE": 10},
        {"DATE": "2022-01-01T23:59:00CET", "VALUE": -9999.999},
        {"DATE": "2022-01-01T23:58:00CET", "VALUE": -9999.999},
    ]
    mock_response.json.return_value = mock_json_content
    mock_response.raise_for_status.return_value = None

    # Mock the requests session object
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response
    date1 = parse_datetime("02/01/2022").tz_localize(TIME_ZONE)
    date2 = parse_datetime("03/01/2022").tz_localize(TIME_ZONE)
    df = _download_bolzano_date_range(logger, mock_session, "abc123", date1, date2)

    assert len(df) == 2  # 2 rows, one per day
    row1 = df.iloc[0]
    assert row1["precipitation"] == 10
    row2 = df.iloc[1]
    assert row2["precipitation"] == 60

def test_range_trentino():
    logger = MagicMock()

    mock_response = MagicMock()
    mock_response.status_code = 200
    
    with open("/home/jfleming/Documents/rs-landslide-monitoring/src/ingestion/rain/test_data_files/2026-04.parquet", 'rb') as f:
        bytes = f.read()
    
    mock_response.content = bytes
    mock_response.raise_for_status.return_value = None

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response
    
    # response = session.get(url)
    # response.raise_for_status()
    # df = pd.read_parquet(io.BytesIO(response.content))
    date1 = parse_datetime("10/04/2026").tz_localize(TIME_ZONE)
    date2 = parse_datetime("09/04/2026").tz_localize(TIME_ZONE)

    df = _download_trentino_archive(logger, mock_session, date2, date1)
    print(df)


def test_range_spanning_month_trentino():
    pass