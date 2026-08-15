import urllib.parse
import re
import time
import concurrent.futures
from typing import List, Dict, Any
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
            browser = pw.chromium.launch(headless=True)
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
                    print(f"  -> {r.get('title', '')[:60]} | Rs.{r.get('price', 0)}")
            
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

def _extract_amazon(page, site_name: str) -> List[Dict[str, Any]]:
    results = []
    cards = page.locator("div[data-component-type='s-search-result']").all()
    
    for i in range(min(5, len(cards))):
        try:
            card = cards[i]
            
            # Title
            title = ""
            for ts in ["h2 a span", "h2 span.a-text-normal", "span.a-size-medium.a-text-normal", "span.a-text-normal", "h2"]:
                el = card.locator(ts).first
                if el.count() > 0:
                    temp_title = el.inner_text() or el.text_content()
                    if temp_title and len(temp_title.strip()) > 10:
                        title = temp_title.strip()
                        break
                    elif temp_title and not title:
                        title = temp_title.strip()
            
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
            
            # Link
            href = ""
            for ls in ["h2 a", "a.a-link-normal"]:
                link_el = card.locator(ls).first
                if link_el.count() > 0:
                    href = link_el.get_attribute("href") or ""
                    if href:
                        if not href.startswith("http"):
                            href = "https://www.amazon.in" + href
                        break
            
            # Rating
            rating = 0.0
            rating_el = card.locator("span.a-icon-alt").first
            if rating_el.count() > 0:
                r_text = rating_el.inner_text() or rating_el.text_content()
                if r_text:
                    r_match = re.search(r'(\d+(\.\d+)?)', r_text)
                    rating = float(r_match.group(1)) if r_match else 0.0
            
            if title:
                results.append(_make_product_dict(site_name, title, price, href, rating))
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
    
    for i in range(min(5, len(cards))):
        try:
            card = cards[i]
            
            # Title — try multiple selectors
            title = ""
            for ts in ["a[title]", "div.KzDlHZ", "div._4rR01T", "a._2rpwqI"]:
                el = card.locator(ts).first
                if el.count() > 0:
                    title = el.get_attribute("title") or el.inner_text()
                    if title:
                        break
            
            # Price
            price = 0.0
            for ps in ["div.Nx9bqj", "div._30jeq3", "div._25b18c div._30jeq3"]:
                el = card.locator(ps).first
                if el.count() > 0:
                    price = extract_price(el.inner_text())
                    if price > 0:
                        break
            
            # Link
            href = ""
            link_el = card.locator("a[href]").first
            if link_el.count() > 0:
                href = link_el.get_attribute("href") or ""
                if href and not href.startswith("http"):
                    href = "https://www.flipkart.com" + href
            
            # Rating
            rating = 0.0
            for rs in ["div._3LWZlK", "div.XQDdHH"]:
                el = card.locator(rs).first
                if el.count() > 0:
                    r_match = re.search(r'(\d+(\.\d+)?)', el.inner_text())
                    rating = float(r_match.group(1)) if r_match else 0.0
                    break
            
            if title:
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


def scrape_all_parallel(query: str) -> List[Dict[str, Any]]:
    """Runs all 5 scrapers in parallel — each with its own Playwright browser."""
    scrapers = [
        scrape_amazon,
        scrape_flipkart,
        scrape_reliance,
        scrape_croma,
        scrape_vijay_sales,
    ]
    
    all_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(scraper, query): scraper for scraper in scrapers}
        for future in concurrent.futures.as_completed(futures):
            try:
                results = future.result(timeout=60)
                all_results.extend(results)
            except Exception as e:
                scraper_name = getattr(futures[future], '__name__', str(futures[future]))
                all_results.append({"site": scraper_name, "error": True, "message": str(e)})
    
    return all_results
