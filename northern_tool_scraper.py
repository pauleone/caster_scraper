import re
import asyncio
from typing import Optional

import requests
from playwright.async_api import async_playwright

URL = "https://www.northerntool.com/products/vestil-caster-wheel-diameter-10-in-caster-type-swivel-package-qty-1-model-cst-f-10x3fm-s-4863671"
JSON_TEMPLATE = (
    "https://www.northerntool.com/wcs/resources/store/6970/price"
    "?q=byPartNumbers&profileName=IBM_Store_EntitledPrice_RangePrice_All&currency=USD&partNumber={part}"
)


def extract_part_number(url: str) -> str:
    match = re.search(r"(\d{7})(?:\D|$)", url)
    return match.group(1) if match else ""


def parse_price(data) -> Optional[str]:
    item = data
    if isinstance(data, list) and data:
        item = data[0]
    if not isinstance(item, dict):
        return None
    for key in ["salePrice", "offerPrice", "unitPrice", "price"]:
        if key in item:
            return str(item[key])
    for key, value in item.items():
        if "price" in key.lower() and isinstance(value, (int, float, str)):
            return str(value)
    return None


def fetch_price_json(url: str) -> Optional[str]:
    part = extract_part_number(url)
    if not part:
        return None
    endpoint = JSON_TEMPLATE.format(part=part)
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        resp = requests.get(endpoint, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return parse_price(data)
    except Exception:
        return None


async def fetch_price_playwright(url: str) -> Optional[str]:
    part = extract_part_number(url)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        def check_response(response):
            if "price" in response.url and "byPartNumbers" in response.url:
                if part:
                    return part in response.url
                return True
            return False

        wait_task = page.wait_for_response(check_response, timeout=15000)
        await page.goto(url, timeout=60000)
        try:
            resp = await wait_task
            data = await resp.json()
            return parse_price(data)
        except Exception:
            return None
        finally:
            await browser.close()


async def fetch_price_async(url: str = URL) -> str:
    price = await fetch_price_playwright(url)
    if price:
        return price
    price = fetch_price_json(url)
    return price or "No price found"


def fetch_price(url: str = URL) -> str:
    return asyncio.run(fetch_price_async(url))


if __name__ == "__main__":
    print("Northern Tool price:", fetch_price())
