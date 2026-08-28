"""Test per core.charts — fetch iTunes/Last.fm/Spotify/M2O + cache SQLite.

Ogni test isola il DB cache in tmp_path via monkeypatch di `_cache_db_path`
e usa `responses`/`mock` per non toccare la rete.
"""

from __future__ import annotations

import time
from unittest import mock

import pytest
import responses
from freezegun import freeze_time

from core import charts


# ------------------------------------------------------------------
# Fixture: cache isolata per test
# ------------------------------------------------------------------
@pytest.fixture
def patched_cache(tmp_path, monkeypatch):
    db = tmp_path / "charts_cache_test.db"
    monkeypatch.setattr(charts, "_cache_db_path", lambda: db)
    return db


# ==================================================================
# iTunes RSS
# ==================================================================
class TestFetchItunes:
    _SAMPLE = {
        "feed": {
            "results": [
                {
                    "name": "Song A",
                    "artistName": "Artist A",
                    "collectionName": "Album A",
                    "artworkUrl100": "https://cdn/a.jpg",
                    "url": "https://itunes/1",
                },
                {
                    "name": "Song B",
                    "artistName": "Artist B",
                    "collectionName": "Album B",
                    "artworkUrl100": "https://cdn/b.jpg",
                    "url": "https://itunes/2",
                },
            ]
        }
    }

    @responses.activate
    def test_fetch_itunes_parses_response(self, patched_cache):
        responses.add(
            responses.GET,
            charts._ITUNES_URL_TPL.format(country="it"),
            json=self._SAMPLE,
            status=200,
        )
        out = charts.fetch_itunes("it", force=True)
        assert len(out) == 2
        assert out[0] == {
            "rank": 1,
            "artist": "Artist A",
            "title": "Song A",
            "album": "Album A",
            "image_url": "https://cdn/a.jpg",
            "popularity": None,
        }
        assert out[1]["rank"] == 2
        assert out[1]["artist"] == "Artist B"

    @responses.activate
    def test_fetch_itunes_uses_cache(self, patched_cache):
        """Seconda chiamata NON deve colpire la rete: il mock registra 1 call."""
        responses.add(
            responses.GET,
            charts._ITUNES_URL_TPL.format(country="us"),
            json=self._SAMPLE,
            status=200,
        )
        first = charts.fetch_itunes("us", force=False)
        second = charts.fetch_itunes("us", force=False)
        assert first == second
        # `responses` fallirebbe se ci fossero call non registrate;
        # verifica esplicitamente che la seconda non ha creato una call in piu'
        assert len(responses.calls) == 1

    @responses.activate
    def test_fetch_itunes_force_bypasses_cache(self, patched_cache):
        responses.add(
            responses.GET,
            charts._ITUNES_URL_TPL.format(country="gb"),
            json=self._SAMPLE,
            status=200,
        )
        responses.add(
            responses.GET,
            charts._ITUNES_URL_TPL.format(country="gb"),
            json=self._SAMPLE,
            status=200,
        )
        charts.fetch_itunes("gb", force=False)
        charts.fetch_itunes("gb", force=True)
        assert len(responses.calls) == 2

    @responses.activate
    def test_fetch_itunes_returns_empty_on_error(self, patched_cache):
        responses.add(
            responses.GET,
            charts._ITUNES_URL_TPL.format(country="ww"),
            status=500,
        )
        assert charts.fetch_itunes("ww", force=True) == []

    @responses.activate
    def test_fetch_itunes_defaults_to_it(self, patched_cache):
        responses.add(
            responses.GET,
            charts._ITUNES_URL_TPL.format(country="it"),
            json={"feed": {"results": []}},
            status=200,
        )
        assert charts.fetch_itunes("", force=True) == []
        assert responses.calls[0].request.url.startswith(
            "https://rss.applemarketingtools.com/api/v2/it/"
        )


# ==================================================================
# Last.fm tag builder
# ==================================================================
class TestBuildLastfmTag:
    def test_only_decade(self):
        assert charts._build_lastfm_tag("80s", "") == "80s"

    def test_only_genre(self):
        assert charts._build_lastfm_tag("", "italo disco") == "italo disco"

    def test_decade_and_genre(self):
        assert charts._build_lastfm_tag("90s", "dance") == "90s dance"

    def test_normalizes_case(self):
        assert charts._build_lastfm_tag("90S", "DANCE") == "90s dance"

    def test_fallback_empty(self):
        assert charts._build_lastfm_tag("", "") == "pop"
        assert charts._build_lastfm_tag(None, None) == "pop"


# ==================================================================
# Last.fm fetch
# ==================================================================
class TestFetchLastfm:
    _SAMPLE = {
        "tracks": {
            "track": [
                {
                    "name": "Blue (Da Ba Dee)",
                    "artist": {"name": "Eiffel 65"},
                    "listeners": "12345",
                    "image": [
                        {"#text": "small.jpg", "size": "small"},
                        {"#text": "large.jpg", "size": "large"},
                    ],
                },
                {
                    "name": "Barbie Girl",
                    "artist": {"name": "Aqua"},
                    "listeners": "9999",
                    "image": [],
                },
            ]
        }
    }

    @responses.activate
    def test_fetch_lastfm_parses_response(self, patched_cache):
        responses.add(responses.GET, charts._LASTFM_URL, json=self._SAMPLE, status=200)
        out = charts.fetch_lastfm("90s", "dance", force=True)
        assert len(out) == 2
        assert out[0]["artist"] == "Eiffel 65"
        assert out[0]["title"] == "Blue (Da Ba Dee)"
        # Ultima immagine della lista
        assert out[0]["image_url"] == "large.jpg"
        assert out[0]["popularity"] == "12345"
        # Traccia senza immagini: image_url vuoto
        assert out[1]["image_url"] == ""

    @responses.activate
    def test_fetch_lastfm_handles_empty_tracks(self, patched_cache):
        responses.add(
            responses.GET, charts._LASTFM_URL,
            json={"tracks": {}}, status=200,
        )
        assert charts.fetch_lastfm("70s", "rock", force=True) == []

    @responses.activate
    def test_fetch_lastfm_returns_empty_on_error(self, patched_cache):
        responses.add(responses.GET, charts._LASTFM_URL, status=500)
        assert charts.fetch_lastfm("80s", "pop", force=True) == []

    @responses.activate
    def test_fetch_lastfm_uses_cache(self, patched_cache):
        responses.add(responses.GET, charts._LASTFM_URL, json=self._SAMPLE, status=200)
        charts.fetch_lastfm("2000s", "house", force=False)
        charts.fetch_lastfm("2000s", "house", force=False)
        assert len(responses.calls) == 1

    @responses.activate
    def test_fetch_lastfm_sends_configured_tag(self, patched_cache):
        responses.add(responses.GET, charts._LASTFM_URL, json=self._SAMPLE, status=200)
        charts.fetch_lastfm("90s", "dance", force=True)
        assert "tag=90s+dance" in responses.calls[0].request.url


# ==================================================================
# Cache TTL
# ==================================================================
class TestCacheTtl:
    @responses.activate
    def test_cache_ttl_expires(self, patched_cache):
        sample = {"feed": {"results": []}}
        responses.add(
            responses.GET,
            charts._ITUNES_URL_TPL.format(country="it"),
            json=sample, status=200,
        )
        responses.add(
            responses.GET,
            charts._ITUNES_URL_TPL.format(country="it"),
            json=sample, status=200,
        )

        with freeze_time("2026-01-01 12:00:00"):
            charts.fetch_itunes("it", force=False)
            assert len(responses.calls) == 1

        # +7h -> cache scaduta (TTL 6h)
        with freeze_time("2026-01-01 19:00:00"):
            charts.fetch_itunes("it", force=False)
            assert len(responses.calls) == 2


# ==================================================================
# Spotify chart playlists
# ==================================================================
class TestSpotifyChartsRegistry:
    def test_spotify_charts_dict_has_expected_keys(self):
        expected = {
            "top50_global", "top50_italy", "top50_usa", "top50_uk",
            "viral50_global", "viral50_italy",
        }
        assert expected.issubset(charts._SPOTIFY_CHARTS.keys())
        # Ognuno mappato a (playlist_id, label)
        for k, v in charts._SPOTIFY_CHARTS.items():
            assert isinstance(v, tuple) and len(v) == 2
            assert v[0] and v[1]


class TestFetchSpotify:
    _TRACKS = {
        "items": [
            {
                "track": {
                    "name": "Track One",
                    "popularity": 88,
                    "artists": [{"name": "Artist X"}, {"name": "Artist Y"}],
                    "album": {
                        "name": "Album Z",
                        "images": [{"url": "https://spo/img.jpg"}],
                    },
                }
            },
            {
                "track": {
                    "name": "Track Two",
                    "popularity": 72,
                    "artists": [{"name": "Solo"}],
                    "album": {"name": "Alb2", "images": []},
                }
            },
        ]
    }

    @responses.activate
    def test_fetch_spotify_parses_response(self, patched_cache, monkeypatch):
        monkeypatch.setattr(
            charts, "_spotify_credentials", lambda: ("cid", "csecret"),
        )
        monkeypatch.setattr(
            "core.spotify_client.get_access_token",
            lambda cid, csecret: "tok",
        )
        pid, _ = charts._SPOTIFY_CHARTS["top50_global"]
        responses.add(
            responses.GET,
            f"https://api.spotify.com/v1/playlists/{pid}/tracks",
            json=self._TRACKS,
            status=200,
        )
        out = charts.fetch_spotify("top50_global", force=True)
        assert len(out) == 2
        assert out[0]["rank"] == 1
        assert out[0]["artist"] == "Artist X, Artist Y"
        assert out[0]["title"] == "Track One"
        assert out[0]["album"] == "Album Z"
        assert out[0]["image_url"] == "https://spo/img.jpg"
        assert out[0]["popularity"] == 88
        assert out[1]["image_url"] == ""

    @responses.activate
    def test_fetch_spotify_uses_cache(self, patched_cache, monkeypatch):
        monkeypatch.setattr(
            charts, "_spotify_credentials", lambda: ("cid", "csecret"),
        )
        monkeypatch.setattr(
            "core.spotify_client.get_access_token",
            lambda cid, csecret: "tok",
        )
        pid, _ = charts._SPOTIFY_CHARTS["top50_italy"]
        responses.add(
            responses.GET,
            f"https://api.spotify.com/v1/playlists/{pid}/tracks",
            json=self._TRACKS, status=200,
        )
        charts.fetch_spotify("top50_italy", force=False)
        charts.fetch_spotify("top50_italy", force=False)
        assert len(responses.calls) == 1

    def test_fetch_spotify_returns_empty_if_no_creds(self, patched_cache, monkeypatch):
        monkeypatch.setattr(charts, "_spotify_credentials", lambda: ("", ""))
        assert charts.fetch_spotify("top50_global", force=True) == []

    def test_fetch_spotify_returns_empty_if_invalid_key(self, patched_cache):
        assert charts.fetch_spotify("not_a_real_key", force=True) == []

    @responses.activate
    def test_fetch_spotify_returns_empty_on_404(self, patched_cache, monkeypatch):
        monkeypatch.setattr(
            charts, "_spotify_credentials", lambda: ("cid", "csecret"),
        )
        monkeypatch.setattr(
            "core.spotify_client.get_access_token",
            lambda cid, csecret: "tok",
        )
        pid, _ = charts._SPOTIFY_CHARTS["viral50_global"]
        responses.add(
            responses.GET,
            f"https://api.spotify.com/v1/playlists/{pid}/tracks",
            status=404,
        )
        assert charts.fetch_spotify("viral50_global", force=True) == []


# ==================================================================
# M2O Chart
# ==================================================================
class TestFetchM2O:
    _HTML = """
    <html><body>
      <main>
        <article>
          <div class="chart-left">
            <span class="position equal">1</span>
            <div class="text-list">
              <h3 class="title small song">MOVIN' TO THE SUN</h3>
              <h4 class="title xsmall author">HUGEL, IMAEL ANGEL, ULTRA NATE</h4>
            </div>
          </div>
          <div class="chart-right">
            <figure><img src="https://m2o/img1.jpg"></figure>
          </div>
        </article>
        <article>
          <div class="chart-left">
            <span class="position">2</span>
            <h3 class="title small song">SECOND SONG</h3>
            <h4 class="title xsmall author">DJ TEST</h4>
          </div>
          <div class="chart-right">
            <figure><img src="https://m2o/img2.jpg"></figure>
          </div>
        </article>
        <article>
          <div class="chart-left">
            <span class="position">N/A</span>
            <h3 class="title small song">INVALID</h3>
          </div>
        </article>
      </main>
    </body></html>
    """

    @responses.activate
    def test_fetch_m2o_parses_html(self, patched_cache):
        responses.add(responses.GET, charts._M2O_URL, body=self._HTML, status=200)
        out = charts.fetch_m2o(force=True)
        # Il 3o article ha "N/A" come position -> skippato
        assert len(out) == 2
        assert out[0]["rank"] == 1
        assert out[0]["title"] == "MOVIN' TO THE SUN"
        assert out[0]["artist"] == "HUGEL, IMAEL ANGEL, ULTRA NATE"
        assert out[0]["image_url"] == "https://m2o/img1.jpg"
        assert out[0]["album"] == ""
        assert out[0]["popularity"] is None
        assert out[1]["rank"] == 2

    @responses.activate
    def test_fetch_m2o_skips_invalid_position(self, patched_cache):
        # Solo 1 article valido nella pagina
        responses.add(
            responses.GET, charts._M2O_URL,
            body="""<article>
              <span class="position">not_a_number</span>
              <h3 class="title small song">X</h3>
            </article>""",
            status=200,
        )
        assert charts.fetch_m2o(force=True) == []

    @responses.activate
    def test_fetch_m2o_uses_cache(self, patched_cache):
        responses.add(responses.GET, charts._M2O_URL, body=self._HTML, status=200)
        charts.fetch_m2o(force=False)
        charts.fetch_m2o(force=False)
        assert len(responses.calls) == 1

    @responses.activate
    def test_fetch_m2o_empty_on_error(self, patched_cache):
        responses.add(responses.GET, charts._M2O_URL, status=500)
        assert charts.fetch_m2o(force=True) == []
