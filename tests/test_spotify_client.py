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


class TestSearchTracks:
    @responses.activate
    def test_returns_list_of_tracks(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={
                "tracks": {
                    "items": [
                        {
                            "id": f"id{i}",
                            "name": f"Track {i}",
                            "artists": [{"name": "Solomun"}],
                            "album": {"name": "Album X"},
                            "duration_ms": 300000 + i * 1000,
                            "external_urls": {"spotify": f"https://open.spotify.com/track/id{i}"},
                        }
                        for i in range(50)
                    ]
                }
            },
            status=200,
        )
        result = spotify_client.search_tracks("t", "solomun", limit=50)
        assert isinstance(result, list)
        assert len(result) == 50
        first = result[0]
        assert first["id"] == "id0"
        assert first["name"] == "Track 0"
        assert first["artists"] == "Solomun"
        assert first["album"] == "Album X"
        assert first["duration_sec"] == 300
        assert first["url"] == "https://open.spotify.com/track/id0"

    @responses.activate
    def test_multiple_artists_joined_with_comma(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": [{
                "id": "x", "name": "n",
                "artists": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
                "album": {"name": "Alb"},
                "duration_ms": 60000,
                "external_urls": {"spotify": "u"},
            }]}},
            status=200,
        )
        result = spotify_client.search_tracks("t", "q", limit=1)
        assert result[0]["artists"] == "A, B, C"

    @responses.activate
    def test_empty_query_returns_empty_list(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": []}},
            status=200,
        )
        result = spotify_client.search_tracks("t", "no-match", limit=50)
        assert result == []

    @responses.activate
    def test_query_params_include_limit(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"tracks": {"items": []}},
            status=200,
        )
        spotify_client.search_tracks("t", "q", limit=25)
        params = responses.calls[0].request.params
        assert params["q"] == "q"
        assert params["type"] == "track"
        assert params["limit"] == "25"
