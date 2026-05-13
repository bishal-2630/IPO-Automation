import os
import psycopg2
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta

from notifications import broadcast_push_notification

# Configuration
UPCOMING_URL = "https://www.sharesansar.com/upcoming-issue"

def init_db():
    """Create the upcoming IPO table if it doesn't exist."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url: return
    
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS automation_upcomingipo (
            id SERIAL PRIMARY KEY,
            company_name TEXT UNIQUE,
            symbol TEXT,
            units TEXT,
            opening_date TEXT,
            closing_date TEXT,
            issue_manager TEXT,
            issue_price TEXT,
            category TEXT,
            status TEXT,
            last_updated TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

def scrape_upcoming():
    print("Checking for upcoming IPOs/FPOs...")
    results = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto(UPCOMING_URL, timeout=60000)
            
            # Categories are usually separated by IDs like #ipo, #fpo, etc.
            categories = {
                "IPO": "#ipo",
                "FPO": "#fpo",
                "Local IPO": "#ipolocal",
                "Foreign Employment": "#ipomigrant",
                "Right Share": "#rightshare"
            }
            
            for cat_name, selector in categories.items():
                print(f"  Scraping category: {cat_name}...")
                try:
                    # Find the table associated with this category
                    # ShareSansar often uses IDs for the section headers
                    rows = page.evaluate(f"""
                        (sel) => {{
                            const table = document.querySelector(sel + " + div table, " + sel + " table");
                            if (!table) return [];
                            return Array.from(table.querySelectorAll('tr')).slice(1).map(tr => {{
                                const cols = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
                                return cols;
                            }});
                        }}
                    """, selector)
                    
                    for row in rows:
                        if len(row) >= 8:
                            # Standard layout: S.No | Company | Symbol | Units | Price | Manager | Open | Close
                            results.append({
                                'company': row[1],
                                'symbol': row[2],
                                'units': row[3],
                                'price': row[4],
                                'manager': row[5],
                                'open': row[6],
                                'close': row[7],
                                'category': cat_name
                            })
                except Exception as e:
                    print(f"    Error scraping {cat_name}: {e}")
                    
        except Exception as e:
            print(f"Scraper error: {e}")
        finally:
            browser.close()
            
    return results

def save_to_db(data):
    db_url = os.getenv("DATABASE_URL")
    if not db_url: return
    
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    new_count = 0
    for item in data:
        # Check if it already exists to avoid duplicate notifications
        cur.execute("SELECT id FROM automation_upcomingipo WHERE company_name = %s", (item['company'],))
        is_new = cur.fetchone() is None

        # Determine status
        status = "COMING SOON"
        try:
            if item['open'] and '-' in item['open']:
                open_date = datetime.strptime(item['open'], '%Y-%m-%d')
                today = datetime.now()
                diff = (open_date - today).days
                if diff == 0:
                    status = "OPENING TODAY"
                elif diff == 1:
                    status = "OPENING IN 24 HOURS"
                elif diff < 0:
                    status = "OPEN"
        except:
            pass

        cur.execute("""
            INSERT INTO automation_upcomingipo 
            (company_name, symbol, units, issue_price, issue_manager, opening_date, closing_date, category, status, last_updated)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (company_name) DO UPDATE SET
                symbol = EXCLUDED.symbol,
                units = EXCLUDED.units,
                issue_price = EXCLUDED.issue_price,
                issue_manager = EXCLUDED.issue_manager,
                opening_date = EXCLUDED.opening_date,
                closing_date = EXCLUDED.closing_date,
                status = EXCLUDED.status,
                last_updated = NOW();
        """, (item['company'], item['symbol'], item['units'], item['price'], item['manager'], item['open'], item['close'], item['category'], status))
        
        if is_new:
            new_count += 1
            print(f"  [New IPO] {item['company']} found! Sending notification...")
            broadcast_push_notification(
                title="Upcoming IPO",
                body=f"{item['company']} is opening on {item['open']}."
            )
    
    conn.commit()
    cur.close()
    conn.close()
    print(f"Successfully updated {len(data)} upcoming issues in the database. ({new_count} new)")

if __name__ == "__main__":
    init_db()
    data = scrape_upcoming()
    if data:
        save_to_db(data)

if __name__ == "__main__":
    init_db()
    data = scrape_upcoming()
    if data:
        save_to_db(data)
