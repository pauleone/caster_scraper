let puppeteer;
try {
  puppeteer = require('puppeteer');
} catch (err) {
  puppeteer = require('puppeteer-core');
}

(async () => {
  const url = process.argv[2];
  if (!url) {
    console.error('URL argument missing');
    process.exit(1);
  }
  const endpoint = process.env.BRIGHTDATA_BROWSER_URL;
  const token = process.env.BRIGHTDATA_API_TOKEN;
  if (!endpoint || !token) {
    console.error('BrightData environment variables not set');
    process.exit(1);
  }
  const browserWSEndpoint = `${endpoint}?token=${token}`;
  try {
    const browser = await puppeteer.connect({ browserWSEndpoint });
    const page = await browser.newPage();
    await page.goto(url, { waitUntil: 'networkidle0', timeout: 60000 });
    const price = await page.evaluate(() => {
      const sel = document.querySelector('[class*="price"], [id*="price"], [itemprop="price"]');
      return sel ? sel.innerText.trim() : '';
    });
    if (price) {
      console.log(price);
    }
    await browser.close();
  } catch (err) {
    console.error(err.message || err.toString());
    process.exit(1);
  }
})();
