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
from bs4 import BeautifulSoup
import argparse

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
CONCURRENCY = int(os.environ.get("SCRAPER_CONCURRENCY", "5"))

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

def write_date_header(service, col_letter):
    """Add a date header above the price column."""
    today = datetime.date.today().strftime("Price %-m/%-d")
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{LINKS_TAB}!{col_letter}1",
        valueInputOption="RAW",
        body={"values": [[today]]}
    ).execute()

def log_errors(service, errors):
    """Append scraping errors to the error log tab."""
    if not errors:
        return
    today = datetime.datetime.now().isoformat()
    values = [
        [today, vendor, url, status, selector, error]
        for vendor, url, status, selector, error in errors
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

async def menards_price_scan(page):
    """Special handler for menards.com pages with graceful fallbacks."""
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

async def fetch_price_from_page(page, url, selector=None):
    """Return the price text from the given URL using optional CSS selector."""
    try:
        response = await page.goto(url, timeout=20000)
        status = response.status if response else None
        await page.wait_for_timeout(3000)

        domain = urlparse(url).netloc.lower()
        if "castercity.com" in domain:
            price = await caster_city_price_scan(page)
            return price, status
        if "menards.com" in domain:
            price = await menards_price_scan(page)
            return price, status

        # Tier 1: Specific selector from sheet
        if selector:
            try:
                await page.wait_for_selector(selector, timeout=6000)
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    price = extract_price(text)
                    return (price if price else "No price found in selector", status)
                else:
                    return ("Selector not found", status)
            except Exception as sel_error:
                return (f"Selector error: {sel_error}", status)

        # Tier 2: Semantic scan
        price = await enhanced_semantic_price_scan(page)
        if price:
            return price, status

        # Tier 3: Fuzzy content scan
        content = await page.content()
        text_price = extract_price(content)
        if not text_price:
            text_price = bs_price_scan(content)
        return (text_price or "No price found in fuzzy scan", status)

    except PlaywrightTimeoutError:
        return "Timeout", None
    except Exception as e:
        return f"Error: {str(e)}", None

async def scrape_all(rows, concurrency=CONCURRENCY):
    """Scrape prices for each row concurrently using a pool of pages."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)

        results = [None] * len(rows)
        errors = []

        # Create a pool of pages according to the desired concurrency
        page_pool = asyncio.Queue()
        for _ in range(concurrency):
            page_pool.put_nowait(await browser.new_page())

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
                result, status = await fetch_price_from_page(page, url, selector)
            finally:
                await page_pool.put(page)

            parsed = extract_price(result or "")
            if parsed:
                results[idx] = [parsed]
            else:
                results[idx] = [""]
                errors.append(
                    (vendor, url, status, selector or "semantic/fuzzy", result)
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
                errors.append(("", "", None, "gather", str(res)))
                logger.error("Unhandled exception during scraping: %s", res)

        # Close all pages in the pool
        while not page_pool.empty():
            page = await page_pool.get()
            await page.close()

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
    write_date_header(service, col_letter)
    log_errors(service, errors)
    logger.info("✅ Scraping complete.")

if __name__ == "__main__":
    main()
