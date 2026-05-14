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
    import io, hashlib
    last_hash = None
    
    img_selectors = [
        "img[src*='Captcha']", "img[src*='captcha']", 
        ".captcha-image img", "#captcha_image", 
        "img[alt*='captcha']", ".captcha-img"
    ]
    
    # Updated refresh selectors based on browser subagent findings
    refresh_selectors = [
        "button.btn:last-child",
        "button[title='Reload Captcha']", 
        "button:has(.fa-refresh)", 
        "button:has(.fa-sync)",
        ".captcha-refresh"
    ]
    
    for attempt in range(max_retries):
        try:
            captcha_img = None
            for sel in img_selectors:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1000):
                        captcha_img = el
                        break
                except: continue
            
            if not captcha_img:
                print("      [Captcha] Image not found. Waiting...")
                page.wait_for_timeout(2000)
                continue

            # 1. Capture and wait for a real, fresh image
            captcha_bytes = None
            for refresh_attempt in range(4):
                # Small wait for animation/load
                page.wait_for_timeout(1000)
                raw = captcha_img.screenshot()
                current_hash = hashlib.md5(raw).hexdigest()
                
                img_check = Image.open(io.BytesIO(raw)).convert('L')
                import numpy as np
                try:
                    all_px = np.array(img_check).flatten()
                except:
                    all_px = list(img_check.getdata())
                
                white_ratio = sum(1 for p in all_px if p > 240) / len(all_px)
                
                # If it's a valid image (not all white) and (first time OR changed from last)
                if white_ratio < 0.95 and (last_hash is None or current_hash != last_hash):
                    captcha_bytes = raw
                    last_hash = current_hash
                    break
                
                print(f"      [Captcha] Refresh needed (white={white_ratio:.2f}, same={current_hash == last_hash}). Attempt {refresh_attempt+1}...")
                
                # Try clicking refresh button with a human-like delay
                page.wait_for_timeout(random.randint(1500, 3000))
                refreshed = False
                for r_sel in refresh_selectors:
                    try:
                        btn = page.locator(r_sel).first
                        if btn.is_visible(timeout=500):
                            btn.click(force=True)
                            refreshed = True
                            break
                    except: continue
                
                if not refreshed:
                    # Fallback: JS refresh
                    page.evaluate("(sel) => { const img = document.querySelector(sel); if(img) { const b = img.src.split('?')[0]; img.src = b + '?v=' + Date.now(); } }", img_selectors[0])
                
                page.wait_for_timeout(2500)

            if not captcha_bytes:
                # If we're stuck, try one "Hard Refresh" of the page as a last resort
                if attempt == max_retries - 1:
                    print("      [Captcha] Persistent stuck image. Triggering page reload...")
                    return "RELOAD"
                continue

            # Image processing and OCR
            os.makedirs("screenshots", exist_ok=True)
            with open(f"screenshots/captcha_raw_{attempt}.png", "wb") as f:
                f.write(captcha_bytes)

            img = Image.open(io.BytesIO(captcha_bytes)).convert('L')
            w, h = img.size
            img3x = img.resize((w * 3, h * 3), Image.Resampling.LANCZOS)
            
            # Multiple preprocessing paths to catch all digits
            paths = [
                # Path 1: Median Denoise (good for grid)
                img3x.filter(ImageFilter.MedianFilter(size=3)),
                # Path 2: Contrast + Sharpness
                ImageEnhance.Sharpness(ImageEnhance.Contrast(img3x).enhance(2.0)).enhance(2.0),
                # Path 3: Aggressive Binary
                img3x.point(lambda p: 255 if p > 128 else 0),
                # Path 4: Light Binary
                img3x.point(lambda p: 255 if p > 180 else 0)
            ]

            best_code = None
            for p_idx, p_img in enumerate(paths):
                # Try both normal and inverted for each path
                for inverted in [False, True]:
                    final_img = ImageOps.invert(p_img) if inverted else p_img
                    buf = io.BytesIO()
                    final_img.save(buf, format='PNG')
                    
                    results = reader.readtext(buf.getvalue(), allowlist='0123456789', detail=1)
                    all_digits = "".join(re.findall(r'\d', "".join(r[1] for r in results)))
                    
                    if len(all_digits) == 5:
                        best_code = all_digits
                        break
                if best_code: break
            
            if best_code:
                print(f"      [Captcha] Solved: {best_code}")
                return best_code

            print(f"      [Captcha] OCR failed to find 5 digits. Found: '{all_digits}'. Retrying...")
            # Trigger refresh for next attempt
            page.wait_for_timeout(1000)
            for r_sel in refresh_selectors:
                try:
                    btn = page.locator(r_sel).first
                    if btn.is_visible(timeout=500):
                        btn.click(force=True)
                        break
                except: continue
            
        except Exception as e:
            print(f"      [Captcha] Error: {e}")
    
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
            )
            page = context.new_page()
            if HAS_STEALTH and stealth_sync:
                stealth_sync(page)
            
            url = "https://iporesult.cdsc.com.np/"
            
            # Natural delay before starting
            print(f"  Preparing stealth session...")
            page.wait_for_timeout(random.randint(3000, 6000))

            print(f"Navigating to {url}...")
            page.goto(url, wait_until='networkidle', timeout=90000)
            
            # Check for WAF rejection
            body_text = page.inner_text("body")
            page_title = page.title()
            print(f"  Page Title: {page_title}")
            
            if "requested URL was rejected" in body_text or "Request Rejected" in body_text or "rejected" in page_title.lower():
                print(f"[CRITICAL] WAF blocked the request. Title: {page_title}.")
                # Save screenshot for debugging
                os.makedirs("screenshots", exist_ok=True)
                page.screenshot(path="screenshots/waf_block.png")
                return

            # Wait for Angular app to fully load
            print("  Waiting for Angular app to load...")
            page.wait_for_selector("ng-select, .ng-select-container", timeout=30000)
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

        for m in matches:
            # Find only accounts that haven't been checked for THIS specific company
            target_accounts = get_unchecked_accounts_for_company(m['db'])
            if not target_accounts:
                continue

            print(f"\n[Company] {m['cdsc']} (Checking {len(target_accounts)} accounts)")
            
            # Navigate once per company to avoid triggering WAF for every single account check
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
                page.wait_for_timeout(random.randint(2000, 4000))
            except: pass

            for account in target_accounts:
                username = account.get('MEROSHARE_USER')
                boid = account.get('BOID')
                if not boid: continue
                
                try:
                    print(f"   [{username}] Checking...")
                    
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
                    page.keyboard.press("Tab") # Lose focus to trigger captcha
                    
                    # Try solving captcha (up to 3 times per account check)
                    print(f"      Solving Captcha...")
                    need_reload = False
                    for cap_attempt in range(4):
                        cap = solve_captcha(page, reader)
                        if cap == "RELOAD":
                            need_reload = True
                            break
                        if not cap: continue
                        
                        # Use JS fill to bypass WAF iframe interception on input fields
                        page.evaluate(f"""() => {{
                            const el = document.querySelector('#captcha') || document.querySelector('#userCaptcha') || document.querySelector('input[name="captcha"]');
                            if (el) {{
                                el.value = '{cap}';
                                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                            }}
                        }}""")
                        page.wait_for_timeout(500)
                        
                        # Submit via smart_click which uses coordinate-based mouse click
                        smart_click("button:has-text('View Result')")
                            
                        page.wait_for_timeout(3000)
                        
                        res = page.evaluate("""
                            () => {
                                const b = document.body.innerText;
                                if (b.includes("Congratulations")) return "Allotted|" + b.split('Congratulations')[1].split('.')[0].strip();
                                if (b.includes("Sorry")) return "Not Allotted|Sorry, not allotted.";
                                if (b.includes("Invalid Captcha")) return "RETRY";
                                return "Pending|No result found.";
                            }
                        """)
                        
                        if res == "RETRY":
                            print(f"      [Captcha] Incorrect code. Retrying attempt {cap_attempt+1}...")
                            continue
                        
                        if res == "Pending|No result found.":
                            # Check for WAF rejection in sub-frame or page
                            if "rejected" in page.title().lower() or "Request Rejected" in page.content():
                                print("      [Check] WAF Blocked during check. Reloading page...")
                                need_reload = True
                                break
                            print(f"      [Check] No result found (possible timeout or site delay).")
                            continue

                        status, feedback = res.split("|")
                        print(f"      Result: {status}")
                        
                        if status != "Pending":
                            save_result_to_db(account, m['db'], status, feedback)
                            send_push_notification(account.get('TOKENS'), username, f"{m['cdsc']}: {status} - {feedback}")
                        break
                    
                    if need_reload:
                        # Break this account loop to reload and retry
                        page.goto(url, wait_until='networkidle')
                        page.wait_for_timeout(3000)
                        # Actually we should probably continue to re-enter BOID etc.
                        # The simplest way is to just let the loop continue and it will re-enter data
                        continue
                except Exception as e:
                    print(f"     Error for {username}: {e}")

    except Exception as e:
        print(f"Fatal Error in automation logic: {e}")

if __name__ == "__main__":
    run_status_check()
