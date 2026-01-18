"""
Keyword extraction for news-trade correlation matching.

Extracts meaningful keywords from market titles and article headlines,
filtering out stopwords and low-value terms.
"""

import re
from typing import Optional

# Common stopwords to remove
STOPWORDS = {
    # Articles and prepositions
    "a", "an", "the", "of", "in", "to", "for", "on", "by", "at", "or", "and",
    "with", "from", "as", "it", "its", "this", "that", "than",
    # Verbs
    "will", "be", "is", "are", "was", "were", "been", "being", "have", "has",
    "had", "do", "does", "did", "can", "could", "would", "should", "may", "might",
    # Time words
    "before", "after", "during", "between", "when", "while", "until",
    # Prediction market terms
    "yes", "no", "win", "lose", "winner", "happen", "end", "reach", "hit",
    "above", "below", "over", "under", "more", "less", "least", "most",
    # Months
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    # Years
    "2024", "2025", "2026", "2027",
    # Time
    "pm", "am", "et", "pt", "utc", "est", "pst", "gmt",
    # Other common words
    "get", "got", "make", "made", "take", "takes", "any", "all", "some",
    "new", "first", "next", "last", "other", "another",
}

# Patterns for markets to exclude from correlation matching
EXCLUDE_PATTERNS = [
    r"up\s+or\s+down",           # Crypto price prediction
    r"updown",                    # Alternate spelling in slugs
    r"\d+:\d+\s*[ap]m.*[ap]m",   # Time range markets "9:00PM-9:15PM"
    r"price\s+of\s+\w+\s+on",    # "Price of X on [date]"
    r"higher\s+or\s+lower",      # Price comparison markets
    r"^\s*\d+[kmb]?\s*$",        # Pure number markets
]

# Patterns indicating sports markets
SPORTS_PATTERNS = [
    r"\bvs\.?\b",                # "Team A vs Team B"
    r"\bv\.?\s+",                # "Team A v Team B"
    r"\bvs\s+",                  # "Team A vs Team B"
    r"\bnfl\b",
    r"\bnba\b",
    r"\bmlb\b",
    r"\bnhl\b",
    r"\bmls\b",
    r"\bufc\b",
    r"\bpga\b",
    r"\bsuper\s*bowl\b",
    r"\bworld\s*series\b",
    r"\bplayoff",
    r"\bchampionship\b",
    r"\bfinal\s*four\b",
    r"\bmarch\s*madness\b",
]

# Keywords indicating political markets
POLITICAL_KEYWORDS = {
    "trump", "biden", "harris", "obama", "desantis", "haley", "pence",
    "election", "electoral", "vote", "votes", "voting", "ballot",
    "president", "presidential", "congress", "senate", "senate",
    "house", "representative", "governor", "mayor",
    "democrat", "democratic", "republican", "gop",
    "impeach", "impeachment", "cabinet", "administration",
    "primaries", "primary", "caucus", "nomination", "nominee",
    "poll", "polls", "polling",
}

# Keywords indicating crypto markets
CRYPTO_KEYWORDS = {
    "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
    "solana", "sol", "cardano", "ada", "dogecoin", "doge", "xrp", "ripple",
    "binance", "bnb", "coinbase", "polygon", "matic", "avalanche", "avax",
    "blockchain", "defi", "nft", "token", "altcoin", "stablecoin",
    "halving", "etf", "sec", "gensler",
}


def extract_keywords(text: str) -> set[str]:
    """
    Extract meaningful keywords from text.

    Args:
        text: Market title or article headline

    Returns:
        Set of lowercase keywords
    """
    if not text:
        return set()

    # Lowercase
    text = text.lower()

    # Replace punctuation with spaces (keep hyphens in compound words)
    text = re.sub(r"[^\w\s-]", " ", text)

    # Split on whitespace
    tokens = text.split()

    keywords = set()
    for token in tokens:
        # Clean up token
        token = token.strip("-")

        # Skip if empty, single char, or stopword
        if len(token) <= 1:
            continue
        if token in STOPWORDS:
            continue

        # Skip pure numbers (but keep alphanumeric like "covid19")
        if token.isdigit():
            continue

        keywords.add(token)

    return keywords


def should_skip_market(market_title: str) -> tuple[bool, str]:
    """
    Check if market should be excluded from correlation matching.

    Args:
        market_title: The market title from whale_trades

    Returns:
        (should_skip: bool, reason: str)
    """
    if not market_title:
        return True, "empty_title"

    title_lower = market_title.lower()

    # Check against exclude patterns
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, title_lower):
            return True, "price_market"

    return False, ""


def detect_market_type(market_title: str) -> str:
    """
    Categorize market type for filtering/display.

    Args:
        market_title: The market title

    Returns:
        'sports', 'politics', 'crypto', or 'other'
    """
    if not market_title:
        return "other"

    title_lower = market_title.lower()

    # Check sports patterns
    for pattern in SPORTS_PATTERNS:
        if re.search(pattern, title_lower):
            return "sports"

    # Extract keywords for checking
    keywords = extract_keywords(market_title)

    # Check political keywords
    if keywords & POLITICAL_KEYWORDS:
        return "politics"

    # Check crypto keywords
    if keywords & CRYPTO_KEYWORDS:
        return "crypto"

    return "other"


def get_entity_keywords(text: str) -> set[str]:
    """
    Extract potential entity names (proper nouns) from text.

    These are words that might be names of people, companies, etc.
    Used to give extra weight to name matches.

    Args:
        text: Market title or article headline

    Returns:
        Set of potential entity keywords
    """
    if not text:
        return set()

    # Find capitalized words in original text
    # This catches names like "Trump", "OpenAI", "Nvidia"
    words = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text)

    entities = set()
    for word in words:
        # Skip if it's a stopword when lowercased
        if word.lower() in STOPWORDS:
            continue
        # Skip very short words
        if len(word) <= 2:
            continue
        entities.add(word.lower())

    return entities
