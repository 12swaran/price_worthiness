import sys, codecs
if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

from playwright.sync_api import sync_playwright
import urllib.parse

def deep_inspect():
    query = "iPhone 16"
    encoded = urllib.parse.quote_plus(query)
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-IN",
            extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"}
        )
        page = context.new_page()
        
        # ── AMAZON ──
        print("="*60)
        print("AMAZON - Finding the REAL title element")
        print("="*60)
        page.goto(f"https://www.amazon.in/s?k={encoded}", timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        
        card = page.locator("div[data-component-type='s-search-result']").first
        if card.count() > 0:
            # Try many possible title selectors
            candidates = [
                "h2 + div span", "h2 ~ div span", "h2 ~ span",
                "a.a-link-normal span.a-text-normal",
                "div.a-section a span.a-text-normal",
                "span.a-size-base-plus.a-color-base.a-text-normal",
                "span.a-size-medium.a-color-base.a-text-normal",
                "div.puis-padding-right-small span.a-text-normal",
                "div.puisg-col-inner span.a-text-normal",
                "a.a-link-normal.s-line-clamp-2",
                "a.a-link-normal[href] span.a-text-normal",
                "div[data-cy='title-recipe'] a span",
                "div[data-cy='title-recipe'] h2 + a span",
                "div[data-cy='title-recipe']",
                ".s-title-instructions-style a span",
                ".a-size-base-plus",
            ]
            for sel in candidates:
                el = card.locator(sel).first
                if el.count() > 0:
                    txt = el.inner_text()[:120]
                    if len(txt) > 10:
                        print(f"  MATCH: '{sel}' -> '{txt}'")
            
            # Also dump the card's direct children structure
            children = card.locator("> div > div").all()
            print(f"\n  Card has {len(children)} top-level div>div children")
            for i, child in enumerate(children[:5]):
                txt = child.inner_text()[:150]
                print(f"  Child {i}: {txt}")
            
            # Try finding the link that contains the full product title
            links = card.locator("a[href*='/dp/']").all()
            print(f"\n  Found {len(links)} product links (a[href*='/dp/'])")
            for i, link in enumerate(links[:5]):
                txt = link.inner_text()[:150]
                href = link.get_attribute("href")[:80] if link.get_attribute("href") else ""
                print(f"  Link {i}: text='{txt}' href='{href}'")
        
        page.close()
        
        # ── FLIPKART ──
        print("\n" + "="*60)
        print("FLIPKART - Finding the REAL title element")
        print("="*60)
        page2 = context.new_page()
        page2.goto(f"https://www.flipkart.com/search?q={encoded}", timeout=30000, wait_until="domcontentloaded")
        page2.wait_for_timeout(5000)
        
        # Close popup
        try:
            close = page2.locator("button._2KpZ6l._2doB4z, button[class*='close'], span[role='button']").first
            if close.count() > 0:
                close.click()
                page2.wait_for_timeout(500)
        except:
            pass
        
        card = page2.locator("div[data-id]").first
        if card.count() > 0:
            candidates = [
                "a[title]", "div.KzDlHZ", "div._4rR01T", "a._2rpwqI",
                "a.wjcEIp", "div.syl9yP", "a.CGtC98", "div.Xpx9id",
                "a.IRpwTa", "a.s1Q9rs", "a.WKTcLC",
                # Generic
                "a[class] > div.KzDlHZ",
                "a > div.KzDlHZ",
            ]
            for sel in candidates:
                el = card.locator(sel).first
                if el.count() > 0:
                    txt = el.inner_text()[:120]
                    title_attr = el.get_attribute("title") if el.count() > 0 else ""
                    print(f"  MATCH: '{sel}' -> text='{txt}' title_attr='{title_attr}'")
            
            # Dump all <a> tags in the card
            all_a = card.locator("a").all()
            print(f"\n  Card has {len(all_a)} <a> tags")
            for i, a in enumerate(all_a[:8]):
                txt = a.inner_text()[:100]
                href = (a.get_attribute("href") or "")[:80]
                cls = (a.get_attribute("class") or "")[:60]
                title_attr = a.get_attribute("title") or ""
                if txt and len(txt) > 5:
                    print(f"  a[{i}]: class='{cls}' title='{title_attr}' text='{txt}' href='{href}'")
            
            # Also try price selectors
            print("\n  PRICE selectors:")
            price_candidates = ["div.Nx9bqj", "div._30jeq3", "div._25b18c div._30jeq3",
                                "div.Nx9bqj._4b5DiR", "span._30jeq3"]
            for sel in price_candidates:
                el = card.locator(sel).first
                if el.count() > 0:
                    print(f"  PRICE MATCH: '{sel}' -> '{el.inner_text()}'")
        
        page2.close()
        browser.close()

deep_inspect()
