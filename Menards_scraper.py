import asyncio
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

URL = "https://www.menards.com/main/hardware/casters-furniture-hardware/casters/shepherd-hardware-reg-8-pneumatic-swivel-caster-wheel/9794ccm/p-1444442243761-c-13090.htm"

CURRENCY_SYMBOLS = "$€£¥₹"
CURRENCY_CODES = "USD|EUR|GBP|CAD|AUD|JPY|CNY|INR"

def extract_price(text):
    """Return the first price-like string found in the text."""
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

async def enhanced_semantic_price_scan(page):
    """Try multiple price selectors and return the first match."""
    selector_patterns = [
        '[class*="price"]',
        '[id*="price"]',
        '[class*="amount"]',
        '[itemprop="price"]',
        'meta[property="product:price:amount"]',
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

async def extract_price_menards():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # show browser for debugging
        page = await browser.new_page()
        await page.goto(URL, timeout=60000)
        await page.wait_for_timeout(7000)  # wait for dynamic content

        selectors = [
            '[data-at-id="full-price-discount-edlp"] span',
            '[data-at-id="full-price-current-edlp"] span',
        ]

        for sel in selectors:
            try:
                element = await page.wait_for_selector(sel, timeout=10000)
                if element:
                    text = await element.inner_text()
                    price = extract_price(text or "")
                    if price:
                        await browser.close()
                        return price
            except Exception:
                continue

        try:
            meta = await page.query_selector('meta[property="product:price:amount"]')
            if meta:
                content = await meta.get_attribute("content")
                price = extract_price(content or "")
                if price:
                    await browser.close()
                    return price
        except Exception:
            pass

        fallback = await enhanced_semantic_price_scan(page)
        if fallback:
            await browser.close()
            return fallback

        await browser.close()
        return "No price found"

if __name__ == "__main__":
    price = asyncio.run(extract_price_menards())
    print("Menards price:", price)
