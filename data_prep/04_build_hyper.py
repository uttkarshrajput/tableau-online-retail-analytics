# Writes the cleaned tables into one Tableau Hyper extract (schema "Extract") plus CSV copies.
import pandas as pd, numpy as np, json
from pathlib import Path
from tableauhyperapi import (HyperProcess, Telemetry, Connection, CreateMode, TableDefinition, SqlType,
                             TableName, Inserter, NOT_NULLABLE, NULLABLE)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HYPER = DATA / "online_retail.hyper"
fact = pd.read_parquet(DATA / "transactions.parquet")
fact.insert(0, "Line ID", np.arange(1, len(fact) + 1))
fact["Customer ID"] = fact["Customer ID"].replace("", None)
pairs = pd.read_parquet(DATA / "product_pairs.parquet")
log = json.load(open(DATA / "cleaning_log.json"))
short = ["Raw source lines", "Sheet overlap removed", "Partial Dec-2011 removed", "Exact duplicates removed", "Non-product lines removed"]
steps = pd.DataFrame({"Step Order": range(1, len(log) + 2), "Step": short[:len(log) + 1],
                      "Rows Remaining": [log[0]["rows_before"]] + [x["rows_after"] for x in log],
                      "Rows Removed": [0] + [x["rows_removed"] for x in log]})

def sqltype(s):
    if pd.api.types.is_integer_dtype(s): return SqlType.big_int()
    if pd.api.types.is_float_dtype(s): return SqlType.double()
    if pd.api.types.is_datetime64_any_dtype(s): return SqlType.timestamp()
    return SqlType.text()

def write(conn, name, df):
    t = TableDefinition(TableName("Extract", name), [TableDefinition.Column(c, sqltype(df[c]), NULLABLE) for c in df.columns])
    conn.catalog.create_table(t)
    rows = df.astype(object).where(df.notna(), None)
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            rows[c] = [None if pd.isna(v) else v.to_pydatetime() for v in df[c]]
    with Inserter(conn, t) as ins:
        ins.add_rows(rows.itertuples(index=False, name=None)); ins.execute()
    print(name, conn.execute_scalar_query(f'SELECT COUNT(*) FROM "Extract"."{name}"'))

with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp:
    with Connection(hp.endpoint, HYPER, CreateMode.CREATE_AND_REPLACE) as conn:
        conn.catalog.create_schema("Extract")
        write(conn, "transactions", fact)
        write(conn, "product_pairs", pairs)
        write(conn, "cleaning_steps", steps)
fact.to_csv(DATA / "transactions.csv", index=False)
pairs.to_csv(DATA / "product_pairs.csv", index=False)
print("hyper MB", round(HYPER.stat().st_size / 1e6, 1))
