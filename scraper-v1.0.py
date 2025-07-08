# scraper-v1.0.py

import datetime
import asyncio
import os
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
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
    values = [[today, vendor, url, selector, error] for vendor, url, selector, error in errors]
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{ERROR_TAB}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values}
    ).execute()

# === SCRAPING HELPERS ===
def extract_price(text):
    """Return the first price-like string found in the text."""
    matches = re.findall(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})", text)
    return matches[0] if matches else None

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

async def fetch_price_from_page(page, url, selector=None):
    """Return the price text from the given URL using optional CSS selector."""
    try:
        await page.goto(url, timeout=20000)
        await page.wait_for_timeout(3000)

        # Tier 1: Specific selector from sheet
        if selector:
            try:
                await page.wait_for_selector(selector, timeout=6000)
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    price = extract_price(text)
                    return price if price else "No price found in selector"
                else:
                    return "Selector not found"
            except Exception as sel_error:
                return f"Selector error: {sel_error}"

        # Tier 2: Semantic scan
        price = await enhanced_semantic_price_scan(page)
        if price:
            return price

        # Tier 3: Fuzzy content scan
        content = await page.content()
        return extract_price(content) or "No price found in fuzzy scan"

    except PlaywrightTimeoutError:
        return "Timeout"
    except Exception as e:
        return f"Error: {str(e)}"

async def scrape_all(rows, concurrency=CONCURRENCY):
    """Scrape prices for each row of vendor data using concurrent browser pages."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)

        results = [None] * len(rows)
        errors = []
        sem = asyncio.Semaphore(concurrency)

        async def scrape_row(idx, row):
            vendor = row[0].strip() if len(row) > 0 else ""
            url = row[1].strip() if len(row) > 1 else ""
            selector = row[2].strip() if len(row) > 2 else ""

            if not url:
                results[idx] = [""]
                return

            print(
                f"Scraping: {vendor} | {url} | Using selector: {selector or 'semantic/fuzzy'}"
            )

            async with sem:
                page = await browser.new_page()
                result = await fetch_price_from_page(page, url, selector)
                await page.close()

            if result and result.startswith("$"):
                results[idx] = [result]
            else:
                results[idx] = [""]
                errors.append(
                    (vendor, url, selector or "semantic/fuzzy", result)
                )

        tasks = [asyncio.create_task(scrape_row(i, row)) for i, row in enumerate(rows)]
        await asyncio.gather(*tasks)
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

    print("🔁 Starting scraper-v1.0...")
    service = get_sheets_service()
    rows = get_links_from_sheet(service)
    col_letter = get_next_col_letter(service)

    prices, errors = asyncio.run(scrape_all(rows, concurrency=CONCURRENCY))

    write_prices(service, col_letter, prices)
    write_date_header(service, col_letter)
    log_errors(service, errors)
    print("✅ Scraping complete.")

if __name__ == "__main__":
    main()
