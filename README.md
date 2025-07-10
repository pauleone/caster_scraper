# Caster Scraper

This project collects pricing information from product pages and records the results in a Google Spreadsheet. It is built with Python, Playwright, and the Google Sheets API.

## Setup
1. Clone this repository and change into the project directory.
2. (Optional) Create and activate a virtual environment.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and add your API keys:
   ```bash
   cp .env.example .env
   ```
5. Create a Google service account and download its credentials JSON file. Grant the service account access to your target spreadsheet.
6. Export the path to the credentials file before running the scraper:
```bash
 export GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service_account.json
  ```
7. (Optional) Set `SCRAPER_CONCURRENCY` to control how many browser pages run in parallel. The default is `2`.
8. (Optional) Override spreadsheet details or browser mode with environment variables:
   ```bash
   export SPREADSHEET_ID=<your_sheet_id>
   export LINKS_TAB="Caster Links"
   export ERROR_TAB="Error Log"
   export HEADLESS=false  # or use --headed when running the script
   export BRIGHTDATA_BROWSER_URL="https://example.brightdata.com/browser"
   export BRIGHTDATA_API_TOKEN=<token>
   export STEALTH_MODE=true
   ```

## Spreadsheet Structure
The scraper expects a spreadsheet with two tabs:

- **Caster Links** – Contains product information to scrape. Rows start at B2 and should include:
  - **Column B**: Vendor or product name
  - **Column C**: Product URL
  - **Column D**: Optional CSS selector for the price
  New price columns are added automatically to the right of the existing data.
- **Error Log** – Receives a timestamped list of any scraping issues. Each entry now records the HTTP status code, the selector used, the method that located the price (such as proxy or semantic scan), and a short HTML snippet alongside the URL and error message.

Set the spreadsheet and tab names using environment variables if they differ from the defaults:

- `SPREADSHEET_ID` – Google Sheet ID (defaults to the demo sheet)
- `LINKS_TAB` – Name of the tab containing URLs (defaults to `Caster Links`)
- `ERROR_TAB` – Name of the tab for logging errors (defaults to `Error Log`)

You can also control whether Playwright runs in headless mode. By default the browser is headless, but this can be overridden with `HEADLESS=false` or by passing `--headed` when running the script.

To improve scraping of heavily protected sites like Grainger and Zoro you can supply BrightData Browser API credentials. When `BRIGHTDATA_BROWSER_URL` and `BRIGHTDATA_API_TOKEN` are set the scraper will attempt to fetch pages through BrightData before falling back to Playwright. Setting `STEALTH_MODE=true` injects a small script to hide automation indicators in the browser context.

## Usage
Run the scraper from the project directory:
```bash
python scraper-v1.0.py
```
The script retrieves the latest prices and writes them to the next empty column
in the **Caster Links** tab. Set the `SCRAPER_CONCURRENCY` environment variable
to control how many pages are fetched simultaneously. Any errors encountered are
appended to the **Error Log** tab along with a short snippet of the page for
troubleshooting.

### Standalone Selenium Example
The repository also includes `selenium_scrapy_grainger.py`, a self-contained
script that demonstrates scraping a Grainger product page using Selenium and
Scrapy. It relies on `webdriver-manager` to download a compatible chromedriver
version automatically. If you have an old driver in your `PATH` it may conflict
with the installed Chrome browser. Remove the outdated driver or ensure the
version matches your Chrome installation.

## Troubleshooting
- Ensure your service account credentials are correct and that the account has permission to edit the spreadsheet.
- If Playwright fails to launch the browser, run `playwright install` to download the required browser binaries.
- Check that your network connection allows access to the target sites.
- Review the console output and the **Error Log** tab for specific error messages.

## Contact
For questions or support, open an issue on this repository or email `support@example.com`.