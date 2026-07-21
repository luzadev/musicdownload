"""Test per core.converter — file scanning + stop event.

I test evitano di invocare ffmpeg reale (che potrebbe non essere in PATH
in CI). La funzione di conversione vera e propria e' coperta manualmente.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import converter


class TestListWavFiles:
    def test_scans_recursively(self, tmp_path: Path):
        # Struttura:
        #   root/a.wav
        #   root/b.WAV  (case insensitive: glob su POSIX distingue,
        #                quindi controllo esplicito che almeno i .wav
        #                minuscoli siano restituiti)
        #   root/c.mp3
        #   root/sub/d.wav
        (tmp_path / "a.wav").write_bytes(b"RIFF")
        (tmp_path / "c.mp3").write_bytes(b"ID3")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "d.wav").write_bytes(b"RIFF")

        got = converter.list_wav_files(str(tmp_path), recursive=True)

        assert len(got) == 2
        names = {Path(p).name for p in got}
        assert names == {"a.wav", "d.wav"}
        # Ordinamento stabile
        assert got == sorted(got)

    def test_non_recursive_ignores_subfolders(self, tmp_path: Path):
        (tmp_path / "a.wav").write_bytes(b"RIFF")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.wav").write_bytes(b"RIFF")

        got = converter.list_wav_files(str(tmp_path), recursive=False)

        assert len(got) == 1
        assert Path(got[0]).name == "a.wav"

    def test_empty_dir_returns_empty(self, tmp_path: Path):
        assert converter.list_wav_files(str(tmp_path)) == []

    def test_missing_dir_returns_empty(self, tmp_path: Path):
        missing = tmp_path / "does-not-exist"
        assert converter.list_wav_files(str(missing)) == []

    def test_ignores_non_wav_files(self, tmp_path: Path):
        (tmp_path / "song.mp3").write_bytes(b"ID3")
        (tmp_path / "song.flac").write_bytes(b"fLaC")
        (tmp_path / "notes.txt").write_text("hello")

        assert converter.list_wav_files(str(tmp_path)) == []


class TestStopEvent:
    def setup_method(self):
        # Ogni test parte con lo stop event pulito.
        converter.reset_stop()

    def teardown_method(self):
        converter.reset_stop()

    def test_reset_initially_not_stopped(self):
        converter.reset_stop()
        assert converter.is_stopped() is False

    def test_request_stop_sets_flag(self):
        converter.request_stop()
        assert converter.is_stopped() is True

    def test_reset_after_stop_clears_flag(self):
        converter.request_stop()
        assert converter.is_stopped() is True
        converter.reset_stop()
        assert converter.is_stopped() is False


class TestConvertWavToMp3Errors:
    def test_missing_input_raises(self, tmp_path: Path):
        missing = tmp_path / "nope.wav"
        out = tmp_path / "out.mp3"
        with pytest.raises(FileNotFoundError):
            converter.convert_wav_to_mp3(str(missing), str(out))


class TestVbrQualityMap:
    def test_all_bitrates_have_mapping(self):
        for br in (128, 192, 256, 320):
            assert br in converter._VBR_QUALITY

    def test_higher_bitrate_lower_or_equal_quality_number(self):
        # -q:a: piu' basso = migliore. Coerenza monotona sulle chiavi.
        vals = [converter._VBR_QUALITY[br] for br in (128, 192, 256, 320)]
        assert vals == sorted(vals, reverse=True)
