"""finance_edu pipeline dry run 测试"""

import asyncio
import json

from src.finance_edu.models import FinanceEduTopic
from src.finance_edu.pipeline import run_finance_edu_video


def test_finance_pipeline_dry_run(tmp_path):
    topic = FinanceEduTopic(topic="60秒带你搞懂MACD")
    result_dir = asyncio.run(
        run_finance_edu_video(
            topic=topic,
            output_dir=tmp_path / "test-job",
            dry_run=True,
        )
    )
    assert (result_dir / "topic.json").exists()
    assert (result_dir / "script.json").exists()
    assert (result_dir / "storyboard.json").exists()
    assert (result_dir / "compliance_check.json").exists()


def test_finance_pipeline_dry_run_creates_valid_json(tmp_path):
    topic = FinanceEduTopic(topic="新手怎么看均线")
    result_dir = asyncio.run(
        run_finance_edu_video(
            topic=topic,
            output_dir=tmp_path / "test-ma",
            dry_run=True,
        )
    )
    with open(result_dir / "topic.json") as f:
        topic_data = json.load(f)
    assert topic_data["topic"] == "新手怎么看均线"

    with open(result_dir / "script.json") as f:
        script_data = json.load(f)
    assert "segments" in script_data
    assert len(script_data["segments"]) >= 5

    with open(result_dir / "compliance_check.json") as f:
        compliance_data = json.load(f)
    assert "passed" in compliance_data
    assert "max_risk_level" in compliance_data
