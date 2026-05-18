from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
import os
import time
import json
import random
import string
import secrets
import re
import datetime
import psycopg2
import logging
from notifications import send_email_notification, send_push_notification
try:
    from PIL import Image, ImageEnhance, ImageOps, ImageFilter
except ImportError:
    pass

try:
    from playwright_stealth import stealth_sync
    HAS_STEALTH = True
except ImportError:
    try:
        from playwright_stealth import Stealth as _Stealth
        def stealth_sync(page):
            _Stealth().apply_stealth_sync(page)
        HAS_STEALTH = True
    except ImportError:
        stealth_sync = None
        HAS_STEALTH = False

# Load environment variables
load_dotenv()

def save_result_to_db(account, company_name, status, remark):
    db_url = os.getenv("DATABASE_URL")
    if not db_url: return
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM automation_applicationlog WHERE account_id = %s AND company_name = %s AND status IN ('Allotted', 'Not Allotted')",
            (account.get("ID"), company_name)
        )
        if cur.fetchone():
            cur.close()
            conn.close()
            return
        cur.execute("""
            INSERT INTO automation_applicationlog
                (account_id, company_name, status, remark, timestamp, is_read)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (account.get("ID"), company_name, status, remark,
              datetime.datetime.now(datetime.timezone.utc), (status == "Allotted")))
        conn.commit()
        cur.close()
        conn.close()
        print(f"    [DB] Result saved for {company_name}")
    except Exception as e:
        print(f"    [DB] Error saving result: {e}")

def get_accounts():
    db_url = os.getenv("DATABASE_URL")
    if not db_url: return []
    try:
        from cryptography.fernet import Fernet
        encryption_key = os.getenv("ENCRYPTION_KEY")
        cipher = Fernet(encryption_key.encode()) if encryption_key else None
        
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT a.id, a.meroshare_user, a.meroshare_pass, a.boid, a.dp_name, a.crn, a.tpin, a.bank_name, a.kitta, u.email, a.owner_id
            FROM automation_account a
            LEFT JOIN auth_user u ON a.owner_id = u.id
            WHERE a.is_active = True;
        """)
        columns = [desc[0] for desc in cur.description]
        db_rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        accounts = []
        for row in db_rows:
            cur.execute("SELECT token FROM automation_fcmtoken WHERE user_id = %s", (row['owner_id'],))
            tokens = [t[0] for t in cur.fetchall()]
            accounts.append({
                "ID": row['id'],
                "MEROSHARE_USER": row['meroshare_user'],
                "MEROSHARE_PASS": cipher.decrypt(row['meroshare_pass'].encode()).decode() if cipher else row['meroshare_pass'],
                "BOID": row['boid'],
                "DP_NAME": row['dp_name'],
                "CRN": row['crn'],
                "TPIN": row['tpin'],
                "TOKENS": tokens
            })
        cur.close()
        conn.close()
        return accounts
    except: return []

def get_applied_companies():
    """
    Returns a list of companies that were successfully applied for
    but are still missing an allotment result (Allotted/Not Allotted).
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url: return []
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        # Find companies where 'Success' exists but 'Allotted'/'Not Allotted' is missing for at least one account
        cur.execute("""
            SELECT DISTINCT company_name 
            FROM automation_applicationlog 
            WHERE status = 'Success' 
            AND company_name NOT IN (
                SELECT DISTINCT company_name 
                FROM automation_applicationlog 
                WHERE status IN ('Allotted', 'Not Allotted')
            )
        """)
        companies = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return [c for c in companies if c]
    except: return []

def get_unchecked_accounts_for_company(company_name):
    """
    Returns accounts that applied for this company but haven't been checked.
    """
    db_url = os.environ.get("DATABASE_URL")
    accounts = get_accounts() # Get all accounts
    if not db_url or not accounts: return []
    
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT account_id 
            FROM automation_applicationlog 
            WHERE company_name = %s AND status IN ('Allotted', 'Not Allotted')
        """, (company_name,))
        checked_ids = set(row[0] for row in cur.fetchall())
        cur.close()
        conn.close()
        
        # Only return accounts that are NOT in the checked list
        return [acc for acc in accounts if acc.get('ID') not in checked_ids]
    except: return accounts

def solve_captcha(page, reader, max_retries=3):
    import io
    for attempt in range(max_retries):
        try:
            # Re-locate captcha each attempt to avoid stale element after JS refresh
            captcha_img = page.locator("img[src*='captcha'], img[src*='Captcha'], img[alt='captcha'], .captcha-image img, #captcha_image").first
            captcha_img.wait_for(state="visible", timeout=20000)

            # Wait for real captcha image to load (not blank white)
            captcha_bytes = None
            for blank_check in range(15):
                raw = captcha_img.screenshot()
                img_check = Image.open(io.BytesIO(raw)).convert('L')
                all_px = list(img_check.getdata())
                white_ratio = sum(1 for px in all_px if px > 240) / len(all_px)
                if white_ratio < 0.9:
                    captcha_bytes = raw
                    break
                print(f"      [Captcha] Blank image (white={white_ratio:.2f}), waiting...")
                
                # Force refresh natively if it remains blank
                if blank_check >= 5:
                    try:
                        captcha_img.click(force=True, timeout=2000)
                    except:
                        pass
                    page.wait_for_timeout(2000)
                else:
                    page.wait_for_timeout(1000)
                    
                captcha_img = page.locator("img[src*='captcha'], img[src*='Captcha'], img[alt='captcha'], .captcha-image img, #captcha_image").first

            if not captcha_bytes:
                print(f"      [Captcha] Could not load real captcha image. Skipping attempt {attempt+1}.")
                continue

            os.makedirs("screenshots", exist_ok=True)
            with open(f"screenshots/captcha_attempt_{attempt}.png", "wb") as f:
                f.write(captcha_bytes)

            # Preprocessing configurations for EasyOCR
            nparr = np.frombuffer(captcha_bytes, np.uint8)
            img_cv = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
            h, w = img_cv.shape
            img_3x = cv2.resize(img_cv, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)
            img_2x = cv2.resize(img_cv, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

            preprocessed_images = {}
            
            # Path 1: 3x Resize + Median Closing (kernel size 3)
            median_closed = cv2.morphologyEx(img_3x, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
            preprocessed_images["3x_Closed"] = median_closed

            # Path 2: 3x Resize + Morphological Erode & Dilate (kernel size 2)
            kernel_2 = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            dilated = cv2.dilate(cv2.erode(img_3x, kernel_2), kernel_2)
            preprocessed_images["3x_ErodeDilate"] = dilated

            # Path 3: 3x Resize + Median Blur 9 + Otsu Binarization
            blur_9 = cv2.medianBlur(img_3x, 9)
            _, otsu_9 = cv2.threshold(blur_9, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            preprocessed_images["3x_Blur9_Otsu"] = otsu_9

            # Path 4: 3x Resize + Median Blur 13 + Otsu Binarization
            blur_13 = cv2.medianBlur(img_3x, 13)
            _, otsu_13 = cv2.threshold(blur_13, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            preprocessed_images["3x_Blur13_Otsu"] = otsu_13

            # Path 5: Grayscale + Horizontal/Vertical Line Subtraction + Morphological Closing + 2x Resize
            thresh = cv2.adaptiveThreshold(img_cv, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 8)
            horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))
            horizontal_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
            vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
            vertical_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
            binary = cv2.adaptiveThreshold(img_cv, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 11)
            digits_only = cv2.subtract(cv2.subtract(binary, horizontal_lines), vertical_lines)
            vertical_closing = cv2.morphologyEx(digits_only, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2)))
            preprocessed_images["1x_Closed_2x"] = cv2.resize(vertical_closing, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

            # Path 6: Raw 2x Resize
            preprocessed_images["Raw_2x"] = img_2x

            # Run OCR on all pathways and gather guesses
            guesses = []
            for name, img_proc in preprocessed_images.items():
                for inverted in [False, True]:
                    final_img = cv2.bitwise_not(img_proc) if inverted else img_proc
                    _, encoded = cv2.imencode('.png', final_img)
                    
                    results = reader.readtext(encoded.tobytes(), allowlist='0123456789', detail=0)
                    all_digits = "".join(re.findall(r'\d', "".join(results)))
                    
                    if len(all_digits) == 5:
                        guesses.append(all_digits)
                    elif len(all_digits) > 5:
                        guesses.append(all_digits[:5])

            # Select the most common 5-digit guess (majority voting)
            if guesses:
                from collections import Counter
                counter = Counter(guesses)
                best_code, count = counter.most_common(1)[0]
                print(f"      [Captcha] Solved: {best_code} (Consensus {count}/{len(guesses)})")
                return best_code

            print(f"      [Captcha] OCR failed. Refreshing captcha...")
            try:
                captcha_img.click(force=True, timeout=2000)
            except:
                pass
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"      [Captcha] Error: {e}")
    print("      [Captcha] Failed all attempts.")
    return None

def run_status_check():
    print("--- IPO Result Check Version: 2026-05-14 V18 (Full Stealth) ---")
    
    # 1. Get companies that need checking
    unchecked_companies = get_applied_companies()
    if not unchecked_companies:
        print("No unchecked IPO results found in database. Everything is up to date!")
        return

    print(f"Found {len(unchecked_companies)} unchecked companies: {unchecked_companies}")

    import easyocr
    reader = easyocr.Reader(['en'], gpu=False)

    with sync_playwright() as p:
        launch_kwargs = {
            "headless": os.environ.get("HEADLESS", "true").lower() != "false",
            "channel": "chrome",
            "ignore_default_args": ["--enable-automation"],
            "args": [
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--window-size=1366,768',
            ]
        }

        try:
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                timezone_id="Asia/Kathmandu",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1"
                }
            )
            page = context.new_page()
            if HAS_STEALTH and stealth_sync:
                stealth_sync(page)
            
            url = "https://iporesult.cdsc.com.np/"
            
            # 1. Warm up session
            print("  Warming up session...")
            try:
                page.goto("https://www.google.com", wait_until='domcontentloaded', timeout=15000)
                page.wait_for_timeout(random.randint(1000, 2000))
            except: pass

            print(f"Navigating to {url}...")
            page.goto(url, wait_until='domcontentloaded', timeout=60000, referer="https://www.google.com/")
            
            # Check for WAF rejection - check raw HTML content too
            page_html = page.content()
            body_text = page.inner_text("body")
            page_title = page.title()
            print(f"  Page Title: '{page_title}'")
            
            if ("rejected" in body_text.lower() or 
                "administrator" in body_text.lower() or
                "Request Rejected" in page_html or
                "rejected" in page_title.lower()):
                print(f"[CRITICAL] WAF blocked the request!")
                print(f"  Body preview: {body_text[:200]}")
                os.makedirs("screenshots", exist_ok=True)
                page.screenshot(path="screenshots/waf_block.png")
                return

            # Wait for Angular app to fully load
            print("  Waiting for Angular app to load...")
            try:
                page.wait_for_selector("ng-select, .ng-select-container", timeout=30000)
            except Exception:
                # One more WAF check if selector timed out
                body_text2 = page.inner_text("body")
                print(f"  [Timeout] Page body: {body_text2[:300]}")
                raise
            page.wait_for_timeout(2000)

            
            # Execute the automation logic
            run_automation_logic(page, reader, unchecked_companies)
            
            browser.close()

        except Exception as e:
            print(f"Fatal Error: {e}")
            try: browser.close()
            except: pass

def run_automation_logic(page, reader, unchecked_companies):
    # Move the actual scraping logic here (was previously in run_status_check)
    url = "https://iporesult.cdsc.com.np/"
    try:
        # Read all companies from CDSC dropdown
        all_cdsc_companies = []
        print("  Opening company dropdown...")
        for attempt in range(5): # More attempts for slow proxies
            page.locator("ng-select").first.click()
            page.wait_for_timeout(3000) # Wait longer for list to populate
            
            all_cdsc_companies = page.evaluate("""
                () => Array.from(document.querySelectorAll('.ng-option, ng-dropdown-panel .ng-option'))
                     .map(o => o.innerText.trim())
                     .filter(t => t.length > 3)
            """)
            
            if len(all_cdsc_companies) > 5: # Real list is large
                break
            
            print(f"    Dropdown has only {len(all_cdsc_companies)} items. Retrying ({attempt+1}/5)...")
            page.keyboard.press("Escape")
            page.wait_for_timeout(2000)
        
        if not all_cdsc_companies:
            print("[Error] Could not read company list from CDSC portal.")
            return

        print(f"  Found {len(all_cdsc_companies)} companies on CDSC portal.")
        if len(all_cdsc_companies) <= 5:
            print(f"  [Debug] Found companies: {all_cdsc_companies}")

        # Match unchecked companies with CDSC portal names
        def norm(n): return re.sub(r'\(.*?\)', '', n).lower().replace('limited', 'ltd').replace('ltd.', 'ltd').replace('company', '').replace('hydropower', 'hp').strip()
        
        matches = []
        for c_name in all_cdsc_companies:
            c_norm = norm(c_name)
            for db_name in unchecked_companies:
                db_norm = norm(db_name)
                # Fuzzy match: check if one contains the other or vice versa
                if c_norm in db_norm or db_norm in c_norm or c_norm.replace(' ', '') in db_norm.replace(' ', ''):
                    matches.append({'cdsc': c_name, 'db': db_name})
                    break
        
        if not matches:
            print(f"  No matching companies found. (Checked {len(unchecked_companies)} in DB vs {len(all_cdsc_companies)} on portal)")
            # Print a few examples for debugging
            print(f"  [Match Debug] CDSC Sample: {all_cdsc_companies[:3]}")
            print(f"  [Match Debug] DB Sample: {unchecked_companies[:3]}")
            return

        print(f"Starting smart check for {len(matches)} matched companies...")

        first_company = True
        for m in matches:
            # Find only accounts that haven't been checked for THIS specific company
            target_accounts = get_unchecked_accounts_for_company(m['db'])
            if not target_accounts:
                continue

            print(f"\n[Company] {m['cdsc']} (Checking {len(target_accounts)} accounts)")
            
            # Navigate once per company (skip for first company to use the verified loaded page)
            if not first_company:
                try:
                    print(f"   Navigating to fresh page for {m['cdsc']}...")
                    page.goto(url, wait_until='domcontentloaded', timeout=60000)
                    page.wait_for_timeout(random.randint(2000, 4000))
                except: pass
            else:
                first_company = False

            for account in target_accounts:
                username = account.get('MEROSHARE_USER')
                boid = account.get('BOID')
                if not boid: continue
                
                try:
                    print(f"   [{username}] Checking...")
                    
                    # WAF detection check
                    body_text = page.inner_text("body")
                    if "rejected" in body_text.lower() or "administrator" in body_text.lower():
                        print("      [WAF] Rejection detected on page! Attempting self-healing reload...")
                        try:
                            page.goto(url, wait_until='domcontentloaded', timeout=60000)
                            page.wait_for_timeout(3000)
                            body_text = page.inner_text("body")
                        except Exception as reload_e:
                            print(f"      [WAF] Reload navigation failed: {reload_e}")
                        
                        if "rejected" in body_text.lower() or "administrator" in body_text.lower():
                            print("      [WAF] Still blocked after reload. Skipping company batch.")
                            break
                    
                    # Close any outstanding modals before starting
                    try:
                        ok_btn = page.locator("button:has-text('Ok'), button:has-text('OK'), button:has-text('Go Back')").first
                        if ok_btn.is_visible(timeout=1000):
                            ok_btn.click(force=True)
                            page.wait_for_timeout(1000)
                    except:
                        pass
                    
                    # Use a resilient click that handles WAF overlays
                    def smart_click(selector):
                        try:
                            el = page.locator(selector).first
                            el.wait_for(state="visible", timeout=10000)
                            box = el.bounding_box()
                            if box:
                                # Human-like movement then click with force=True to bypass interception
                                page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
                                page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                                # Fallback click just in case
                                el.click(force=True, timeout=2000)
                            else:
                                el.click(force=True)
                        except:
                            try: page.locator(selector).first.click(force=True)
                            except: pass

                    # Selection with human-like typing
                    smart_click(".ng-select-container")
                    page.wait_for_timeout(500)
                    page.keyboard.type(m['cdsc'], delay=80)
                    page.wait_for_timeout(800)
                    page.keyboard.press("Enter")
                    
                    # BOID with human-like typing
                    print(f"      Typing BOID...")
                    smart_click("input#boid")
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(boid, delay=random.randint(80, 150))
                    
                    # Try solving captcha (up to 3 times per account check)
                    print(f"      Solving Captcha...")
                    for cap_attempt in range(3):
                        cap = solve_captcha(page, reader)
                        if not cap: continue
                        
                        # Use JS fill to bypass WAF iframe interception on input fields
                        page.evaluate(f"""() => {{
                            const el = document.querySelector('#captcha');
                            if (el) {{
                                el.value = '{cap}';
                                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                            }}
                        }}""")
                        page.wait_for_timeout(300)
                        
                        # Submit via smart_click which uses coordinate-based mouse click
                        smart_click("button:has-text('View Result')")
                        
                        # Dynamically wait for CDSC response modal (Congratulations / Sorry / Invalid Captcha)
                        try:
                            page.locator("text=Congratulations, text=Sorry, text=Invalid, text=Incorrect, text=Wrong").first.wait_for(state="visible", timeout=8000)
                        except:
                            pass
                            
                        res = page.evaluate("""
                            () => {
                                const b = document.body.innerText;
                                const lower = b.toLowerCase();
                                if (lower.includes("congratulations")) {
                                    const parts = b.split(/congratulations/i);
                                    const details = parts.length > 1 ? parts[1].split('.')[0].trim() : "";
                                    return "Allotted|" + details;
                                }
                                if (lower.includes("sorry")) {
                                    return "Not Allotted|Sorry, not allotted.";
                                }
                                if (lower.includes("invalid") || lower.includes("incorrect") || lower.includes("wrong")) {
                                    return "RETRY";
                                }
                                return "Pending|No result found.";
                            }
                        """)
                        
                        if res == "RETRY":
                            print(f"      [Captcha] Incorrect code. Retrying attempt {cap_attempt+1}...")
                            # Close the invalid captcha modal alert to return to form
                            try:
                                ok_btn = page.locator("button:has-text('Ok'), button:has-text('OK'), button:has-text('Go Back')").first
                                if ok_btn.is_visible(timeout=3000):
                                    ok_btn.click(force=True)
                                    page.wait_for_timeout(1000)
                            except:
                                pass
                            continue
                        
                        if res == "Pending|No result found.":
                            print(f"      [Check] No result found (possible timeout or site delay).")
                            continue

                        status, feedback = res.split("|")
                        print(f"      Result: {status}")
                        
                        if status != "Pending":
                            save_result_to_db(account, m['db'], status, feedback)
                            send_push_notification(account.get('TOKENS'), username, f"{m['cdsc']}: {status} - {feedback}")
                        
                        # Close the successful/unsuccessful result modal to return to the form for the next account
                        try:
                            ok_btn = page.locator("button:has-text('Ok'), button:has-text('OK'), button:has-text('Go Back')").first
                            if ok_btn.is_visible(timeout=3000):
                                ok_btn.click(force=True)
                                page.wait_for_timeout(1000)
                            else:
                                # Safe keyboard escape as fallback modal closer
                                page.keyboard.press("Escape")
                        except:
                            pass
                        break
                except Exception as e:
                    print(f"     Error for {username}: {e}")

    except Exception as e:
        print(f"Fatal Error in automation logic: {e}")

if __name__ == "__main__":
    run_status_check()
