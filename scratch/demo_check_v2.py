import asyncio
from playwright.async_api import async_playwright
import easyocr
import re
import os

async def run_demo_check_v2():
    print("--- CDSC IPO Result Check Demo V2 ---")
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
            
            # 1. Handle Custom Dropdown (v-select)
            print("Selecting company...")
            # Click the dropdown to open it
            await page.click(".v-select, .vs__dropdown-toggle, .vs__search")
            await asyncio.sleep(1)
            
            # Click the first option
            await page.click(".vs__dropdown-menu li, .vs__dropdown-option")
            company_name = await page.inner_text(".vs__selected, .v-select")
            print(f"Selected Company: {company_name.strip()}")

            # 2. Enter Random BOID
            random_boid = "1301060001234567"
            print(f"Entering Random BOID: {random_boid}")
            await page.fill("input[name='boid'], #boid", random_boid)

            # 3. Solve Captcha
            print("Solving Captcha with AI...")
            reader = easyocr.Reader(['en'], gpu=False)
            
            # Find the canvas
            captcha_el = await page.query_selector("canvas")
            if captcha_el:
                img_bytes = await captcha_el.screenshot()
                results = reader.readtext(img_bytes)
                if results:
                    captcha_code = "".join(re.findall(r'\d', results[0][1]))
                    print(f"Captcha Solved: {captcha_code}")
                    await page.fill("input[name='userCaptcha'], #captcha", captcha_code)
                    
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
                    
                    await page.screenshot(path="d:\\ipoautomation\\scratch\\demo_success.png")
            else:
                print("FAILED: Captcha element not found.")

        except Exception as e:
            print(f"Error: {e}")
            await page.screenshot(path="d:\\ipoautomation\\scratch\\demo_v2_error.png")
            
        await browser.close()
        print("\nDemo Complete.")

if __name__ == "__main__":
    asyncio.run(run_demo_check_v2())
