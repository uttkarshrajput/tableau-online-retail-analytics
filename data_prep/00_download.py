# Downloads the UCI Online Retail II dataset (CC BY 4.0) into raw/.
import urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"; RAW.mkdir(exist_ok=True)
URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
zip_path = RAW / "online_retail_ii.zip"
urllib.request.urlretrieve(URL, zip_path)
zipfile.ZipFile(zip_path).extractall(RAW)
print("saved", [p.name for p in RAW.iterdir()])
