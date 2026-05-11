import asyncio
from playwright.async_api import async_playwright
import easyocr
import re
import os

async def test_captcha_final_v2():
    print("Testing CDSC Captcha Solver (V2 Stealth)...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, 
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()
        
        print("Navigating to CDSC Portal...")
        await page.goto("https://iporesult.cdsc.com.np/", timeout=60000)
        
        # Wait specifically for the company dropdown which indicates the form is loading
        try:
            await page.wait_for_selector("select#company", timeout=30000)
            print("Form loaded!")
        except:
            print("Form did not load in 30s.")
            await page.screenshot(path="d:\\ipoautomation\\scratch\\form_fail.png")
            await browser.close()
            return
            
        await asyncio.sleep(2)
        
        # Take screenshot of the whole form area
        await page.screenshot(path="d:\\ipoautomation\\scratch\\full_form.png")
        
        # Try to find ALL canvases and images
        elements = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('canvas, img, div')).map(el => ({
                tag: el.tagName,
                id: el.id,
                class: el.className,
                src: el.src || "",
                visible: el.offsetWidth > 0
            })).filter(e => e.visible);
        }''')
        
        print("\n--- VISIBLE ELEMENTS ---")
        for e in elements:
            if e['tag'] in ['CANVAS', 'IMG'] or 'captcha' in e['class'].lower() or 'captcha' in e['id'].lower():
                print(e)
        
        # Attempt OCR on the first canvas found
        captcha_el = await page.query_selector("canvas, img[src*='captcha']")
        if captcha_el:
            print("\nFound Captcha Element!")
            img_bytes = await captcha_el.screenshot()
            reader = easyocr.Reader(['en'], gpu=False)
            results = reader.readtext(img_bytes)
            if results:
                print(f"AI Result: {results[0][1]}")
            else:
                print("AI could not read text.")
        else:
            print("\nStill could not find captcha element.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_captcha_final_v2())
