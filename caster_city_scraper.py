import asyncio
from playwright.async_api import async_playwright

URL = "https://castercity.com/product/8-swivel-pneumatic-caster-black/"
WRAPPER = ".summaryfull.entry-summaryfull"
SELECTOR = ".woocommerce-Price-amount.amount"

async def extract_price_caster_city():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, timeout=60000)
        await page.wait_for_timeout(5000)  # allow JS to finish rendering

        wrapper = await page.query_selector(WRAPPER)
        if not wrapper:
            return "Price wrapper not found"

        price_elements = await wrapper.query_selector_all(SELECTOR)
        prices = []
        for el in price_elements:
            text = await el.inner_text()
            if "$" in text and text.strip() != "$0.00":
                prices.append(text.strip())

        await browser.close()
        return prices[0] if prices else "No valid price found in wrapper"

if __name__ == "__main__":
    price = asyncio.run(extract_price_caster_city())
    print("Caster City price:", price)
