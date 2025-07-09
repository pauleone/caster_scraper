# scraper-v1.0.py

import datetime
import asyncio
import os
import re
import logging
from urllib.parse import urlparse
from google.oauth2 import service_account
from googleapiclient.discovery import build
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import random
import requests
from bs4 import BeautifulSoup
import json
import argparse
from harbor_freight_scraper import fetch_price as hf_fetch_price
from northern_tool_scraper import price_from_page as nt_price_from_page

# === CONFIG ===
SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID", "1UmYEGz8jibtvNUkq5X5HbG3lCdZTfQ4Blooq9bwDZwc"
)
LINKS_TAB = os.environ.get("LINKS_TAB", "Caster Links")
ERROR_TAB = os.environ.get("ERROR_TAB", "Error Log")
START_ROW = 2
CREDENTIALS_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

HEADLESS_ENV = os.environ.get("HEADLESS", "true").lower() in ("1", "true", "yes", "y")
HEADLESS = HEADLESS_ENV
CONCURRENCY = int(os.environ.get("SCRAPER_CONCURRENCY", "2"))

# API keys for optional scraping services
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")
SCRAPINGBEE_KEY = os.environ.get("SCRAPINGBEE_KEY")
SCRAPEDO_KEY = os.environ.get("SCRAPEDO_KEY")
APIFY_TOKEN = os.environ.get("APIFY_TOKEN")
ZYTE_API_KEY = os.environ.get("ZYTE_API_KEY")

# === LOGGING SETUP ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# === GOOGLE SHEETS FUNCTIONS ===
def get_sheets_service():
    """Return a Google Sheets service client using the credentials file."""
    if not CREDENTIALS_FILE:
        raise EnvironmentError(
            "GOOGLE_APPLICATION_CREDENTIALS environment variable not set"
        )
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return build('sheets', 'v4', credentials=creds)

def get_links_from_sheet(service):
    """Return rows containing vendor, URL and selector information."""
    range_name = f"{LINKS_TAB}!B{START_ROW}:D"
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=range_name).execute()
    return result.get('values', [])

def get_next_col_letter(service):
    """Compute the next empty column letter in the links tab."""
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{LINKS_TAB}!1:1").execute()
    headers = result.get('values', [[]])[0]
    next_col = len(headers) + 1
    result_col = ""
    while next_col > 0:
        next_col, remainder = divmod(next_col - 1, 26)
        result_col = chr(65 + remainder) + result_col
    return result_col

def write_prices(service, col_letter, prices):
    """Write a column of price values to the spreadsheet."""
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{LINKS_TAB}!{col_letter}{START_ROW}",
        valueInputOption="RAW",
        body={"values": prices}
    ).execute()

def write_timestamp_header(service, col_letter):
    """Add a timestamp header above the price column."""
    ts = datetime.datetime.now().strftime("Price %Y-%m-%d %H:%M:%S")
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{LINKS_TAB}!{col_letter}1",
        valueInputOption="RAW",
        body={"values": [[ts]]}
    ).execute()

def log_errors(service, errors):
    """Append scraping errors to the error log tab."""
    if not errors:
        return
    today = datetime.datetime.now().isoformat()
    values = [
        [today, vendor, url, status, selector, error, snippet]
        for vendor, url, status, selector, error, snippet in errors
    ]
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{ERROR_TAB}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values}
    ).execute()

# === SCRAPING HELPERS ===
CURRENCY_SYMBOLS = "$€£¥₹"
CURRENCY_CODES = "USD|EUR|GBP|CAD|AUD|JPY|CNY|INR"

def extract_price(text):
    """Return the first price-like string found in the text.

    The parser understands common currency symbols and codes both before and
    after the numeric value (e.g. ``€9.99``, ``9.99 USD``).
    """

    patterns = [
        rf"[{CURRENCY_SYMBOLS}]\s?\d{{1,3}}(?:[,.]\d{{3}})*(?:[,.]\d{{2}})?",
        rf"\d{{1,3}}(?:[,.]\d{{3}})*(?:[,.]\d{{2}})?\s?(?:{CURRENCY_CODES})",
        rf"(?:{CURRENCY_CODES})\s?\d{{1,3}}(?:[,.]\d{{3}})*(?:[,.]\d{{2}})?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None

def bs_price_scan(html):
    """Parse HTML with BeautifulSoup to locate a price when regex fails."""
    soup = BeautifulSoup(html, "html.parser")
    for text_node in soup.stripped_strings:
        price = extract_price(text_node)
        if price:
            return price
    return None

def _json_price_search(data):
    """Recursively look for a numeric price field in JSON data."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() == "price" and isinstance(value, (str, int, float)):
                return str(value)
            found = _json_price_search(value)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _json_price_search(item)
            if found:
                return found
    return None


def script_price_scan(html):
    """Search <script> tags for a price value."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        content = script.string or ""
        if script.get("type") == "application/ld+json":
            try:
                data = json.loads(content)
            except Exception:
                data = None
            if data:
                price = _json_price_search(data)
                if price:
                    return f"${price}" if not extract_price(str(price)) else str(price)
        else:
            match = re.search(r"[\"']price[\"']\s*[:=]\s*[\"']?(\d+(?:[.,]\d+)?)", content)
            if match:
                return f"${match.group(1)}"
    return None

def fetch_with_scraping_services(url):
    """Fetch a URL using one of the configured scraping services."""
    services = []
    if SCRAPERAPI_KEY:
        services.append(
            (
                "scraperapi",
                f"http://api.scraperapi.com/?api_key={SCRAPERAPI_KEY}&url={url}&render=true",
            )
        )
    if SCRAPINGBEE_KEY:
        services.append(
            (
                "scrapingbee",
                f"https://app.scrapingbee.com/api/v1/?api_key={SCRAPINGBEE_KEY}&url={url}&render_js=true",
            )
        )
    if SCRAPEDO_KEY:
        services.append(
            (
                "scrape.do",
                f"https://api.scrape.do/?token={SCRAPEDO_KEY}&url={url}&render=true",
            )
        )
    if APIFY_TOKEN:
        services.append(
            (
                "apify",
                f"http://proxy.apify.com/?token={APIFY_TOKEN}&url={url}&render=true",
            )
        )
    if ZYTE_API_KEY:
        services.append(
            (
                "zyte",
                f"https://api.zyte.com/v1/extract?url={url}&apikey={ZYTE_API_KEY}&render=true",
            )
        )

    random.shuffle(services)
    headers = {"User-Agent": "Mozilla/5.0"}
    for name, service_url in services:
        try:
            resp = requests.get(service_url, headers=headers, timeout=30)
            if resp.status_code == 200 and resp.text:
                logger.info("Fetched %s via %s", url, name)
                return resp.text
            logger.warning("%s returned status %s", name, resp.status_code)
        except Exception as e:
            logger.warning("Service %s failed: %s", name, e)
    return None

def menards_price_from_html(html):
    """Extract price from Menards HTML content."""
    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        "#itemFinalPrice",
        '[data-at-id="itemFinalPrice"]',
        '[data-at-id="full-price-discount-edlp"] span',
        '[data-at-id="full-price-current-edlp"] span',
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if not el:
            continue
        if "itemFinalPrice" in sel:
            attr = el.get("data-final-price")
            price = extract_price(attr or "")
        else:
            price = extract_price(el.get_text() or "")
        if price:
            return price
    meta = soup.select_one('meta[property="product:price:amount"]')
    if meta:
        price = extract_price(meta.get("content") or "")
        if price:
            return price
    return bs_price_scan(html)

async def enhanced_semantic_price_scan(page):
    """Try multiple price selectors on the page and return the first match."""
    selector_patterns = [
        '[class*="price"]',
        '[id*="price"]',
        '[class*="amount"]',
        '[itemprop="price"]',
        'meta[property="product:price:amount"]'
    ]
    for selector in selector_patterns:
        try:
            elements = await page.query_selector_all(selector)
            for element in elements:
                try:
                    if "meta" in selector:
                        content = await element.get_attribute("content")
                        price = extract_price(content or "")
                    else:
                        text = await element.inner_text()
                        price = extract_price(text or "")
                    if price:
                        return price
                except Exception:
                    continue
        except Exception:
            continue
    return None

async def caster_city_price_scan(page):
    """Special handler for castercity.com pages."""
    await page.wait_for_timeout(5000)
    wrapper = await page.query_selector(".summaryfull.entry-summaryfull")
    if not wrapper:
        return "Price wrapper not found"
    elements = await wrapper.query_selector_all(".woocommerce-Price-amount.amount")
    prices = []
    for el in elements:
        try:
            text = await el.inner_text()
            if "$" in text and text.strip() != "$0.00":
                prices.append(text.strip())
        except Exception:
            continue
    return prices[0] if prices else "No valid price found in wrapper"

async def menards_price_scan(page, url):
    """Special handler for menards.com pages with proxy fallbacks."""

    html = fetch_with_scraping_services(url)
    if html:
        price = menards_price_from_html(html)
        if price:
            return price

    # Proxy failed, try loading directly via Playwright
    response = await page.goto(url, timeout=20000)
    status = response.status if response else None
    await page.wait_for_timeout(7000)

    selectors = [
        '#itemFinalPrice',  # hidden element with data-final-price attribute
        '[data-at-id="itemFinalPrice"]',
        '[data-at-id="full-price-discount-edlp"] span',
        '[data-at-id="full-price-current-edlp"] span',
    ]

    for sel in selectors:
        try:
            element = await page.wait_for_selector(sel, timeout=5000)
            if element:
                if "itemFinalPrice" in sel:
                    attr = await element.get_attribute("data-final-price")
                    price = extract_price(attr or "")
                else:
                    text = await element.inner_text()
                    price = extract_price(text or "")
                if price:
                    return price
        except Exception:
            continue

    try:
        meta = await page.query_selector('meta[property="product:price:amount"]')
        if meta:
            content = await meta.get_attribute("content")
            price = extract_price(content or "")
            if price:
                return price
    except Exception:
        pass

    fallback = await enhanced_semantic_price_scan(page)
    return fallback or "No price found"

def grainger_price_from_html(html):
    """Extract the price from Grainger HTML using JSON-LD or fuzzy scan."""
    price = script_price_scan(html)
    if price:
        return price
    return bs_price_scan(html)

async def grainger_price_scan(page, url):
    """Special handler for grainger.com pages with proxy fallback."""
    html = fetch_with_scraping_services(url)
    if html:
        price = grainger_price_from_html(html)
        if price:
            return price

    response = await page.goto(url, timeout=20000)
    _ = response.status if response else None
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        await page.wait_for_timeout(5000)
    page_html = await page.content()
    price = grainger_price_from_html(page_html)
    if price:
        return price
    fallback = await enhanced_semantic_price_scan(page)
    return fallback or "No price found"


def msc_price_from_html(html):
    """Extract the price from MSC Direct HTML using JSON-LD or fuzzy scan."""
    price = script_price_scan(html)
    if price:
        return price
    return bs_price_scan(html)


async def msc_price_scan(page, url):
    """Special handler for MSC Direct pages with proxy fallback."""
    html = fetch_with_scraping_services(url)
    if html:
        price = msc_price_from_html(html)
        if price:
            return price

    response = await page.goto(url, timeout=20000)
    _ = response.status if response else None
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        await page.wait_for_timeout(5000)
    page_html = await page.content()
    price = msc_price_from_html(page_html)
    if price:
        return price
    fallback = await enhanced_semantic_price_scan(page)
    return fallback or "No price found"

async def harbor_freight_price_scan(url):
    """Fetch price data from Harbor Freight's Dynamic Yield endpoint."""

    def _fetch():
        return hf_fetch_price(url)

    try:
        price = await asyncio.to_thread(_fetch)
        return price
    except Exception as e:
        return f"Error: {e}"

async def fetch_price_from_page(page, url, selector=None):
    """Return the price text from the given URL using optional CSS selector."""
    page_html = ""
    try:
        domain = urlparse(url).netloc.lower()
        if "menards.com" in domain:
            price = await menards_price_scan(page, url)
            return price, None, None

        if "harborfreight.com" in domain:
            price = await harbor_freight_price_scan(url)
            return price, None, None

        if "grainger.com" in domain:
            price = await grainger_price_scan(page, url)
            return price, None, None

        if "mscdirect.com" in domain:
            price = await msc_price_scan(page, url)
            return price, None, None

        if "northerntool.com" in domain:
            price = await nt_price_from_page(page, url)
            return price or "No price found", None, None

        response = await page.goto(url, timeout=20000)
        status = response.status if response else None
        await page.wait_for_timeout(3000)
        page_html = await page.content()

        if "castercity.com" in domain:
            price = await caster_city_price_scan(page)
            return price, status, None

        # Tier 1: Specific selector from sheet
        if selector:
            element = None
            try:
                await page.wait_for_selector(selector, timeout=6000)
                element = await page.query_selector(selector)
            except Exception as sel_error:
                logger.debug("Selector failed for %s: %s", selector, sel_error)

            if element:
                try:
                    text = await element.inner_text()
                except Exception:
                    text = ""
                price = extract_price(text)
                if price:
                    return price, status, None
                logger.debug("No price found in selector for %s", selector)
            else:
                logger.debug("Selector not found: %s", selector)
            # Fall through to semantic scan if selector didn't yield a price

        # Tier 2: Semantic scan
        price = await enhanced_semantic_price_scan(page)
        if price:
            return price, status, None

        # Tier 3: Look inside script tags for price data
        script_price = script_price_scan(page_html)
        if script_price:
            return script_price, status, None

        # Tier 4: Fuzzy content scan
        text_price = extract_price(page_html)
        if not text_price:
            text_price = bs_price_scan(page_html)
        return (text_price or "No price found in fuzzy scan", status, page_html[:500])

    except PlaywrightTimeoutError:
        return "Timeout", None, page_html[:500]
    except Exception as e:
        return f"Error: {str(e)}", None, page_html[:500]

async def scrape_all(rows, concurrency=CONCURRENCY):
    """Scrape prices for each row concurrently using a pool of pages."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/113.0.0.0 Safari/537.36"
            ),
        )

        results = [None] * len(rows)
        errors = []

        # Create a pool of pages according to the desired concurrency
        page_pool = asyncio.Queue()
        for _ in range(concurrency):
            page_pool.put_nowait(await context.new_page())

        async def scrape_row(idx, row):
            vendor = row[0].strip() if len(row) > 0 else ""
            url = row[1].strip() if len(row) > 1 else ""
            selector = row[2].strip() if len(row) > 2 else ""

            if not url:
                results[idx] = [""]
                return

            logger.info(
                "Scraping: %s | %s | Using selector: %s",
                vendor,
                url,
                selector or "semantic/fuzzy",
            )

            page = await page_pool.get()
            try:
                result, status, snippet = await fetch_price_from_page(page, url, selector)
            finally:
                await page_pool.put(page)

            parsed = extract_price(result or "")
            if parsed:
                results[idx] = [parsed]
            else:
                results[idx] = [""]
                errors.append(
                    (
                        vendor,
                        url,
                        status,
                        selector or "semantic/fuzzy",
                        result,
                        snippet,
                    )
                )
                logger.error(
                    "Error scraping %s (%s) - status %s: %s",
                    vendor,
                    url,
                    status,
                    result,
                )

        tasks = [asyncio.create_task(scrape_row(i, row)) for i, row in enumerate(rows)]
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any unexpected exceptions captured by asyncio.gather
        for res in task_results:
            if isinstance(res, Exception):
                errors.append(("", "", None, "gather", str(res), ""))
                logger.error("Unhandled exception during scraping: %s", res)

        # Close all pages in the pool
        while not page_pool.empty():
            page = await page_pool.get()
            await page.close()

        await context.close()
        await browser.close()
        return results, errors

# === MAIN ===
def main():
    """Entry point to fetch prices and update the spreadsheet."""
    global HEADLESS

    parser = argparse.ArgumentParser(description="Run the price scraper")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="Run browser in headless mode",
    )
    group.add_argument(
        "--headed",
        dest="headless",
        action="store_false",
        help="Run browser with UI",
    )
    parser.set_defaults(headless=HEADLESS_ENV)
    args = parser.parse_args()
    HEADLESS = args.headless

    logger.info("🔁 Starting scraper-v1.0...")
    service = get_sheets_service()
    rows = get_links_from_sheet(service)
    col_letter = get_next_col_letter(service)

    prices, errors = asyncio.run(scrape_all(rows, concurrency=CONCURRENCY))

    write_prices(service, col_letter, prices)
    write_timestamp_header(service, col_letter)
    log_errors(service, errors)
    logger.info("✅ Scraping complete.")

if __name__ == "__main__":
    main()