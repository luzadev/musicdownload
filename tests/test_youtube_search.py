"""Test per core.youtube_search."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from core import youtube_search


def _mock_ytdlp_result(entries: list) -> MagicMock:
    """Mock subprocess.CompletedProcess con JSON stub."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = json.dumps({"entries": entries})
    result.stderr = ""
    return result


class TestSearchYoutube:
    def test_parses_entries(self):
        entries = [
            {
                "id": "abc123",
                "url": "https://www.youtube.com/watch?v=abc123",
                "title": "Kapuchon - Hot Sauce (Official Video)",
                "uploader": "Kapuchon Official",
                "duration": 336,
            },
            {
                "id": "def456",
                "url": "https://www.youtube.com/watch?v=def456",
                "title": "Solomun @ Cocoricò 2024",
                "uploader": "Cocoricò",
                "duration": 3600,
            },
        ]
        with patch("core.youtube_search.find_ytdlp", return_value="/fake/yt-dlp"), \
             patch("core.youtube_search.subprocess.run", return_value=_mock_ytdlp_result(entries)):
            result = youtube_search.search_youtube("kapuchon hot sauce", limit=50)
        assert len(result) == 2
        assert result[0]["title"] == "Kapuchon - Hot Sauce (Official Video)"
        assert result[0]["channel"] == "Kapuchon Official"
        assert result[0]["duration_sec"] == 336
        assert result[0]["url"] == "https://www.youtube.com/watch?v=abc123"

    def test_empty_entries_returns_empty(self):
        with patch("core.youtube_search.find_ytdlp", return_value="/fake/yt-dlp"), \
             patch("core.youtube_search.subprocess.run", return_value=_mock_ytdlp_result([])):
            result = youtube_search.search_youtube("no-match", limit=50)
        assert result == []

    def test_raises_when_ytdlp_missing(self):
        with patch("core.youtube_search.find_ytdlp", return_value=None):
            with pytest.raises(RuntimeError, match="yt-dlp"):
                youtube_search.search_youtube("q", limit=50)

    def test_command_uses_ytsearch_with_limit(self):
        with patch("core.youtube_search.find_ytdlp", return_value="/fake/yt-dlp"), \
             patch("core.youtube_search.subprocess.run", return_value=_mock_ytdlp_result([])) as mock_run:
            youtube_search.search_youtube("solomun", limit=30)
        args = mock_run.call_args.args[0]
        assert args[0] == "/fake/yt-dlp"
        search_arg = [a for a in args if a.startswith("ytsearch")]
        assert search_arg == ["ytsearch30:solomun"]

    def test_timeout_raises_runtime_error(self):
        import subprocess as sp
        with patch("core.youtube_search.find_ytdlp", return_value="/fake/yt-dlp"), \
             patch("core.youtube_search.subprocess.run", side_effect=sp.TimeoutExpired("yt-dlp", 30)):
            with pytest.raises(RuntimeError, match="[Tt]imeout"):
                youtube_search.search_youtube("q", limit=50)

    def test_nonzero_exit_raises(self):
        bad = MagicMock()
        bad.returncode = 1
        bad.stdout = ""
        bad.stderr = "some yt-dlp error"
        with patch("core.youtube_search.find_ytdlp", return_value="/fake/yt-dlp"), \
             patch("core.youtube_search.subprocess.run", return_value=bad):
            with pytest.raises(RuntimeError, match="yt-dlp"):
                youtube_search.search_youtube("q", limit=50)
