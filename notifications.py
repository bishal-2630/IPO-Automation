"""
notifications.py
----------------
Email notification utilities for the IPO automation.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()


def send_email_notification(to_email, subject, message):
    """
    Sends an email notification via Gmail SMTP.
    Reads SENDER_EMAIL, SENDER_PASSWORD, SMTP_SERVER, SMTP_PORT from .env.
    Silently skips if credentials are missing or no recipient is given.
    """
    if not to_email:
        return

    # 1. Try Google Apps Script (Web API) first - Works on Hugging Face
    gmail_api_url = os.getenv("GMAIL_API_URL")
    if gmail_api_url:
        try:
            import requests
            response = requests.post(
                gmail_api_url,
                json={"to": to_email, "subject": subject, "body": message},
                timeout=10
            )
            if response.status_code == 200:
                print(f"✅ Email sent via Google Apps Script to {to_email}")
                return True
            else:
                print(f"❌ Google Apps Script Error: {response.text}")
        except Exception as e:
            print(f"❌ Google Apps Script Exception: {str(e)}")

    # 2. Fallback to SMTP
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER") or "smtp.gmail.com"
    smtp_port = int(os.getenv("SMTP_PORT") or 465)

    if not (sender_email and sender_password or gmail_api_url):
        print("Warning: Skipping email notification (No SENDER_EMAIL or GMAIL_API_URL found)")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = f"IPO Automation <{sender_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(message, "plain"))

        if sender_email and sender_password:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10)
            server.login(sender_email, sender_password)
            server.send_message(msg)
            server.quit()
            print(f"✅ Email sent via SMTP to {to_email}")
            return True
        return False
    except Exception as e:
        print(f"❌ SMTP Error: {str(e)}")
        return False


def send_push_notification(tokens, title, body):
    """
    Sends FCM Push Notification to list of tokens.
    """
    if not tokens:
        return

    try:
        import firebase_admin
        from firebase_admin import credentials, messaging

        if not firebase_admin._apps:
            # Look for config in default location
            cred_path = os.path.join(os.path.dirname(__file__), "config", "firebase_vcc.json")
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
            else:
                # Fallback: load from base64-encoded env variable (GitHub Actions)
                import base64, json
                b64 = os.environ.get("FIREBASE_CREDENTIALS_B64", "")
                if not b64:
                    print(f"Warning: Firebase credentials not found. Set FIREBASE_CREDENTIALS_B64 env var. Skipping push notification.")
                    return
                cred_json = json.loads(base64.b64decode(b64).decode())
                cred = credentials.Certificate(cred_json)
            firebase_admin.initialize_app(cred)

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
            tokens=tokens,
            android=android_config,
        )
        response = messaging.send_each_for_multicast(message)
        print(f"Push Notification Sent: {response.success_count} success, {response.failure_count} failure")
        return response
    except Exception as e:
        print(f"Warning: Failed to send push notification: {e}")


def broadcast_push_notification(title, body):
    """
    Fetches all unique FCM tokens from the database and sends a broadcast message.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not found. Cannot broadcast.")
        return

    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT token FROM automation_fcmtoken")
        tokens = [t[0] for t in cur.fetchall()]
        cur.close()
        conn.close()

        if tokens:
            print(f"Broadcasting to {len(tokens)} tokens...")
            return send_push_notification(tokens, title, body)
        else:
            print("No tokens found to broadcast.")
    except Exception as e:
        print(f"Error in broadcast: {e}")


def get_fcm_tokens_for_user(username, owner_id=None):
    """
    Fetches all FCM tokens for a user, using owner_id if provided, 
    or falling back to lookup by meroshare username.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return []
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # If owner_id is not provided, look it up from the account table
        if not owner_id and username:
            cur.execute("SELECT owner_id FROM automation_account WHERE meroshare_user = %s", (username,))
            row = cur.fetchone()
            if row:
                owner_id = row[0]
        
        if owner_id:
            cur.execute("SELECT token FROM automation_fcmtoken WHERE user_id = %s", (owner_id,))
            tokens = [r[0] for r in cur.fetchall()]
            cur.close()
            conn.close()
            return tokens
            
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error fetching FCM tokens for user {username}: {e}")
    return []

