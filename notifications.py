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

    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER") or "smtp.gmail.com"
    smtp_port = int(os.getenv("SMTP_PORT") or 587)

    if not (sender_email and sender_password):
        print("Warning: Skipping email notification (Sender credentials missing in .env)")
        return

    try:
        msg = MIMEMultipart()
        msg["From"] = f"IPO Automation <{sender_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(message, "plain"))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent successfully to {to_email}")
        return True
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
