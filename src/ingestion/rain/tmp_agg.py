import pandas as pd

today = pd.to_datetime("01/07/2025", format="%d/%m/%Y")
yesterday = today - pd.Timedelta(days=3)

df = pd.read_csv("/home/jfleming/Documents/tmp/hello.csv")
df['DATE'] = pd.to_datetime(df["DATE"].str.replace(":00CEST", "", regex=False))
result = (
    df.groupby(
        pd.Grouper(
            key="DATE",
            freq="1D",
            offset="9h",
            closed="left",  # Includes 9am 06/01, excludes 9am 07/01
            label="right",  # Labels the period with 07/01
        )
    )["VALUE"]
    .sum()
    .reset_index()
)

result = result[:-1]

print(result)
