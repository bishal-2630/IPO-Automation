import os
import psycopg2
from playwright.sync_api import sync_playwright
from notifications import broadcast_push_notification, send_push_notification

# Configuration
LISTING_URL = "https://www.sharesansar.com/category/share-listing"

def get_applied_companies():
    """Fetch unique applied company names from the database."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not found. Cannot fetch applied IPOs.")
        return []

    companies = set()
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        # Fetch all unique companies that were ever applied (Successful or Allotted)
        cur.execute("SELECT DISTINCT company_name FROM automation_applicationlog")
        rows = cur.fetchall()
        for row in rows:
            if row[0]:
                companies.add(row[0].strip())
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error fetching applied companies: {e}")
    
    return list(companies)

def get_tokens_for_allotted_users(company_name):
    """Fetch 16-digit BOIDs and FCM tokens for users who were allotted the company."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return {}

    account_data = {} # {account_id: {'boid': boid, 'tokens': set()}}
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        # Join with the LATEST status only for each account/company
        query = """
            SELECT DISTINCT a.id, a.boid, t.token 
            FROM automation_account a
            JOIN automation_fcmtoken t ON a.owner_id = t.user_id
            JOIN (
                SELECT account_id, status, 
                       ROW_NUMBER() OVER (PARTITION BY account_id, company_name ORDER BY timestamp DESC) as rn
                FROM automation_applicationlog
                WHERE company_name = %s
            ) l ON a.id = l.account_id
            WHERE l.rn = 1 AND l.status = 'Allotted'
        """
        cur.execute(query, (company_name,))
        rows = cur.fetchall()
        for acc_id, boid, token in rows:
            if not acc_id or not boid: continue
            if acc_id not in account_data:
                account_data[acc_id] = {'boid': boid, 'tokens': set()}
            if token:
                account_data[acc_id]['tokens'].add(token)
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error fetching tokens for allotted users: {e}")
    
    # Convert sets back to lists for easy JSON serialization if needed
    for acc_id in account_data:
        account_data[acc_id]['tokens'] = list(account_data[acc_id]['tokens'])
        
    return account_data

def get_previously_notified():
    """Query the database for companies that already have a 'Listed' log entry.
    This replaces the old file-based cache so the state persists across runs.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not found. Cannot check previously notified listings.")
        return set()

    notified = set()
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT company_name FROM automation_applicationlog "
            "WHERE status = 'Listed' AND is_listed = TRUE"
        )
        for row in cur.fetchall():
            if row[0]:
                notified.add(row[0].strip())
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error fetching previously notified listings from DB: {e}")

    return notified

def scrape_listing_headlines():
    """Scrape recent listing headlines from ShareSansar."""
    print("Checking ShareSansar for new listings...")
    headlines = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto(LISTING_URL, timeout=60000)
            page.wait_for_selector(".featured-news-list, .news-standard-list", timeout=15000)
            
            extracted = page.evaluate("""
                () => {
                    const selectors = [
                        '.news-standard-list h4 a', 
                        '.featured-news-list h4 a',
                        '.news-list a',
                        '.news-listing h4 a',
                        'div:has(> h2:text-is("Listing")) + div a'
                    ];
                    let allHeadlines = [];
                    selectors.forEach(sel => {
                        try {
                            const found = Array.from(document.querySelectorAll(sel))
                                .map(el => el.innerText.trim())
                                .filter(t => t.length > 20);
                            allHeadlines = allHeadlines.concat(found);
                        } catch(e) {}
                    });
                    
                    if (allHeadlines.length === 0) {
                        const listingHeaders = Array.from(document.querySelectorAll('h2, h3, h4, span'))
                            .filter(el => el.innerText.trim().toLowerCase() === 'listing');
                        
                        listingHeaders.forEach(header => {
                            const parent = header.parentElement;
                            if (parent) {
                                const links = Array.from(parent.querySelectorAll('a'))
                                    .map(a => a.innerText.trim())
                                    .filter(t => t.length > 20);
                                allHeadlines = allHeadlines.concat(links);
                            }
                        });
                    }
                    return [...new Set(allHeadlines)];
                }
            """)
            headlines = extracted
        except Exception as e:
            print(f"Error during scraping: {e}")
        finally:
            browser.close()
            
    return headlines

def save_listing_log(account_id, company_name, headline):
    """Save a listing event to the ApplicationLog table."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return
    
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        query = """
            INSERT INTO automation_applicationlog (account_id, company_name, status, remark, is_read, is_listed, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """
        cur.execute(query, (account_id, company_name, 'Listed', headline, False, True))
        conn.commit()
        cur.close()
        conn.close()
        print(f"Log saved for account {account_id}: {company_name} listed.")
    except Exception as e:
        print(f"Error saving listing log for account {account_id}: {e}")

def check_for_new_listings():
    applied_companies = get_applied_companies()
    if not applied_companies:
        print("No applied IPOs found in the database. Nothing to check.")
        return

    print(f"Found {len(applied_companies)} applied IPO(s) to monitor.")
    headlines = scrape_listing_headlines()
    
    if not headlines:
        print("No news headlines could be extracted.")
        return

    notified = get_previously_notified()
    found_new_listing = False

    for company in applied_companies:
        if company in notified:
            continue
            
        # Create a simplified version of the company name for matching
        # e.g. "Api Power Company Limited" -> "Api Power"
        simplified_name = company.lower().replace(" limited", "").replace(" ltd", "").replace(" company", "").strip()
        main_words = simplified_name.split()
        
        # Require at least the first two words (or one robust word) to match to avoid false positives
        search_term = " ".join(main_words[:2]) if len(main_words) >= 2 else main_words[0]

        # Check if the search term + "list" is in any headline
        for headline in headlines:
            headline_lower = headline.lower()
            if search_term in headline_lower and ("list" in headline_lower or "secondary" in headline_lower):
                print(f"MATCH FOUND! {company} is listed in headline: '{headline}'")
                
                # 1. Broad Notification (General Alert)
                broadcast_push_notification(
                    title=f"🚀 IPO Listed in NEPSE!",
                    body=f"{company} has been listed in the secondary market."
                )

                # 2. Personalized Notification (for Allotted Users) and saving to DB
                account_data = get_tokens_for_allotted_users(company)
                for acc_id, data in account_data.items():
                    boid = data['boid']
                    tokens = data['tokens']
                    
                    # Save to database so it appears in Status tab
                    save_listing_log(acc_id, company, headline)

                    # Send push notification
                    if tokens:
                        # Extract last 8 digits of BOID for the title (e.g. 04598041)
                        account_number = boid[-8:] if len(boid) >= 8 else boid
                        send_push_notification(
                            tokens=tokens,
                            title=f"{account_number}",
                            body=f"Your alloted {company} IPO has been listed in secondary market."
                        )
                
                # DB already updated via save_listing_log — no separate cache needed
                found_new_listing = True
                break

    if not found_new_listing:
        print("No new listings found for the monitored companies.")

if __name__ == "__main__":
    check_for_new_listings()
