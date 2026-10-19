# Cleans the raw Online Retail II lines into an analysis-ready fact table and logs every rule applied.
import pandas as pd, numpy as np, json, re, string
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data"; OUT.mkdir(exist_ok=True)
raw = pd.read_parquet(ROOT / "raw" / "online_retail_raw.parquet")
log = []
def step(name, before, after, note):
    log.append({"step": name, "rows_before": int(before), "rows_after": int(after), "rows_removed": int(before - after), "note": note})
    print(f"{name:<38}{before:>10,} -> {after:>10,}  ({before-after:,} removed)")

# 1. The two source sheets overlap on 1-9 Dec 2010: keep sheet 1 only up to 30 Nov 2010.
SHEET1_ROWS = 525_461
sheet = np.where(np.arange(len(raw)) < SHEET1_ROWS, 1, 2)
n0 = len(raw)
df = raw[~((sheet == 1) & (raw.InvoiceDate >= "2010-12-01"))].copy()
step("Remove sheet overlap (1-9 Dec 2010)", n0, len(df), "Rows from the 2009-2010 sheet dated on/after 2010-12-01 also appear in the 2010-2011 sheet.")

# 2. Keep 24 complete months (Dec 2009 - Nov 2011); Dec 2011 has only 9 days.
n = len(df); df = df[df.InvoiceDate < "2011-12-01"]
step("Drop partial month (1-9 Dec 2011)", n, len(df), "Keeps two complete Dec-Nov fiscal years so year-over-year comparisons are like-for-like.")

# 3. Exact duplicate lines (same invoice, product, qty, price, timestamp, customer).
n = len(df); df = df.drop_duplicates()
step("Drop exact duplicate lines", n, len(df), "Identical lines inside the same invoice are treated as double scans.")

# 4. Classify each line.
NON_PRODUCT = {"POST", "DOT", "M", "m", "C2", "C3", "D", "S", "BANK CHARGES", "ADJUST", "ADJUST2", "AMAZONFEE",
               "PADS", "CRUK", "B", "TEST001", "TEST002", "SP1002"}
code = df.StockCode.str.strip()
is_non_product = code.isin(NON_PRODUCT) | code.str.lower().str.startswith("gift_") | code.str.upper().str.startswith("TEST")
is_cancel = df.Invoice.str.startswith("C")
is_adjust = df.Invoice.str.startswith("A")
df["Line Type"] = np.select(
    [is_adjust, is_non_product, df.Price <= 0, is_cancel & (df.Quantity < 0), (~is_cancel) & (df.Quantity > 0), (~is_cancel) & (df.Quantity <= 0)],
    ["Bad-debt adjustment", "Shipping, fees & manual", "Zero / negative price", "Return", "Sale", "Stock write-off"], default="Other")
counts = df["Line Type"].value_counts().to_dict(); print(counts)

# 5. Large orders that were fully reversed (same customer, product and quantity) are order-entry errors.
sales = df[df["Line Type"] == "Sale"]; rets = df[df["Line Type"] == "Return"]
key = ["Customer ID", "StockCode"]
big = sales[sales.Quantity >= 1000].reset_index().merge(
    rets.assign(Q=-rets.Quantity).reset_index()[["index", "Customer ID", "StockCode", "Q", "InvoiceDate"]],
    left_on=key + ["Quantity"], right_on=key + ["Q"], suffixes=("", "_r"))
big = big[(big.InvoiceDate_r >= big.InvoiceDate) & ((big.InvoiceDate_r - big.InvoiceDate).dt.days <= 31)]
big = big.assign(gap=big.InvoiceDate_r - big.InvoiceDate).sort_values("gap").drop_duplicates("index_r").drop_duplicates("index")  # one sale per return
err_idx = set(big["index"]) | set(big["index_r"])
df.loc[list(err_idx), "Line Type"] = "Reversed order error"
print("reversed order errors:", len(err_idx), big[["Description", "Quantity", "InvoiceDate", "InvoiceDate_r"]].to_string())

removed = {k: int(v) for k, v in counts.items() if k not in ("Sale", "Return")}
n = len(df); df = df[df["Line Type"].isin(["Sale", "Return"])].copy()
step("Keep product sales & returns only", n, len(df),
     "Removed lines: " + "; ".join(f"{k}: {v:,}" for k, v in removed.items())
     + f"; reversed order errors: {len(err_idx):,}. Revenue = product sales net of returns.")

# 6. Tidy text fields.
df["Description"] = (df.Description.fillna("").str.strip().str.replace(r"\s+", " ", regex=True).str.upper())
# One canonical description per stock code (the most frequent spelling).
canon = df[df.Description != ""].groupby("StockCode").Description.agg(lambda s: s.value_counts().index[0])
df["Product"] = df.StockCode.map(canon).fillna("UNKNOWN PRODUCT")
df["Product"] = df["Product"].str.lower().map(string.capwords).str.replace(r"([-/(])([a-z])", lambda m: m.group(1) + m.group(2).upper(), regex=True)

COUNTRY = {"EIRE": "Ireland", "RSA": "South Africa", "USA": "United States", "Korea": "South Korea",
           "European Community": "Unspecified", "West Indies": "Unspecified"}
df["Country"] = df.Country.replace(COUNTRY)
REGION = {"United Kingdom": "United Kingdom", "Ireland": "Western Europe", "Channel Islands": "United Kingdom",
          "France": "Western Europe", "Germany": "Western Europe", "Netherlands": "Western Europe", "Belgium": "Western Europe",
          "Switzerland": "Western Europe", "Austria": "Western Europe", "Spain": "Southern Europe", "Portugal": "Southern Europe",
          "Italy": "Southern Europe", "Greece": "Southern Europe", "Cyprus": "Southern Europe", "Malta": "Southern Europe",
          "Norway": "Nordics", "Sweden": "Nordics", "Denmark": "Nordics", "Finland": "Nordics", "Iceland": "Nordics",
          "Poland": "Central & Eastern Europe", "Czech Republic": "Central & Eastern Europe", "Lithuania": "Central & Eastern Europe"}
df["Region"] = df.Country.map(REGION).fillna("Rest of World")

# 7. Rule-based product category (first matching rule wins).
RULES = [
    ("Christmas & Seasonal", r"CHRISTMAS|XMAS|ADVENT|REINDEER|SANTA|SNOWFLAKE|SNOWMAN|EASTER|BAUBLE|NATIVITY|HALLOWEEN"),
    ("Bags & Storage", r"\bBAGS?\b|SHOPPER|STORAGE|BASKET|TOTE|HOLDALL|CASE\b|BOX(?:ES)?\b(?!.*(?:CAKE|LUNCH|SNACK))"),
    ("Candles & Lighting", r"T-LIGHT|CANDLE|LIGHTS?\b|LANTERN|LAMP|TEALIGHT|HLDR|LED\b"),
    ("Kitchen & Dining", r"CAKE|TEA\b|TEACUP|TEAPOT|MUG|CUPS?\b|BOWL|PLATE|JAR|TINS?\b|KITCHEN|BAKING|LUNCH BOX|SNACK|SPOON|NAPKIN|JUG|BREAD|CUTLERY|GLASS|COASTER|APRON|OVEN|SCALES|TRAY|DOILY|STRAW|CHOPSTICK|EGG|JAM\b|RECIPE|PANTRY|BOTTLE(?!.*HOT)"),
    ("Home Decor", r"SIGN\b|FRAME|CLOCK|DOOR ?MAT|CUSHION|DECORATION|CHALKBOARD|MIRROR|HOOK|COAT|CABINET|DRAWER|WICKER|ORNAMENT|HANGING|BIRDCAGE|WREATH|HEART|PHOTO|VASE|PLAQUE|MEMOBOARD|SHELF|CURTAIN|THROW|QUILT|BLOCK WORD|LETTERS"),
    ("Party & Gifting", r"BUNTING|PARTY|CARDS?\b|WRAP|GIFT|RIBBON|TAGS?\b|BALLOON|PAPER CHAIN|CONFETTI|NAPKINS|INVITES|BIRTHDAY|CRACKER"),
    ("Toys & Kids", r"TOY|GAME|PLAY|DOLL|SPACEBOY|CHILD|KIDS|HARMONICA|PAINT SET|COLOURING|BLOCKS|SNAP|CROQUET|JIGSAW|DOLLY|SKIPPING|TEDDY|PUPPET|BINGO|DOMINOES|ROUNDERS|GLIDER|SPINNING TOP|MAGIC"),
    ("Stationery & Craft", r"PEN\b|PENCIL|NOTEBOOK|STICKER|CRAFT|SEWING|KNITTING|STAMP|ERASER|MEMO|JOURNAL|CRAYON|RULER|SHARPENER|ENVELOPE|PAPER|NOTE ?BOOK|CHALK|BOOKMARK|DIARY|SKETCHBOOK|CALENDAR"),
    ("Personal & Wellness", r"HOT WATER BOTTLE|HAND WARMER|PLASTER|UMBRELLA|PARASOL|JEWEL|NECKLACE|BRACELET|EARRING|PURSE|WALLET|SOAP|BATH|COMB|HAIR|RING\b|BROOCH|CHARM|SCARF|SLIPPER|WASH BAG|MAKE UP|LIP|KEY ?RING|FAN\b"),
    ("Garden & Outdoor", r"GARDEN|PLANT|FLOWER POT|WATERING|BIRD FEEDER|PICNIC|GROW|SEED|HERB|TRUG|BIRD HOUSE|BIRD TABLE|WINDMILL|PLANTER"),
]
desc_u = df["Product"].str.upper()
df["Category"] = "Other Gifts"
assigned = pd.Series(False, index=df.index)
for cat, pat in RULES:
    m = (~assigned) & desc_u.str.contains(pat, regex=True)
    df.loc[m, "Category"] = cat; assigned |= m

# 8. Final columns.
df["Revenue"] = (df.Quantity * df.Price).round(2)
df["Customer ID"] = df["Customer ID"].astype("Int64").astype(str).replace("<NA>", "")
df["Customer Type"] = np.where(df["Customer ID"] == "", "Guest (no ID)", "Registered")
fact = df.rename(columns={"Invoice": "Invoice No", "StockCode": "Stock Code", "InvoiceDate": "Invoice Date",
                          "Price": "Unit Price"})[[
    "Invoice No", "Invoice Date", "Stock Code", "Product", "Category", "Quantity", "Unit Price", "Revenue",
    "Line Type", "Customer ID", "Customer Type", "Country", "Region"]].sort_values("Invoice Date").reset_index(drop=True)
fact.to_parquet(OUT / "transactions.parquet", index=False)
json.dump(log, open(OUT / "cleaning_log.json", "w"), indent=2)

cat = fact[fact["Line Type"] == "Sale"].groupby("Category").Revenue.sum().sort_values(ascending=False)
print((cat / cat.sum() * 100).round(1).to_string())
print("final rows", len(fact), "net revenue", round(fact.Revenue.sum(), 2))

