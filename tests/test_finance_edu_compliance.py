"""finance_edu 合规检查测试"""

from src.finance_edu.compliance import check_finance_compliance
from src.finance_edu.models import FinanceEduScript, FinanceEduScriptSegment


def _make_script(text: str) -> FinanceEduScript:
    return FinanceEduScript(
        title="测试",
        hook="钩子",
        narration=text,
        segments=[
            FinanceEduScriptSegment(
                scene_type="hook", start=0, duration=3,
                narration=text, screen_title="标题", screen_subtitle="副标题",
            )
        ],
        risk_disclaimer="风险提示",
    )


def test_compliance_passes_clean_script():
    script = _make_script("MACD是趋势观察工具，不能单独作为买卖依据。")
    report = check_finance_compliance(script)
    assert report.passed
    assert report.max_risk_level == "low"


def test_compliance_blocks_buy_advice():
    script = _make_script("这只股票现在可以买入，稳赚不赔。")
    report = check_finance_compliance(script)
    assert not report.passed
    assert report.max_risk_level == "high"
    categories = [i.category for i in report.issues]
    assert "buy_sell_advice" in categories


def test_compliance_blocks_prediction():
    script = _make_script("明天大涨，赶紧上车。")
    report = check_finance_compliance(script)
    assert not report.passed
    assert report.max_risk_level == "high"


def test_compliance_blocks_profit_promise():
    script = _make_script("这个方法稳赚，翻倍不是梦。")
    report = check_finance_compliance(script)
    assert not report.passed
    assert report.max_risk_level == "high"


def test_compliance_detects_missing_disclaimer():
    script = FinanceEduScript(
        title="测试",
        hook="钩子",
        narration="MACD是趋势观察工具",
        segments=[
            FinanceEduScriptSegment(
                scene_type="hook", start=0, duration=3,
                narration="MACD是趋势观察工具", screen_title="标题", screen_subtitle="",
            )
        ],
        risk_disclaimer="",
    )
    report = check_finance_compliance(script)
    categories = [i.category for i in report.issues]
    assert "missing_disclaimer" in categories


def test_compliance_warns_medium_risk():
    script = _make_script("加仓减仓要谨慎，涨停跌停都是常态。风险提示。")
    report = check_finance_compliance(script)
    assert report.passed
    assert report.max_risk_level == "medium"
    assert len(report.issues) > 0
