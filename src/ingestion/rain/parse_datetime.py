import re
from typing import overload

import pandas as pd


@overload
def parse_datetime(str_or_series: pd.Series) -> pd.Series: ...
@overload
def parse_datetime(str_or_series: str) -> pd.Timestamp: ...


def parse_datetime(
    str_or_series: str | pd.Series,
) -> pd.Timestamp | pd.Series:
    """
    Parse various timestamp formats into project specific format with time element stripped off.
    """
    if isinstance(str_or_series, pd.Series):
        to_test = str_or_series.iloc[0]
    else:
        to_test = str_or_series

    if re.search(r"\d{2}:\d{2}:\d{2} \d{2}/\d{2}/\d{4}", to_test):
        temp = pd.to_datetime(str_or_series, format="%H:%M:%S %d/%m/%Y", dayfirst=True)
    elif re.search(r"\d{2}/\d{2}/\d{4}", to_test):
        temp = pd.to_datetime(str_or_series, format="%d/%m/%Y", dayfirst=True)
    elif re.search(r"\d{4}-\d{2}-\d{2}", to_test):
        temp = pd.to_datetime(str_or_series, format="%Y-%m-%d", dayfirst=False)
    else:
        raise AssertionError(
            f"{to_test} does not match format a known timestamp format"
        )

    if isinstance(temp, pd.Series):
        temp = temp.dt.floor("D")  # strip off timestamp which is useless and hurts brain
    else:
        temp = temp.floor("D")

    return temp
