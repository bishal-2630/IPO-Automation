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
    db_url = os.environ.get("DATABASE_URL")
    if not db_url: return []
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
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
    db_url = os.environ.get("DATABASE_URL")
    accounts = get_accounts()
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
        return [acc for acc in accounts if acc.get('ID') not in checked_ids]
    except: return accounts

def solve_captcha(page, reader, max_retries=3):
    import io
    for attempt in range(max_retries):
        try:
            captcha_img = page.locator("img[src*='Captcha']").first
            if not captcha_img.is_visible(timeout=5000):
                page.wait_for_timeout(2000)
                continue

            raw = captcha_img.screenshot()
            img = Image.open(io.BytesIO(raw)).convert('L')
            w, h = img.size
            img3x = img.resize((w * 3, h * 3), Image.Resampling.LANCZOS)
            
            # Multi-Path OCR Logic
            paths = [
                img3x.filter(ImageFilter.MedianFilter(size=3)),
                ImageEnhance.Contrast(img3x).enhance(2.5),
                img3x.point(lambda p: 255 if p > 128 else 0),
                img3x.point(lambda p: 255 if p > 180 else 0)
            ]

            best_code = None
            for p_img in paths:
                for inverted in [False, True]:
                    final_img = ImageOps.invert(p_img) if inverted else p_img
                    buf = io.BytesIO()
                    final_img.save(buf, format='PNG')
                    results = reader.readtext(buf.getvalue(), allowlist='0123456789', detail=0)
                    code = "".join(re.findall(r'\d', "".join(results)))
                    if len(code) == 5:
                        best_code = code
                        break
                if best_code: break
            
            if best_code:
                print(f"      [Captcha] Solved: {best_code}")
                return best_code
            
            print(f"      [Captcha] OCR failed. Retrying...")
            page.locator("button[title='Reload Captcha']").first.click(force=True)
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"      [Captcha] Error: {e}")
    return None

def run_status_check():
    print("--- IPO Result Check Version: 2026-05-14 V18 (Clean Revert) ---")
    companies = get_applied_companies()
    if not companies: return
    
    import easyocr
    reader = easyocr.Reader(['en'], gpu=False)

    with sync_playwright() as p:
        is_headless = os.getenv("HEADLESS", "true").lower() == "true"
        browser = p.chromium.launch(headless=is_headless, channel="chrome", args=['--no-sandbox'])
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        page = browser.new_page(user_agent=user_agent)
        
        try:
            print("Navigating to portal...")
            page.goto("https://iporesult.cdsc.com.np/", timeout=60000)
            
            print("  Waiting for dropdown...")
            page.wait_for_selector("ng-select", timeout=30000)
            
            # Dropdown logic
            page.locator("ng-select").first.click()
            page.wait_for_timeout(2000)
            all_options = page.evaluate("() => Array.from(document.querySelectorAll('.ng-option')).map(o => o.innerText.trim())")
            print(f"  Found {len(all_options)} companies.")

            def norm(n): return re.sub(r'\(.*?\)', '', n).lower().replace('limited', 'ltd').strip()
            
            for target in companies:
                matched = next((c for c in all_options if norm(target) in norm(c) or norm(c) in norm(target)), None)
                if not matched: continue
                
                accounts = get_unchecked_accounts_for_company(target)
                print(f"\n[Company] {matched} ({len(accounts)} accounts)")
                
                for acc in accounts:
                    print(f"   [{acc['MEROSHARE_USER']}] Checking...")
                    page.locator("ng-select").first.click()
                    page.keyboard.type(matched)
                    page.keyboard.press("Enter")
                    page.locator("input#boid").fill(acc['BOID'])
                    
                    for _ in range(3):
                        cap = solve_captcha(page, reader)
                        if not cap: continue
                        page.locator("#userCaptcha").first.fill(cap)
                        page.locator("button:has-text('View Result')").click()
                        page.wait_for_timeout(3000)
                        
                        res = page.evaluate("""() => {
                            const b = document.body.innerText;
                            if (b.includes("Congratulations")) return "Allotted";
                            if (b.includes("Sorry")) return "Not Allotted";
                            if (b.includes("Invalid Captcha")) return "RETRY";
                            if (b.includes("Not Found")) return "NotFound";
                            return "Pending";
                        }""")
                        
                        if res == "RETRY": continue
                        if res in ["Allotted", "Not Allotted", "NotFound"]:
                            status = "Not Allotted" if res == "NotFound" else res
                            print(f"      Result: {status}")
                            save_result_to_db(acc, target, status, "Checked automatically")
                            send_push_notification(acc.get('TOKENS'), acc['MEROSHARE_USER'], f"{matched}: {status}")
                            break
        except Exception as e:
            print(f"Fatal Error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    run_status_check()
