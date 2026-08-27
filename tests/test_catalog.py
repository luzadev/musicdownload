"""Test per core.catalog — sanitize + move_files + scan_folder.

Focus principale sui casi in cui il piano ha promesso comportamento
esplicito: sanitize dei chars vietati, struttura year/genre, gestione
di anno/genere mancanti, conflitto di filename.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from core import catalog


# ------------------------------------------------------------------
# Sanitize
# ------------------------------------------------------------------
class TestSanitizeFolder:
    def test_sanitize_folder_removes_forbidden_chars(self):
        # `/` (dai tag musicbrainz), `:` (Windows), `?`, `*`, `|`, ecc.
        s = catalog._sanitize_folder("electronic/house")
        assert "/" not in s
        assert "electronic" in s and "house" in s

        s2 = catalog._sanitize_folder("prog:rock?")
        for ch in '<>:"|?*\\/':
            assert ch not in s2

    def test_sanitize_folder_collapses_spaces(self):
        assert catalog._sanitize_folder("  tech  house  ") == "tech house"

    def test_sanitize_folder_empty_returns_empty(self):
        assert catalog._sanitize_folder("") == ""
        assert catalog._sanitize_folder(None) == ""

    def test_sanitize_folder_truncates_long(self):
        s = catalog._sanitize_folder("a" * 300)
        assert len(s) <= 100


# ------------------------------------------------------------------
# move_files
# ------------------------------------------------------------------
def _touch(path: Path, size: int = 8) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    return path


class TestMoveFiles:
    def test_move_files_creates_year_genre_structure(self, tmp_path):
        """Un file matched → finisce in <target>/<year>/<genre>/<filename>."""
        src = _touch(tmp_path / "source" / "song.mp3")
        target = tmp_path / "cat"
        entries = [{
            "path": str(src), "size": src.stat().st_size,
            "matched": True, "year": 2005, "genre": "House",
            "artist": "X", "title": "T", "fingerprint": "FP",
        }]

        res = catalog.move_files(entries, str(target))

        assert res["moved"] == 1
        assert res["failed"] == []
        dst = target / "2005" / "House" / "song.mp3"
        assert dst.exists()
        assert not src.exists()
        # Log operations popolato
        assert res["operations"] and res["operations"][0]["src"] == str(src)
        assert res["operations"][0]["dst"] == str(dst)

    def test_move_files_handles_missing_year_or_genre(self, tmp_path):
        """Year/genre mancanti → Unknown Year / Unknown Genre."""
        no_year = _touch(tmp_path / "src" / "no_year.mp3")
        no_genre = _touch(tmp_path / "src" / "no_genre.mp3")
        no_both = _touch(tmp_path / "src" / "no_both.mp3")

        target = tmp_path / "cat"
        entries = [
            {"path": str(no_year), "matched": True, "year": None,
             "genre": "House"},
            {"path": str(no_genre), "matched": True, "year": 2010,
             "genre": ""},
            {"path": str(no_both), "matched": False, "year": None,
             "genre": ""},
        ]

        res = catalog.move_files(entries, str(target))
        assert res["moved"] == 3
        assert (target / "Unknown Year" / "House" / "no_year.mp3").exists()
        assert (target / "2010" / "Unknown Genre" / "no_genre.mp3").exists()
        assert (target / "Unknown Year" / "Unknown Genre"
                / "no_both.mp3").exists()

    def test_move_files_dedup_conflicting_filenames(self, tmp_path):
        """Se un file con lo stesso nome esiste gia' nel target, aggiungi
        suffisso _1, _2, ... (mai overwrite)."""
        src1 = _touch(tmp_path / "srcA" / "song.mp3", size=10)
        src2 = _touch(tmp_path / "srcB" / "song.mp3", size=20)
        target = tmp_path / "cat"

        entries = [
            {"path": str(src1), "matched": True, "year": 2000,
             "genre": "Rock"},
            {"path": str(src2), "matched": True, "year": 2000,
             "genre": "Rock"},
        ]
        res = catalog.move_files(entries, str(target))
        assert res["moved"] == 2
        d1 = target / "2000" / "Rock" / "song.mp3"
        d2 = target / "2000" / "Rock" / "song_1.mp3"
        assert d1.exists() and d2.exists()
        # Contenuto preservato dal move (src1 = 10 byte, src2 = 20 byte).
        # L'ordine di iterazione garantisce che song.mp3 = src1.
        assert d1.stat().st_size == 10
        assert d2.stat().st_size == 20

    def test_move_files_sanitizes_forbidden_genre(self, tmp_path):
        """Genere con `/` (tipico di musicbrainz) va sanitizzato in `_`."""
        src = _touch(tmp_path / "src" / "song.mp3")
        target = tmp_path / "cat"
        entries = [{
            "path": str(src), "matched": True, "year": 2020,
            "genre": "electronic/house",
        }]

        res = catalog.move_files(entries, str(target))
        assert res["moved"] == 1
        # NON deve creare "electronic" e dentro "house": e' un solo nome.
        assert not (target / "2020" / "electronic").is_dir()
        # La cartella deve contenere entrambe le parti sanitizzate
        year_dir = target / "2020"
        subdirs = [p.name for p in year_dir.iterdir() if p.is_dir()]
        assert len(subdirs) == 1
        assert "/" not in subdirs[0]
        assert "electronic" in subdirs[0] and "house" in subdirs[0]

    def test_move_files_missing_source_reports_failed(self, tmp_path):
        """File che non esiste piu' → finisce in failed, non alza."""
        target = tmp_path / "cat"
        entries = [{
            "path": str(tmp_path / "does_not_exist.mp3"),
            "matched": True, "year": 2000, "genre": "X",
        }]
        res = catalog.move_files(entries, str(target))
        assert res["moved"] == 0
        assert len(res["failed"]) == 1
        assert "non esiste" in res["failed"][0]["error"].lower()

    def test_move_files_empty_list_returns_zero(self, tmp_path):
        res = catalog.move_files([], str(tmp_path / "cat"))
        assert res["moved"] == 0
        assert res["failed"] == []
        assert res["operations"] == []


# ------------------------------------------------------------------
# scan_folder — smoke integration test (mock fpcalc + lookup)
# ------------------------------------------------------------------
class TestScanFolder:
    def test_scan_folder_empty_directory(self, tmp_path):
        # Cartella senza file audio → lista vuota, no crash
        with mock.patch.object(catalog, "find_fpcalc",
                                return_value="/fake/fpcalc"):
            entries = catalog.scan_folder(str(tmp_path), recursive=False)
        assert entries == []

    def test_scan_folder_processes_files(self, tmp_path):
        # Un file audio fake + mock di fpcalc + lookup
        (tmp_path / "a.mp3").write_bytes(b"\x00" * 100)
        (tmp_path / "readme.txt").write_text("hi")

        with mock.patch.object(catalog, "find_fpcalc",
                                return_value="/fake/fpcalc"), \
             mock.patch.object(catalog, "compute_fingerprint",
                                return_value={"fingerprint": "FP", "duration": 100}), \
             mock.patch.object(catalog, "lookup",
                                return_value={
                                    "matched": True, "year": 2018,
                                    "genre": "House", "artist": "A",
                                    "title": "T",
                                }):
            entries = catalog.scan_folder(str(tmp_path), recursive=False)

        assert len(entries) == 1
        e = entries[0]
        assert e["matched"] is True
        assert e["year"] == 2018
        assert e["genre"] == "House"
        assert e["fingerprint"] == "FP"

    def test_scan_folder_records_fpcalc_error(self, tmp_path):
        """fpcalc fallito → entry con matched=False + error."""
        (tmp_path / "broken.mp3").write_bytes(b"\x00" * 10)
        with mock.patch.object(catalog, "find_fpcalc",
                                return_value="/fake/fpcalc"), \
             mock.patch.object(catalog, "compute_fingerprint",
                                return_value={"_error": "fingerprint vuoto"}):
            entries = catalog.scan_folder(str(tmp_path), recursive=False)
        assert len(entries) == 1
        assert entries[0]["matched"] is False
        assert "vuoto" in entries[0]["error"]
