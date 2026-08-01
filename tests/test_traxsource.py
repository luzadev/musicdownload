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
