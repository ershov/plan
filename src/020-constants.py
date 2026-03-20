# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAFE_BUILTINS = {
    "len": len, "any": any, "all": all,
    "min": min, "max": max, "sorted": sorted,
    "int": int, "str": str, "float": float,
    "True": True, "False": False, "None": None,
}

LINK_MIRRORS = {
    "blocked": "blocking",
    "blocking": "blocked",
    "related": "related",
    "derived": "derived-from",
    "derived-from": "derived",
    "caused": "caused-by",
    "caused-by": "caused",
}

ACTIVE_STATUSES = {"open", "in-progress", "assigned", "blocked", "reviewing", "testing"}
DEFERRED_STATUSES = {"backlog", "deferred", "future", "someday", "wishlist", "paused", "on-hold"}
OPEN_STATUSES = ACTIVE_STATUSES | DEFERRED_STATUSES
