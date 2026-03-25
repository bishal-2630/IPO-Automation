import os
import psycopg2
from playwright.sync_api import sync_playwright
from notifications import broadcast_push_notification, send_push_notification

# Configuration
LISTING_URL = "https://www.sharesansar.com/category/share-listing"
CACHE_FILE = "notified_listings.txt"

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

    user_tokens = {} # {boid: [tokens]}
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        # Join with the LATEST status only for each account/company
        query = """
            SELECT DISTINCT a.boid, t.token 
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
        for boid, token in rows:
            if not boid: continue
            if boid not in user_tokens:
                user_tokens[boid] = []
            user_tokens[boid].append(token)
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error fetching tokens for allotted users: {e}")
    
    return user_tokens

def get_previously_notified():
    """Read the cache file to see which companies we already notified about."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f.readlines() if line.strip())
    return set()

def update_notified_cache(company_name):
    """Append a newly listed company to the cache."""
    with open(CACHE_FILE, "a", encoding="utf-8") as f:
        f.write(f"{company_name}\n")

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

                # 2. Personalized Notification (for Allotted Users)
                allotted_users = get_tokens_for_allotted_users(company)
                for boid, tokens in allotted_users.items():
                    # Extract last 8 digits of BOID for the title (e.g. 04598041)
                    account_number = boid[-8:] if len(boid) >= 8 else boid
                    send_push_notification(
                        tokens=tokens,
                        title=f"{account_number}",
                        body=f"Your alloted {company} IPO has been listed in secondary market."
                    )
                
                update_notified_cache(company)
                found_new_listing = True
                break

    if not found_new_listing:
        print("No new listings found for the monitored companies.")

if __name__ == "__main__":
    check_for_new_listings()
