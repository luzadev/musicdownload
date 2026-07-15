"""Test per core.tagger — filename sanitization + write_tags safety net."""

from __future__ import annotations

from core import tagger


class TestSanitizeFilenameStem:
    def test_removes_bad_chars(self):
        # Tutti i char vietati su Windows/macOS: < > : " / \ | ? *
        got = tagger.sanitize_filename_stem('bad<name>:"/\\|?*test')
        # Nessuno dei char proibiti sopravvive
        for ch in '<>:"/\\|?*':
            assert ch not in got
        # E ho ottenuto qualcosa di non vuoto
        assert got

    def test_collapses_whitespace(self):
        assert tagger.sanitize_filename_stem("a    b    c") == "a b c"

    def test_truncates_long_stem(self):
        s = "x" * 500
        got = tagger.sanitize_filename_stem(s, max_len=180)
        assert len(got) <= 180

    def test_empty_returns_untitled(self):
        assert tagger.sanitize_filename_stem("") == "untitled"
        assert tagger.sanitize_filename_stem("   ") == "untitled"


class TestBuildFilenameStem:
    def test_format_artist_dash_title(self):
        assert tagger.build_filename_stem("Kapuchon", "Hot Sauce") == "Kapuchon - Hot Sauce"

    def test_multiple_artists_ok(self):
        got = tagger.build_filename_stem("Kapuchon, Miss Monique & GLZ", "Hot Sauce (Extended)")
        assert got == "Kapuchon, Miss Monique & GLZ - Hot Sauce (Extended)"

    def test_missing_artist_uses_title_only(self):
        assert tagger.build_filename_stem("", "Only Title") == "Only Title"

    def test_missing_title_uses_artist_only(self):
        assert tagger.build_filename_stem("Only Artist", "") == "Only Artist"

    def test_sanitizes_bad_chars(self):
        got = tagger.build_filename_stem("A/B", "C:D")
        # Nessuno slash o colon residuo
        assert "/" not in got
        assert ":" not in got


class TestWriteTagsMissingFile:
    def test_missing_file_is_noop(self):
        # Non deve sollevare alcuna eccezione se il file non esiste
        tagger.write_tags("/nonexistent/path/to/file.mp3", {
            "title": "x", "artist": "y", "cover_url": "http://example.com/x.jpg",
        })
