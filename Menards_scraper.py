import asyncio
from playwright.async_api import async_playwright

URL = "https://www.menards.com/main/hardware/casters-furniture-hardware/casters/shepherd-hardware-reg-8-pneumatic-swivel-caster-wheel/9794ccm/p-1444442243761-c-13090.htm"

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
                    price = text.strip()
                    if price:
                        await browser.close()
                        return price
            except Exception:
                continue

        try:
            meta = await page.query_selector('meta[property="product:price:amount"]')
            if meta:
                content = await meta.get_attribute("content")
                if content:
                    await browser.close()
                    return content.strip()
        except Exception:
            pass

        await browser.close()
        return "No price found"

if __name__ == "__main__":
    price = asyncio.run(extract_price_menards())
    print("Menards price:", price)
