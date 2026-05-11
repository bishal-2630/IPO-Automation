import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating to https://www.nmbcl.com.np/ipo...")
        await page.goto("https://www.nmbcl.com.np/ipo", timeout=60000)
        await asyncio.sleep(5)
        
        # Check selectors
        selectors = [
            "select#company", "select[name='company']",
            "#boidNumber", "input[name='boid']",
            "button#submit", "button:has-text('Submit')"
        ]
        
        print("\n--- SELECTOR CHECK ---")
        for sel in selectors:
            try:
                el = await page.locator(sel).first
                visible = await el.is_visible()
                print(f"Selector '{sel}': {'VISIBLE' if visible else 'NOT VISIBLE'}")
            except:
                print(f"Selector '{sel}': ERROR")
            
        await browser.close()

asyncio.run(run())
