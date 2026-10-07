import requests as r
from requests.adapters import HTTPAdapter, Retry


def build_storico_trentino_session() -> r.Session:
    session = r.Session()
    retries = Retry(total=5,
                    backoff_factor=0.1,
                    status_forcelist=[ 400, 404, 429 ]) # Service 400's and 404's as a timeout mechanism
    session.mount('http://', HTTPAdapter(max_retries=retries))
    return session
