import re
import requests
from urllib.parse import quote

URL = "https://www.harborfreight.com/material-handling/tires-casters/swivel-casters/8-inch-pneumatic-swivel-caster-42485.html"

DY_ENDPOINT = "https://st.dynamicyield.com/spa/json"
SEC_ID = "8772758"


def product_id_from_url(url: str) -> str:
    match = re.search(r"-(\d+)\.html", url)
    return match.group(1) if match else ""


def build_dy_url(url: str) -> str:
    prod_id = product_id_from_url(url)
    ctx = f"%7B%22type%22%3A%22PRODUCT%22%2C%22data%22%3A%5B%22{prod_id}%22%5D%7D"
    ref = quote(url, safe="")
    return f"{DY_ENDPOINT}?sec={SEC_ID}&ref={ref}&isSesNew=false&ctx={ctx}"


def fetch_price(url: str = URL) -> str:
    dy_url = build_dy_url(url)
    resp = requests.get(dy_url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("feedProperties", {}).get("price", "No price found")


if __name__ == "__main__":
    price = fetch_price()
    print("Harbor Freight price:", price)
