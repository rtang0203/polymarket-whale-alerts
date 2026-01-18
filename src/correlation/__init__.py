"""
News-Trade Correlation System

Detects potential insider trading by finding whale trades
that precede related news articles.
"""

from .checker import CorrelationChecker
from .matcher import CorrelationMatch

__all__ = ["CorrelationChecker", "CorrelationMatch"]
