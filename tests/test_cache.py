"""
Tests for app.utils.cache — TTL in-memory cache.
Covers: set, get (hit), get (miss), expiry (TTL), clear, and key isolation.
"""
import time
import pytest
from unittest.mock import patch
from app.utils.cache import get_cached, set_cache, clear_cache, _CACHE, TTL_SECONDS


@pytest.fixture(autouse=True)
def _clean_cache():
    """Ensure cache is empty before and after every test."""
    _CACHE.clear()
    yield
    _CACHE.clear()


# ─── Basic get/set ────────────────────────────────────────────────────────────

class TestCacheBasics:
    def test_get_returns_none_when_empty(self):
        assert get_cached("amazon", "iphone 15") is None

    def test_set_then_get_returns_value(self):
        data = [{"title": "iPhone 15", "price": 65000}]
        set_cache("amazon", "iphone 15", data)
        result = get_cached("amazon", "iphone 15")
        assert result == data

    def test_get_different_site_returns_none(self):
        set_cache("amazon", "iphone 15", [{"price": 65000}])
        assert get_cached("flipkart", "iphone 15") is None

    def test_get_different_query_returns_none(self):
        set_cache("amazon", "iphone 15", [{"price": 65000}])
        assert get_cached("amazon", "galaxy s24") is None


# ─── TTL expiry ───────────────────────────────────────────────────────────────

class TestCacheTTL:
    def test_ttl_is_ten_minutes(self):
        assert TTL_SECONDS == 600

    def test_get_expired_returns_none(self):
        set_cache("amazon", "iphone 15", [{"price": 65000}])
        # Simulate time passing beyond TTL
        with patch("app.utils.cache.time") as mock_time:
            # set_cache records time.time() at set-time; we already called it for real.
            # So we patch time.time() on the GET call to be way in the future.
            mock_time.time.return_value = time.time() + TTL_SECONDS + 1
            result = get_cached("amazon", "iphone 15")
        assert result is None

    def test_get_just_before_expiry_returns_value(self):
        now = time.time()
        with patch("app.utils.cache.time") as mock_time:
            mock_time.time.return_value = now
            set_cache("amazon", "q", "data")
            mock_time.time.return_value = now + TTL_SECONDS - 1
            result = get_cached("amazon", "q")
        assert result == "data"


# ─── Clear ────────────────────────────────────────────────────────────────────

class TestCacheClear:
    def test_clear_removes_all_entries(self):
        set_cache("a", "q1", "v1")
        set_cache("b", "q2", "v2")
        clear_cache()
        assert get_cached("a", "q1") is None
        assert get_cached("b", "q2") is None

    def test_clear_on_empty_cache_no_error(self):
        clear_cache()  # Should not raise


# ─── Edge cases ───────────────────────────────────────────────────────────────

class TestCacheEdgeCases:
    def test_overwrite_same_key(self):
        set_cache("s", "q", "old")
        set_cache("s", "q", "new")
        assert get_cached("s", "q") == "new"

    def test_cache_stores_various_types(self):
        """Cache should accept lists, dicts, strings, numbers."""
        for val in [42, "hello", {"key": "val"}, [1, 2, 3], None]:
            set_cache("s", "q", val)
            assert get_cached("s", "q") == val

    def test_empty_strings_as_keys(self):
        set_cache("", "", "val")
        assert get_cached("", "") == "val"
