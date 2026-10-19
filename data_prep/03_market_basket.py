# Market-basket analysis: product-pair support, confidence and lift across sales invoices.
import pandas as pd, numpy as np
from scipy import sparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
fact = pd.read_parquet(ROOT / "data" / "transactions.parquet")
s = fact[fact["Line Type"] == "Sale"][["Invoice No", "Product", "Category"]].drop_duplicates(["Invoice No", "Product"])
n_inv = s["Invoice No"].nunique()

TOP = 250  # products bought on the most invoices
by_rev = fact[fact["Line Type"] == "Sale"].groupby("Product").Revenue.sum().nlargest(60).index
top = s.Product.value_counts().head(TOP).index.union(by_rev)  # anchors: most-bought plus top-revenue products
s = s[s.Product.isin(top)]
inv_codes, inv_idx = np.unique(s["Invoice No"], return_inverse=True)
prod_codes, prod_idx = np.unique(s.Product, return_inverse=True)
M = sparse.csr_matrix((np.ones(len(s), dtype=np.int32), (inv_idx, prod_idx)), shape=(len(inv_codes), len(prod_codes)))
co = (M.T @ M).tocoo()
single = np.asarray(M.sum(axis=0)).ravel()
cat = s.drop_duplicates("Product").set_index("Product").Category

pairs = pd.DataFrame({"a": co.row, "b": co.col, "both": co.data})
pairs = pairs[(pairs.a != pairs.b) & (pairs.both >= 40)]
pairs["Product A"] = prod_codes[pairs.a]; pairs["Product B"] = prod_codes[pairs.b]
pairs["Orders With A"] = single[pairs.a]; pairs["Orders With B"] = single[pairs.b]
pairs["Orders With Both"] = pairs.both
pairs["Support"] = pairs.both / n_inv
pairs["Confidence"] = pairs.both / pairs["Orders With A"]
pairs["Lift"] = pairs.Confidence / (pairs["Orders With B"] / n_inv)
pairs["Category A"] = pairs["Product A"].map(cat); pairs["Category B"] = pairs["Product B"].map(cat)
out = pairs[["Product A", "Category A", "Product B", "Category B", "Orders With A", "Orders With B", "Orders With Both",
             "Support", "Confidence", "Lift"]].sort_values(["Product A", "Lift"], ascending=[True, False]).reset_index(drop=True)
out.to_parquet(ROOT / "data" / "product_pairs.parquet", index=False)
print(f"invoices={n_inv:,} pairs={len(out):,} anchors={out['Product A'].nunique()}")
print(out.sort_values("Lift", ascending=False).head(12)[["Product A", "Product B", "Orders With Both", "Confidence", "Lift"]].to_string())
