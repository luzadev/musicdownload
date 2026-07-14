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
