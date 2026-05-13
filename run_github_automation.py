import os
import psycopg2
import datetime
import time
import re
from playwright.sync_api import sync_playwright
from main import login, apply_ipo, handle_password_reset
from expiry_handler import handle_expired_account

# ── Firebase setup ──────────────────────────────────────────────────
import firebase_admin
from firebase_admin import credentials, messaging

def _init_firebase():
    if not firebase_admin._apps:
        cred_path = os.path.join(os.path.dirname(__file__), "config", "firebase_vcc.json")
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
        else:
            import base64, json
            b64 = os.environ.get("FIREBASE_CREDENTIALS_B64", "")
            if not b64:
                print("  ⚠️  Firebase credentials not found. Skipping notifications.")
                return False
            cred_json = json.loads(base64.b64decode(b64).decode())
            cred = credentials.Certificate(cred_json)
        firebase_admin.initialize_app(cred)
    return True

def send_push_notification(fcm_tokens: list, title: str, body: str):
    if not fcm_tokens:
        return
    if not _init_firebase():
        return
    android_config = messaging.AndroidConfig(
        priority='high',
        notification=messaging.AndroidNotification(
            channel_id='high_importance_channel',
            sticky=True,
            default_vibrate_timings=True,
            default_sound=True,
        )
    )
    message = messaging.MulticastMessage(
        notification=messaging.Notification(title=title, body=body),
        tokens=fcm_tokens,
        android=android_config,
    )
    try:
        response = messaging.send_each_for_multicast(message)
        print(f"  FCM: {response.success_count} sent, {response.failure_count} failed.")
    except Exception as e:
        print(f"  FCM error: {e}")

# ── Database connection ─────────────────────────────────────────────
DB_URL = os.environ.get("DATABASE_URL")

# ── Encryption ─────────────────────────────────────────────────────
from cryptography.fernet import Fernet
_ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "").encode()

def decrypt(token: str) -> str:
    if not token:
        return token
    if not _ENCRYPTION_KEY:
        return token
    if not token.startswith('gAAAAA'):
        return token
    try:
        return Fernet(_ENCRYPTION_KEY).decrypt(token.encode()).decode()
    except Exception as e:
        print(f"  ⚠️  Decryption failed: {e}")
        return token

# ── Main automation ─────────────────────────────────────────────────

def run_automation():
    if not DB_URL:
        print("Error: DATABASE_URL not set.")
        return

    try:
        # 1. Fetch active accounts
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT a.id, a.meroshare_user, a.meroshare_pass, a.dp_name,
                   a.crn, a.tpin, a.bank_name, a.kitta, a.owner_id
            FROM automation_account a
            WHERE a.is_active = True;
        """)
        columns = [desc[0] for desc in cur.description]
        accounts = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()

        if not accounts:
            print("No active accounts found.")
            return

        print(f"Found {len(accounts)} active accounts. Starting automation...")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                permissions=['geolocation'],
                geolocation={'latitude': 27.7172, 'longitude': 85.3240}
            )

            for acc in accounts:
                print(f"\n{'='*50}\nProcessing: {acc['meroshare_user']}")
                notification_sent = False
                status = "Error"
                remark = "Unknown error"
                ipo_name = "Auto-Check"
                page = context.new_page()
                try:
                    decrypted_pass = decrypt(acc['meroshare_pass'])
                    if decrypted_pass.startswith('gAAAAA'):
                        print(f"  ⚠️  WARNING: Password for {acc['meroshare_user']} still looks ENCRYPTED. Check your ENCRYPTION_KEY.")
                    else:
                        print(f"  🔑 Password Decrypted. Length: {len(decrypted_pass)} chars.")

                    account_data = {
                        'MEROSHARE_USER': acc['meroshare_user'],
                        'MEROSHARE_PASS': decrypted_pass,
                        'DP_NAME': acc['dp_name'],
                        'CRN': acc['crn'],
                        'TPIN': acc['tpin'],
                        'BANK_NAME': acc['bank_name'],
                        'KITTA': str(acc['kitta']),
                    }

                    page.goto("https://meroshare.cdsc.com.np", timeout=60000)
                    login_result = login(page, account_data['MEROSHARE_USER'], account_data['MEROSHARE_PASS'], account_data['DP_NAME'])

                    if login_result is True:
                        print(f"  ✅ Login OK. Applying IPO...")
                        success, result_detail = apply_ipo(page, account_data)
                        if success:
                            status = "Success"
                            ipo_name = result_detail
                            remark = f"{ipo_name} applied successfully."
                        else:
                            status = "Failed"
                            remark = result_detail
                    elif login_result == "EXPIRED":
                        print(f"  [{acc['meroshare_user']}] Password expired. Handling reset...")
                        if handle_password_reset(page, account_data):
                            status = "Success"
                            remark = "Password reset successfully. Re-run required."
                        else:
                            status = "Failed"
                            remark = "Password expired and reset failed."
                    else:
                        print(f"  ❌ MeroShare Login failed for {acc['meroshare_user']}.")
                        status = "Failed"
                        remark = "MeroShare login failed"

                except Exception as e:
                    print(f"  ❌ Inner Exception: {e}")
                    remark = str(e)
                finally:
                    # 3. Final Logging and Notification
                    try:
                        conn = psycopg2.connect(DB_URL)
                        cur = conn.cursor()
                        if remark != "No ordinary shares found":
                            cur.execute("""
                                INSERT INTO automation_applicationlog
                                    (account_id, company_name, status, remark, timestamp, is_read, is_listed)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """, (acc['id'], ipo_name, status, remark, datetime.datetime.now(datetime.timezone.utc), False, False))
                            conn.commit()
                        else:
                            print(f"  ℹ️  Skipping database log for: {remark}")

                        if acc.get('owner_id') and status != "Error" and "No ordinary shares" not in remark and not notification_sent:
                            if ipo_name and ipo_name != "Auto-Check":
                                cur.execute("""
                                    SELECT COUNT(*) FROM automation_applicationlog l
                                    JOIN automation_account a ON l.account_id = a.id
                                    WHERE a.owner_id = %s AND l.company_name = %s AND l.status = 'Success'
                                """, (acc['owner_id'], ipo_name))
                                has_applied = cur.fetchone()[0] > 0

                                if not has_applied:
                                    cur.execute("SELECT token FROM automation_fcmtoken WHERE user_id = %s", (acc['owner_id'],))
                                    all_tokens = [row[0] for row in cur.fetchall()]
                                    send_push_notification(all_tokens, acc['meroshare_user'], f"{ipo_name or 'IPO'} - New IPO is available.")

                            cur.execute("SELECT token FROM automation_fcmtoken WHERE user_id = %s", (acc['owner_id'],))
                            tokens = [row[0] for row in cur.fetchall()]
                            send_push_notification(tokens, acc['meroshare_user'], f"{ipo_name or 'IPO'} - {'✅' if status=='Success' else '⚠️'} {status}: {remark}")
                            notification_sent = True

                        cur.close()
                        conn.close()
                    except Exception as fatal:
                        print(f"  ⚠️  Fatal Logging Error: {fatal}")

                    try: page.close()
                    except: pass

            browser.close()
        print("\nAutomation run completed.")

    except Exception as e:
        print(f"Global Error: {e}")

if __name__ == "__main__":
    run_automation()
