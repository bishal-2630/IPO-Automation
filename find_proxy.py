import requests
import concurrent.futures

def test_proxy(proxy):
    url = "https://iporesult.cdsc.com.np/"
    proxies = {
        "http": f"http://{proxy}",
        "https": f"http://{proxy}",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, proxies=proxies, headers=headers, timeout=12, allow_redirects=True)
        # Must get 200 AND not be the WAF rejection page
        if resp.status_code == 200 and "Request Rejected" not in resp.text and "requested URL was rejected" not in resp.text:
            return proxy
    except:
        pass
    return None

def find_working_proxy():
    print("Searching for fresh proxies...")
    try:
        resp = requests.get(
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
            timeout=15
        )
        all_proxies = [p.strip() for p in resp.text.strip().split("\n") if p.strip()]
        print(f"Found {len(all_proxies)} candidates. Testing top 150...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
            results = list(executor.map(test_proxy, all_proxies[:150]))

        working = [r for r in results if r]
        if working:
            print(f"Success! Found {len(working)} working proxies. Saving top 5...")
            return working[:5]
        else:
            print("No working proxy found that bypasses CDSC WAF.")
    except Exception as e:
        print(f"Error fetching proxies: {e}")

    return []

if __name__ == "__main__":
    proxies = find_working_proxy()
    if proxies:
        with open("proxy.txt", "w") as f:
            f.write("\n".join(proxies))
        print(f"Saved {len(proxies)} proxies to proxy.txt")
    else:
        print("No working proxy found.")
