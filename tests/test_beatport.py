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
