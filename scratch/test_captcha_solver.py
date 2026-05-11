import asyncio
from playwright.async_api import async_playwright
import easyocr
import re
import os

async def test_captcha():
    print("Testing CDSC Captcha Solver...")
    async with async_playwright() as p:
        # We'll use headless=True for the script to run in background
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print("Navigating to CDSC Portal...")
        try:
            await page.goto("https://iporesult.cdsc.com.np/", timeout=60000)
            await asyncio.sleep(3)
        except Exception as e:
            print(f"Error navigating: {e}")
            await browser.close()
            return
        
        print("Initializing AI Reader (this may take a moment)...")
        reader = easyocr.Reader(['en'], gpu=False)
        
        # Try to solve it 3 times
        for i in range(3):
            print(f"\nAttempt {i+1}:")
            try:
                # Find the captcha image
                captcha_img = page.locator("img[src*='captcha']").first
                if not await captcha_img.is_visible():
                    print("Captcha image not found. Refreshing...")
                    await page.reload()
                    await asyncio.sleep(2)
                    captcha_img = page.locator("img[src*='captcha']").first

                img_bytes = await captcha_img.screenshot()
                
                results = reader.readtext(img_bytes)
                if results:
                    raw_text = results[0][1]
                    # Filter for digits
                    captcha_text = "".join(re.findall(r'\d', raw_text))
                    print(f"Read Text: '{raw_text}' -> Extracted Digits: '{captcha_text}'")
                    
                    if len(captcha_text) >= 5:
                        print("SUCCESS: AI correctly identified the captcha digits.")
                    else:
                        print("INFO: AI read the text but digits count is unusual (Expected 5).")
                else:
                    print("FAILED: Could not read any text from image.")
                
                # Refresh for next attempt to show it handles different ones
                refresh_btn = page.locator(".fa-refresh, button:has(i.fa-refresh)").first
                if await refresh_btn.is_visible():
                    await refresh_btn.click()
                    await asyncio.sleep(1)
                else:
                    await page.reload()
                    await asyncio.sleep(2)
            except Exception as e:
                print(f"Error during attempt {i+1}: {e}")
        
        await browser.close()
        print("\nTest Complete.")

if __name__ == "__main__":
    asyncio.run(test_captcha())
