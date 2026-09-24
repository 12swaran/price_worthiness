"""Focused checks for price parsing and the retailer layouts used by live search."""

import pytest
from playwright.sync_api import sync_playwright

from app.tools.scrapers import (
    _extract_amazon,
    _extract_flipkart,
    _make_product_dict,
    extract_price,
)


@pytest.mark.parametrize("text,expected", [
    ("₹24,990", 24990.0),
    ("Rs. 24990.00", 24990.0),
    ("₹1,50,000", 150000.0),
    ("", 0.0),
    (None, 0.0),
])
def test_extract_price(text, expected):
    assert extract_price(text) == expected


def test_product_dict_has_price_and_direct_link():
    result = _make_product_dict("Amazon.in", " iPhone 17 ", 98900,
                                "https://www.amazon.in/dp/B0FQFYXCC4")
    assert result["title"] == "iPhone 17"
    assert result["price"] == 98900
    assert result["url"] == "https://www.amazon.in/dp/B0FQFYXCC4"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Playwright Chromium unavailable: {exc}")
        yield browser
        browser.close()


def test_amazon_uses_full_title_and_asin_link(browser):
    page = browser.new_page()
    page.set_content('''
        <div data-component-type="s-search-result" data-asin="B0FQFYXCC4">
          <h2>Apple</h2>
          <div data-cy="title-recipe">
            <a href="/iPhone-17/dp/B0FQFYXCC4">Apple iPhone 17 256 GB</a>
          </div>
          <span class="a-price"><span class="a-offscreen">₹98,900</span></span>
        </div>
    ''')
    results = _extract_amazon(page, "Amazon.in")
    assert len(results) == 1
    assert results[0]["title"] == "Apple iPhone 17 256 GB"
    assert results[0]["price"] == 98900
    assert results[0]["url"] == "https://www.amazon.in/dp/B0FQFYXCC4"
    page.close()


def test_flipkart_uses_image_title_and_visible_rupee_price(browser):
    page = browser.new_page()
    page.set_content('''
        <div data-id="MOBHQV9YAZYYWY8A">
          <a href="/apple-iphone-17-white-256-gb/p/item123">
            <img alt="Apple iPhone 17 (White, 256 GB)">
          </a>
          <span>4.6 Ratings</span>
          <div>₹99,900</div>
          <div>Up to ₹78,550 off on exchange</div>
        </div>
    ''')
    results = _extract_flipkart(page, "Flipkart")
    assert len(results) == 1
    assert results[0]["title"] == "Apple iPhone 17 (White, 256 GB)"
    assert results[0]["price"] == 99900
    assert results[0]["url"].startswith("https://www.flipkart.com/apple-iphone-17")
    page.close()
