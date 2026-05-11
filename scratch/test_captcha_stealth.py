import asyncio
from playwright.async_api import async_playwright
import easyocr
import re
import os

async def test_captcha_stealth():
    print("Testing CDSC Captcha Solver (Stealth Mode)...")
    async with async_playwright() as p:
        # Using a more stealthy launch
        browser = await p.chromium.launch(
            headless=True, 
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()
        
        # Additional stealth headers
        await page.set_extra_http_headers({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        })

        print("Navigating to CDSC Portal...")
        try:
            # We'll go to the base URL first
            await page.goto("https://iporesult.cdsc.com.np/", timeout=60000, wait_until='networkidle')
            await asyncio.sleep(5)
            
            # Check if we got blocked
            body_text = await page.inner_text("body")
            if "requested URL was rejected" in body_text:
                print("FAILED: Still blocked by CDSC Firewall.")
                await page.screenshot(path="d:\\ipoautomation\\scratch\\blocked.png")
                await browser.close()
                return
                
            print("Successfully reached the portal!")
            
            print("Initializing AI Reader...")
            reader = easyocr.Reader(['en'], gpu=False)
            
            # Find the captcha image
            # In some versions of CDSC portal, it might be an 'img' or a 'canvas'
            # Let's try to find it by common attributes
            captcha_el = await page.query_selector("img[src*='captcha'], .captcha-img, canvas")
            
            if captcha_el:
                print("Found captcha element!")
                img_bytes = await captcha_el.screenshot()
                results = reader.readtext(img_bytes)
                
                if results:
                    raw_text = results[0][1]
                    captcha_text = "".join(re.findall(r'\d', raw_text))
                    print(f"AI Result: '{raw_text}' -> Extracted Digits: '{captcha_text}'")
                    if len(captcha_text) >= 5:
                        print("SUCCESS: AI correctly identified the digits.")
                    else:
                        print("INFO: AI read something, but not a clear 5-digit code.")
                else:
                    print("FAILED: AI could not read text from the element.")
            else:
                print("FAILED: Could not locate captcha element on page.")
                await page.screenshot(path="d:\\ipoautomation\\scratch\\not_found.png")

        except Exception as e:
            print(f"Error: {e}")
        
        await browser.close()
        print("\nTest Complete.")

if __name__ == "__main__":
    asyncio.run(test_captcha_stealth())
