import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating...")
        await page.goto("https://iporesult.cdsc.com.np/", timeout=60000)
        await asyncio.sleep(5)
        
        # Get all images
        imgs = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('img')).map(el => ({
                src: el.src,
                alt: el.alt,
                id: el.id,
                class: el.className
            }));
        }''')
        
        print("\n--- IMAGES FOUND ---")
        for img in imgs:
            print(img)
            
        await browser.close()

asyncio.run(run())
