from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
import os
import time
import json
import random
import string
import secrets

from notifications import send_email_notification
from expiry_handler import (
    detect_account_expiry,
    check_account_expiry_warning,
    handle_expired_account,
)

# Load environment variables
load_dotenv()


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
        # Using flexible selectors in case they change
        page.wait_for_selector("input[placeholder='Old Password'], #oldPassword", timeout=10000)
        
        page.fill("input[placeholder='Old Password'], #oldPassword", old_password)
        page.fill("input[placeholder='New Password'], #newPassword", new_password)
        page.fill("input[placeholder='Confirm Password'], #confirmPassword", new_password)
        
        page.click("button:has-text('Change'), button:has-text('Update')")
        
        # Wait for toast message or redirection
        try:
            toast = page.wait_for_selector(".toast-success, .toast-message", timeout=10000)
            toast_text = toast.inner_text().strip()
            print(f"[{username}] Reset Result: {toast_text}")
            
            if "success" in toast_text.lower() or "successfully" in toast_text.lower():
                # Notify User
                msg = f"Your MeroShare password for {username} has been automatically reset because it expired.\n\nNew Password: {new_password}\n\nPlease update your GitHub secrets or local config if the automatic update failed."
                send_email_notification(account.get('EMAIL'), f"[MeroShare] Password Reset Successful", msg)
                
                # Update local file
                update_local_account_password(username, new_password)
                return True
            else:
                print(f"[{username}] Password reset reported failure: {toast_text}")
        except:
             # Fallback check: if we are no longer on change-password page and see dashboard
             page.wait_for_timeout(3000)
             if "change-password" not in page.url and (page.locator("text=My ASBA").is_visible() or "dashboard" in page.url):
                 print(f"[{username}] Password reset appears successful (redirected).")
                 msg = f"Your MeroShare password for {username} has been automatically reset.\n\nNew Password: {new_password}"
                 send_email_notification(account.get('EMAIL'), f"[MeroShare] Password Reset Successful", msg)
                 update_local_account_password(username, new_password)
                 return True
                 
    except Exception as e:
        print(f"[{username}] Error during password reset: {e}")
        page.screenshot(path=f"debug_reset_fail_{username}.png")
        
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
        return False, "Bank/Branch/Account selection failed"

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
        min_kitta_value = page.evaluate("""
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
                    let matches = textContent.match(/\\d+/g);
                    if (matches && matches.length > 0) return parseInt(matches[matches.length - 1]);
                    if (minLabel.nextElementSibling) {
                        const nextText = minLabel.nextElementSibling.innerText;
                        const matchNext = nextText.match(/\\d+/);
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
                msg = f"{company_name} has been applied successfully."
                send_email_notification(account.get('EMAIL'), f"[MeroShare] Success: {company_name}", f"Hi {username},\n\n{msg}")
                return True, company_name
            else:
                error_msg = toast_text
                if "balance" in error_msg.lower() or "insufficient" in error_msg.lower():
                    msg = f"Your IPO has not been applied due to insufficient balance. Please topup amount and try again."
                    send_email_notification(account.get('EMAIL'), f"[MeroShare] Failed: Insufficient Balance", f"Hi {username},\n\n{msg}")
                    return False, "Insufficient balance"
                else:
                    msg = f"❌ FAILED: {error_msg} - {username}"
                    send_email_notification(account.get('EMAIL'), f"[MeroShare] Error: Application Failed", f"Hi {username},\n\n{msg}")
                    return False, error_msg
        except:
             if not page.is_visible("#transactionPIN"):
                 print(f"[{username}] Application submitted successfully (modal closed).")
                 return True, company_name
             else:
                 print(f"Error: [{username}] Application submission failed (modal still open).")
                 return False, "Application submission failed (modal still open)"
    else:
        print(f"Warning: [{username}] No TPIN provided. Skipping submission.")
        return False, "No TPIN provided"


def login(page, username, password, dp_name):
    """
    Attempts to login a specific user.
    """
    print(f"Logging in as {username}...")
    
    print(f"Selecting DP: {dp_name}...")
    try:
        # Robust DP Selection: Try multiple common selectors for the DP dropdown
        dp_selectors = ["#selectBranch", "select[name='selectBranch']", ".select2-selection", "select"]
        dp_found = False
        for selector in dp_selectors:
            if page.locator(selector).is_visible():
                page.click(selector)
                dp_found = True
                break
        
        if not dp_found:
             page.wait_for_selector("#selectBranch", timeout=15000)
             page.click("#selectBranch")

        page.wait_for_timeout(1000) 
        page.keyboard.type(dp_name)
        page.wait_for_timeout(1000) 
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000) 
    except Exception as e:
        print(f"Warning: DP Selection issue: {e}")
        # Take a screenshot to see what's wrong with the login page
        page.screenshot(path=f"debug_login_dp_{username}.png")
    
    # NEW: Try to blur the dropdown to ensure fields are interactable
    page.mouse.click(0, 0) 
    page.wait_for_timeout(500)

    try:
        # Use a more flexible selector for username (ID, Name, or Placeholder)
        username_selectors = ["#txtUserName", "input[name='username']", "input[placeholder='Username']"]
        found = False
        for selector in username_selectors:
            if page.locator(selector).is_visible():
                page.fill(selector, username)
                found = True
                break
        
        if not found:
            # If none found immediately, wait longer for the primary one
            page.wait_for_selector("#txtUserName", timeout=20000)
            page.fill("#txtUserName", username)
        
        # Small pause before password
        page.wait_for_timeout(500)
        
        # Robust password selection
        password_selectors = ["#txtPassword", "input[name='password']", "input[placeholder='Password']"]
        p_found = False
        for selector in password_selectors:
            if page.locator(selector).is_visible():
                page.fill(selector, password)
                p_found = True
                break
        
        if not p_found:
            page.wait_for_selector("#txtPassword", timeout=10000)
            page.fill("#txtPassword", password)
            
    except Exception as e:
        print(f"[{username}] Could not find form fields. State at failure:")
        page.screenshot(path=f"debug_login_fields_{username}.png")
        return False

    # Capture login button text for debugging and try to click
    print(f"Clicking Login button for {username}...")
    page.click("button:has-text('Login')")
    
    # Wait for navigation/dashboard
    try:
        page.wait_for_load_state('networkidle', timeout=15000)
        page.wait_for_timeout(2000) 
        
        # Check for Password Expiry Redirect
        if "change-password" in page.url or "changepassword" in page.url or page.locator("text=Change Password").is_visible():
            print(f"[{username}] ΓÜá∩╕Å Password Expired / Change required detected.")
            return "EXPIRED"

        # Check for DEMAT or MeroShare account expiry
        expiry_result = detect_account_expiry(page, username)
        if expiry_result:
            return expiry_result

        if page.locator("text=My ASBA").is_visible():
            return True
        elif page.locator(".toast-message").is_visible():
            error_msg = page.locator(".toast-message").inner_text()
            print(f"ΓÜá∩╕Å Login Failed: {error_msg}")
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
    page.wait_for_selector(".nav-link:has-text('My ASBA')")
    page.click(".nav-link:has-text('My ASBA')")

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
        clicked_ipo = page.evaluate("""
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
                        // Extract company name (first line or before the first dash)
                        const rawName = row.innerText.split(/[\\n-]/)[0].trim();
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
        page.screenshot(path=f"debug_asba_{username}.png")
        return False, "No ordinary shares found"

def get_accounts():
    """
    Retrieves accounts from environment variable (JSON) or local file.
    """
    accounts = []
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
                    print(f"[{username}] ΓÅ│ Report list still loading or empty. Proactively re-clicking...")
                    page.click(report_link_selector)
                    page.wait_for_timeout(3000)
                else:
                    print(f"[{username}] ΓÜá∩╕Å 'Report' buttons didn't appear after retry. Saving debug screenshot.")
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
                    print(f"[{username}] ΓÅ│ {target_ipo} not found or has no available action.")
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
                    print(f"[{username}] Γ£à SUCCESS: {target_ipo} is Verified. (Email skipped as per configuration)")
                    # send_email_notification(account.get('EMAIL'), f"[MeroShare] Status: Verified!", f"Hi {username},\n\n{target_ipo} has been applied successfully.")
                elif "rejected" in status_val or "insufficient" in remark_val or "balance" in remark_val:
                    msg = f"Your IPO ({target_ipo}) was rejected. REMARK: {remark_val}."
                    print(f"[{username}] Γ¥î REJECTED: {msg}")

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
                        send_email_notification(account.get('EMAIL'), f"[MeroShare] Status: Rejected", f"Hi {username},\n\n{msg}\n\nTo reapply, please topup and the automation will retry in the next scheduled run.")
                else:
                    print(f"[{username}] ΓÅ│ {target_ipo} still pending ({status_val}).")

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
        browser = p.chromium.launch(headless=headless)

        for i, account in enumerate(accounts):
            username = account.get('MEROSHARE_USER')
            print(f"\n=============================================")
            print(f"Processing Account {i+1}/{count}: {username}")
            print(f"=============================================")

            page = browser.new_page()
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


def run_status_check():
    """
    Watchdog: Logs in to each account and checks Application Report.
    Only sends notification when a FINAL status is found.
    Runs silently if still in process (bank/holiday delay).
    """
    accounts = get_accounts()
    if not accounts:
        print("Error: No accounts found.")
        return

    count = len(accounts)
    print(f"≡ƒöì Status Watchdog: Checking {count} account(s)...")

    with sync_playwright() as p:
        headless = os.getenv("HEADLESS", "true").lower() == "true"
        browser = p.chromium.launch(headless=headless)

        for i, account in enumerate(accounts):
            username = account.get('MEROSHARE_USER')
            print(f"\n=============================================")
            print(f"Status Check {i+1}/{count}: {username}")
            print(f"=============================================")

            page = browser.new_page()
            try:
                page.goto("https://meroshare.cdsc.com.np", timeout=60000)
                MAX_RETRIES = 3
                logged_in = False
                for attempt in range(1, MAX_RETRIES + 1):
                    login_result = login(page, username, account['MEROSHARE_PASS'], account['DP_NAME'])
                    if login_result is True:
                        logged_in = True
                        break
                    elif login_result in ("EXPIRED", "DEMAT_EXPIRED", "MEROSHARE_EXPIRED"):
                        print(f"[{username}] Login blocked ({login_result}). Skipping check in status mode.")
                        break
                    else:
                        page.reload()
                        page.wait_for_load_state('networkidle')
                        time.sleep(2)

                if logged_in:
                    check_status(page, account)
                else:
                    print(f"Error: [{username}] Could not log in for status check (or checks restricted to apply mode).")

            except Exception as e:
                print(f"Error: [{username}] {e}")
            finally:
                page.close()

        browser.close()
        print("\nStatus check run complete.")


if __name__ == "__main__":
    # RUN_MODE=check_status ΓåÆ runs the status watchdog
    # RUN_MODE=apply (default) ΓåÆ applies for IPOs
    mode = os.getenv("RUN_MODE", "apply").lower()
    if mode == "check_status":
        run_status_check()
    else:
        run_automation()
