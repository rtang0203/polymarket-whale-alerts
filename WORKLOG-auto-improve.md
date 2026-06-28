# polymarket-whale-alerts — Auto-Improve Worklog
Branch: `auto-improve/2026-06-28`

---

### test: add unit tests for keyword extraction and market detection

- **What:** Created `tests/test_keywords.py` with 59 unit tests covering the four pure functions in `src/correlation/keywords.py`: `extract_keywords`, `should_skip_market`, `detect_market_type`, and `get_entity_keywords`. Tests cover edge cases: empty string, stopword-only input, pure numbers, alphanumeric tokens, year/month stopwords, punctuation handling, sports-pattern detection, political/crypto keyword classification, entity capitalization, multi-word proper nouns, all-caps abbreviations not matching the `[A-Z][a-z]+` regex, and the greedy multi-word grouping behavior of the entity extractor.
- **Why:** These functions had zero test coverage despite being pure, import-only functions with no network or DB dependencies. Tests document behavioral guarantees and will catch regressions if the stopword list or regex patterns change.
- **Files:** `tests/test_keywords.py` (created)
- **Gate:** Baseline 22 passed → Post-change 81 passed (59 new tests, all green). Command: `venv/bin/python -m pytest -q`
- **Commit:** `1b91c80`

---

### refactor: remove unused run_periodic method from ResolutionTracker

- **What:** Deleted the `run_periodic()` async method (19 lines) from `src/resolution.py`. This method looped calling `check_resolutions()` on a timed interval but was never invoked anywhere in the codebase.
- **Why:** Dead code — grep of `src/` confirmed `run_periodic` appeared only at its definition. The `stop()` method (which sets `self._running = False`) and `fetch_market_raw()` are preserved; `stop()` is used in `src/main.py` for graceful shutdown.
- **Files:** `src/resolution.py`
- **Gate:** Baseline 81 passed → Post-change 81 passed. Command: `venv/bin/python -m pytest -q`
- **Commit:** `7f9c5fb`
