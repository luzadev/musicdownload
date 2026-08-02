"""Test per core.dedup — audio fingerprinting via fpcalc + cache SQLite.

Tutti gli unit test usano mock per fpcalc / send2trash: nessuna
integrazione reale, nessun file audio necessario.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from core import dedup


# ------------------------------------------------------------------
# Fixture: dedup con cache DB isolato in tmp_path
# ------------------------------------------------------------------
@pytest.fixture
def patched_cache(tmp_path, monkeypatch):
    """Isola la cache SQLite in tmp_path per non toccare il config dir."""
    db = tmp_path / "dedup_cache_test.db"
    monkeypatch.setattr(dedup, "_cache_db_path", lambda: db)
    return db


def _make_fake_audio(tmp_path: Path, name: str, size: int = 1024) -> Path:
    """Crea un file 'audio' fake (byte casuali con estensione .mp3)."""
    f = tmp_path / name
    f.write_bytes(b"\x00" * size)
    return f


# ------------------------------------------------------------------
# scan_folder
# ------------------------------------------------------------------
class TestScanFolder:
    def test_no_audio_files(self, tmp_path, patched_cache):
        """Cartella senza audio -> gruppi vuoti, nessuna eccezione."""
        # Solo un file .txt (non audio)
        (tmp_path / "readme.txt").write_text("hello")

        # Anche senza fpcalc disponibile, con 0 audio file ritorna [].
        with mock.patch.object(dedup, "find_fpcalc", return_value="/fake/fpcalc"):
            groups = dedup.scan_folder(str(tmp_path), recursive=False)

        assert groups == []

    def test_uses_cache_on_second_scan(self, tmp_path, patched_cache):
        """Prima scan chiama fpcalc; seconda scan riusa la cache."""
        _make_fake_audio(tmp_path, "song.mp3", size=2048)

        calls: list[str] = []

        def fake_compute(fpcalc, path):
            calls.append(path)
            return {"duration": 180.5, "fingerprint": "FP-A"}

        with mock.patch.object(dedup, "find_fpcalc", return_value="/fake/fpcalc"), \
             mock.patch.object(dedup, "compute_fingerprint", side_effect=fake_compute), \
             mock.patch.object(dedup, "get_bitrate", return_value=320):
            # Prima invocazione: fpcalc DEVE essere chiamato
            groups1 = dedup.scan_folder(str(tmp_path), recursive=False)
            first_calls = len(calls)

            # Seconda invocazione (stesso file, stesso mtime/size):
            # cache HIT, fpcalc NON viene richiamato
            groups2 = dedup.scan_folder(str(tmp_path), recursive=False)
            second_calls = len(calls)

        assert first_calls == 1, "prima scan deve chiamare fpcalc una volta"
        assert second_calls == 1, "seconda scan deve riusare la cache"
        # Con un solo file, nessun gruppo di duplicati
        assert groups1 == []
        assert groups2 == []

    def test_groups_duplicates(self, tmp_path, patched_cache):
        """3 file con lo stesso fingerprint -> 1 gruppo di 3, ordinato per bitrate DESC."""
        _make_fake_audio(tmp_path, "a.mp3", size=1000)
        _make_fake_audio(tmp_path, "b.mp3", size=3000)  # size maggiore
        _make_fake_audio(tmp_path, "c.mp3", size=2000)

        # Tutti stesso fingerprint. Bitrate differente per verificare
        # l'ordinamento: b=320 (top), a=192, c=128.
        bitrate_by_name = {"a.mp3": 192, "b.mp3": 320, "c.mp3": 128}

        with mock.patch.object(dedup, "find_fpcalc", return_value="/fake/fpcalc"), \
             mock.patch.object(dedup, "compute_fingerprint",
                               return_value={"duration": 200, "fingerprint": "SAME-FP"}), \
             mock.patch.object(dedup, "get_bitrate",
                               side_effect=lambda p: bitrate_by_name[Path(p).name]):
            groups = dedup.scan_folder(str(tmp_path), recursive=False)

        assert len(groups) == 1, "esattamente un gruppo di duplicati"
        g = groups[0]
        assert len(g) == 3, "tre file nel gruppo"
        # Ordine: bitrate DESC -> b (320), a (192), c (128)
        assert [Path(e["path"]).name for e in g] == ["b.mp3", "a.mp3", "c.mp3"]
        # Ogni entry ha i campi attesi
        for e in g:
            assert set(e.keys()) >= {"path", "size", "bitrate", "duration", "fingerprint"}
            assert e["fingerprint"] == "SAME-FP"

    def test_ignores_singletons(self, tmp_path, patched_cache):
        """File con fingerprint unico non compaiono nei gruppi."""
        _make_fake_audio(tmp_path, "dup1.mp3")
        _make_fake_audio(tmp_path, "dup2.mp3")
        _make_fake_audio(tmp_path, "unique.mp3")

        fp_by_name = {"dup1.mp3": "FP-X", "dup2.mp3": "FP-X", "unique.mp3": "FP-Y"}

        def fake_compute(fpcalc, path):
            return {"duration": 100, "fingerprint": fp_by_name[Path(path).name]}

        with mock.patch.object(dedup, "find_fpcalc", return_value="/fake/fpcalc"), \
             mock.patch.object(dedup, "compute_fingerprint", side_effect=fake_compute), \
             mock.patch.object(dedup, "get_bitrate", return_value=256):
            groups = dedup.scan_folder(str(tmp_path), recursive=False)

        # Solo il gruppo con dup1/dup2
        assert len(groups) == 1
        names = {Path(e["path"]).name for e in groups[0]}
        assert names == {"dup1.mp3", "dup2.mp3"}
        # unique.mp3 non appare in nessun gruppo
        for g in groups:
            for e in g:
                assert Path(e["path"]).name != "unique.mp3"


# ------------------------------------------------------------------
# move_to_trash
# ------------------------------------------------------------------
class TestMoveToTrash:
    def test_returns_moved_and_failed_summary(self, tmp_path, patched_cache):
        """Verifica che il summary contenga moved/failed correttamente."""
        # 2 path OK + 1 path che alza eccezione
        ok1 = str(tmp_path / "ok1.mp3")
        ok2 = str(tmp_path / "ok2.mp3")
        bad = str(tmp_path / "bad.mp3")

        def fake_send(p):
            if p == bad:
                raise OSError("simulated failure")
            # ok: no-op

        # Il modulo importa send2trash *dentro* la funzione, quindi
        # dobbiamo patchare il modulo importato.
        with mock.patch("send2trash.send2trash", side_effect=fake_send):
            res = dedup.move_to_trash([ok1, bad, ok2])

        assert set(res["moved"]) == {ok1, ok2}
        assert len(res["failed"]) == 1
        assert res["failed"][0]["path"] == bad
        assert "simulated failure" in res["failed"][0]["error"]


# ------------------------------------------------------------------
# compute_fingerprint
# ------------------------------------------------------------------
class TestComputeFingerprint:
    def test_timeout_returns_none(self):
        """Timeout di fpcalc -> None (non alza eccezione)."""
        with mock.patch("core.dedup.subprocess.run",
                        side_effect=subprocess.TimeoutExpired(cmd="fpcalc", timeout=30)):
            result = dedup.compute_fingerprint("/fake/fpcalc", "/some/file.mp3")
        assert result is None

    def test_success_returns_dict(self):
        """Output JSON valido -> {duration, fingerprint}."""
        fake_proc = mock.Mock()
        fake_proc.returncode = 0
        fake_proc.stdout = '{"duration": 123.4, "fingerprint": "ABCDEF"}'
        with mock.patch("core.dedup.subprocess.run", return_value=fake_proc):
            result = dedup.compute_fingerprint("/fake/fpcalc", "/some/file.mp3")
        assert result == {"duration": 123.4, "fingerprint": "ABCDEF"}

    def test_bad_json_returns_none(self):
        fake_proc = mock.Mock()
        fake_proc.returncode = 0
        fake_proc.stdout = "not json at all"
        with mock.patch("core.dedup.subprocess.run", return_value=fake_proc):
            result = dedup.compute_fingerprint("/fake/fpcalc", "/some/file.mp3")
        assert result is None

    def test_missing_fpcalc_returns_none(self):
        # Nessuna chiamata subprocess se fpcalc e' vuoto
        result = dedup.compute_fingerprint("", "/some/file.mp3")
        assert result is None
