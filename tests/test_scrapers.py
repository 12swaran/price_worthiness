"""
Tests for app.tools.scrapers — Price extraction utility and scraper structure.
Live scraping tests are NOT included (they'd be flaky). Instead we test:
- extract_price parsing
- _make_product_dict structure
- scrape_all_parallel error handling (mocked)
"""
import pytest
from unittest.mock import patch, MagicMock
from app.tools.scrapers import extract_price, _make_product_dict, scrape_all_parallel


# ─── extract_price ────────────────────────────────────────────────────────────

class TestExtractPrice:
    def test_rupee_symbol_with_comma(self):
        assert extract_price("₹24,990") == 24990.0

    def test_rs_prefix(self):
        assert extract_price("Rs. 24990.00") == 24990.0

    def test_rs_without_dot(self):
        assert extract_price("Rs 15000") == 15000.0

    def test_plain_number(self):
        assert extract_price("65000") == 65000.0

    def test_number_with_decimal(self):
        assert extract_price("₹1,499.99") == 1499.99

    def test_empty_string(self):
        assert extract_price("") == 0.0

    def test_none_input(self):
        assert extract_price(None) == 0.0

    def test_no_number_in_text(self):
        assert extract_price("Price not available") == 0.0

    def test_multiple_numbers_takes_first(self):
        result = extract_price("₹24,990 (was ₹29,990)")
        assert result == 24990.0

    def test_large_price(self):
        assert extract_price("₹1,50,000") == 150000.0

    def test_just_currency_symbol(self):
        assert extract_price("₹") == 0.0

    def test_whitespace_around(self):
        assert extract_price("  ₹ 24,990  ") == 24990.0


# ─── _make_product_dict ──────────────────────────────────────────────────────

class TestMakeProductDict:
    def test_returns_correct_structure(self):
        result = _make_product_dict("Amazon.in", "iPhone 15", 65000.0, "https://amazon.in/iphone")
        assert result["site"] == "Amazon.in"
        assert result["title"] == "iPhone 15"
        assert result["price"] == 65000.0
        assert result["currency"] == "INR"
        assert result["url"] == "https://amazon.in/iphone"
        assert result["availability"] == "In Stock"
        assert result["error"] is False

    def test_out_of_stock_when_price_zero(self):
        result = _make_product_dict("Flipkart", "Phone", 0.0, "")
        assert result["availability"] == "Out of Stock"

    def test_strips_title_whitespace(self):
        result = _make_product_dict("Test", "  iPhone 15  ", 1000, "")
        assert result["title"] == "iPhone 15"

    def test_empty_title(self):
        result = _make_product_dict("Test", "", 1000, "")
        assert result["title"] == ""

    def test_none_title_handled(self):
        # title is None → strip() would fail; but function does `title.strip() if title`
        result = _make_product_dict("Test", None, 1000, "")
        assert result["title"] == ""

    def test_rating_default(self):
        result = _make_product_dict("Test", "Product", 1000, "")
        assert result["rating"] == 0.0

    def test_rating_passed(self):
        result = _make_product_dict("Test", "Product", 1000, "", rating=4.5)
        assert result["rating"] == 4.5

    def test_reviews_count_is_none(self):
        result = _make_product_dict("Test", "Product", 1000, "")
        assert result["reviews_count"] is None


# ─── scrape_all_parallel (mocked) ─────────────────────────────────────────────

class TestScrapeAllParallel:
    @patch("app.tools.scrapers.scrape_amazon")
    @patch("app.tools.scrapers.scrape_flipkart")
    @patch("app.tools.scrapers.scrape_reliance")
    @patch("app.tools.scrapers.scrape_croma")
    @patch("app.tools.scrapers.scrape_vijay_sales")
    def test_aggregates_all_results(self, mock_vj, mock_cr, mock_rel, mock_fk, mock_amz):
        mock_amz.return_value = [{"site": "Amazon.in", "title": "P1", "error": False}]
        mock_fk.return_value = [{"site": "Flipkart", "title": "P2", "error": False}]
        mock_rel.return_value = [{"site": "Reliance", "title": "P3", "error": False}]
        mock_cr.return_value = [{"site": "Croma", "title": "P4", "error": False}]
        mock_vj.return_value = [{"site": "Vijay", "title": "P5", "error": False}]

        results = scrape_all_parallel("test query")
        assert len(results) == 5
        sites = {r["site"] for r in results}
        assert "Amazon.in" in sites

    @patch("app.tools.scrapers.scrape_amazon")
    @patch("app.tools.scrapers.scrape_flipkart")
    @patch("app.tools.scrapers.scrape_reliance")
    @patch("app.tools.scrapers.scrape_croma")
    @patch("app.tools.scrapers.scrape_vijay_sales")
    def test_handles_scraper_exception(self, mock_vj, mock_cr, mock_rel, mock_fk, mock_amz):
        """If one scraper throws, others should still return results."""
        mock_amz.side_effect = Exception("Browser crashed")
        mock_fk.return_value = [{"site": "Flipkart", "title": "P2", "error": False}]
        mock_rel.return_value = [{"site": "Reliance", "title": "P3", "error": False}]
        mock_cr.return_value = [{"site": "Croma", "title": "P4", "error": False}]
        mock_vj.return_value = [{"site": "Vijay", "title": "P5", "error": False}]

        results = scrape_all_parallel("test query")
        # 4 normal + 1 error entry
        assert len(results) == 5
        error_results = [r for r in results if r.get("error")]
        assert len(error_results) == 1

    @patch("app.tools.scrapers.scrape_amazon")
    @patch("app.tools.scrapers.scrape_flipkart")
    @patch("app.tools.scrapers.scrape_reliance")
    @patch("app.tools.scrapers.scrape_croma")
    @patch("app.tools.scrapers.scrape_vijay_sales")
    def test_all_scrapers_fail(self, mock_vj, mock_cr, mock_rel, mock_fk, mock_amz):
        """All scrapers failing should return 5 error entries."""
        mock_amz.side_effect = Exception("Fail 1")
        mock_fk.side_effect = Exception("Fail 2")
        mock_rel.side_effect = Exception("Fail 3")
        mock_cr.side_effect = Exception("Fail 4")
        mock_vj.side_effect = Exception("Fail 5")

        results = scrape_all_parallel("test query")
        assert len(results) == 5
        assert all(r.get("error") for r in results)

    @patch("app.tools.scrapers.scrape_amazon")
    @patch("app.tools.scrapers.scrape_flipkart")
    @patch("app.tools.scrapers.scrape_reliance")
    @patch("app.tools.scrapers.scrape_croma")
    @patch("app.tools.scrapers.scrape_vijay_sales")
    def test_returns_multiple_results_per_site(self, mock_vj, mock_cr, mock_rel, mock_fk, mock_amz):
        mock_amz.return_value = [
            {"site": "Amazon.in", "title": f"P{i}", "error": False} for i in range(5)
        ]
        mock_fk.return_value = []
        mock_rel.return_value = []
        mock_cr.return_value = []
        mock_vj.return_value = []

        results = scrape_all_parallel("test")
        amazon_results = [r for r in results if r.get("site") == "Amazon.in"]
        assert len(amazon_results) == 5
