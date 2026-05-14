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
    from PIL import Image, ImageEnhance, ImageOps
except ImportError:
    pass

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

def solve_captcha(page, reader, max_retries=5):
    for attempt in range(max_retries):
        try:
            captcha_img = page.locator("img[src*='captcha'], .captcha-image img").first
            captcha_img.wait_for(state="visible", timeout=10000)
            captcha_bytes = captcha_img.screenshot()
            
            import io
            img = Image.open(io.BytesIO(captcha_bytes)).convert('L')
            enhancements = [
                ImageEnhance.Contrast(img).enhance(2.0),
                ImageOps.invert(img),
                ImageEnhance.Sharpness(img).enhance(3.0)
            ]
            possible_texts = []
            for e_img in enhancements:
                buf = io.BytesIO()
                e_img.save(buf, format='PNG')
                res = reader.readtext(buf.getvalue())
                if res:
                    text = "".join(re.findall(r'\d', res[0][1]))
                    if len(text) == 5: possible_texts.append(text)

            if possible_texts:
                final_text = max(set(possible_texts), key=possible_texts.count)
                print(f"      [Captcha] Solved: {final_text}")
                return final_text
            
            print(f"      [Captcha] Attempt {attempt+1} unclear. Refreshing...")
            refresh_btn = page.locator(".fa-refresh, button:has-text('Refresh')").first
            if refresh_btn.is_visible(): refresh_btn.click()
            else: page.reload()
            page.wait_for_timeout(2000)
        except: pass
    return None

def run_status_check():
    print("--- IPO Result Check Version: 2026-05-14 V17 (Smart Backlog) ---")
    
    # 1. Get companies that need checking
    unchecked_companies = get_applied_companies()
    if not unchecked_companies:
        print(" No unchecked IPO results found in database. Everything is up to date!")
        return

    import easyocr
    reader = easyocr.Reader(['en'], gpu=False)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        url = "https://iporesult.cdsc.com.np/"
        
        try:
            print(f"Navigating to {url}...")
            page.goto(url, wait_until='domcontentloaded')
            page.wait_for_timeout(3000)
            
            # Read all companies from CDSC dropdown
            page.wait_for_selector(".ng-select-container", timeout=30000)
            all_cdsc_companies = []
            for _ in range(3):
                page.locator(".ng-select-container").first.click()
                page.wait_for_timeout(1500)
                all_cdsc_companies = page.evaluate("() => Array.from(document.querySelectorAll('.ng-option')).map(o => o.innerText.trim()).filter(t => t.length > 5)")
                if all_cdsc_companies: break
                page.keyboard.press("Escape")
            
            if not all_cdsc_companies:
                print(" Could not read company list from CDSC portal.")
                return

            # Match unchecked companies with CDSC portal names
            def norm(n): return re.sub(r'\(.*?\)', '', n).lower().replace('limited', 'ltd').replace('ltd.', 'ltd').strip().lower()
            matches = []
            for c_name in all_cdsc_companies:
                c_norm = norm(c_name)
                for db_name in unchecked_companies:
                    db_norm = norm(db_name)
                    if c_norm in db_norm or db_norm in c_norm:
                        matches.append({'cdsc': c_name, 'db': db_name})
                        break
            
            if not matches:
                print(f" Found {len(unchecked_companies)} unchecked companies in DB, but none match the current CDSC results list.")
                return

            print(f"Starting smart check for {len(matches)} matched companies...")

            for m in matches:
                # Find only accounts that haven't been checked for THIS specific company
                target_accounts = get_unchecked_accounts_for_company(m['db'])
                if not target_accounts:
                    continue

                print(f"\n[Company] {m['cdsc']} (Checking {len(target_accounts)} accounts)")

                for account in target_accounts:
                    username = account.get('MEROSHARE_USER')
                    boid = account.get('BOID')
                    if not boid: continue
                    
                    try:
                        print(f"   [{username}] Checking...")
                        page.goto(url, wait_until='domcontentloaded')
                        page.wait_for_timeout(1500)
                        
                        # Selection with human-like typing
                        page.locator(".ng-select-container").first.click()
                        page.wait_for_timeout(500)
                        page.keyboard.type(m['cdsc'], delay=80)
                        page.wait_for_timeout(800)
                        page.keyboard.press("Enter")
                        
                        # BOID with human-like typing
                        page.locator("input#boid").click()
                        page.keyboard.type(boid, delay=100)
                        
                        # Try solving captcha (up to 5 times per account check)
                        for cap_attempt in range(5):
                            cap = solve_captcha(page, reader)
                            if not cap: continue
                            
                            page.locator("#captcha").click()
                            page.keyboard.press("Control+A")
                            page.keyboard.press("Backspace")
                            page.keyboard.type(cap, delay=120)
                            
                            # Coordination-based click to bypass WAF
                            btn = page.locator("button:has-text('View Result')").first
                            box = btn.bounding_box()
                            if box:
                                page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                            else:
                                btn.click()
                                
                            page.wait_for_timeout(2500)
                            
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
                            
                            status, feedback = res.split("|")
                            print(f"      Result: {status}")
                            
                            if status != "Pending":
                                save_result_to_db(account, m['db'], status, feedback)
                                send_push_notification(account.get('TOKENS'), username, f"{m['cdsc']}: {status} - {feedback}")
                            break
                    except Exception as e:
                        print(f"     Error for {username}: {e}")

        except Exception as e:
            print(f"Fatal Error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    run_status_check()
