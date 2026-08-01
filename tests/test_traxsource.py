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
