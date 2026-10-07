from bs4 import BeautifulSoup


def parse_storico_trentino_html(station_id:str, response_bytes: bytes) -> list[dict]:
    """
    Parse through HTML table and turn it into list of dicts for writing/ further parsing

    Args:
        station_id (str): _description_
        response_bytes (bytes): _description_

    Returns:
        list[dict]: _description_
    """
    soup = BeautifulSoup(response_bytes, "html.parser")
    rows = []

    for tr in soup.find_all("tr"):
        time_cell = tr.find("td", class_="tabledtimecells")

        # Skip header/non-data rows
        if time_cell is None:
            continue

        data_cells = tr.find_all("td", class_="tabledatacells")

        rows.append(
            {
                "station_id": station_id,
                "datetime": time_cell.get_text(strip=True),
                "piogga(mm)": data_cells[0].get_text(strip=True),
                "qual": data_cells[1].get_text(strip=True),
            }
        )
    return rows
