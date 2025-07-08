# caster_scraper

This project scrapes product prices and writes them to a Google Sheet.

## Environment Variables

The scraper expects the path to your Google service account credentials to be
provided in the `GOOGLE_APPLICATION_CREDENTIALS` environment variable. Set this
variable before running `scraper-v1.0.py`:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service_account.json
python scraper-v1.0.py
```
