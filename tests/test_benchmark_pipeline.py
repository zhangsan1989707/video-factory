from __future__ import annotations

import unittest

from scripts.benchmark_pipeline import format_timing_summary


class BenchmarkPipelineTest(unittest.TestCase):
    def test_format_timing_summary_lists_total_and_stages(self) -> None:
        report = {
            "total_seconds": 1.2345,
            "stages": [
                {"name": "repository_fetch", "seconds": 0.5},
                {"name": "compose_video", "seconds": 0.734},
            ],
        }

        summary = format_timing_summary(report)

        self.assertIn("total: 1.234s", summary)
        self.assertIn("- repository_fetch: 0.500s", summary)
        self.assertIn("- compose_video: 0.734s", summary)


if __name__ == "__main__":
    unittest.main()
