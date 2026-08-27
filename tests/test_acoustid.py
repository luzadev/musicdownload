"""Test per core.acoustid — lookup AcoustID + cache SQLite.

Mock su `requests.get` in modo che i test siano offline. Ogni test
isola la cache SQLite in tmp_path via monkeypatch di
`_cache_db_path`.
"""

from __future__ import annotations

from unittest import mock

import pytest

from core import acoustid


# ------------------------------------------------------------------
# Fixture: cache isolata + reset del rate-limit
# ------------------------------------------------------------------
@pytest.fixture
def patched_cache(tmp_path, monkeypatch):
    db = tmp_path / "acoustid_cache_test.db"
    monkeypatch.setattr(acoustid, "_cache_db_path", lambda: db)
    # Rate-limit: azzera cosi' i test non aspettano throttle
    monkeypatch.setattr(acoustid, "_RATE_LIMIT_SEC", 0.0)
    monkeypatch.setattr(acoustid, "_last_request_at", [0.0])
    return db


def _mock_resp(status_code: int = 200, json_data: dict = None):
    """Costruisce un mock di response `requests`."""
    m = mock.Mock()
    m.status_code = status_code
    m.json.return_value = json_data or {}
    return m


# ------------------------------------------------------------------
# lookup — cache
# ------------------------------------------------------------------
class TestLookupCache:
    def test_lookup_uses_cache(self, patched_cache):
        """Seconda chiamata con lo stesso fingerprint riusa la cache."""
        payload = {
            "status": "ok",
            "results": [{
                "score": 0.99,
                "recordings": [{
                    "title": "Some Song",
                    "artists": [{"name": "Artist X"}],
                    "releases": [
                        {"date": {"year": 2005},
                         "releasegroup": {"tags": [{"name": "House", "count": 5}]}},
                    ],
                }],
            }],
        }
        with mock.patch.object(acoustid.requests, "get",
                                return_value=_mock_resp(200, payload)) as m:
            r1 = acoustid.lookup("FP-1", 180.0)
            r2 = acoustid.lookup("FP-1", 180.0)

        assert m.call_count == 1, "la seconda chiamata deve venire dalla cache"
        assert r1 == r2
        assert r1["matched"] is True
        assert r1["year"] == 2005
        assert r1["genre"].lower() == "house"
        assert r1["title"] == "Some Song"
        assert r1["artist"] == "Artist X"


# ------------------------------------------------------------------
# lookup — no results / errori
# ------------------------------------------------------------------
class TestLookupNoResults:
    def test_lookup_no_results_returns_unmatched(self, patched_cache):
        payload = {"status": "ok", "results": []}
        with mock.patch.object(acoustid.requests, "get",
                                return_value=_mock_resp(200, payload)):
            r = acoustid.lookup("FP-NORESULT", 100.0)

        assert r["matched"] is False
        # deve essere cacheato
        with mock.patch.object(acoustid.requests, "get") as m:
            r2 = acoustid.lookup("FP-NORESULT", 100.0)
            assert m.call_count == 0
        assert r2 == r

    def test_lookup_no_recordings_returns_unmatched(self, patched_cache):
        """results presenti ma senza recordings -> matched=False."""
        payload = {
            "status": "ok",
            "results": [{"score": 0.5, "recordings": []}],
        }
        with mock.patch.object(acoustid.requests, "get",
                                return_value=_mock_resp(200, payload)):
            r = acoustid.lookup("FP-EMPTYREC", 200)
        assert r["matched"] is False


# ------------------------------------------------------------------
# lookup — anno minimo
# ------------------------------------------------------------------
class TestLookupYearExtraction:
    def test_lookup_extracts_min_year(self, patched_cache):
        """3 releases (2003, 1998, 2010) -> year=1998."""
        payload = {
            "status": "ok",
            "results": [{
                "score": 0.95,
                "recordings": [{
                    "title": "Classic",
                    "artists": [{"name": "Artist"}],
                    "releases": [
                        {"date": {"year": 2003}},
                        {"date": {"year": 1998}},
                        {"date": {"year": 2010}},
                    ],
                }],
            }],
        }
        with mock.patch.object(acoustid.requests, "get",
                                return_value=_mock_resp(200, payload)):
            r = acoustid.lookup("FP-YEAR", 180)

        assert r["matched"] is True
        assert r["year"] == 1998

    def test_lookup_missing_year_becomes_none(self, patched_cache):
        """Nessuna release con year valido -> year=None (matched se ha titolo)."""
        payload = {
            "status": "ok",
            "results": [{
                "score": 0.9,
                "recordings": [{
                    "title": "T",
                    "artists": [{"name": "A"}],
                    "releases": [{"date": {}}, {"other": 1}],
                }],
            }],
        }
        with mock.patch.object(acoustid.requests, "get",
                                return_value=_mock_resp(200, payload)):
            r = acoustid.lookup("FP-NOY", 100)
        # matched puo' essere True se ha almeno un titolo
        assert r["year"] is None
        assert r["title"] == "T"


# ------------------------------------------------------------------
# lookup — errori HTTP / rete
# ------------------------------------------------------------------
class TestLookupErrors:
    def test_lookup_returns_error_on_http_failure(self, patched_cache):
        with mock.patch.object(acoustid.requests, "get",
                                return_value=_mock_resp(500, {})):
            r = acoustid.lookup("FP-HTTP", 100)
        assert r["matched"] is False
        assert "HTTP 500" in r.get("error", "")

    def test_lookup_returns_error_on_network_failure(self, patched_cache):
        with mock.patch.object(acoustid.requests, "get",
                                side_effect=acoustid.requests.ConnectionError("boom")):
            r = acoustid.lookup("FP-NET", 100)
        assert r["matched"] is False
        assert "network" in r.get("error", "").lower() or "boom" in r.get("error", "")

    def test_lookup_empty_fingerprint_returns_unmatched(self, patched_cache):
        r = acoustid.lookup("", 100)
        assert r["matched"] is False
        assert "fingerprint" in r.get("error", "").lower()

    def test_lookup_api_status_error(self, patched_cache):
        payload = {"status": "error",
                    "error": {"message": "invalid fingerprint"}}
        with mock.patch.object(acoustid.requests, "get",
                                return_value=_mock_resp(200, payload)):
            r = acoustid.lookup("FP-BAD", 100)
        assert r["matched"] is False
        assert "invalid" in r.get("error", "").lower()


# ------------------------------------------------------------------
# helper: _extract_top_genre
# ------------------------------------------------------------------
class TestGenreExtraction:
    def test_top_genre_picks_highest_count(self):
        releases = [{
            "releasegroup": {
                "tags": [
                    {"name": "electronic", "count": 3},
                    {"name": "house", "count": 12},
                    {"name": "dance", "count": 7},
                ]
            }
        }]
        assert acoustid._extract_top_genre(releases).lower() == "house"

    def test_top_genre_no_tags_returns_empty(self):
        releases = [{"releasegroup": {"tags": []}}]
        assert acoustid._extract_top_genre(releases) == ""

    def test_top_genre_no_releasegroup_returns_empty(self):
        assert acoustid._extract_top_genre([{}]) == ""
