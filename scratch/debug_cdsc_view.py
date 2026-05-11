import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        # Using a more "human" browser configuration
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        print("Navigating to CDSC...")
        await page.goto("https://iporesult.cdsc.com.np/", timeout=60000, wait_until='networkidle')
        await asyncio.sleep(5)
        
        # Take screenshot
        await page.screenshot(path="d:\\ipoautomation\\scratch\\cdsc_view.png")
        print("Screenshot saved to scratch\\cdsc_view.png")
        
        # Get body text
        text = await page.inner_text("body")
        print("\n--- BODY TEXT ---")
        print(text[:500])
        
        await browser.close()

asyncio.run(run())
