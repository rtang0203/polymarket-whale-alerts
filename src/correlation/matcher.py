"""
Match articles to whale trades based on keyword overlap.

Finds trades that occurred before related news articles,
indicating potential informed trading.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .keywords import (
    extract_keywords,
    should_skip_market,
    detect_market_type,
    get_entity_keywords,
)


@dataclass
class CorrelationMatch:
    """Represents a potential correlation between a trade and article."""

    # Trade info
    trade_id: int
    trade_timestamp: str
    wallet_address: str
    market_title: str
    trade_value: float
    trade_side: str
    trade_outcome: str

    # Article info
    article_url: str
    article_title: str
    article_source: str
    article_scraped_at: str

    # Match metadata
    matched_keywords: list[str]
    time_delta_seconds: int  # Negative = trade before article
    confidence: str  # 'high', 'medium', 'low'
    market_type: str


def calculate_time_delta(trade_timestamp: str, article_scraped_at: str) -> int:
    """
    Calculate seconds between trade and article.

    Args:
        trade_timestamp: ISO format timestamp of trade
        article_scraped_at: ISO format timestamp of article scrape

    Returns:
        Seconds difference (negative = trade was before article)
    """
    try:
        # Handle various ISO format variations
        trade_ts = trade_timestamp.replace("Z", "+00:00")
        article_ts = article_scraped_at.replace("Z", "+00:00")

        # Try parsing with timezone
        try:
            trade_dt = datetime.fromisoformat(trade_ts)
        except ValueError:
            # Fallback: assume local time if no timezone
            trade_dt = datetime.fromisoformat(trade_timestamp.split("+")[0].split("Z")[0])

        try:
            article_dt = datetime.fromisoformat(article_ts)
        except ValueError:
            article_dt = datetime.fromisoformat(article_scraped_at.split("+")[0].split("Z")[0])

        # If one has timezone and other doesn't, strip both
        if trade_dt.tzinfo is not None and article_dt.tzinfo is None:
            trade_dt = trade_dt.replace(tzinfo=None)
        elif trade_dt.tzinfo is None and article_dt.tzinfo is not None:
            article_dt = article_dt.replace(tzinfo=None)

        delta = trade_dt - article_dt
        return int(delta.total_seconds())

    except Exception:
        # If parsing fails, return 0 (will likely be filtered out)
        return 0


def calculate_match_confidence(
    matched_keywords: list[str],
    market_type: str,
    time_delta_seconds: int,
    has_entity_match: bool = False,
) -> str:
    """
    Determine confidence level based on match quality.

    Rules:
    - high: 3+ keyword matches AND non-sports market
    - high: 2+ keywords AND trade within 6 hours before article AND non-sports
    - high: Entity name match (person/company) with 2+ total keywords
    - medium: 2+ keywords for any market type
    - medium: Sports market with 3+ keywords
    - low: Everything else that passed minimum threshold

    Args:
        matched_keywords: List of keywords that matched
        market_type: 'sports', 'politics', 'crypto', 'other'
        time_delta_seconds: Time between trade and article (negative = trade first)
        has_entity_match: Whether an entity (name) was matched

    Returns:
        'high', 'medium', or 'low'
    """
    num_keywords = len(matched_keywords)
    is_sports = market_type == "sports"
    hours_before = abs(time_delta_seconds) / 3600

    # Sports markets have lower confidence due to high false positive rate
    if is_sports:
        if num_keywords >= 4:
            return "medium"
        return "low"

    # Entity match (person/company name) is strong signal
    if has_entity_match and num_keywords >= 2:
        return "high"

    # 3+ keywords on non-sports is high confidence
    if num_keywords >= 3:
        return "high"

    # 2 keywords within 6 hours is high confidence
    if num_keywords >= 2 and hours_before <= 6:
        return "high"

    # 2 keywords is medium confidence
    if num_keywords >= 2:
        return "medium"

    return "low"


def find_matches(
    article_keywords: set[str],
    article_entities: set[str],
    article_title: str,
    article_url: str,
    article_source: str,
    article_scraped_at: str,
    trades: list[dict],
    min_keyword_overlap: int = 2,
) -> list[CorrelationMatch]:
    """
    Find trades that match an article based on keyword overlap.

    Args:
        article_keywords: Extracted keywords from article title
        article_entities: Entity keywords (names) from article
        article_title: Original article title
        article_url: Article URL
        article_source: Article source (BBC, AP, etc.)
        article_scraped_at: When article was scraped
        trades: List of trade dicts from whale_trades table
        min_keyword_overlap: Minimum keywords required to match (default 2)

    Returns:
        List of CorrelationMatch objects for trades that match
    """
    matches = []

    for trade in trades:
        # Check if market should be skipped
        market_title = trade.get("market_title", "")
        should_skip, _ = should_skip_market(market_title)
        if should_skip:
            continue

        # Extract keywords from market title
        market_keywords = extract_keywords(market_title)
        market_entities = get_entity_keywords(market_title)

        # Find keyword overlap
        keyword_overlap = article_keywords & market_keywords
        entity_overlap = article_entities & market_entities

        # Combine overlaps
        all_matched = keyword_overlap | entity_overlap

        # Check minimum overlap threshold
        if len(all_matched) < min_keyword_overlap:
            continue

        # Calculate time delta
        trade_timestamp = trade.get("timestamp", "")
        time_delta = calculate_time_delta(trade_timestamp, article_scraped_at)

        # Only include if trade was BEFORE article (negative time delta)
        if time_delta >= 0:
            continue

        # Determine market type
        market_type = detect_market_type(market_title)

        # Check if we have entity match
        has_entity_match = len(entity_overlap) > 0

        # Calculate confidence
        confidence = calculate_match_confidence(
            list(all_matched),
            market_type,
            time_delta,
            has_entity_match,
        )

        # Create match
        match = CorrelationMatch(
            trade_id=trade.get("id", 0),
            trade_timestamp=trade_timestamp,
            wallet_address=trade.get("wallet_address", ""),
            market_title=market_title,
            trade_value=trade.get("trade_value", 0),
            trade_side=trade.get("side", ""),
            trade_outcome=trade.get("outcome", ""),
            article_url=article_url,
            article_title=article_title,
            article_source=article_source,
            article_scraped_at=article_scraped_at,
            matched_keywords=sorted(list(all_matched)),
            time_delta_seconds=time_delta,
            confidence=confidence,
            market_type=market_type,
        )

        matches.append(match)

    return matches
