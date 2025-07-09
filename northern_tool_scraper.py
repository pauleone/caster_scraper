@@ -0,0 +1,125 @@
import re
import asyncio
from typing import Optional

import requests
from playwright.async_api import async_playwright, Page

URL = "https://www.northerntool.com/products/vestil-caster-wheel-diameter-10-in-caster-type-swivel-package-qty-1-model-cst-f-10x3fm-s-4863671"
JSON_TEMPLATE = (
    "https://www.northerntool.com/wcs/resources/store/6970/price"
    "?q=byPartNumbers&profileName=IBM_Store_EntitledPrice_RangePrice_All&currency=USD&partNumber={part}"
)


def extract_part_number(url: str) -> str:
    match = re.search(r"(\d{7})(?:\D|$)", url)
    return match.group(1) if match else ""


def parse_price(data) -> Optional[str]:
    """Recursively search common price fields in the given data."""

    if isinstance(data, dict):
        # direct keys that may contain numeric value or nested price dict
        for key in ["salePrice", "offerPrice", "unitPrice", "price", "value"]:
            if key in data:
                val = data[key]
                if isinstance(val, dict):
                    if "value" in val:
                        return str(val["value"])
                elif isinstance(val, (int, float, str)):
                    return str(val)

        # search any key containing "price"
        for key, val in data.items():
            if "price" in key.lower():
                if isinstance(val, dict) and "value" in val:
                    return str(val["value"])
                if isinstance(val, (int, float, str)):
                    return str(val)
            price = parse_price(val)
            if price:
                return price

    elif isinstance(data, list):
        for item in data:
            price = parse_price(item)
            if price:
                return price

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

        def matches(resp):
            if "price" in resp.url and "byPartNumbers" in resp.url:
                return part in resp.url if part else True
            return False

        await page.goto(url, timeout=60000)
        try:
            resp = await page.wait_for_event("response", matches, timeout=15000)
            data = await resp.json()
            return parse_price(data)
        except Exception:
            return None
        finally:
            await browser.close()


async def price_from_page(page: Page, url: str) -> Optional[str]:
    """Use an existing Playwright page to fetch the price."""
    part = extract_part_number(url)

    def matches(resp):
        if "price" in resp.url and "byPartNumbers" in resp.url:
            return part in resp.url if part else True
        return False

    await page.goto(url, timeout=60000)
    try:
        resp = await page.wait_for_event("response", matches, timeout=15000)
        data = await resp.json()
        price = parse_price(data)
        if price:
            return price
    except Exception:
        pass
    return fetch_price_json(url)


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