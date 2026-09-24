import urllib.parse
import re
import time
import concurrent.futures
from urllib.parse import urljoin
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def extract_price(text: str) -> float:
    """Extract a numeric price from text like '₹24,990' or 'Rs. 24990.00'."""
    if not text:
        return 0.0
    text = text.replace(',', '').replace('₹', '').replace('Rs.', '').replace('Rs', '').strip()
    match = re.search(r'(\d+(\.\d+)?)', text)
    return float(match.group(1)) if match else 0.0


def _scrape_with_own_browser(
    query: str,
    site_name: str,
    search_url_template: str,
    scrape_fn
) -> List[Dict[str, Any]]:
    """
    Each scraper gets its OWN Playwright instance + browser + context.
    This is required because Playwright sync API is NOT thread-safe.
    """
    print(f"[SCRAPER] Starting {site_name} for query: '{query}'")
    results = []
    pw = None
    browser = None
    
    for attempt in range(2):
        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True, timeout=10000)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-IN",
                extra_http_headers={
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                }
            )
            page = context.new_page()
            
            url = search_url_template.format(query=urllib.parse.quote_plus(query))
            print(f"[SCRAPER] {site_name} navigating to: {url}")
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)  # Wait for JS-rendered content
            
            # Debug: log the page title
            print(f"[SCRAPER] {site_name} page title: {page.title()}")
            
            results = scrape_fn(page, site_name)
            print(f"[SCRAPER] {site_name} found {len(results)} results")
            for r in results[:2]:
                if not r.get("error"):
                    print(f"  -> {ascii(r.get('title', '')[:60])} | Rs.{r.get('price', 0)}")
            
            page.close()
            context.close()
            browser.close()
            pw.stop()
            
            if results:
                return results
                
        except Exception as e:
            print(f"[SCRAPER] {site_name} ERROR (attempt {attempt+1}): {e}")
            # Cleanup on error
            try:
                if browser:
                    browser.close()
                if pw:
                    pw.stop()
            except:
                pass
            
            if attempt == 0:
                time.sleep(2)  # Wait before retry
                pw = None
                browser = None
                continue
            else:
                return [{"site": site_name, "error": True, "message": str(e)}]
    
    print(f"[SCRAPER] {site_name} returning {len(results)} results (after retries)")
    return results if results else [{"site": site_name, "error": True, "message": "No results found after retries"}]


def _make_product_dict(site: str, title: str, price: float, url: str, rating: float = 0.0) -> Dict[str, Any]:
    return {
        "site": site,
        "title": title.strip() if title else "",
        "price": price,
        "currency": "INR",
        "url": url or "",
        "availability": "In Stock" if price > 0 else "Out of Stock",
        "rating": rating,
        "reviews_count": None,
        "error": False
    }


# ─── Individual site scrapers ────────────────────────────────────────────────

def _extract_amazon_html(html: str) -> List[Dict[str, Any]]:
    """Read product cards from Amazon's server-rendered search HTML."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen_asins = set()
    for card in soup.select("div[data-component-type='s-search-result']")[:30]:
        asin = card.get("data-asin")
        if not asin or asin in seen_asins:
            continue
        title_node = card.select_one('[data-cy="title-recipe"] a[href*="/dp/"]')
        if not title_node:
            title_node = card.select_one("h2")
        title = title_node.get_text(" ", strip=True) if title_node else ""
        title = re.sub(r'^Sponsored Ad -\s*', '', title, flags=re.I)
        price_node = card.select_one(".a-price .a-offscreen")
        price = extract_price(price_node.get_text(strip=True)) if price_node else 0
        if len(title) < 10 or price <= 0:
            continue
        rating_node = card.select_one("span.a-icon-alt")
        rating_match = re.search(r'\d+(?:\.\d+)?', rating_node.get_text()) if rating_node else None
        rating = float(rating_match.group()) if rating_match else 0.0
        results.append(_make_product_dict(site="Amazon.in", title=title, price=price,
                                          url=f"https://www.amazon.in/dp/{asin}", rating=rating))
        seen_asins.add(asin)
    return results


def scrape_amazon_html(query: str) -> List[Dict[str, Any]]:
    url = f"https://www.amazon.in/s?k={urllib.parse.quote_plus(query)}"
    try:
        response = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
            "Accept-Language": "en-IN,en;q=0.9",
        }, timeout=10)
        response.raise_for_status()
        results = _extract_amazon_html(response.text)
        if results:
            return results
        return [{"site": "Amazon.in", "error": True, "message": "No product cards were available"}]
    except requests.RequestException as exc:
        return [{"site": "Amazon.in", "error": True, "message": str(exc)}]

def _extract_amazon(page, site_name: str) -> List[Dict[str, Any]]:
    results = []
    cards = page.locator("div[data-component-type='s-search-result']").all()
    seen_asins = set()
    
    for i in range(min(30, len(cards))):
        try:
            card = cards[i]
            asin = card.get_attribute("data-asin")
            if not asin or asin in seen_asins:
                continue
            
            # Amazon may put only the brand in h2; the product link has the full title.
            title = ""
            for ts in ['[data-cy="title-recipe"] a[href*="/dp/"]', "h2 a", "h2", "img[alt]"]:
                el = card.locator(ts).first
                if el.count() > 0:
                    temp_title = el.get_attribute("alt") if ts == "img[alt]" else el.inner_text()
                    if temp_title and len(temp_title.strip()) > 10:
                        title = re.sub(r'^Sponsored Ad -\s*', '', temp_title.strip(), flags=re.I)
                        break
            
            # Price
            price = 0.0
            for ps in [".a-price .a-offscreen", ".a-price-whole", ".a-color-price"]:
                price_el = card.locator(ps).first
                if price_el.count() > 0:
                    pt = price_el.inner_text() or price_el.text_content()
                    if pt:
                        price = extract_price(pt)
                        if price > 0:
                            break
            
            # ASIN gives a direct product link, including for sponsored listings.
            href = f"https://www.amazon.in/dp/{asin}"
            
            # Rating
            rating = 0.0
            rating_el = card.locator("span.a-icon-alt").first
            if rating_el.count() > 0:
                r_text = rating_el.inner_text() or rating_el.text_content()
                if r_text:
                    r_match = re.search(r'(\d+(\.\d+)?)', r_text)
                    rating = float(r_match.group(1)) if r_match else 0.0
            
            if title and price > 0:
                results.append(_make_product_dict(site_name, title, price, href, rating))
                seen_asins.add(asin)
        except:
            continue
    
    return results


def _extract_flipkart(page, site_name: str) -> List[Dict[str, Any]]:
    results = []
    
    # Close login popup if it appears
    try:
        close_btn = page.locator("button._2KpZ6l._2doB4z, button[class*='close'], span[role='button']").first
        if close_btn.count() > 0:
            close_btn.click()
            page.wait_for_timeout(500)
    except:
        pass
    
    # Flipkart uses various card selectors; try the most common ones
    card_selectors = [
        "div[data-id]",
        "div._1AtVbE",
        "div._1xHGtK._373qXS",
        "div._2kHMtA",
    ]
    
    cards = []
    for sel in card_selectors:
        cards = page.locator(sel).all()
        if len(cards) > 0:
            break
    
    for i in range(min(30, len(cards))):
        try:
            card = cards[i]
            
            # Title — try multiple selectors
            title = ""
            for ts in ["img[alt]", "a[title]", "div.KzDlHZ", "div._4rR01T", "a._2rpwqI"]:
                el = card.locator(ts).first
                if el.count() > 0:
                    title = el.get_attribute("alt") or el.get_attribute("title") or el.inner_text()
                    if title and len(title.strip()) > 5:
                        break
            
            # Price
            price = 0.0
            for ps in ["div.Nx9bqj", "div._30jeq3", "div._25b18c div._30jeq3"]:
                el = card.locator(ps).first
                if el.count() > 0:
                    price = extract_price(el.inner_text())
                    if price > 0:
                        break
            if not price:
                # Flipkart rotates CSS class names; use the first rupee amount in the card.
                match = re.search(r'₹\s*([\d,]+(?:\.\d+)?)', card.inner_text())
                if match:
                    price = float(match.group(1).replace(',', ''))
            
            # Link
            href = ""
            link_el = card.locator('a[href*="/p/"]').first
            if link_el.count() > 0:
                href = link_el.get_attribute("href") or ""
                href = urljoin("https://www.flipkart.com", href)
            
            # Rating
            rating = 0.0
            for rs in ["div._3LWZlK", "div.XQDdHH"]:
                el = card.locator(rs).first
                if el.count() > 0:
                    r_match = re.search(r'(\d+(\.\d+)?)', el.inner_text())
                    rating = float(r_match.group(1)) if r_match else 0.0
                    break
            
            if title and price > 0 and href:
                results.append(_make_product_dict(site_name, title, price, href, rating))
        except:
            continue
    
    return results


def _extract_reliance(page, site_name: str) -> List[Dict[str, Any]]:
    results = []
    
    card_selectors = [
        "div.sp__product",
        "div.sp.grid",
        "li.product",
        "div[class*='product-card']",
    ]
    
    cards = []
    for sel in card_selectors:
        cards = page.locator(sel).all()
        if len(cards) > 0:
            break
    
    # Fallback: try to grab all links that look like product listings
    if not cards:
        cards = page.locator("div.grid div a[href*='/']").all()
    
    for i in range(min(5, len(cards))):
        try:
            card = cards[i]
            
            title = ""
            for ts in ["p.sp__name", "span.sp__name", "p[class*='name']", "h3", "div[class*='title']"]:
                el = card.locator(ts).first
                if el.count() > 0:
                    title = el.inner_text()
                    if title:
                        break
            
            price = 0.0
            for ps in ["span[class*='price']", "div[class*='price']", "span.amount"]:
                el = card.locator(ps).first
                if el.count() > 0:
                    price = extract_price(el.inner_text())
                    if price > 0:
                        break
            
            href = ""
            link_el = card.locator("a[href]").first
            if link_el.count() > 0:
                href = link_el.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = "https://www.reliancedigital.in" + href
            
            if title:
                results.append(_make_product_dict(site_name, title, price, href))
        except:
            continue
    
    return results


def _extract_croma(page, site_name: str) -> List[Dict[str, Any]]:
    results = []
    
    card_selectors = [
        "div.product-item",
        "li.product-item",
        "div[class*='product-card']",
        "div.cp-product",
    ]
    
    cards = []
    for sel in card_selectors:
        cards = page.locator(sel).all()
        if len(cards) > 0:
            break
    
    for i in range(min(5, len(cards))):
        try:
            card = cards[i]
            
            title = ""
            for ts in ["h3.product-title a", "h3 a", "a[class*='product-title']", "span[class*='name']"]:
                el = card.locator(ts).first
                if el.count() > 0:
                    title = el.inner_text()
                    if title:
                        break
            
            price = 0.0
            for ps in ["span.amount", "span[class*='price']", "div[class*='price']"]:
                el = card.locator(ps).first
                if el.count() > 0:
                    price = extract_price(el.inner_text())
                    if price > 0:
                        break
            
            href = ""
            link_el = card.locator("a[href]").first
            if link_el.count() > 0:
                href = link_el.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = "https://www.croma.com" + href
            
            if title:
                results.append(_make_product_dict(site_name, title, price, href))
        except:
            continue
    
    return results


def _extract_vijay_sales(page, site_name: str) -> List[Dict[str, Any]]:
    results = []
    
    card_selectors = [
        "div.Vj-prod-box",
        "div[class*='product-card']",
        "div.product-item",
        "li.product-item",
    ]
    
    cards = []
    for sel in card_selectors:
        cards = page.locator(sel).all()
        if len(cards) > 0:
            break
    
    for i in range(min(5, len(cards))):
        try:
            card = cards[i]
            
            title = ""
            for ts in ["h2", "h3", "a[class*='prod']", "div[class*='title']", "span[class*='name']"]:
                el = card.locator(ts).first
                if el.count() > 0:
                    title = el.inner_text()
                    if title:
                        break
            
            price = 0.0
            for ps in ["span.vj-sell-price", "span[class*='price']", "div[class*='price']"]:
                el = card.locator(ps).first
                if el.count() > 0:
                    price = extract_price(el.inner_text())
                    if price > 0:
                        break
            
            href = ""
            link_el = card.locator("a[href]").first
            if link_el.count() > 0:
                href = link_el.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = "https://www.vijaysales.com" + href
            
            if title:
                results.append(_make_product_dict(site_name, title, price, href))
        except:
            continue
    
    return results


# ─── Public scraper functions ────────────────────────────────────────────────

def scrape_amazon(query: str) -> List[Dict[str, Any]]:
    return _scrape_with_own_browser(query, "Amazon.in", "https://www.amazon.in/s?k={query}", _extract_amazon)

def scrape_flipkart(query: str) -> List[Dict[str, Any]]:
    return _scrape_with_own_browser(query, "Flipkart", "https://www.flipkart.com/search?q={query}", _extract_flipkart)

def scrape_reliance(query: str) -> List[Dict[str, Any]]:
    return _scrape_with_own_browser(query, "Reliance Digital", "https://www.reliancedigital.in/search?q={query}", _extract_reliance)

def scrape_croma(query: str) -> List[Dict[str, Any]]:
    return _scrape_with_own_browser(query, "Croma", "https://www.croma.com/search/?text={query}", _extract_croma)

def scrape_vijay_sales(query: str) -> List[Dict[str, Any]]:
    return _scrape_with_own_browser(query, "Vijay Sales", "https://www.vijaysales.com/search?q={query}", _extract_vijay_sales)


def _run_sequential_scrape(query: str, sites: List[Any]) -> List[Dict[str, Any]]:
    all_results = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, timeout=10000)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-IN",
                extra_http_headers={
                    "Accept-Language": "en-IN,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                }
            )
            
            for site_name, url_template, scrape_fn in sites:
                results = []
                for attempt in range(1):
                    page = None
                    try:
                        page = context.new_page()
                        url = url_template.format(query=urllib.parse.quote_plus(query))
                        print(f"[SCRAPER] {site_name} navigating to: {url}")
                        
                        response = page.goto(url, timeout=10000, wait_until="domcontentloaded")
                        if response and response.status >= 400:
                            raise RuntimeError(f"Retailer returned HTTP {response.status}")
                        page.wait_for_timeout(1500)
                        
                        results = scrape_fn(page, site_name)
                        print(f"[SCRAPER] {site_name} found {len(results)} results")
                        for r in results[:2]:
                            if not r.get("error"):
                                print(f"  -> {ascii(r.get('title', '')[:60])} | Rs.{r.get('price', 0)}")
                        
                        page.close()
                        break
                    except Exception as e:
                        print(f"[SCRAPER] {site_name} ERROR (attempt {attempt+1}): {e}")
                        if page:
                            try: page.close()
                            except: pass
                        all_results.append({"site": site_name, "error": True, "message": str(e)})
                        break
                
                if results:
                    all_results.extend(results)
                    
            browser.close()
    except Exception as e:
        print(f"[SCRAPER] Global ERROR: {e}")
        all_results.append({"site": "System", "error": True, "message": f"Global Scraper Error: {str(e)}"})
        
    return all_results


def scrape_all_sequential(query: str) -> List[Dict[str, Any]]:
    """Fetch Amazon's HTML, then search Flipkart in a bounded browser session."""
    amazon_results = scrape_amazon_html(query)
    sites = [
        ("Flipkart", "https://www.flipkart.com/search?q={query}", _extract_flipkart),
    ]
    
    print(f"[SCRAPER] Starting sequential scraping for query: '{query}'")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_sequential_scrape, query, sites)
        try:
            return amazon_results + future.result(timeout=35)
        except Exception as e:
            return amazon_results + [{"site": "Flipkart", "error": True, "message": f"Browser error: {str(e)}"}]
