from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.composer.vertical import compose_vertical_video
from src.models import AssetManifest, ScriptSegment, Shot, ShotPlan, VideoScript, VisualAsset


class FakeVideoClip:
    def __init__(self, make_frame, duration: float):
        self.make_frame = make_frame
        self.duration = duration

    def with_audio(self, _audio):
        return self

    def write_videofile(self, *args, fps=30, **kwargs):
        self.make_frame(0.10)
        self.make_frame(0.11)

    def close(self):
        pass


class FakeAudioClip:
    def __init__(self, *args, **kwargs):
        pass

    def close(self):
        pass


class VerticalComposerCacheTest(unittest.TestCase):
    def test_compose_vertical_video_reuses_discretized_rendered_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            asset_path = base / "asset.png"
            Image.new("RGB", (320, 240), (255, 0, 0)).save(asset_path)

            script = VideoScript(
                title="测试",
                total_duration=1,
                segments=[
                    ScriptSegment(
                        timestamp=0,
                        duration=1,
                        narration="测试口播",
                        action="show",
                        target="",
                    )
                ],
            )
            shot_plan = ShotPlan(
                title="测试",
                shots=[
                    Shot(
                        start=0,
                        duration=1,
                        visual_asset="a1",
                        visual_treatment="hotlist_opening",
                        narration_intent="开场",
                        subtitle="测试",
                    )
                ],
            )
            manifest = AssetManifest(assets=[
                VisualAsset(
                    id="a1",
                    type="image",
                    source=str(asset_path),
                    path=str(asset_path),
                    caption="测试",
                    use_case="测试",
                    quality="high",
                )
            ])

            calls = 0

            def fake_render(*args, **kwargs):
                nonlocal calls
                calls += 1
                return Image.new("RGB", (1080, 1920), (0, 0, 0))

            with (
                patch("src.composer.vertical.VideoClip", FakeVideoClip),
                patch("src.composer.vertical.AudioClip", FakeAudioClip),
                patch("src.composer.vertical._render_frame", side_effect=fake_render),
            ):
                compose_vertical_video(
                    script=script,
                    shot_plan=shot_plan,
                    manifest=manifest,
                    audio_dir=base / "audio",
                    output_path=base / "final.mp4",
                    preview_dir=base / "preview",
                    fps=30,
                )

            self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
