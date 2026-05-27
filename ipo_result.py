"""
ipo_result.py
-------------
Checks IPO allotment status on MeroShare dashboard for all active accounts.
"""
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
import os
import time
import datetime
import psycopg2
from main import login, check_allotment_results
from expiry_handler import handle_expired_account, detect_account_expiry

# Load environment variables
load_dotenv()

def get_accounts():
    db_url = os.getenv("DATABASE_URL")
    if not db_url: 
        print("DATABASE_URL not set.")
        return []
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
                "BANK_NAME": row['bank_name'],
                "EMAIL": row['email'],
                "owner_id": row['owner_id'],
                "TOKENS": tokens
            })
        cur.close()
        conn.close()
        return accounts
    except Exception as e:
        print(f"Error fetching accounts: {e}")
        return []

def run_status_check():
    print("--- IPO Result Check via MeroShare Dashboard ---")
    
    accounts = get_accounts()
    if not accounts:
        print("No active accounts found in database.")
        return

    print(f"Found {len(accounts)} active accounts to check.")

    with sync_playwright() as p:
        headless = os.environ.get("HEADLESS", "true").lower() != "false"
        browser = p.chromium.launch(
            headless=headless,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )

        for i, account in enumerate(accounts):
            username = account.get('MEROSHARE_USER')
            print(f"\n=============================================")
            print(f"Checking Account {i+1}/{len(accounts)}: {username}")
            print(f"=============================================")

            page = context.new_page()
            try:
                page.goto("https://meroshare.cdsc.com.np", timeout=60000)
                page.wait_for_timeout(3000)
                
                MAX_RETRIES = 3
                logged_in = False
                for attempt in range(1, MAX_RETRIES + 1):
                    login_result = login(page, username, account['MEROSHARE_PASS'], account['DP_NAME'])
                    if login_result is True:
                        logged_in = True
                        break
                    elif login_result == "EXPIRED":
                        print(f"[{username}] Password expired. Skipping check.")
                        break
                    elif login_result in ("DEMAT_EXPIRED", "MEROSHARE_EXPIRED"):
                        handle_expired_account(account, login_result)
                        break
                    else:
                        print(f"Login failed (Attempt {attempt}). Retrying...")
                        page.reload()
                        page.wait_for_load_state('networkidle')
                        time.sleep(2)

                if logged_in:
                    print(f"[{username}] Login OK. Checking allotment results...")
                    check_allotment_results(page, account)
                else:
                    print(f"[{username}] Skipping result check due to login failure.")

            except Exception as e:
                print(f"[{username}] Error processing account: {e}")
            finally:
                try: page.close()
                except: pass

        browser.close()
        print("\nIPO allotment check run completed.")

if __name__ == "__main__":
    run_status_check()
