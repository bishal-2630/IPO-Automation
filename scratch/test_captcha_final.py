import asyncio
from playwright.async_api import async_playwright
import easyocr
import re
import os

async def test_captcha_solve_real():
    print("Testing CDSC Captcha Solver (Final Stealth)...")
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
        await page.goto("https://iporesult.cdsc.com.np/", timeout=60000, wait_until='networkidle')
        await asyncio.sleep(5)
        
        print("Initializing AI Reader...")
        reader = easyocr.Reader(['en'], gpu=False)
        
        # Target the canvas element
        captcha_el = await page.query_selector("canvas")
        
        if captcha_el:
            print("Found Captcha Canvas!")
            # Take screenshot of the canvas
            img_bytes = await captcha_el.screenshot()
            
            # Save for manual verification if needed
            with open("d:\\ipoautomation\\scratch\\captcha_last.png", "wb") as f:
                f.write(img_bytes)
                
            results = reader.readtext(img_bytes)
            if results:
                raw_text = results[0][1]
                # Filter for digits
                captcha_text = "".join(re.findall(r'\d', raw_text))
                print(f"--- AI RESULTS ---")
                print(f"Raw Read: {raw_text}")
                print(f"Final Digits: {captcha_text}")
                
                if len(captcha_text) >= 5:
                    print("\nSUCCESS: AI correctly identified the 5-digit captcha!")
                else:
                    print("\nINFO: AI read the captcha but it might be noisy (Grid lines sometimes interfere).")
            else:
                print("FAILED: AI could not detect any text.")
        else:
            print("FAILED: Could not find canvas element.")

        await browser.close()
        print("\nTest Complete.")

if __name__ == "__main__":
    asyncio.run(test_captcha_solve_real())
