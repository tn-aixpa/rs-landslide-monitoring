import requests as r
from requests.adapters import HTTPAdapter, Retry

TOTAL_RETRIES = 5
BACK_OFF_FACTOR = 0.1

def build_storico_trentino_session() -> r.Session:
    """_summary_
    Resilient handling of storico meteo trentino webapp.
    Returns:
        r.Session: _description_
    """
    session = r.Session()
    retries = Retry(total=TOTAL_RETRIES,
                    backoff_factor=BACK_OFF_FACTOR,
                    status_forcelist=[ 400, 404, 429 ]) # Service sometimes uses 400's and 404's as a timeout mechanism
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session


def build_buergernetz_session() -> r.Session:
    """
    This commonly responds with weird TLS errors; make sure its resilient enough
    to handle these.

    Returns:
        r.Session: _description_
    """
    session = r.Session()
    retries = Retry(
        total=TOTAL_RETRIES,
        backoff_factor=BACK_OFF_FACTOR,
        raise_on_status=False
    )
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session
