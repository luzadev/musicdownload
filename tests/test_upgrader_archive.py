"""Test unitari per le funzioni di archive-lookup in core.upgrader.

Focalizzati su _normalize_stem, _scan_archive, _find_candidates.
Non testiamo il flow end-to-end di upgrade_folder (richiederebbe mock
di subprocess/yt-dlp/ffmpeg — out of scope, coperto da smoke test manuale).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core import upgrader


# ============================================================
# _normalize_stem
# ============================================================
class TestNormalizeStem:
    def test_lowercase_and_dedup(self):
        # "Hot" e "hot" → un solo token; token duplicati collassano nel set
        got = upgrader._normalize_stem("Hot Sauce hot sauce")
        assert got == {"hot", "sauce"}

    def test_filters_short_tokens(self):
        # Token di lunghezza < 3 vengono scartati (di, il, a, b, cd...)
        got = upgrader._normalize_stem("A B cd Boombox")
        assert "a" not in got
        assert "b" not in got
        assert "cd" not in got
        assert "boombox" in got

    def test_removes_punctuation(self):
        # Trattini, virgole, parentesi, apostrofi → tutti sostituiti con spazi
        got = upgrader._normalize_stem("Artist - Title (Extended Mix)")
        assert got == {"artist", "title", "extended", "mix"}

    def test_empty_input(self):
        assert upgrader._normalize_stem("") == set()
        assert upgrader._normalize_stem("   ") == set()

    def test_only_short_tokens_returns_empty(self):
        assert upgrader._normalize_stem("a b c d") == set()


# ============================================================
# _scan_archive
# ============================================================
class TestScanArchive:
    def test_recursive_scan(self, tmp_path: Path):
        # Crea albero: top-level + sub/ + sub/sub2/
        (tmp_path / "Artist - Song.mp3").touch()
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "Second Track.mp3").touch()
        (tmp_path / "sub" / "sub2").mkdir()
        (tmp_path / "sub" / "sub2" / "Deep One.m4a").touch()
        # File non-audio devono essere ignorati
        (tmp_path / "readme.txt").touch()

        index = upgrader._scan_archive(str(tmp_path))
        # 3 entries totali (una per ogni file audio, ognuna con token distinti)
        assert len(index) == 3
        # Verifica che le path siano riferite ai file corretti
        all_paths = [p for paths in index.values() for p in paths]
        names = sorted(p.name for p in all_paths)
        assert names == ["Artist - Song.mp3", "Deep One.m4a", "Second Track.mp3"]

    def test_case_insensitive_extensions(self, tmp_path: Path):
        (tmp_path / "one.MP3").touch()
        (tmp_path / "two.Mp3").touch()
        (tmp_path / "three.WAV").touch()
        (tmp_path / "four.FLAC").touch()
        (tmp_path / "five.txt").touch()  # non-audio: ignorato
        index = upgrader._scan_archive(str(tmp_path))
        all_paths = [p for paths in index.values() for p in paths]
        assert len(all_paths) == 4  # 4 file audio, 1 skippato

    def test_duplicates_appended(self, tmp_path: Path):
        # Due file con stesso token set → stessa key, due path
        (tmp_path / "sub1").mkdir()
        (tmp_path / "sub2").mkdir()
        (tmp_path / "sub1" / "Hot Sauce.mp3").touch()
        (tmp_path / "sub2" / "Hot Sauce.mp3").touch()
        index = upgrader._scan_archive(str(tmp_path))
        assert len(index) == 1
        # Una sola chiave, con 2 path
        paths = list(index.values())[0]
        assert len(paths) == 2

    def test_nonexistent_dir_returns_empty(self, tmp_path: Path):
        assert upgrader._scan_archive(str(tmp_path / "nope")) == {}

    def test_empty_stems_skipped(self, tmp_path: Path):
        # File il cui stem produce zero token utili (solo caratteri corti) → skip
        (tmp_path / "a.mp3").touch()
        (tmp_path / "Real Track Name.mp3").touch()
        index = upgrader._scan_archive(str(tmp_path))
        # Solo "Real Track Name.mp3" ha token >=3 chars
        all_paths = [p for paths in index.values() for p in paths]
        assert len(all_paths) == 1
        assert all_paths[0].name == "Real Track Name.mp3"


# ============================================================
# _find_candidates
# ============================================================
class TestFindCandidates:
    def _fake_index(self, tmp_path: Path, entries: list) -> dict:
        """Helper: crea file (touch) e ritorna un index manuale."""
        index: dict = {}
        for name in entries:
            p = tmp_path / name
            p.touch()
            tokens = upgrader._normalize_stem(p.stem)
            key = upgrader._tokens_to_key(tokens)
            index.setdefault(key, []).append(p)
        return index

    def test_ranking_bitrate_desc_then_similarity_desc(self, tmp_path: Path):
        # 3 candidati: variamo bitrate + similarity per verificare l'ordine
        #   a: sim alta (0.75), bitrate basso (128)
        #   b: sim media (0.5), bitrate alto (320)
        #   c: sim alta (0.75), bitrate medio (192)
        # Ordine atteso: b(320) > c(192, sim 0.75) > a(128)
        idx = self._fake_index(tmp_path, [
            "Artist - Hot Sauce.mp3",             # a: 3 token comuni su 4 = 0.75
            "Different Song Boombox.mp3",         # b: 1 su 5 = 0.2  (troppo bassa, filtrato)
            "Artist Hot Sauce Extended.mp3",      # c: 3 su 4 = 0.75
        ])
        # Target: "Artist Hot Sauce" → tokens = {artist, hot, sauce}
        target = "Artist Hot Sauce"

        # Mock bitrate: mappa nome → kbps
        def fake_bitrate(p):
            n = Path(p).name
            if n == "Artist - Hot Sauce.mp3":       return 128
            if n == "Different Song Boombox.mp3":   return 320
            if n == "Artist Hot Sauce Extended.mp3": return 192
            return 0

        with patch.object(upgrader, "get_bitrate", side_effect=fake_bitrate):
            results = upgrader._find_candidates(target, idx, min_similarity=0.3)

        # "b" viene filtrato (sim 1/5 = 0.2 < 0.3 min); restano a e c
        assert len(results) == 2
        # c (bitrate 192) prima di a (bitrate 128)
        assert results[0][0].name == "Artist Hot Sauce Extended.mp3"
        assert results[1][0].name == "Artist - Hot Sauce.mp3"

    def test_below_threshold_filtered(self, tmp_path: Path):
        # Un solo candidato con similarity ~ 1/5 = 0.2 → sotto default 0.5 → escluso
        idx = self._fake_index(tmp_path, [
            "Foo Bar Baz Qux Extra.mp3",
        ])
        with patch.object(upgrader, "get_bitrate", return_value=320):
            results = upgrader._find_candidates("Hot Sauce", idx)  # solo "hot"/"sauce"
        assert results == []

    def test_exact_match_returned(self, tmp_path: Path):
        idx = self._fake_index(tmp_path, [
            "Hot Sauce Extended.mp3",
        ])
        with patch.object(upgrader, "get_bitrate", return_value=320):
            results = upgrader._find_candidates("Hot Sauce Extended", idx)
        assert len(results) == 1
        assert results[0][1] == 1.0  # perfect Jaccard
        assert results[0][2] == 320
