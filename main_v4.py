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
import firebase_admin
from firebase_admin import credentials, messaging
from expiry_handler import (
    detect_account_expiry,
    check_account_expiry_warning,
    handle_expired_account,
)
# easyocr imported locally in run_status_check


# Silence playwright logs
logging.getLogger('playwright').setLevel(logging.ERROR)

# Load environment variables
load_dotenv()

MIN_BALANCE = 2000.0  # Minimum required balance to apply for IPO (Rs.)


def generate_new_password(length=12):
    """
    Generates a secure random password satisfying MeroShare requirements:
    - Uppercase, Lowercase, Number, and Special Character
    """
    alphabet = string.ascii_letters + string.digits + "@#$!%*?&"
    while True:
        password = ''.join(secrets.choice(alphabet) for i in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and sum(c.isdigit() for c in password) >= 1
                and any(c in "@#$!%*?&" for c in password)):
            return password

def update_local_account_password(username, new_password):
    """
    Updates the password for a specific user in the local accounts.json file.
    """
    if not os.path.exists("accounts.json"):
        return False

    try:
        with open("accounts.json", "r") as f:
            accounts = json.load(f)
        
        updated = False
        for acc in accounts:
            if acc.get("MEROSHARE_USER") == username:
                acc["MEROSHARE_PASS"] = new_password
                updated = True
        
        if updated:
            with open("accounts.json", "w") as f:
                json.dump(accounts, f, indent=4)
            print(f"Successfully updated local accounts.json for {username}")
            return True
    except Exception as e:
        print(f"Warning: Failed to update local accounts.json: {e}")
    return False

def update_remote_account_password(username, new_password):
    """
    Updates the password for a specific user in the remote database.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return False

    try:
        from cryptography.fernet import Fernet
        import psycopg2

        encryption_key = os.getenv("ENCRYPTION_KEY")
        if not encryption_key:
            print(f"Warning: ENCRYPTION_KEY missing. Cannot update DB for {username}")
            return False

        cipher = Fernet(encryption_key.encode())
        encrypted_pass = cipher.encrypt(new_password.encode()).decode()

        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            "UPDATE automation_account SET meroshare_pass = %s WHERE meroshare_user = %s",
            (encrypted_pass, username)
        )
        conn.commit()
        updated = cur.rowcount > 0
        cur.close()
        conn.close()

        if updated:
            print(f"Successfully updated remote database password for {username}")
            return True
    except Exception as e:
        print(f"Warning: Failed to update remote database for {username}: {e}")
    return False

def handle_password_reset(page, account):
    """
    Handles the password change process when an expiry is detected.
    """
    username = account['MEROSHARE_USER']
    old_password = account['MEROSHARE_PASS']
    new_password = generate_new_password()
    
    print(f"[{username}] Starting automatic password reset...")
    try:
        # MeroShare change password page usually has these fields
        # Using flexible selectors and Angular-aware typing
        page.wait_for_selector("input[placeholder='Old Password'], #oldPassword", state="visible", timeout=15000)
        
        # Old Password
        page.locator("input[placeholder='Old Password'], #oldPassword").first.click()
        page.locator("input[placeholder='Old Password'], #oldPassword").first.fill("")
        page.locator("input[placeholder='Old Password'], #oldPassword").first.type(old_password, delay=80)
        
        # New Password
        page.locator("input[placeholder='New Password'], #newPassword").first.click()
        page.locator("input[placeholder='New Password'], #newPassword").first.fill("")
        page.locator("input[placeholder='New Password'], #newPassword").first.type(new_password, delay=80)
        
        # Confirm Password
        page.locator("input[placeholder='Confirm Password'], #confirmPassword").first.click()
        page.locator("input[placeholder='Confirm Password'], #confirmPassword").first.fill("")
        page.locator("input[placeholder='Confirm Password'], #confirmPassword").first.type(new_password, delay=80)
        
        page.wait_for_timeout(1000)
        page.click("button:has-text('Change'), button:has-text('Update')")
        
        # Wait for toast message or redirection
        try:
            toast = page.wait_for_selector(".toast-success, .toast-message", timeout=10000)
            toast_text = toast.inner_text().strip()
            print(f"[{username}] Reset Result: {toast_text}")
            
            if "success" in toast_text.lower() or "successfully" in toast_text.lower():
                # Notify User (FCM Only as per preference)
                msg = f"Password has been changed successfully. Your new password is {new_password}"
                send_push_notification(account.get('TOKENS'), "Account", f"Password Reset - {username} - {msg}")
                
                # Update records
                update_local_account_password(username, new_password)
                update_remote_account_password(username, new_password)

                # Ensure we navigate to dashboard before returning
                print(f"[{username}] Reset successful. Navigating to dashboard...")
                page.goto("https://meroshare.cdsc.com.np/#/dashboard")
                page.wait_for_load_state('networkidle')
                return True
            else:
                print(f"[{username}] Password reset reported failure: {toast_text}")
        except:
             # Fallback check: if we are no longer on change-password page and see dashboard
             page.wait_for_timeout(3000)
             if "change-password" not in page.url and (page.locator("text=My ASBA").first.is_visible() or "dashboard" in page.url):
                 print(f"[{username}] Password reset appears successful (redirected).")
                 # Notify User (FCM Only as per preference)
                 msg = f"Password has been changed successfully. Your new password is {new_password}"
                 send_push_notification(account.get('TOKENS'), "Account", f"Password Reset - {username} - {msg}")
                 
                 # Update records
                 update_local_account_password(username, new_password)
                 update_remote_account_password(username, new_password)

                 # Ensure we navigate to dashboard before returning
                 page.goto("https://meroshare.cdsc.com.np/#/dashboard")
                 page.wait_for_load_state('networkidle')
                 return True
                 
    except Exception as e:
        print(f"[{username}] Error during password reset: {e}")
        try:
            page.screenshot(path=f"debug_reset_fail_{username}.png")
        except: pass
        
    return False
def fill_and_submit_form(page, account, company_name=None):
    """
    Fills the IPO application form and submits it with TPIN.
    Can be called from initial application or status check (Edit mode).
    """
    username = account['MEROSHARE_USER']
    tpin = account.get('TPIN')
    bank_name = account.get('BANK_NAME')

    print(f"[{username}] Filling application form...")
    # Wait for the form to actually be visible
    page.wait_for_timeout(2000)

    print(f"Selecting Bank: {bank_name}...")
    try:
        page.wait_for_selector("#selectBank", timeout=20000)

        # BRUTE FORCE JS SELECTION
        selected_bank = page.evaluate(f"""
            (bankName) => {{
                const select = document.querySelector('#selectBank');
                if (!select) return "NOT_FOUND";
                const options = Array.from(select.options);
                const target = bankName.toLowerCase().trim();
                const match = options.find(o => o.innerText.toLowerCase().trim().includes(target));
                if (match) {{
                    select.value = match.value;
                    select.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    select.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    return match.innerText.trim();
                }}
                return "FAIL: " + options.map(o => o.innerText.trim()).join(', ');
            }}
        """, bank_name)

        if "FAIL" in selected_bank:
             raise Exception(f"Bank selection failed: {selected_bank}")
        print(f"[{username}] Selected Bank: {selected_bank}")

        page.wait_for_timeout(1500) # Wait for Branch to populate

        print(f"[{username}] Selecting Branch...")
        selected_branch = page.evaluate("""
            () => {
                const el = document.querySelector('#selectBranch');
                if (!el) return "NOT_FOUND";
                if (el.tagName === 'SELECT') {
                    const options = Array.from(el.options);
                    const validOptions = options.filter(o => !o.innerText.toLowerCase().includes('choose') && o.innerText.trim() !== '');
                    if (validOptions.length > 0) {
                        el.value = validOptions[0].value;
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        return "SELECT: " + validOptions[0].innerText.trim();
                    }
                    return "SELECT: NONE_FOUND";
                }
                if (el.tagName === 'INPUT') return "INPUT_FIELD";
                return "UNKNOWN_TAG: " + el.tagName;
            }
        """)

        if selected_branch == "INPUT_FIELD":
             page.click("#selectBranch")
             page.wait_for_timeout(500)
             page.keyboard.press("ArrowDown")
             page.wait_for_timeout(500)
             page.keyboard.press("Enter")
             print(f"[{username}] Selected Branch via keyboard interaction")
        elif "NOT_FOUND" in selected_branch or "NONE_FOUND" in selected_branch:
             print(f"[{username}] Branch selection auto-skipped: {selected_branch}")
        else:
             print(f"[{username}] {selected_branch}")

        page.wait_for_timeout(1000)

        print(f"[{username}] Selecting Bank Account Number...")
        page.wait_for_selector("#accountNumber", timeout=10000)
        account_selected = page.evaluate("""
            () => {
                const select = document.querySelector('#accountNumber');
                if (!select) return "NOT_FOUND";
                const options = Array.from(select.options);
                const validOptions = options.filter(o => o.innerText.trim() !== '' && !o.innerText.toLowerCase().includes('choose'));
                if (validOptions.length > 0) {
                    select.value = validOptions[0].value;
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    select.dispatchEvent(new Event('input', { bubbles: true }));
                    return validOptions[0].innerText.trim();
                }
                return "NONE_FOUND";
            }
        """)
        print(f"[{username}] Selected Account: {account_selected}")

    except Exception as e:
        print(f"[{username}] Bank/Branch/Account selection failed. Diagnostics:")
        page.screenshot(path=f"debug_bank_fail_{username}.png")
        raise e

    print(f"[{username}] Filling Kitta and CRN with validation triggers...")
    detected_min_kitta = 10
    if not company_name:
        company_name = "Unknown"
        try:
            company_elem = page.locator(".company-name, .issue-name, h4.modal-title").first
            if company_elem.is_visible():
                company_name = company_elem.inner_text().strip()
                print(f"[{username}] Company (Detected): {company_name}")
        except: pass

    try:
        min_kitta_value = page.evaluate(r"""
            () => {
                const labels = Array.from(document.querySelectorAll('label, span, td, th, div'));
                const minLabel = labels.find(el => {
                    const text = el.innerText.toLowerCase().trim();
                    return text === 'minimum unit' || text === 'minimum quantity' || text === 'min unit' || 
                           text.includes('minimum unit:') || text.includes('minimum quantity:');
                });
                if (minLabel) {
                    let parent = minLabel.parentElement;
                    let textContent = parent.innerText;
                    let matches = textContent.match(/\d+/g);
                    if (matches && matches.length > 0) return parseInt(matches[matches.length - 1]);
                    if (minLabel.nextElementSibling) {
                        const nextText = minLabel.nextElementSibling.innerText;
                        const matchNext = nextText.match(/\d+/);
                        if (matchNext) return parseInt(matchNext[0]);
                    }
                }
                return null;
            }
        """)
        if min_kitta_value:
            detected_min_kitta = int(min_kitta_value)
            print(f"[{username}] Detected Minimum Kitta (on page): {detected_min_kitta}")

        if "RELIANCE" in company_name.upper() or "NIFRA" in company_name.upper():
            if detected_min_kitta < 50:
                 detected_min_kitta = max(detected_min_kitta, 50)
    except Exception as e:
        print(f"Warning: [{username}] Could not detect minimum kitta: {e}")

    user_kitta = int(account.get('KITTA', '10'))
    final_kitta = max(user_kitta, detected_min_kitta)
    if final_kitta != user_kitta:
        print(f"[{username}] Adjusting Kitta from {user_kitta} to {final_kitta} based on requirements.")

    kitta_loc = page.locator("#appliedKitta")
    kitta_loc.clear()
    kitta_loc.type(str(final_kitta))
    page.keyboard.press("Tab")
    page.wait_for_timeout(500)

    crn_loc = page.locator("#crnNumber")
    crn_loc.clear()
    crn_loc.type(account['CRN'])
    page.keyboard.press("Tab")
    page.wait_for_timeout(500)

    print(f"[{username}] Waiting for amount calculation...")
    try:
        page.wait_for_function("document.querySelector('#amount') && document.querySelector('#amount').value !== '' && document.querySelector('#amount').value !== '0'", timeout=5000)
        amount = page.locator("#amount").input_value()
        print(f"[{username}] Calculated Amount: {amount}")
    except:
        print(f"Warning: [{username}] Amount was not calculated.")

    page.uncheck("#disclaimer")
    page.wait_for_timeout(300)
    page.check("#disclaimer")
    page.mouse.click(0, 0)
    page.wait_for_timeout(1000)

    print(f"Form filled. Checking Proceed button state...")
    proceed_btn = page.locator("button:has-text('Proceed')")
    try:
        page.wait_for_function("document.querySelector('button:has-text(\"Proceed\")').disabled === false", timeout=5000)
    except: pass
    proceed_btn.click()

    if tpin:
        print(f"[{username}] Entering TPIN...")
        page.wait_for_selector("#transactionPIN", timeout=10000)
        page.locator("#transactionPIN").click()
        page.locator("#transactionPIN").clear()
        page.locator("#transactionPIN").type(tpin)
        page.keyboard.press("Tab")
        page.wait_for_timeout(1000)
        print(f"[{username}] Submitting application...")

        apply_btn = page.locator(".modal-footer button:has-text('Apply')").first
        if not apply_btn.is_visible():
            apply_btn = page.locator("button:has-text('Apply')").first
        apply_btn.click()

        try:
            toast = page.wait_for_selector(".toast-success, .toast-message", timeout=10000)
            toast_text = toast.inner_text().strip()
            print(f"[{username}] Result: {toast_text}")

            if "success" in toast_text.lower() or "successfully" in toast_text.lower():
                print(f"Application SUCCESS!")
                msg = f"✅ Success: {company_name} has been applied successfully."
                subj = f"[MeroShare] Success: {company_name}"
                send_email_notification(account.get('EMAIL'), subj, f"Hi {username},\n\n{msg}")
                send_push_notification(account.get('TOKENS'), username, msg)
                return True, company_name
            else:
                error_msg = toast_text
                if "balance" in error_msg.lower() or "insufficient" in error_msg.lower():
                    msg = f"⚠️ Failed: Insufficient balance for {company_name}. Please topup."
                    subj = f"[MeroShare] Failed: {company_name}"
                    send_email_notification(account.get('EMAIL'), subj, f"Hi {username},\n\n{msg}")
                    send_push_notification(account.get('TOKENS'), username, msg)
                else:
                    msg = f"❌ Failed: {error_msg} for {company_name}"
                    subj = f"[MeroShare] Failed: {company_name}"
                    send_email_notification(account.get('EMAIL'), subj, f"Hi {username},\n\n{msg}")
                    send_push_notification(account.get('TOKENS'), username, msg)
                return False, error_msg
        except:
             if not page.is_visible("#transactionPIN"):
                 print(f"[{username}] Application submitted successfully (modal closed).")
                 return True, company_name
             else:
                 print(f"Error: [{username}] Application submission failed (modal still open).")
                 return False, "Application modal still open"
    else:
        print(f"Warning: [{username}] No TPIN provided. Skipping submission.")
        return False, "No TPIN"


def login(page, username, password, dp_name):
    """
    Attempts to login a specific user.
    """
    print(f"Logging in as {username}...")

    # Wait for the login page to fully load before interacting
    page.wait_for_load_state('networkidle', timeout=30000)
    
    # Wait for splash screen / loading overlay to disappear
    try:
        print(f"  [{username}] Checking for splash screen...")
        page.wait_for_selector(".splash, #splash, .loader", state="hidden", timeout=10000)
    except: pass

    # Verify we are on the login page or try to navigate there
    if "/#/login" not in page.url and "meroshare.cdsc.com.np" in page.url:
         print(f"  [{username}] Not on login hash ({page.url}). Forcing navigation...")
         page.goto("https://meroshare.cdsc.com.np/#/login", wait_until="networkidle")
         page.wait_for_timeout(2000)
    
    page.wait_for_timeout(1000)

    print(f"Selecting DP: {dp_name}...")
    dp_target = dp_name.lower().strip()

    # Since MeroShare uses an Angular wrapper around Select2 (<select2>), 
    # programmatic JS modifications bypass the Angular ngModel binding, 
    # leaving the form invalid. We MUST interact via the UI.
    try:
        # 1. Click the select2 container to open the dropdown
        # Try a few selectors and use a retry loop
        dp_selectors = [
            "select2 span.select2-selection",
            "span.select2-selection",
            ".select2-selection--single",
            "[name='selectBank'] + span.select2-selection",
            ".select2-selection"
        ]
        
        target_dp_sel = ", ".join(dp_selectors)
        clicked = False
        for attempt in range(3):
            try:
                print(f"  [DP] Opening dropdown (Attempt {attempt+1})...")
                dp_elem = page.locator(target_dp_sel).first
                dp_elem.wait_for(state="visible", timeout=15000)
                dp_elem.click(force=True)
                page.wait_for_timeout(1000)
                
                # Check if search box is now visible
                search_box = page.locator(".select2-search__field, .select2-search input").first
                if search_box.is_visible(timeout=5000):
                    clicked = True
                    break
            except Exception as e:
                print(f"  [DP] Attempt {attempt+1} failed: {e}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(1500)

        if not clicked:
            print("  [DP] Standard clicks failed. Attempting JS-based force open...")
            page.evaluate(f"""
                (sel) => {{
                    const el = document.querySelector(sel);
                    if (el) {{
                        el.click();
                        // Trigger Select2 internal events if possible
                        const $el = window.jQuery ? window.jQuery(el) : null;
                        if ($el && $el.data('select2')) {{
                            $el.select2('open');
                        }}
                    }}
                }}
            """, target_dp_sel)
            page.wait_for_timeout(2000)
            # Check for search box one last time
            search_box = page.locator(".select2-search__field, .select2-search input").first
            search_box_visible = False
            try:
                if search_box.is_visible():
                    search_box_visible = True
                else:
                    search_box.wait_for(state="visible", timeout=3000)
                    search_box_visible = True
            except: pass

            if not search_box_visible:
                 print("  [DP] JS force open also failed. Trying keyboard trigger...")
                 page.locator(target_dp_sel).first.focus()
                 page.keyboard.press("Enter")
                 page.wait_for_timeout(1000)

        # 2. Type a shorter prefix of the DP name into the search box for better results
        # e.g., "NIC ASIA BANK LTD." -> "NIC"
        dp_prefix = dp_name.split()[0] if dp_name.split() else dp_name
        search_box = page.locator(".select2-search__field, .select2-search input").first
        search_box.wait_for(state="visible", timeout=5000)
        search_box.fill(dp_prefix)
        page.wait_for_timeout(2000)
        
        # 3. Find the best match in the results
        success = page.evaluate(rf"""
            (targetName) => {{
                const options = Array.from(document.querySelectorAll('.select2-results__option'));
                if (options.length === 0) return false;
                
                const noResults = options.find(o => o.innerText.includes('No results found'));
                if (noResults) return "NO_RESULTS";

                const clean = (s) => s.toLowerCase().replace(/[^a-z0-9\s]/g, '').replace(/\b(ltd|limited|corp|inc|plc|bank)\b/g, '').trim();
                const targetClean = clean(targetName);
                const targetWords = targetClean.split(/\s+/).filter(w => w.length > 1);

                // Strategy 1: Look for most relevant match (intersection of words)
                let bestMatch = null;
                let maxMatches = -1;

                for (const o of options) {{
                    const text = clean(o.innerText);
                    const matchCount = targetWords.filter(w => text.includes(w)).length;
                    if (matchCount > maxMatches && matchCount > 0) {{
                        maxMatches = matchCount;
                        bestMatch = o;
                    }}
                }}

                if (bestMatch) {{
                    const selectedName = bestMatch.innerText;
                    bestMatch.click();
                    return "SUCCESS:" + selectedName;
                }}
                return false;
            }}
        """, dp_name)
        
        if success and success.startswith("SUCCESS:"):
            selected_name = success.split("SUCCESS:")[1]
            print(f"  [DP] Selected: {selected_name}")
        elif success == "NO_RESULTS":
            print(f"  ❌ No results found for DP: {dp_name}. Clearing overlay...")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            page.keyboard.press("Escape") # Second escape for safety
        elif not success or not success.startswith("SUCCESS:"): # Modified condition
            print(f"  Warning: Specific match for '{dp_name}' not found. Clicking first result...")
            first_option = page.locator(".select2-results__option--highlighted, .select2-results__option").first
            if first_option.is_visible() and "No results found" not in first_option.inner_text():
                first_option.click()
            else:
                print(f"  ❌ No valid results found for DP: {dp_name}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                page.keyboard.press("Escape")
                
        print(f"  DP selection process completed.")
    except Exception as e:
        print(f"  Warning: UI DP selection failed: {e}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.screenshot(path=f"debug_login_dp_{username}.png")

    page.wait_for_timeout(1000)

    # Ensure no Select2 overlays are blocking the input
    try:
        if page.locator(".select2-container--open").is_visible():
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except: pass

    try:
        # Use a more flexible selector for username (ID, Name, or Placeholder)
        username_selectors = ["#username", "#txtUserName", "input[name='username']", "input[placeholder='Username']"]
        found = False
        for selector in username_selectors:
            # Ensure it's the visible one (MeroShare sometimes has hidden inputs)
            loc = page.locator(selector).first
            if loc.is_visible():
                print(f"  Typing username into {selector}...")
                # Use force=True for click if something is partially overlapping
                loc.click(force=True)
                page.wait_for_timeout(300)
                loc.fill("")
                loc.type(username, delay=100)
                found = True
                break
        
        if not found:
            # If none found immediately, wait longer for the primary one
            print(f"  Attempting wait for primary username selector...")
            page.wait_for_selector("#username", state="visible", timeout=15000)
            page.locator("#username").first.click()
            page.wait_for_timeout(300)
            page.locator("#username").first.fill("")
            page.locator("#username").first.type(username, delay=100)
        
        # Small pause before password
        page.wait_for_timeout(1000)
        
        # Robust password selection
        password_selectors = ["#password", "#txtPassword", "input[name='password']", "input[placeholder='Password']"]
        p_found = False
        for selector in password_selectors:
            # Check if element is visible and attached
            loc = page.locator(selector).filter(has_text=re.compile(r".*", re.IGNORECASE)) # Dummy filter to force state check
            if loc.first.is_visible():
                print(f"  Typing password into {selector}...")
                loc.first.click()
                page.wait_for_timeout(300)
                loc.first.fill("")
                loc.first.type(password, delay=100)
                p_found = True
                break
        
        if not p_found:
            print(f"  Attempting wait for primary password selector...")
            page.wait_for_selector("#password", state="visible", timeout=10000)
            page.locator("#password").first.click()
            page.wait_for_timeout(300)
            page.locator("#password").first.fill("")
            page.locator("#password").first.type(password, delay=100)
            
    except Exception as e:
        print(f"[{username}] ❌ Login Interaction Failed: {e}")
        try:
            page.screenshot(path=f"debug_login_fields_{username}.png")
        except: pass
        return False

    # Small delay to let Angular validation settle
    page.wait_for_timeout(1500)

    # Aggressive login button handling
    print(f"Clicking Login button for {username}...")
    login_btn_sel = "button[type='submit'], .btn-login, button:has-text('Login'), .sign-in"
    login_btn = page.locator(login_btn_sel).first
    
    try:
        # Trigger Angular validation by clicking/typing dummy stuff
        if login_btn.is_visible() and login_btn.is_disabled():
            print(f"[{username}] ⚠️ Login button still disabled. Triggering validation...")
            page.locator("#password").first.focus()
            page.keyboard.press("Space")
            page.keyboard.press("Backspace")
            page.wait_for_timeout(1000)
            
        if login_btn.is_visible() and login_btn.is_disabled():
            print(f"[{username}] ⚠️ Still disabled. Forcing aggressive enable...")
            page.evaluate(f"""
                (sel) => {{
                    const buttons = Array.from(document.querySelectorAll('button, input[type="submit"]'));
                    const btn = buttons.find(b => 
                        b.type === 'submit' || 
                        b.classList.contains('sign-in') || 
                        (b.textContent && b.textContent.trim().toLowerCase() === 'login')
                    );
                    if (btn) {{
                        btn.disabled = false;
                        btn.removeAttribute('disabled');
                        btn.classList.remove('disabled');
                        btn.classList.remove('ng-disabled');
                        btn.style.opacity = '1';
                        btn.style.pointerEvents = 'auto';
                    }}
                }}
            """)
            page.wait_for_timeout(500)
    except: pass

    page.click(login_btn_sel, force=True)
    
    # Wait for navigation/dashboard
    try:
        page.wait_for_load_state('networkidle', timeout=15000)
        page.wait_for_timeout(2000) 
        
        # Check for Password Expiry Redirect
        if "change-password" in page.url or "changepassword" in page.url or page.locator("text=Change Password").first.is_visible():
            print(f"[{username}] ⚠️ Password Expired / Change required detected.")
            return "EXPIRED"

        # Check for DEMAT or MeroShare account expiry
        expiry_result = detect_account_expiry(page, username)
        if expiry_result:
            return expiry_result

        if page.locator("text=My ASBA").is_visible():
            return True
        elif page.locator(".toast-message").is_visible():
            error_msg = page.locator(".toast-message").inner_text()
            print(f"⚠️ Login Failed: {error_msg}")
            
            # Additional debug info: check what's in the fields
            try:
                actual_user = page.locator("#username").input_value()
                if actual_user != username:
                    print(f"  [Debug] Username field mismatch! Page has '{actual_user}', expected '{username}'")
            except: pass
            
            try:
                # Ensure directory exists on the user's side
                os.makedirs("screenshots", exist_ok=True)
                page.wait_for_timeout(500)
                path = f"screenshots/login_fail_{username}_{int(time.time())}.png"
                page.screenshot(path=path)
                print(f"  [Debug] Screenshot saved to {path}")
            except Exception as e: 
                print(f"  [Debug] Failed to save screenshot: {e}")
            return False
        else:
             if "dashboard" in page.url or "dashboard" in page.content().lower():
                 return True
             return False
    except Exception as e:
        print(f"Warning: Login Check Error: {e}")
        return False

def apply_ipo(page, account):
    """
    Applies for IPO for a logged-in session.
    """
    username = account['MEROSHARE_USER']
    print(f"[{username}] Navigating to My ASBA...")
    asba_selectors = [".nav-link:has-text('My ASBA')", "a:has-text('My ASBA')", ".ms-icon-my-asba", "[routerlink='/asba']"]
    target_asba = ", ".join(asba_selectors)
    page.wait_for_selector(target_asba, state="visible", timeout=30000)
    page.click(target_asba)

    try:
        page.wait_for_selector("a:has-text('Apply for Issue')", timeout=10000)
        page.click("a:has-text('Apply for Issue')")
        page.wait_for_load_state('networkidle')
    except Exception as e:
        print(f"Warning: [{username}] Could not find 'Apply for Issue' tab: {e}")

    print(f"[{username}] Waiting for IPO list to load...")
    page.wait_for_timeout(5000) # Increased wait for MeroShare's slow table

    # Try up to 2 times with a refresh in between if nothing found
    for attempt in range(2):
        clicked_ipo = page.evaluate(r"""
            () => {
                // Find all possible row containers
                const containers = Array.from(document.querySelectorAll('tr, .row, .list-item, .entry-list-item'));
                
                for (const row of containers) {
                    const text = row.innerText.toLowerCase();
                    // Find any clickable 'Apply' element (button or link)
                    const clickable = row.querySelector('button, a.btn, a[class*="btn"]');
                    if (!clickable) continue;
                    
                    const label = clickable.innerText.toLowerCase().trim();
                    if (!label.includes('apply')) continue;

                    // Keywords for Ordinary Shares
                    const isOrdinary = text.includes('ordinary') || text.includes('equity') || text.includes('public issue');
                    
                    // Keywords to exclude
                    const isExclude = text.includes('debenture') || 
                                      text.includes('bond') || 
                                      text.includes('mutual fund') || 
                                      text.includes('preference') ||
                                      text.includes('right') ||
                                      text.includes('promoter');
                    
                    if (isOrdinary && !isExclude) {
                        // Extract company name (first line)
                        const rawName = row.innerText.split('\n')[0].trim();
                        // Clean up if it grabbed headers
                        if (rawName.toLowerCase().includes('company') || rawName.length < 3) continue;
                        
                        clickable.click();
                        return rawName;
                    }
                }
                return null;
            }
        """)

        if clicked_ipo:
            break
        
        if attempt == 0:
            print(f"[{username}] No 'Ordinary Shares' found on first pass. Refreshing list...")
            page.reload(wait_until='networkidle')
            page.wait_for_timeout(4000)

    if clicked_ipo:
        print(f"[{username}] Targeted IPO: {clicked_ipo}")

        return fill_and_submit_form(page, account, company_name=clicked_ipo)
    else:
        print(f"[{username}] No 'Ordinary Shares' found to apply. Skipping silently.")
        return False, "No ordinary shares found"

def get_accounts():
    """
    Retrieves accounts from environment variable (JSON), PostgreSQL database, or local file.
    """
    accounts = []

    # 1. Try Remote Database (PostgreSQL)
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        print("Connecting to remote database to fetch accounts...")
        try:
            import psycopg2
            from cryptography.fernet import Fernet
            
            encryption_key = os.getenv("ENCRYPTION_KEY")
            cipher = None
            if encryption_key:
                try:
                    cipher = Fernet(encryption_key.encode())
                except Exception as e:
                    print(f"Warning: Invalid ENCRYPTION_KEY: {e}")

            def decrypt_val(token):
                if not token or not cipher:
                    return token
                try:
                    return cipher.decrypt(token.encode()).decode()
                except:
                    return token

            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            # Fetch accounts and join with auth_user to get the email
            cur.execute("""
                SELECT a.id, a.meroshare_user, a.meroshare_pass, a.boid, a.dp_name, a.crn, a.tpin, a.bank_name, a.kitta, u.email, a.owner_id
                FROM automation_account a
                LEFT JOIN auth_user u ON a.owner_id = u.id
                WHERE a.is_active = True;
            """)
            
            columns = [desc[0] for desc in cur.description]
            db_rows = [dict(zip(columns, row)) for row in cur.fetchall()]
            
            for row in db_rows:
                # Fetch FCM Tokens for this user
                tokens = []
                if row.get('owner_id'):
                    cur.execute("SELECT token FROM automation_fcmtoken WHERE user_id = %s", (row['owner_id'],))
                    tokens = [t[0] for t in cur.fetchall()]

                accounts.append({
                    "ID": row['id'],
                    "MEROSHARE_USER": row['meroshare_user'],
                    "MEROSHARE_PASS": decrypt_val(row['meroshare_pass']),
                    "DP_NAME": row['dp_name'],
                    "CRN": row['crn'],
                    "TPIN": row['tpin'],
                    "BANK_NAME": row['bank_name'],
                    "KITTA": str(row['kitta']),
                    "EMAIL": row.get('email'),
                    "TOKENS": tokens,
                    "BOID": row.get('boid'),
                    "BANK_CODE": row.get('bank_code'),
                    "BANK_PHONE": row.get('phone_number'),
                    "BANK_PASS": decrypt_val(row.get('bank_password'))
                })
            
            cur.close()
            conn.close()
            if accounts:
                print(f"Successfully loaded {len(accounts)} active account(s) from database.")
                return accounts
        except ImportError:
            print("Warning: psycopg2 or cryptography not installed. Skipping database fetch.")
        except Exception as e:
            print(f"Warning: Failed to fetch accounts from database: {e}")

    # 2. Try environment variable (JSON)
    accounts_env = os.getenv("ACCOUNTS_JSON")
    if accounts_env:
        try:
            accounts = json.loads(accounts_env)
        except json.JSONDecodeError:
            print("Error: Error decoding ACCOUNTS_JSON environment variable.")

    if not accounts and os.path.exists("accounts.json"):
        try:
            with open("accounts.json", "r") as f:
                accounts = json.load(f)
        except json.JSONDecodeError:
            print("Error: Error decoding local accounts.json file.")

    if not accounts and os.getenv("MEROSHARE_USER"):
        accounts = [{
            "MEROSHARE_USER": os.getenv("MEROSHARE_USER"),
            "MEROSHARE_PASS": os.getenv("MEROSHARE_PASS"),
            "BOID": os.getenv("BOID"),
            "DP_NAME": os.getenv("DP_NAME"),
            "CRN": os.getenv("CRN"),
            "TPIN": os.getenv("TPIN"),
            "BANK_NAME": os.getenv("BANK_NAME"),
            "KITTA": os.getenv("KITTA", "10")
        }]

    return accounts

def check_status(page, account):
    """
    Refined Status Watchdog:
    1. Scrapes available IPO names from 'Apply for Issue'.
    2. Only checks the status for those specific names in 'Application Report'.
    """
    username = account['MEROSHARE_USER']
    print(f"[{username}] Starting targeted Status Watchdog...")

    try:
        # Step 1: Collect names of available IPOs from 'Apply for Issue'
        page.wait_for_selector(".nav-link:has-text('My ASBA')", timeout=15000)
        page.click(".nav-link:has-text('My ASBA')")
        page.wait_for_timeout(2000)

        page.wait_for_selector("a:has-text('Apply for Issue')", timeout=10000)
        page.click("a:has-text('Apply for Issue')")
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(3000)

        active_ipo_names = page.evaluate("""
            () => {
                const items = Array.from(document.querySelectorAll('.company-name, .issue-name, h4, .d-flex b, strong'));
                const names = [];
                for (const el of items) {
                    let text = el.innerText.trim();
                    if (text.length > 5) {
                        // Clean up: Take only the first part before any '-' or newline
                        // This usually captures the core "Super Khudi Hydropower Limited"
                        const cleanName = text.split(/[\\n-]/)[0].trim();
                        if (cleanName.length > 5) names.push(cleanName);
                    }
                }
                return [...new Set(names)];
            }
        """)

        if not active_ipo_names:
            print(f"[{username}] No active IPOs found in 'Apply for Issue'. Skipping status check.")
            return

        print(f"[{username}] Monitoring status for: {', '.join(active_ipo_names)}")

        # Step 2: Switch to 'Application Report'
        report_link_selector = "a:has-text('Application Report')"
        page.click(report_link_selector)

        # Robust wait for the list to load - handle 'loading' spinner
        print(f"[{username}] Waiting for Application Report to populate...")

        for attempt in range(2):
            try:
                # Wait for loading text/spinner to DISAPPEAR
                page.wait_for_selector("text=loading", state="detached", timeout=10000)
                # Then wait for actual buttons to appear
                page.wait_for_selector("button:has-text('Report'), a:has-text('Report')", timeout=15000)
                break
            except:
                if attempt == 0:
                    print(f"[{username}] ⏳ Report list still loading or empty. Proactively re-clicking...")
                    page.click(report_link_selector)
                    page.wait_for_timeout(3000)
                else:
                    print(f"[{username}] ⚠️ 'Report' buttons didn't appear after retry. Saving debug screenshot.")
                    page.screenshot(path=f"debug_timeout_report_{username}.png")
                    return

        for target_ipo in active_ipo_names:
            print(f"[{username}] Checking report for: {target_ipo}")
            try:
                # Identify and click 'Report' or 'Edit' for the specific IPO
                clicked_info = page.evaluate(f"""
                    (targetName) => {{
                        const targetLow = targetName.toLowerCase().trim();
                        const searchWords = targetLow.split(' ').filter(w => w.length > 2).slice(0, 3);
                        
                        // Look for common row containers
                        const allRows = Array.from(document.querySelectorAll('tr, .d-flex-row, .application-item, .card, div[class*="row"]'))
                                         .filter(el => el.querySelector('button, a'));
                        
                        for (const row of allRows) {{
                            const text = row.innerText.toLowerCase();
                            const hasFull = text.includes(targetLow);
                            const hasWords = searchWords.length > 0 && searchWords.every(w => text.includes(w));
                            
                            if (hasFull || hasWords) {{
                                // Find buttons inside this row
                                const btn = Array.from(row.querySelectorAll('button, a'))
                                             .find(el => {{
                                                 const t = el.innerText.trim().toLowerCase();
                                                 return t === 'report' || t === 'edit' || t.includes('view');
                                             }});
                                if (btn) {{
                                    btn.click();
                                    return {{ success: true, mode: btn.innerText.trim() }};
                                }}
                            }}
                        }}
                        return {{ success: false }};
                    }}
                """, target_ipo)

                if not clicked_info.get('success'):
                    print(f"[{username}] ⏳ {target_ipo} not found or has no available action.")
                    continue

                if clicked_info.get('mode', '').lower() == 'edit':
                    print(f"[{username}] 'Edit' mode detected from list view. Filling form...")
                    fill_and_submit_form(page, account, company_name=target_ipo)
                    page.goto("https://meroshare.cdsc.com.np/#/asba/report", wait_until='networkidle')
                    continue

                page.wait_for_load_state('networkidle')
                page.wait_for_timeout(4000)

                # Read status from the detail page (robust extraction)
                detail_status = page.evaluate("""
                    () => {
                        const bodyText = document.body.innerText.toLowerCase();
                        const labels = Array.from(document.querySelectorAll('label, th, td, b, span, p, div'));
                        
                        const findValue = (searchText) => {
                            const label = labels.find(el => {
                                const t = el.innerText.toLowerCase().trim();
                                return t === searchText || t.startsWith(searchText + ':') || t.includes(searchText + ' ');
                            });
                            if (!label) return null;
                            
                            let val = null;
                            if (label.nextElementSibling) val = label.nextElementSibling.innerText.trim();
                            else if (label.parentElement && label.parentElement.nextElementSibling) {
                                val = label.parentElement.nextElementSibling.innerText.trim();
                            } else if (label.innerText.includes(':')) {
                                val = label.innerText.split(':')[1].trim();
                            }
                            
                            // Filter out garbage (dates, times, too short)
                            if (val && (val.toLowerCase().includes('date') || val.toLowerCase().includes('time') || val.length < 3)) return null;

                            return val;
                        };
                        
                        // Prioritize specific status fields
                        const statusKeys = ['block amount status', 'verification status', 'bank status', 'status'];
                        let statusLine = null;
                        for (const k of statusKeys) {
                            statusLine = findValue(k);
                            if (statusLine) break;
                        }
                        
                        // Fallback: Check if common status words are present in the body
                        if (!statusLine || statusLine.length < 3) {
                            if (bodyText.includes('verified') && !bodyText.includes('unverified')) statusLine = 'verified';
                            else if (bodyText.includes('rejected')) statusLine = 'rejected';
                            else if (bodyText.includes('unverified')) statusLine = 'unverified';
                        }

                        return { 
                            status: statusLine, 
                            remark: findValue('remark') || findValue('reason') 
                        };
                    }
                """)

                status_val = (detail_status.get('status') or "").lower()
                remark_val = (detail_status.get('remark') or "").lower()
                print(f"[{username}] {target_ipo} -> Status: {status_val}, Remark: {remark_val}")

                # Notification logic for final results
                if "verified" in status_val and "unverified" not in status_val:
                    print(f"[{username}] ✅ SUCCESS: {target_ipo} is Verified. (Email skipped as per configuration)")
                    # send_email_notification(account.get('EMAIL'), f"[MeroShare] Status: Verified!", f"Hi {username},\n\n{target_ipo} has been applied successfully.")
                elif "rejected" in status_val or "insufficient" in remark_val or "balance" in remark_val:
                    msg = f"Your IPO ({target_ipo}) was rejected. REMARK: {remark_val}."
                    print(f"[{username}] ❌ REJECTED: {msg}")

                    auto_reapply_enabled = os.getenv("AUTO_REAPPLY", "false").lower() == "true"
                    
                    if auto_reapply_enabled:
                        print(f"[{username}] Auto-reapply enabled. Looking for button...")
                        reapply_btn = page.locator("button:has-text('Edit'), button:has-text('Re-Apply'), button:has-text('Reapply')").first
                        if reapply_btn.is_visible():
                            print(f"[{username}] Found Reapply/Edit button. Clicking...")
                            reapply_btn.click()
                            page.wait_for_load_state('networkidle')
                            # fill_and_submit_form handles its own success/failure notifications
                            fill_and_submit_form(page, account, company_name=target_ipo)
                            page.goto("https://meroshare.cdsc.com.np/#/asba/report", wait_until='networkidle')
                            continue
                        else:
                            print(f"[{username}] No reapply button found for rejected IPO. Ending silently.")
                            # No notification sent when reapply enabled but button missing (silent end)
                    else:
                        print(f"[{username}] Auto-reapply disabled. Sending rejection notification.")
                        subj = f"[MeroShare] Rejected: {target_ipo}"
                        msg_body = f"❌ Rejected: {target_ipo}. REMARK: {remark_val}."
                        body_email = f"Hi {username},\n\n{msg_body}\n\nTo reapply, please topup and the automation will retry in the next scheduled run."
                        send_email_notification(account.get('EMAIL'), subj, body_email)
                        send_push_notification(account.get('TOKENS'), username, msg_body)
                else:
                    print(f"[{username}] ⏳ {target_ipo} still pending ({status_val}).")

                # Return to list
                page.go_back()
                page.wait_for_load_state('networkidle')
                page.wait_for_timeout(2000)

            except Exception as e:
                print(f"[{username}] Error checking {target_ipo}: {e}")
                page.goto("https://meroshare.cdsc.com.np/#/asba/report", wait_until='networkidle')

    except Exception as e:
        print(f"[{username}] Fatal error in check_status: {e}")


def run_automation():
    accounts = get_accounts()
    if not accounts:
        print("Error: No accounts found. Check accounts.json, ACCOUNTS_JSON secret, or .env file.")
        return

    count = len(accounts)
    print(f"Found {count} account(s) to process.")

    with sync_playwright() as p:
        headless = os.getenv("HEADLESS", "true").lower() == "true"
        browser = p.chromium.launch(
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--no-sandbox',
                '--window-size=1280,720'
            ]
        )

        for i, account in enumerate(accounts):
            username = account.get('MEROSHARE_USER')
            print(f"\n=============================================")
            print(f"Processing Account {i+1}/{count}: {username}")
            print(f"=============================================")

            # Create a context with geolocation permissions
            context = browser.new_context(
                permissions=['geolocation'],
                geolocation={'latitude': 27.7172, 'longitude': 85.3240}, # Kathmandu
                viewport={'width': 1280, 'height': 720}
            )

            page = context.new_page()
            try:
                page.goto("https://meroshare.cdsc.com.np", timeout=60000)
                MAX_RETRIES = 3
                logged_in = False
                for attempt in range(1, MAX_RETRIES + 1):
                    login_result = login(page, username, account['MEROSHARE_PASS'], account['DP_NAME'])
                    if login_result is True:
                        print(f"Login Successful!")
                        logged_in = True
                        break
                    elif login_result == "EXPIRED":
                        if handle_password_reset(page, account):
                            print(f"[{username}] Password successfully reset and logged in.")
                            logged_in = True
                        else:
                            print(f"[{username}] Password reset failed.")
                        break # Don't retry login if expired/reset attempted
                    elif login_result in ("DEMAT_EXPIRED", "MEROSHARE_EXPIRED"):
                        handle_expired_account(account, login_result)
                        break
                    else:
                        print(f"Error: [{username}] Login failed (Attempt {attempt}). Retrying...")
                        page.reload()
                        page.wait_for_load_state('networkidle')
                        time.sleep(2)

                if logged_in:
                    check_account_expiry_warning(page, account)
                    apply_ipo(page, account)
                else:
                    print(f"Error: [{username}] Failed to login after {MAX_RETRIES} attempts.")

            except Exception as e:
                print(f"Error: [{username}] Error processing account: {e}")
            finally:
                page.close()

        browser.close()
        print("\nAll accounts processed.")



def solve_captcha(page, reader, max_retries=5):
    """
    Solves the CDSC IPO Result captcha using EasyOCR.
    """
    for attempt in range(max_retries):
        try:
            print(f"  [Captcha] Attempt {attempt + 1}/{max_retries}...")
            
            # Locate the captcha image
            # The CDSC portal usually has the image next to the input
            captcha_img = page.locator("img[src*='captcha']").first
            if not captcha_img.is_visible():
                # Fallback: find any image near the captcha input
                captcha_img = page.locator("input#captcha + img, .captcha-image img").first
            
            if not captcha_img.is_visible():
                print("  ⚠️ Captcha image not found. Refreshing page...")
                page.reload()
                page.wait_for_timeout(2000)
                continue

            # Take a screenshot of the captcha element
            img_bytes = captcha_img.screenshot()
            
            # Use EasyOCR to read text
            # CDSC captchas are usually 5 digits
            results = reader.readtext(img_bytes)
            
            if results:
                # Filter for digits only
                raw_text = results[0][1]
                captcha_text = "".join(re.findall(r'\d', raw_text))
                
                if len(captcha_text) >= 5:
                    print(f"  [Captcha] Solved: {captcha_text}")
                    return captcha_text
                else:
                    print(f"  [Captcha] Read '{raw_text}' but didn't find 5 digits. Retrying...")
            
            # Refresh captcha if failed
            # Look for refresh icon/button
            refresh_btn = page.locator(".fa-refresh, button:has(i.fa-refresh), img[src*='refresh']").first
            if refresh_btn.is_visible():
                refresh_btn.click()
            else:
                page.reload()
            
            page.wait_for_timeout(1500)
            
        except Exception as e:
            print(f"  [Captcha] Error: {e}")
            page.wait_for_timeout(1000)
            
    return None

def run_status_check():
    print("--- IPO Result Check Version: 2026-05-13 V4 ---")
    """
    Official CDSC Portal Result Check (With AI Captcha Solving).
    """
    accounts = get_accounts()
    if not accounts:
        print("Error: No accounts found.")
        return

    print(f"🔍 Official CDSC Status Check: Processing {len(accounts)} account(s)...")

    # Initialize OCR Reader (Done once per run)
    print("  [AI] Initializing EasyOCR...")
    import easyocr
    reader = easyocr.Reader(['en'], gpu=False)

    with sync_playwright() as p:
        headless = os.getenv("HEADLESS", "true").lower() == "true"
        browser = p.chromium.launch(
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--no-sandbox',
                '--window-size=1280,720'
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 720}
        )
        page = context.new_page()
        

        try:
            url = "https://iporesult.cdsc.com.np/"
            print(f"Navigating to {url}...")
            page.goto(url, timeout=60000, wait_until='domcontentloaded')
            print("  Page loaded. Waiting for Angular to initialize...")
            page.wait_for_timeout(6000)
            
            # Wait for the dropdown to be visible
            try:
                print("  Waiting for CDSC portal to be ready...")
                page.wait_for_selector(
                    "ng-select, select#companyShare, .ng-select-container",
                    timeout=45000
                )
                print("  ✅ Portal ready.")
            except Exception as e:
                print(f"  ❌ Portal took too long to load: {e}")
                os.makedirs("screenshots", exist_ok=True)
                page.screenshot(path="screenshots/portal_load_fail.png")
                with open("screenshots/portal_page_source.html", "w") as f:
                    f.write(page.content())
                print("  [Debug] Screenshot and page source saved to screenshots/")
                return

            # ── STEP 1: Read the first company from the CDSC dropdown ──────────
            print("\n  Opening dropdown to read latest company with results...")
            # Target the inner container (the actual clickable part of ng-select)
            page.dispatch_event(".ng-select-container", "click")
            page.wait_for_timeout(2500)

            first_company = page.evaluate("""
                () => {
                    // Try multiple selectors in order of specificity
                    const selectors = [
                        '.ng-dropdown-panel .ng-option:first-child',
                        '.ng-option:first-child',
                        '[role="option"]:first-child',
                        '.ng-option-label'
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText && el.innerText.trim().length > 2) {
                            return el.innerText.trim();
                        }
                    }
                    return null;
                }
            """)

            if not first_company:
                print("  ❌ Could not read company list from dropdown. Exiting.")
                return

            print(f"  📋 Latest company with results: {first_company}")

            # ── STEP 2: Check if we applied for this company ───────────────────
            applied_companies = get_applied_companies()
            # Normalize: strip trailing punctuation for comparison
            applied_normalized = [c.strip().rstrip('.').lower() for c in applied_companies]
            first_company_norm = first_company.strip().rstrip('.').lower()

            is_applied = any(
                first_company_norm in ac or ac in first_company_norm
                for ac in applied_normalized
            )

            if not is_applied:
                print(f"  ⏭️  '{first_company}' — Not in our applied list. Nothing to check.")
                print(f"  Applied companies in DB: {applied_companies}")
                return

            print(f"  ✅ Match found! '{first_company}' was applied for. Proceeding with result check...")

            # ── STEP 3: Select the company in the dropdown ─────────────────────
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            page.dispatch_event(".ng-select-container", "click")
            page.wait_for_timeout(800)
            page.type("ng-select input", first_company, delay=50)
            page.wait_for_timeout(1200)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1000)

            # Verify BOID form appeared
            try:
                page.wait_for_selector("input#boid, input[name='boid']", timeout=8000)
                print("  ✅ BOID form visible. Starting account checks...")
            except:
                print(f"  ❌ BOID form did not appear after selecting '{first_company}'. Results may not be published yet.")
                return

            # Now check for each account for this company
            for account in accounts:
                username = account.get('MEROSHARE_USER')
                boid = account.get('BOID')
                
                if not boid:
                    print(f"[{username}] Skipping: No BOID.")
                    continue

                # Try to solve and submit
                success_found = False
                for attempt in range(5):
                    try:
                        # 1. Fill BOID
                        page.fill("input#boid, input[name='boid']", boid)
                        
                        # 2. Solve Captcha
                        captcha_code = solve_captcha(page, reader)
                        if not captcha_code:
                            print(f"  [{username}] Could not solve captcha. Skipping account.")
                            break
                            
                        page.fill("input#captcha, input[name='userCaptcha']", captcha_code)
                        
                        # 3. Submit
                        page.click("button[type='submit'], .btn-submit")
                        page.wait_for_timeout(3000)
                        
                        # 4. Check result
                        res_info = page.evaluate("""
                            () => {
                                const bodyText = document.body.innerText.toLowerCase();
                                if (bodyText.includes("congratulations") || bodyText.includes("allotted")) {
                                    const msg = document.querySelector('.text-success, h3, p')?.innerText || "Allotted";
                                    return "Allotted|" + msg;
                                }
                                if (bodyText.includes("not allotted") || bodyText.includes("sorry")) {
                                    return "Not Allotted|Sorry, you are not allotted for this IPO.";
                                }
                                if (bodyText.includes("invalid captcha")) {
                                    return "RETRY_CAPTCHA|Invalid Captcha";
                                }
                                return "Unknown|No result detected";
                            }
                        """)
                        
                        if res_info.startswith("RETRY_CAPTCHA"):
                            print(f"  [{username}] AI misread captcha. Retrying...")
                            page.click(".fa-refresh, .refresh-captcha")
                            page.wait_for_timeout(1000)
                            continue
                        
                        status_category, feedback = res_info.split("|", 1)
                        print(f"[{username}] Result for {first_company}: {status_category} - {feedback}")
                        
                        if status_category != "Unknown":
                            send_push_notification(account.get('TOKENS'), username, f"{first_company}: {feedback}")
                            if os.getenv("DATABASE_URL"):
                                try:
                                    import datetime
                                    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
                                    cur = conn.cursor()
                                    cur.execute("""
                                        INSERT INTO automation_applicationlog
                                            (account_id, company_name, status, remark, timestamp, is_read)
                                        VALUES (%s, %s, %s, %s, %s, %s)
                                    """, (account.get('ID'), first_company, status_category, feedback,
                                          datetime.datetime.now(datetime.timezone.utc), (status_category == "Allotted")))
                                    conn.commit()
                                    cur.close()
                                    conn.close()
                                except Exception as e:
                                    print(f"  [DB] Failed to save result: {e}")
                            
                            success_found = True
                            page.click("button:has-text('Reset'), .btn-reset")
                            page.wait_for_timeout(1000)
                            break
                        
                    except Exception as e:
                        print(f"  [{username}] Error: {e}")
                        page.reload()
                        page.wait_for_timeout(3000)
                        
                if not success_found:
                    print(f"  [{username}] Could not verify result for {first_company} after multiple attempts.")
                
                page.wait_for_timeout(1000)


        except Exception as e:
            print(f"Error during status check: {e}")
        finally:
            browser.close()
    
    print("\nOfficial CDSC status check run complete.")
    
    print("\nGlobal IME status check run complete.")


def get_applied_companies():
    """
    Fetches unique company names from ApplicationLog where status is 'Success'.
    """
    DB_URL = os.environ.get("DATABASE_URL")
    if not DB_URL:
        return []
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT company_name FROM automation_applicationlog WHERE status = 'Success'")
        companies = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return [c for c in companies if c]
    except Exception as e:
        print(f"Error fetching companies: {e}")
        return []

if __name__ == "__main__":
    # RUN_MODE=check_status → runs the status watchdog
    # RUN_MODE=apply (default) → applies for IPOs
    mode = os.getenv("RUN_MODE", "apply").lower()
    if mode == "check_status":
        run_status_check()
    else:
        run_automation()
