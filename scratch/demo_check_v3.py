import asyncio
from playwright.async_api import async_playwright
import easyocr
import re
import os

async def run_demo_check_v3():
    print("--- CDSC IPO Result Check Demo V3 (Final Attempt) ---")
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
        
        url = "https://iporesult.cdsc.com.np/"
        print(f"Navigating to {url}...")
        try:
            await page.goto(url, timeout=60000, wait_until='networkidle')
            await asyncio.sleep(5)
            
            # Check for block
            if "requested URL was rejected" in await page.inner_text("body"):
                print("FAILED: Blocked by CDSC Firewall.")
                await browser.close()
                return

            print("Reached Portal successfully!")
            
            # 1. Select Company using ng-select
            print("Selecting company...")
            try:
                # Click the ng-select component
                await page.click("ng-select")
                await asyncio.sleep(1)
                
                # Click the first option in the dropdown panel
                await page.click(".ng-option")
                company_name = await page.inner_text("ng-select")
                print(f"Selected Company: {company_name.strip()}")
            except Exception as e:
                print(f"Dropdown error: {e}")
                await page.screenshot(path="d:\\ipoautomation\\scratch\\demo_v3_dropdown_error.png")

            # 2. Enter Random BOID
            random_boid = "1301060001234567"
            print(f"Entering Random BOID: {random_boid}")
            await page.fill("input#boid, input[name='boid']", random_boid)

            # 3. Solve Captcha
            print("Solving Captcha with AI...")
            reader = easyocr.Reader(['en'], gpu=False)
            
            captcha_el = await page.query_selector("canvas")
            if captcha_el:
                img_bytes = await captcha_el.screenshot()
                results = reader.readtext(img_bytes)
                if results:
                    captcha_code = "".join(re.findall(r'\d', results[0][1]))
                    print(f"Captcha Solved: {captcha_code}")
                    await page.fill("input#captcha, input[name='userCaptcha']", captcha_code)
                    
                    # 4. Submit
                    print("Submitting...")
                    await page.click("button[type='submit'], .btn-submit")
                    await asyncio.sleep(3)
                    
                    # 5. Result
                    body_text = await page.inner_text("body")
                    if "not allotted" in body_text.lower():
                        print("\nFINAL RESULT: Sorry, you are not allotted for this IPO.")
                    elif "congratulations" in body_text.lower():
                        print("\nFINAL RESULT: Congratulations! You are allotted!")
                    else:
                        print(f"\nFINAL RESULT: {body_text[:200].strip()}")
                    
                    await page.screenshot(path="d:\\ipoautomation\\scratch\\demo_v3_success.png")
            else:
                print("FAILED: Captcha element not found.")

        except Exception as e:
            print(f"Error: {e}")
            await page.screenshot(path="d:\\ipoautomation\\scratch\\demo_v3_error.png")
            
        await browser.close()
        print("\nDemo Complete.")

if __name__ == "__main__":
    asyncio.run(run_demo_check_v3())
