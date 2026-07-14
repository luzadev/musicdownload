"""Test per core.spotify_client.search_track()."""

from __future__ import annotations

from unittest.mock import patch

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


class TestSearchArtistDiscography:
    @responses.activate
    def test_exact_name_match_beats_popular(self):
        # 3 candidati: uno esatto (case-insensitive), altri popolari
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"artists": {"items": [
                {"id": "pop", "name": "Solomun Tribute", "popularity": 90},
                {"id": "exact", "name": "SOLOMUN", "popularity": 60},
                {"id": "unrelated", "name": "Other", "popularity": 70},
            ]}},
            status=200,
        )
        # Mock top-tracks vuoto per non allungare il test
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/exact/top-tracks",
            json={"tracks": []},
            status=200,
        )
        # Mock albums vuoto
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/exact/albums",
            json={"items": []},
            status=200,
        )
        result = spotify_client.search_artist_discography("t", "Solomun")
        assert result == []
        # Verifica che sia stato chiamato l'artista "exact", non "pop"
        top_tracks_calls = [c for c in responses.calls if "/top-tracks" in c.request.url]
        assert len(top_tracks_calls) == 1
        assert "/exact/top-tracks" in top_tracks_calls[0].request.url

    @responses.activate
    def test_falls_back_to_most_popular_if_no_exact_match(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"artists": {"items": [
                {"id": "a1", "name": "Solomun Fanpage", "popularity": 30},
                {"id": "a2", "name": "Solomun Live", "popularity": 80},
            ]}},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/a2/top-tracks",
            json={"tracks": []},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/a2/albums",
            json={"items": []},
            status=200,
        )
        spotify_client.search_artist_discography("t", "solomun")
        top_tracks_calls = [c for c in responses.calls if "/top-tracks" in c.request.url]
        assert "/a2/top-tracks" in top_tracks_calls[0].request.url

    @responses.activate
    def test_raises_when_no_artist_found(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"artists": {"items": []}},
            status=200,
        )
        with pytest.raises(ValueError, match="Artista"):
            spotify_client.search_artist_discography("t", "asdgjhkasdgj")

    @responses.activate
    def test_combines_top_tracks_and_album_tracks(self):
        # 1 artista esatto
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"artists": {"items": [{"id": "artX", "name": "artX", "popularity": 50}]}},
            status=200,
        )
        # 3 top-tracks
        top_tracks_data = {"tracks": [
            {
                "id": f"t{i}", "name": f"Top{i}",
                "artists": [{"name": "artX"}],
                "album": {"name": "AlbTop"},
                "duration_ms": 200000,
                "external_urls": {"spotify": f"u{i}"},
            } for i in range(3)
        ]}
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/artX/top-tracks",
            json=top_tracks_data,
            status=200,
        )
        # 2 album
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/artX/albums",
            json={"items": [
                {"id": "alb1", "name": "Album 1"},
                {"id": "alb2", "name": "Album 2"},
            ]},
            status=200,
        )
        # album 1: 2 tracce
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/albums/alb1/tracks",
            json={"items": [
                {
                    "id": f"a1t{i}", "name": f"Alb1Track{i}",
                    "artists": [{"name": "artX"}],
                    "duration_ms": 180000,
                    "external_urls": {"spotify": f"a1u{i}"},
                } for i in range(2)
            ]},
            status=200,
        )
        # album 2: 1 traccia
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/albums/alb2/tracks",
            json={"items": [
                {
                    "id": "a2t0", "name": "Alb2Track0",
                    "artists": [{"name": "artX"}],
                    "duration_ms": 240000,
                    "external_urls": {"spotify": "a2u0"},
                }
            ]},
            status=200,
        )
        with patch("core.spotify_client.time.sleep"):  # no wait
            result = spotify_client.search_artist_discography("t", "artX")
        # 3 top + 2 alb1 + 1 alb2 = 6
        assert len(result) == 6
        titles = {r["name"] for r in result}
        assert "Top0" in titles
        assert "Alb1Track0" in titles
        assert "Alb2Track0" in titles

    @responses.activate
    def test_dedupe_across_top_and_album(self):
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/search",
            json={"artists": {"items": [{"id": "aX", "name": "aX", "popularity": 50}]}},
            status=200,
        )
        # Stesso track name+artist in top-tracks e in album (id diverso)
        common = {
            "name": "Same Song",
            "artists": [{"name": "aX"}],
            "album": {"name": "OG Album"},
            "duration_ms": 200000,
            "external_urls": {"spotify": "u"},
        }
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/aX/top-tracks",
            json={"tracks": [{**common, "id": "top-id"}]},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/artists/aX/albums",
            json={"items": [{"id": "alb", "name": "OG"}]},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://api.spotify.com/v1/albums/alb/tracks",
            json={"items": [{**common, "id": "alb-id"}]},
            status=200,
        )
        with patch("core.spotify_client.time.sleep"):
            result = spotify_client.search_artist_discography("t", "aX")
        assert len(result) == 1
