import json
import re
from scrapy import Selector
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

GRAINGER_URL = "https://www.grainger.com/product/MYTON-INDUSTRIES-Bulk-Container-7-cu-ft-4LMC3"


def extract_price(html: str) -> str | None:
    sel = Selector(text=html)
    scripts = sel.css('script[type="application/ld+json"]::text').getall()
    for script in scripts:
        try:
            data = json.loads(script)
        except Exception:
            continue
        if isinstance(data, dict):
            offer = data.get("offers")
            if isinstance(offer, dict) and offer.get("price"):
                return str(offer["price"])
    text_nodes = sel.css('[class*="price"]::text').getall()
    for text in text_nodes:
        m = re.search(r"\$?\d+(?:[.,]\d+)?", text)
        if m:
            return m.group(0)
    return None


def fetch_price(url: str) -> str | None:
    opts = Options()
    opts.add_argument("--headless")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    try:
        driver.get(url)
        WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState") == "complete")
        html = driver.page_source
    finally:
        driver.quit()
    return extract_price(html)


if __name__ == "__main__":
    price = fetch_price(GRAINGER_URL)
    print("Price:", price)
