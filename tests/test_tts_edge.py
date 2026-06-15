from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src.models import ScriptSegment, VideoScript
from src.tts.edge_tts import generate_all_audio


def _script(count: int) -> VideoScript:
    return VideoScript(
        title="测试脚本",
        total_duration=float(count),
        segments=[
            ScriptSegment(
                timestamp=float(index),
                duration=1.0,
                narration=f"第 {index} 段",
                action="show",
                target="",
            )
            for index in range(count)
        ],
    )


class EdgeTtsTest(unittest.TestCase):
    def test_generate_all_audio_keeps_order_while_generating_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            started: list[str] = []

            async def fake_generate(text: str, output_path: Path, voice: str = "", rate: str = "") -> Path:
                started.append(text)
                await asyncio.sleep(0.03 if output_path.name == "segment-000.mp3" else 0.01)
                output_path.write_bytes(b"audio")
                return output_path

            with (
                patch("src.tts.edge_tts._is_valid_audio", return_value=False),
                patch("src.tts.edge_tts.generate_audio_segment", side_effect=fake_generate),
            ):
                before = time.perf_counter()
                result = asyncio.run(generate_all_audio(_script(3), Path(tmp)))
                elapsed = time.perf_counter() - before

            self.assertEqual([path.name for path in result], ["segment-000.mp3", "segment-001.mp3", "segment-002.mp3"])
            self.assertEqual(started, ["第 0 段", "第 1 段", "第 2 段"])
            self.assertLess(elapsed, 0.06)

    def test_generate_all_audio_reuses_valid_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio_dir = Path(tmp) / "audio"
            audio_dir.mkdir()
            reused = audio_dir / "segment-000.mp3"
            reused.write_bytes(b"existing")

            async def fake_generate(text: str, output_path: Path, voice: str = "", rate: str = "") -> Path:
                output_path.write_bytes(b"new")
                return output_path

            def fake_valid(path: Path) -> bool:
                return path.name == "segment-000.mp3"

            with (
                patch("src.tts.edge_tts._is_valid_audio", side_effect=fake_valid),
                patch("src.tts.edge_tts.generate_audio_segment", side_effect=fake_generate) as generate,
            ):
                result = asyncio.run(generate_all_audio(_script(2), Path(tmp)))

            generate.assert_called_once()
            self.assertEqual(result, [audio_dir / "segment-000.mp3", audio_dir / "segment-001.mp3"])


if __name__ == "__main__":
    unittest.main()
