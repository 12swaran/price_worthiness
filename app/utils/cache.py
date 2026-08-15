import time
from typing import Dict, Any, Tuple

# In-memory dictionary: (site, query) -> (timestamp, results)
_CACHE: Dict[Tuple[str, str], Tuple[float, Any]] = {}

TTL_SECONDS = 600  # 10 minutes

def get_cached(site: str, query: str) -> Any:
    """Returns cached results if valid, else None."""
    key = (site, query)
    if key in _CACHE:
        timestamp, results = _CACHE[key]
        if time.time() - timestamp < TTL_SECONDS:
            return results
        else:
            del _CACHE[key]
    return None

def set_cache(site: str, query: str, results: Any):
    """Stores results in cache."""
    _CACHE[(site, query)] = (time.time(), results)

def clear_cache():
    """Clears the entire cache."""
    _CACHE.clear()
