# Independent pandas calculation of every headline number, used to cross-check the Tableau workbook.
import pandas as pd, numpy as np, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
f = pd.read_parquet(ROOT / "data" / "transactions.parquet")
f["Customer ID"] = f["Customer ID"].replace("", np.nan)
f["FY"] = np.where(f["Invoice Date"].dt.month == 12, f["Invoice Date"].dt.year + 1, f["Invoice Date"].dt.year)
sale = f[f["Line Type"] == "Sale"]; ret = f[f["Line Type"] == "Return"]
E = {}

def kpis(d, s):
    gross = s.Revenue.sum(); net = d.Revenue.sum(); orders = s["Invoice No"].nunique()
    return {"net_revenue": round(net, 2), "gross_sales": round(gross, 2), "returns": round(gross - net, 2),
            "return_rate": round((gross - net) / gross, 4), "orders": int(orders), "aov": round(gross / orders, 2),
            "customers": int(s["Customer ID"].nunique()), "units": int(s.Quantity.sum())}
E["total"] = kpis(f, sale)
for fy in (2010, 2011):
    E[f"FY{fy}"] = kpis(f[f.FY == fy], sale[sale.FY == fy])
E["yoy"] = {k: round(E["FY2011"][k] / E["FY2010"][k] - 1, 4) for k in ("net_revenue", "orders", "aov", "customers")}

reg = f[f["Customer ID"].notna()]
E["guest_share_of_net"] = round(1 - reg.Revenue.sum() / f.Revenue.sum(), 4)
cust = reg.groupby("Customer ID").agg(last=("Invoice Date", "max"), net=("Revenue", "sum"))
cust["orders"] = sale.dropna(subset=["Customer ID"]).groupby("Customer ID")["Invoice No"].nunique()
cust = cust[cust.orders.notna()]  # customers with at least one sale
cust["orders"] = cust.orders.astype(int)
snap = pd.Timestamp("2011-12-01")
lastsale = sale.dropna(subset=["Customer ID"]).groupby("Customer ID")["Invoice Date"].max()
cust["recency"] = (snap.normalize() - lastsale.reindex(cust.index).dt.normalize()).dt.days
E["registered_customers"] = len(cust)
E["repeat_rate"] = round((cust.orders >= 2).mean(), 4)

# RFM: recency & monetary quintile cut points (linear percentiles over customers), frequency bands.
rq = cust.recency.quantile([.2, .4, .6, .8]).round(2).tolist(); mq = cust.net.quantile([.2, .4, .6, .8]).round(2).tolist()
E["rfm_recency_cuts"] = rq; E["rfm_monetary_cuts"] = mq
cust["R"] = np.select([cust.recency <= rq[0], cust.recency <= rq[1], cust.recency <= rq[2], cust.recency <= rq[3]], [5, 4, 3, 2], 1)
cust["F"] = np.select([cust.orders >= 10, cust.orders >= 5, cust.orders >= 3, cust.orders >= 2], [5, 4, 3, 2], 1)
cust["M"] = np.select([cust.net > mq[3], cust.net > mq[2], cust.net > mq[1], cust.net > mq[0]], [5, 4, 3, 2], 1)
def seg(r, fq):
    if r >= 5 and fq >= 4: return "Champions"
    if r >= 3 and fq >= 4: return "Loyal Customers"
    if r <= 2 and fq == 5: return "Can't Lose Them"
    if r <= 2 and fq >= 3: return "At Risk"
    if r <= 2: return "Hibernating"
    if r == 3 and fq == 3: return "Need Attention"
    if r == 3: return "About to Sleep"
    if fq == 1: return "New Customers" if r == 5 else "Promising"
    return "Potential Loyalists"
cust["Segment"] = [seg(r, q) for r, q in zip(cust.R, cust.F)]
g = cust.groupby("Segment").agg(customers=("net", "size"), revenue=("net", "sum"))
g["cust_share"] = (g.customers / g.customers.sum()).round(4); g["rev_share"] = (g.revenue / g.revenue.sum()).round(4)
E["segments"] = g.round(2).sort_values("revenue", ascending=False).to_dict("index")

srt = cust.net.sort_values(ascending=False)
E["top20_customer_rev_share"] = round(srt.head(int(round(len(srt) * .2))).sum() / srt.sum(), 4)

# Cohorts (registered customers, first sale month).
s2 = sale.dropna(subset=["Customer ID"]).copy()
s2["m"] = s2["Invoice Date"].dt.to_period("M")
first = s2.groupby("Customer ID").m.min().rename("cohort")
s2 = s2.join(first, on="Customer ID"); s2["age"] = (s2.m - s2.cohort).apply(lambda x: x.n)
ret_tbl = s2.groupby(["cohort", "age"])["Customer ID"].nunique().unstack()
size = ret_tbl[0]; pct = ret_tbl.div(size, axis=0)
E["cohort_sizes_first3"] = {str(k): int(v) for k, v in size.head(3).items()}
ex = pct.iloc[1:]  # exclude Dec-2009 (left-censored)
E["avg_retention"] = {f"M{m}": round(ex[m].mean(), 4) for m in (1, 3, 6, 12)}
E["new_customers_FY"] = {str(k): int(v) for k, v in first.groupby(np.where(first.dt.month == 12, first.dt.year + 1, first.dt.year)).size().items()}

# Products.
p = sale.groupby("Product").Revenue.sum().sort_values(ascending=False)
cum = p.cumsum() / p.sum()
E["products"] = int(len(p)); E["products_for_80pct"] = int((cum < .8).sum() + 1)
E["products_for_80pct_share"] = round(E["products_for_80pct"] / len(p), 4)
E["category_share"] = (sale.groupby("Category").Revenue.sum() / sale.Revenue.sum()).round(4).sort_values(ascending=False).to_dict()
E["category_return_rate"] = (ret.groupby("Category").Revenue.sum().abs() / sale.groupby("Category").Revenue.sum()).round(4).sort_values(ascending=False).to_dict()

# Geography & seasonality.
E["uk_share"] = round(f[f.Country == "United Kingdom"].Revenue.sum() / f.Revenue.sum(), 4)
intl = f[f.Country != "United Kingdom"].groupby("FY").Revenue.sum(); uk = f[f.Country == "United Kingdom"].groupby("FY").Revenue.sum()
E["intl_yoy"] = round(intl[2011] / intl[2010] - 1, 4); E["uk_yoy"] = round(uk[2011] / uk[2010] - 1, 4)
E["top_countries_ex_uk"] = f[f.Country != "United Kingdom"].groupby("Country").Revenue.sum().sort_values(ascending=False).head(6).round(2).to_dict()
mon = f.groupby(f["Invoice Date"].dt.to_period("M")).Revenue.sum()
E["peak_month"] = [str(mon.idxmax()), round(mon.max(), 2)]
E["sep_nov_share"] = round(f[f["Invoice Date"].dt.month.isin([9, 10, 11])].Revenue.sum() / f.Revenue.sum(), 4)
o = sale.drop_duplicates("Invoice No")
E["orders_by_weekday"] = o["Invoice Date"].dt.day_name().value_counts().to_dict()
E["peak_hour"] = int(o["Invoice Date"].dt.hour.value_counts().idxmax())
# Extra tiles used on the dashboards.
elig = s2[(s2.cohort > pd.Period("2009-12", "M")) & (s2.cohort < pd.Period("2011-11", "M"))]
E["m1_retention_pooled"] = round(elig[elig.age == 1]["Customer ID"].nunique() / elig["Customer ID"].nunique(), 4)
seg_rev = cust.groupby("Segment").net.sum()
E["champions_rev_share"] = round(seg_rev["Champions"] / seg_rev.sum(), 4)
E["at_risk_revenue"] = round(seg_rev[["At Risk", "Can't Lose Them"]].sum(), 2)
E["hibernating_customers"] = int((cust.Segment == "Hibernating").sum())
p80 = cust.net.quantile(.8); E["top20_by_p80_share"] = round(cust[cust.net >= p80].net.sum() / cust.net.sum(), 4)
E["intl_share"] = round(1 - E["uk_share"], 4)
E["countries"] = int(f.loc[~f.Country.isin(["Unspecified"]), "Country"].nunique())
E["products_sold"] = int(sale.Product.nunique()); E["units_per_order"] = round(sale.Quantity.sum() / sale["Invoice No"].nunique(), 1)
E["avg_unit_price"] = round(sale.Revenue.sum() / sale.Quantity.sum(), 2)
E["intl_FY2011"] = round(intl[2011], 2); E["uk_FY2011"] = round(uk[2011], 2)
E["delta_by_region"] = (f[f.FY == 2011].groupby("Region").Revenue.sum() - f[f.FY == 2010].groupby("Region").Revenue.sum()).round(0).to_dict()
json.dump(E, open(ROOT / "data" / "expected.json", "w"), indent=2, default=float)
print(json.dumps(E, indent=1, default=float))
