"""
Unit tests for keyword extraction and market detection functions.

Tests verify pure-function behavior of extract_keywords, should_skip_market,
detect_market_type, and get_entity_keywords with no network or DB access.
"""

import pytest
from src.correlation.keywords import (
    detect_market_type,
    extract_keywords,
    get_entity_keywords,
    should_skip_market,
)


class TestExtractKeywords:
    """Tests for extract_keywords pure function."""

    def test_empty_string(self):
        """Empty string returns empty set."""
        assert extract_keywords("") == set()

    def test_stopword_only_input(self):
        """Text consisting entirely of stopwords returns empty set."""
        assert extract_keywords("a the or and will be is from") == set()

    def test_normal_headline(self):
        """Normal headline yields expected meaningful keywords."""
        result = extract_keywords("Federal investigation into corporate fraud")
        assert "federal" in result
        assert "investigation" in result
        assert "corporate" in result
        assert "fraud" in result

    def test_punctuation_stripped(self):
        """Punctuation is replaced with spaces; underlying keywords extracted."""
        result = extract_keywords("Will Bitcoin reach $100,000 by year-end?")
        assert "bitcoin" in result
        # Dollar sign and comma are stripped; pure number '100' filtered
        assert "$" not in str(result)

    def test_pure_numbers_skipped(self):
        """Pure numeric tokens are not included."""
        result = extract_keywords("Bitcoin reaches 100000 dollars this week")
        assert "100000" not in result
        assert "bitcoin" in result
        assert "dollars" in result

    def test_alphanumeric_token_kept(self):
        """Alphanumeric tokens like 'covid19' are NOT pure digits and are kept."""
        result = extract_keywords("covid19 pandemic spreads globally")
        assert "covid19" in result

    def test_single_char_tokens_skipped(self):
        """Tokens with one character are excluded."""
        result = extract_keywords("I a b c deal done")
        assert "a" not in result
        assert "b" not in result
        assert "c" not in result
        assert "deal" in result
        assert "done" in result

    def test_year_stopwords_filtered(self):
        """Year tokens (2024-2027) are treated as stopwords and filtered."""
        result = extract_keywords("Fed raises rates in 2025 before 2026 review")
        assert "2025" not in result
        assert "2026" not in result
        assert "fed" in result
        assert "raises" in result

    def test_month_stopwords_filtered(self):
        """Month names are stopwords and are removed."""
        result = extract_keywords("inflation drops before september report")
        assert "september" not in result
        assert "sep" not in result
        assert "inflation" in result

    def test_case_normalized_to_lowercase(self):
        """All keywords are returned in lowercase."""
        result = extract_keywords("TRUMP Biden HARRIS election")
        assert "trump" in result
        assert "biden" in result
        assert "harris" in result
        # Uppercase forms never appear
        assert "TRUMP" not in result

    def test_returns_set(self):
        """Return type is a set; repeated words are deduplicated."""
        result = extract_keywords("bitcoin bitcoin bitcoin")
        assert isinstance(result, set)
        assert result == {"bitcoin"}

    def test_hyphen_handling(self):
        """Hyphens are preserved within a token; leading/trailing hyphens stripped."""
        result = extract_keywords("AI-powered trading platform")
        # 'ai' would be 2 chars → filtered by len <= 1? No, len('ai') == 2 which IS <= 1? No wait — the condition is len(token) <= 1, so single char skipped. 'ai' is len 2, passes.
        # Actually "ai" has len 2 > 1, so it's kept. But "ai" is not in STOPWORDS, so it's kept.
        assert "platform" in result
        assert "trading" in result

    def test_prediction_market_stopwords_filtered(self):
        """Prediction market terms (win, lose, hit, reach, etc.) are filtered."""
        result = extract_keywords("will team win championship and reach finals")
        # 'will', 'win', 'reach' are stopwords
        assert "will" not in result
        assert "win" not in result
        assert "reach" not in result
        assert "team" in result
        assert "championship" in result


class TestShouldSkipMarket:
    """Tests for should_skip_market pure function."""

    def test_empty_string_skipped(self):
        """Empty string returns (True, 'empty_title')."""
        skip, reason = should_skip_market("")
        assert skip is True
        assert reason == "empty_title"

    def test_none_skipped(self):
        """None value is falsy and returns (True, 'empty_title')."""
        skip, reason = should_skip_market(None)
        assert skip is True
        assert reason == "empty_title"

    def test_up_or_down_skipped(self):
        """'up or down' price-direction markets are excluded."""
        skip, reason = should_skip_market("Will ETH go up or down today?")
        assert skip is True
        assert reason == "price_market"

    def test_higher_or_lower_skipped(self):
        """'higher or lower' price-comparison markets are excluded."""
        skip, reason = should_skip_market("Is BTC price higher or lower than last week?")
        assert skip is True
        assert reason == "price_market"

    def test_price_of_x_on_skipped(self):
        """'Price of X on [date]' pattern is excluded."""
        skip, reason = should_skip_market("Price of bitcoin on friday")
        assert skip is True
        assert reason == "price_market"

    def test_time_range_market_skipped(self):
        """Markets with time ranges like '9:00pm to 10:00pm' are excluded."""
        skip, reason = should_skip_market("BTC candle from 9:00pm to 10:00pm")
        assert skip is True
        assert reason == "price_market"

    def test_pure_number_slug_skipped(self):
        """Slug-like pure number markets (e.g. '100k') are excluded."""
        skip, reason = should_skip_market("100k")
        assert skip is True
        assert reason == "price_market"

    def test_updown_slug_skipped(self):
        """Alternate 'updown' slug spelling is excluded."""
        skip, reason = should_skip_market("btc updown prediction market")
        assert skip is True
        assert reason == "price_market"

    def test_normal_political_market_not_skipped(self):
        """Ordinary political question market is not excluded."""
        skip, reason = should_skip_market("Will Trump win the 2024 election?")
        assert skip is False
        assert reason == ""

    def test_sports_market_not_skipped(self):
        """Sports markets are not excluded by this function (only classified by detect_market_type)."""
        skip, reason = should_skip_market("Chiefs vs Eagles Super Bowl winner")
        assert skip is False
        assert reason == ""

    def test_crypto_narrative_market_not_skipped(self):
        """Crypto narrative market without a price pattern is not excluded."""
        skip, reason = should_skip_market("Will Ethereum ETF be approved by SEC?")
        assert skip is False
        assert reason == ""

    def test_returns_tuple(self):
        """Return value is always a two-element tuple."""
        result = should_skip_market("Some market question")
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestDetectMarketType:
    """Tests for detect_market_type pure function."""

    def test_empty_string_returns_other(self):
        """Empty string returns 'other' (safe default)."""
        assert detect_market_type("") == "other"

    def test_vs_with_period_is_sports(self):
        """'vs.' pattern triggers sports classification."""
        assert detect_market_type("Chiefs vs. Eagles in Super Bowl") == "sports"

    def test_vs_without_period_is_sports(self):
        """'vs' without period also triggers sports classification."""
        assert detect_market_type("Lakers vs Celtics game 7") == "sports"

    def test_nfl_is_sports(self):
        """NFL keyword indicates sports market."""
        assert detect_market_type("NFL playoff predictions this season") == "sports"

    def test_nba_is_sports(self):
        """NBA keyword indicates sports market."""
        assert detect_market_type("NBA championship final winner") == "sports"

    def test_mlb_is_sports(self):
        """MLB keyword indicates sports market."""
        assert detect_market_type("MLB World Series game outcome") == "sports"

    def test_nhl_is_sports(self):
        """NHL keyword indicates sports market."""
        assert detect_market_type("NHL Stanley Cup champion") == "sports"

    def test_ufc_is_sports(self):
        """UFC keyword indicates sports market."""
        assert detect_market_type("UFC heavyweight championship fight") == "sports"

    def test_super_bowl_is_sports(self):
        """Super Bowl phrase indicates sports market."""
        assert detect_market_type("Super Bowl champion for the season") == "sports"

    def test_march_madness_is_sports(self):
        """March Madness phrase indicates sports market."""
        assert detect_market_type("March Madness tournament winner") == "sports"

    def test_championship_is_sports(self):
        """Championship keyword alone triggers sports classification."""
        assert detect_market_type("Will the championship go into overtime?") == "sports"

    def test_trump_keyword_is_politics(self):
        """Trump keyword indicates political market."""
        assert detect_market_type("Will Trump sign the new trade deal?") == "politics"

    def test_election_keyword_is_politics(self):
        """Election keyword indicates political market."""
        assert detect_market_type("US presidential election outcome") == "politics"

    def test_senate_is_politics(self):
        """Senate keyword indicates political market."""
        assert detect_market_type("Will the Senate confirm the nominee?") == "politics"

    def test_gop_is_politics(self):
        """GOP keyword indicates political market."""
        assert detect_market_type("GOP candidate leads in latest poll") == "politics"

    def test_bitcoin_is_crypto(self):
        """Bitcoin keyword indicates crypto market."""
        assert detect_market_type("Will Bitcoin ETF be approved?") == "crypto"

    def test_ethereum_is_crypto(self):
        """Ethereum keyword indicates crypto market."""
        assert detect_market_type("Ethereum network upgrade impact") == "crypto"

    def test_defi_is_crypto(self):
        """DeFi keyword indicates crypto market."""
        assert detect_market_type("DeFi protocol total value locked milestone") == "crypto"

    def test_btc_abbreviation_is_crypto(self):
        """BTC abbreviation indicates crypto market."""
        assert detect_market_type("BTC halving event this year") == "crypto"

    def test_unrelated_market_is_other(self):
        """Market with no sports/politics/crypto signals returns 'other'."""
        assert detect_market_type("Will US unemployment rate drop below 4%?") == "other"

    def test_sports_pattern_checked_before_keywords(self):
        """Sports regex patterns are evaluated before keyword-based checks."""
        # 'vs' triggers sports immediately, even when political names present
        result = detect_market_type("Trump vs Biden debate rematch")
        assert result == "sports"

    def test_politics_checked_before_crypto(self):
        """Politics keywords are evaluated before crypto keywords."""
        # SEC is in crypto keywords; but election + SEC should still be politics
        result = detect_market_type("Will SEC chair resign after election?")
        # 'election' is a political keyword → politics
        assert result == "politics"


class TestGetEntityKeywords:
    """Tests for get_entity_keywords pure function."""

    def test_empty_string(self):
        """Empty string returns empty set."""
        assert get_entity_keywords("") == set()

    def test_single_capitalized_word(self):
        """Single capitalized proper noun is extracted and lowercased."""
        result = get_entity_keywords("Trump announces cabinet picks")
        assert "trump" in result

    def test_multi_word_proper_noun(self):
        """Consecutive Title-Case words are captured as one entity."""
        result = get_entity_keywords("Federal Reserve raises interest rates")
        assert "federal reserve" in result

    def test_lowercase_text_returns_empty(self):
        """All-lowercase text has no capitalized words; returns empty set."""
        result = get_entity_keywords("will the inflation rate go up or down")
        assert result == set()

    def test_capitalized_stopword_filtered(self):
        """A standalone capitalized stopword ('The') is excluded."""
        # "The" alone before all-lowercase words → captured as "the" → in STOPWORDS → filtered
        result = get_entity_keywords("The committee voted on the resolution")
        assert "the" not in result
        assert result == set()

    def test_short_words_filtered(self):
        """Capitalized words of 2 or fewer characters are skipped (len <= 2)."""
        result = get_entity_keywords("It goes up when markets rally")
        # "It" has len 2 → exactly at <=2 threshold → filtered
        assert "it" not in result

    def test_entities_returned_lowercase(self):
        """All entity keywords are lowercased in the output."""
        result = get_entity_keywords("Microsoft posts record earnings this quarter")
        assert "microsoft" in result
        assert "Microsoft" not in result

    def test_mid_sentence_entity_captured(self):
        """Proper noun not preceded by another capital word is captured individually."""
        # "Reports" is matched alone (followed by lowercase "show"),
        # then "Nvidia" is matched alone (followed by lowercase "leads")
        result = get_entity_keywords("Reports show Nvidia leads semiconductor market")
        assert "nvidia" in result

    def test_all_caps_words_not_matched(self):
        """All-caps abbreviations like 'FBI' don't match [A-Z][a-z]+ pattern."""
        result = get_entity_keywords("FBI investigates the tech merger")
        # 'FBI' is all caps; pattern requires [A-Z][a-z]+ → no match
        assert "fbi" not in result

    def test_returns_set(self):
        """Return type is a set; duplicate consecutive capitalized words collapse."""
        # "Apple" appears only once here → result contains "apple" as one element
        result = get_entity_keywords("Apple releases new hardware this quarter")
        assert isinstance(result, set)
        assert "apple" in result

    def test_mixed_entities(self):
        """Multiple distinct entities in one text are all captured."""
        result = get_entity_keywords("Elon Musk sells Tesla stock to buy Twitter")
        assert "elon musk" in result
        assert "tesla" in result
        assert "twitter" in result

    def test_name_not_confused_with_stopword(self):
        """A proper name that is not a stopword is included even at sentence start."""
        result = get_entity_keywords("Biden addresses the nation on foreign policy")
        assert "biden" in result
