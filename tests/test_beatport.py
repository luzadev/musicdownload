"""Test per core.beatport."""

from __future__ import annotations

import pytest

from core import beatport


class TestListGenres:
    def test_returns_list_of_dicts(self):
        result = beatport.list_genres()
        assert isinstance(result, list)
        assert len(result) >= 10  # almeno 10 generi
        for g in result:
            assert set(g.keys()) == {"slug", "id", "name"}
            assert isinstance(g["slug"], str) and g["slug"]
            assert isinstance(g["id"], int) and g["id"] > 0
            assert isinstance(g["name"], str) and g["name"]

    def test_sorted_alphabetically_by_name(self):
        result = beatport.list_genres()
        names = [g["name"] for g in result]
        assert names == sorted(names, key=str.casefold)

    def test_melodic_house_techno_present(self):
        result = beatport.list_genres()
        slugs = [g["slug"] for g in result]
        assert "melodic-house-techno" in slugs


class TestBeatportTrack:
    def test_display_format(self):
        t = beatport.BeatportTrack(
            position=1,
            title="Hot Sauce",
            mix="Extended",
            artists="Kapuchon, Miss Monique & GLZ",
            duration_sec=336,
            beatport_id=12345,
        )
        assert t.display == "Kapuchon, Miss Monique & GLZ – Hot Sauce (Extended) (5:36)"

    def test_display_pads_seconds(self):
        t = beatport.BeatportTrack(
            position=1, title="X", mix="Y", artists="A",
            duration_sec=65, beatport_id=1,
        )
        assert t.display.endswith("(1:05)")

    def test_spotify_query(self):
        t = beatport.BeatportTrack(
            position=1,
            title="Hot Sauce",
            mix="Extended",
            artists="Kapuchon, Miss Monique & GLZ",
            duration_sec=336,
            beatport_id=12345,
        )
        assert t.spotify_query == "Kapuchon, Miss Monique & GLZ Hot Sauce"

    def test_is_frozen(self):
        t = beatport.BeatportTrack(
            position=1, title="X", mix="Y", artists="A",
            duration_sec=1, beatport_id=1,
        )
        with pytest.raises(Exception):
            t.title = "Z"  # frozen=True impedisce mutazione


class TestExtractNextData:
    def test_extracts_json_from_valid_html(self, fixtures_dir):
        html = (fixtures_dir / "beatport_melodic_top100.html").read_text()
        data = beatport._extract_next_data(html)
        assert isinstance(data, dict)
        assert "props" in data

    def test_missing_script_raises(self):
        with pytest.raises(beatport.BeatportParseError, match="__NEXT_DATA__ non trovato"):
            beatport._extract_next_data("<html><body>nulla</body></html>")

    def test_malformed_json_raises(self):
        broken = '<script id="__NEXT_DATA__" type="application/json">{not: valid}</script>'
        with pytest.raises(beatport.BeatportParseError, match="JSON malformato"):
            beatport._extract_next_data(broken)


class TestParseTracks:
    def test_extracts_100_tracks(self, fixtures_dir):
        html = (fixtures_dir / "beatport_melodic_top100.html").read_text()
        data = beatport._extract_next_data(html)
        tracks = beatport._parse_tracks(data)
        assert len(tracks) == 100

    def test_positions_are_sequential_1_to_100(self, fixtures_dir):
        html = (fixtures_dir / "beatport_melodic_top100.html").read_text()
        tracks = beatport._parse_tracks(beatport._extract_next_data(html))
        positions = [t.position for t in tracks]
        assert positions == list(range(1, 101))

    def test_track_shape(self, fixtures_dir):
        html = (fixtures_dir / "beatport_melodic_top100.html").read_text()
        tracks = beatport._parse_tracks(beatport._extract_next_data(html))
        first = tracks[0]
        assert isinstance(first, beatport.BeatportTrack)
        assert first.title
        assert first.artists
        assert first.duration_sec > 0
        assert first.beatport_id > 0

    def test_schema_missing_results_raises(self):
        with pytest.raises(beatport.BeatportParseError, match="results"):
            beatport._parse_tracks({"props": {"pageProps": {}}})


from unittest.mock import patch, MagicMock

from freezegun import freeze_time


def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    def _raise():
        if status_code >= 400:
            raise Exception(f"HTTP {status_code}")
    resp.raise_for_status = _raise
    return resp


class TestFetchTop100:
    @pytest.fixture
    def fixture_html(self, fixtures_dir):
        return (fixtures_dir / "beatport_melodic_top100.html").read_text()

    def test_success_returns_100_tracks(self, fixture_html):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response(fixture_html, 200)
            tracks = beatport.fetch_top100("melodic-house-techno")
        assert len(tracks) == 100

    def test_invalid_slug_raises_value_error(self):
        with pytest.raises(ValueError, match="slug"):
            beatport.fetch_top100("not-a-real-genre")

    def test_5xx_retries_and_raises_unreachable(self):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response("", 503)
            with patch("core.beatport.time.sleep"):  # skip backoff
                with pytest.raises(beatport.BeatportUnreachableError):
                    beatport.fetch_top100("melodic-house-techno")
            assert mock_get.call_count == 3  # 1 + 2 retry

    def test_cache_hit_within_ttl(self, fixture_html):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response(fixture_html, 200)
            beatport.fetch_top100("melodic-house-techno")
            beatport.fetch_top100("melodic-house-techno")
            assert mock_get.call_count == 1

    def test_cache_expires_after_ttl(self, fixture_html):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response(fixture_html, 200)
            with freeze_time("2026-01-01 10:00:00") as frozen:
                beatport.fetch_top100("melodic-house-techno")
                frozen.tick(delta=beatport._CACHE_TTL_SEC + 1)
                beatport.fetch_top100("melodic-house-techno")
            assert mock_get.call_count == 2

    def test_force_refresh_bypasses_cache(self, fixture_html):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response(fixture_html, 200)
            beatport.fetch_top100("melodic-house-techno")
            beatport.fetch_top100("melodic-house-techno", force_refresh=True)
            assert mock_get.call_count == 2

    def test_uses_chrome_impersonation(self, fixture_html):
        beatport._cache.clear()
        with patch("core.beatport._cffi_requests.get") as mock_get:
            mock_get.return_value = _mock_response(fixture_html, 200)
            beatport.fetch_top100("melodic-house-techno")
            call_kwargs = mock_get.call_args.kwargs
            assert "impersonate" in call_kwargs
            assert call_kwargs["impersonate"].startswith("chrome")
