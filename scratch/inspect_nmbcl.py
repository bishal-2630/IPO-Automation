import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating to https://www.nmbcl.com.np/ipo...")
        await page.goto("https://www.nmbcl.com.np/ipo", timeout=60000)
        await asyncio.sleep(5)
        
        # Get all inputs and selects
        inputs = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('input, select, button')).map(el => ({
                tag: el.tagName,
                id: el.id,
                name: el.name,
                placeholder: el.placeholder,
                text: el.innerText
            }));
        }''')
        
        print("\n--- ELEMENTS FOUND ---")
        for inp in inputs:
            print(inp)
            
        await browser.close()

asyncio.run(run())
