# Caster Scraper

This project collects pricing information from product pages and records the results in a Google Spreadsheet. It is built with Python, Playwright, and the Google Sheets API.

## Setup
1. Clone this repository and change into the project directory.
2. (Optional) Create and activate a virtual environment.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create a Google service account and download its credentials JSON file. Grant the service account access to your target spreadsheet.
5. Export the path to the credentials file before running the scraper:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service_account.json
   ```

## Spreadsheet Structure
The scraper expects a spreadsheet with two tabs:

- **Caster Links** – Contains product information to scrape. Rows start at B2 and should include:
  - **Column B**: Vendor or product name
  - **Column C**: Product URL
  - **Column D**: Optional CSS selector for the price
  New price columns are added automatically to the right of the existing data.
- **Error Log** – Receives a timestamped list of any scraping issues.

Update the `SPREADSHEET_ID` constant in `scraper-v1.0.py` if you are using a different spreadsheet.

## Usage
Run the scraper from the project directory:
```bash
python scraper-v1.0.py
```
The script retrieves the latest prices and writes them to the next empty column in the **Caster Links** tab. Any errors encountered are appended to the **Error Log** tab.

## Troubleshooting
- Ensure your service account credentials are correct and that the account has permission to edit the spreadsheet.
- If Playwright fails to launch the browser, run `playwright install` to download the required browser binaries.
- Check that your network connection allows access to the target sites.
- Review the console output and the **Error Log** tab for specific error messages.

## Contact
For questions or support, open an issue on this repository or email `support@example.com`.
