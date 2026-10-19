# Reads both sheets of the UCI Online Retail II workbook into one raw parquet file.
import pandas as pd, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
t = time.time()
sheets = pd.read_excel(ROOT / "raw" / "online_retail_II.xlsx", sheet_name=None, dtype={"Invoice": str, "StockCode": str, "Description": str, "Country": str})
df = pd.concat(sheets.values(), ignore_index=True)
df.to_parquet(ROOT / "raw" / "online_retail_raw.parquet", index=False)
print(f"rows={len(df):,} cols={list(df.columns)} sheets={list(sheets)} secs={time.time()-t:.0f}")
print(df.dtypes)
print(df.head())

