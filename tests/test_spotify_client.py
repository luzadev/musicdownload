"""Test per core.spotify_client.search_track()."""

from __future__ import annotations

import pytest
import responses

from core import spotify_client


class TestSearchTrack:
    @responses.activate
    def test_returns_track_dict_when_found(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={
                "tracks": {
                    "items": [
                        {
                            "id": "abc123",
                            "name": "Hot Sauce",
                            "artists": [{"name": "Kapuchon"}],
                            "external_urls": {"spotify": "https://open.spotify.com/track/abc123"},
                        }
                    ]
                }
            },
            status=200,
        )
        result = spotify_client.search_track("fake-token", "Kapuchon Hot Sauce")
        assert result is not None
        assert result["id"] == "abc123"
        assert result["url"] == "https://open.spotify.com/track/abc123"

    @responses.activate
    def test_returns_none_when_no_results(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": []}},
            status=200,
        )
        result = spotify_client.search_track("fake-token", "no-match")
        assert result is None

    @responses.activate
    def test_sends_bearer_token(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": []}},
            status=200,
        )
        spotify_client.search_track("my-token", "q")
        assert responses.calls[0].request.headers["Authorization"] == "Bearer my-token"

    @responses.activate
    def test_query_params_correct(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": []}},
            status=200,
        )
        spotify_client.search_track("t", "Kapuchon Hot Sauce")
        params = responses.calls[0].request.params
        assert params["q"] == "Kapuchon Hot Sauce"
        assert params["type"] == "track"
        assert params["limit"] == "1"
