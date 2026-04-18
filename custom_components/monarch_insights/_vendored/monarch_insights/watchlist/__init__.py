"""Watchlist tracking — symbols you want price/news/signals on, even if you don't own them.

The watchlist is just a small SQLite table living next to the supplements DB. Schema:

    watchlist(symbol PRIMARY KEY, added_at, target_price, target_kind, notes, tags_json)

``target_kind`` is one of ``buy_below`` / ``sell_above`` / ``alert_move`` so a single
record can represent "buy NVDA below $150", "trim AAPL above $260", or "wake me up
when TSLA moves more than 5% in a day". The signal engine reads this list to decide
what to score nightly.
"""

from monarch_insights.watchlist.store import WatchlistEntry, WatchlistStore

__all__ = ["WatchlistEntry", "WatchlistStore"]
