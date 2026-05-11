import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating...")
        await page.goto("https://iporesult.cdsc.com.np/", timeout=60000)
        await asyncio.sleep(5)
        
        # Get all elements that might be the captcha
        els = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('canvas, div, span')).filter(el => {
                const style = window.getComputedStyle(el);
                return (el.tagName === 'CANVAS') || 
                       (style.backgroundImage && style.backgroundImage !== 'none') ||
                       (el.innerText && /^[0-9]{5}$/.test(el.innerText.trim()));
            }).map(el => ({
                tag: el.tagName,
                id: el.id,
                class: el.className,
                text: el.innerText ? el.innerText.trim() : ""
            }));
        }''')
        
        print("\n--- POTENTIAL CAPTCHA ELEMENTS ---")
        for el in els:
            print(el)
            
        await browser.close()

asyncio.run(run())
