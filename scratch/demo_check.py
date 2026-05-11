import asyncio
from playwright.async_api import async_playwright
import easyocr
import re
import os

async def run_demo_check():
    print("--- CDSC IPO Result Check Demo ---")
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
                print("FAILED: Blocked by CDSC Firewall. Please try again in a moment.")
                await browser.close()
                return

            print("Reached Portal successfully!")
            
            # 1. Select First Company
            await page.wait_for_selector("select#company", timeout=15000)
            company_name = await page.evaluate("""
                () => {
                    const select = document.querySelector('select#company');
                    if (select.options.length > 1) {
                        select.selectedIndex = 1; // Select first real company
                        select.dispatchEvent(new Event('change'));
                        return select.options[1].innerText;
                    }
                    return null;
                }
            """)
            print(f"Selected Company: {company_name}")

            # 2. Enter Random BOID
            random_boid = "1301060001234567"
            print(f"Entering Random BOID: {random_boid}")
            await page.fill("input#boid", random_boid)

            # 3. Solve Captcha
            print("Solving Captcha with AI...")
            reader = easyocr.Reader(['en'], gpu=False)
            
            max_retries = 3
            for attempt in range(max_retries):
                captcha_el = await page.query_selector("canvas")
                if not captcha_el:
                     print("Captcha element not found!")
                     break
                
                img_bytes = await captcha_el.screenshot()
                results = reader.readtext(img_bytes)
                
                if results:
                    captcha_code = "".join(re.findall(r'\d', results[0][1]))
                    if len(captcha_code) >= 5:
                        print(f"Captcha Solved: {captcha_code}")
                        await page.fill("input#captcha", captcha_code)
                        
                        # 4. Submit
                        print("Submitting...")
                        await page.click("button[type='submit']")
                        await asyncio.sleep(3)
                        
                        # 5. Extract Result
                        result_text = await page.evaluate("""
                            () => {
                                const body = document.body.innerText.toLowerCase();
                                if (body.includes("not allotted")) return "Not Allotted";
                                if (body.includes("congratulations")) return "Allotted!";
                                if (body.includes("invalid captcha")) return "RETRY";
                                return "Unknown: " + document.body.innerText.substring(0, 100);
                            }
                        """)
                        
                        if result_text == "RETRY":
                            print("AI misread captcha, refreshing...")
                            await page.reload()
                            await asyncio.sleep(3)
                            continue
                        
                        print(f"\nFINAL RESULT: {result_text}")
                        await page.screenshot(path="d:\\ipoautomation\\scratch\\demo_result.png")
                        break
                    else:
                        print(f"AI read '{results[0][1]}', refreshing...")
                        await page.reload()
                        await asyncio.sleep(3)
                else:
                    print("AI could not read captcha, refreshing...")
                    await page.reload()
                    await asyncio.sleep(3)

        except Exception as e:
            print(f"Error: {e}")
            await page.screenshot(path="d:\\ipoautomation\\scratch\\demo_error.png")
            
        await browser.close()
        print("\nDemo Complete.")

if __name__ == "__main__":
    asyncio.run(run_demo_check())
