"""Test per core.traxsource."""

from __future__ import annotations

import pytest

from core import traxsource


class TestListGenres:
    def test_returns_list_of_dicts(self):
        result = traxsource.list_genres()
        assert isinstance(result, list)
        assert len(result) >= 10
        for g in result:
            assert set(g.keys()) == {"slug", "id", "name"}
            assert isinstance(g["slug"], str) and g["slug"]
            assert isinstance(g["id"], int) and g["id"] > 0
            assert isinstance(g["name"], str) and g["name"]

    def test_sorted_alphabetically_by_name(self):
        result = traxsource.list_genres()
        names = [g["name"] for g in result]
        assert names == sorted(names, key=str.casefold)

    def test_tech_house_present(self):
        result = traxsource.list_genres()
        slugs = [g["slug"] for g in result]
        assert "tech-house" in slugs


class TestTraxsourceTrack:
    def test_frozen(self):
        t = traxsource.TraxsourceTrack(
            position=1, title="X", mix="Y", artists="A", label="L",
            traxsource_id=1, slug="x",
        )
        with pytest.raises(Exception):
            t.title = "Z"

    def test_defaults(self):
        t = traxsource.TraxsourceTrack(
            position=1, title="X", mix="", artists="A", label="",
            traxsource_id=1, slug="x",
        )
        assert t.image_url == ""
        assert t.cover_url_large == ""


class TestSplitTitleMix:
    def test_with_parens(self):
        assert traxsource._split_title_mix("Foo (Extended Mix)") == ("Foo", "Extended Mix")

    def test_without_parens(self):
        assert traxsource._split_title_mix("Foo") == ("Foo", "")

    def test_multiple_parens_takes_last(self):
        # es. "Foo (feat. Bar) (Original Mix)" -> mix = "Original Mix"
        assert traxsource._split_title_mix("Foo (feat. Bar) (Original Mix)") == ("Foo (feat. Bar)", "Original Mix")

    def test_empty(self):
        assert traxsource._split_title_mix("") == ("", "")


class TestFormatArtists:
    def test_single(self):
        assert traxsource._format_artists(["Kapuchon"]) == "Kapuchon"

    def test_two(self):
        assert traxsource._format_artists(["A", "B"]) == "A & B"

    def test_three(self):
        assert traxsource._format_artists(["A", "B", "C"]) == "A, B & C"

    def test_empty(self):
        assert traxsource._format_artists([]) == ""

    def test_strips_whitespace(self):
        assert traxsource._format_artists(["  A  ", " B "]) == "A & B"


class TestLargeCover:
    def test_substitutes_52x52_with_500x500(self):
        url = "https://www.traxsource.com/scripts/image.php/52x52/abc.jpg"
        assert traxsource._large_cover(url) == "https://www.traxsource.com/scripts/image.php/500x500/abc.jpg"

    def test_no_change_when_no_pattern(self):
        assert traxsource._large_cover("https://example.com/x.jpg") == "https://example.com/x.jpg"

    def test_empty(self):
        assert traxsource._large_cover("") == ""


class TestExceptions:
    def test_exceptions_are_subclasses(self):
        assert issubclass(traxsource.TraxsourceUnreachableError, traxsource.TraxsourceError)
        assert issubclass(traxsource.TraxsourceParseError, traxsource.TraxsourceError)


class TestDiscoverTop100Url:
    def test_extracts_link_from_genre_page(self, fixtures_dir):
        html = (fixtures_dir / "traxsource_tech_house_genre.html").read_text()
        url = traxsource._discover_top100_url(html)
        assert url.startswith("/title/")
        assert "top-100" in url

    def test_raises_when_no_link(self):
        with pytest.raises(traxsource.TraxsourceParseError, match="Top 100"):
            traxsource._discover_top100_url("<html>nulla</html>")


class TestParseTracks:
    def test_parses_100_tracks(self, fixtures_dir):
        html = (fixtures_dir / "traxsource_tech_house_top100.html").read_text()
        tracks = traxsource._parse_tracks(html)
        assert len(tracks) == 100

    def test_positions_sequential_1_to_100(self, fixtures_dir):
        html = (fixtures_dir / "traxsource_tech_house_top100.html").read_text()
        tracks = traxsource._parse_tracks(html)
        positions = [t.position for t in tracks]
        assert positions == list(range(1, 101))

    def test_track_shape(self, fixtures_dir):
        html = (fixtures_dir / "traxsource_tech_house_top100.html").read_text()
        tracks = traxsource._parse_tracks(html)
        first = tracks[0]
        assert first.title
        assert first.artists
        assert first.traxsource_id > 0
        assert first.slug
        assert first.image_url.startswith("https://")
        assert first.cover_url_large.startswith("https://")
        assert "500x500" in first.cover_url_large

    def test_raises_when_no_tracks(self):
        with pytest.raises(traxsource.TraxsourceParseError, match="track"):
            traxsource._parse_tracks("<html>vuoto</html>")
