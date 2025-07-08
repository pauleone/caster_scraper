import asyncio
from playwright.async_api import async_playwright

URL = "https://www.menards.com/main/hardware/casters-furniture-hardware/casters/shepherd-hardware-reg-8-pneumatic-swivel-caster-wheel/9794ccm/p-1444442243761-c-13090.htm"

async def extract_price_menards():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # show browser for debugging
        page = await browser.new_page()
        await page.goto(URL, timeout=60000)
        await page.wait_for_timeout(7000)  # wait for dynamic content

        try:
            locator = page.locator('[data-at-id="full-price-discount-edlp"] span')
            await locator.wait_for(timeout=10000, state="visible")
            price = await locator.first.inner_text()
            await browser.close()
            return price.strip()
        except Exception as e:
            print("Selector error:", str(e))
            await browser.close()
            return "No price found"

if __name__ == "__main__":
    price = asyncio.run(extract_price_menards())
    print("Menards price:", price)