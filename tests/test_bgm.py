from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.composer.bgm import post_process_video
from src.utils.config import BGM_VOLUME


class BgmTest(unittest.TestCase):
    def test_post_process_uses_custom_bgm_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "video.mp4"
            bgm = Path(tmp) / "custom.mp3"
            video.write_bytes(b"video")
            bgm.write_bytes(b"audio")

            with (
                patch("src.composer.bgm.add_bgm") as add_bgm,
                patch("src.composer.bgm.normalize_audio") as normalize_audio,
            ):
                normalize_audio.side_effect = lambda path: path
                post_process_video(video, bgm_path=bgm)

            add_bgm.assert_called_once_with(video, bgm, video, volume=BGM_VOLUME)


if __name__ == "__main__":
    unittest.main()
