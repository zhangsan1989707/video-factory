"""炒股科普合规检查"""

from __future__ import annotations

import re

from src.finance_edu.constants import (
    BANNED_HIGH_RISK,
    BANNED_MEDIUM_RISK,
    DEFAULT_RISK_DISCLAIMER,
    DISCLAIMER_KEYWORDS,
)
from src.finance_edu.models import (
    FinanceComplianceIssue,
    FinanceComplianceReport,
    FinanceEduScript,
)


def check_finance_compliance(script: FinanceEduScript) -> FinanceComplianceReport:
    """检查脚本合规性"""
    text = script.collect_all_text()
    issues: list[FinanceComplianceIssue] = []

    for pattern in BANNED_HIGH_RISK:
        if pattern in text:
            issues.append(FinanceComplianceIssue(
                level="high",
                category=_categorize_banned(pattern),
                text=pattern,
                suggestion=f"请删除或改写包含「{pattern}」的内容",
            ))

    for pattern in BANNED_MEDIUM_RISK:
        count = text.count(pattern)
        if count > 0 and pattern not in [i.text for i in issues]:
            issues.append(FinanceComplianceIssue(
                level="medium",
                category="hype_marketing",
                text=f"{pattern}（出现 {count} 次）",
                suggestion=f"「{pattern}」在科普视频中使用需谨慎，建议改为更中性的表达",
            ))

    if not _has_disclaimer(text):
        issues.append(FinanceComplianceIssue(
            level="medium",
            category="missing_disclaimer",
            text="未找到风险提示",
            suggestion=f"建议在视频中添加风险提示：{DEFAULT_RISK_DISCLAIMER}",
        ))

    max_level = _resolve_max_level(issues)
    passed = max_level != "high"

    return FinanceComplianceReport(
        passed=passed,
        max_risk_level=max_level,
        issues=issues,
        rewritten_text=None,
    )


def _categorize_banned(pattern: str) -> str:
    """根据禁止词分类风险类别"""
    buy_sell = {"可以买", "可以买入", "建议买入", "建议卖出", "闭眼买", "无脑买入", "梭哈", "抄底", "逃顶", "赶紧上车"}
    prediction = {"明天上涨", "明天大涨"}
    profit = {"稳赚", "稳赚不赔", "翻倍", "必涨"}
    hype = {"牛股", "黑马股", "这只股票可以买", "明天大概率上涨", "现在就是买点", "主力要拉升"}

    if pattern in buy_sell:
        return "buy_sell_advice"
    if pattern in prediction:
        return "price_prediction"
    if pattern in profit:
        return "profit_promise"
    if pattern in hype:
        return "hype_marketing"
    return "other"


def _has_disclaimer(text: str) -> bool:
    """检查是否包含风险提示"""
    return any(keyword in text for keyword in DISCLAIMER_KEYWORDS)


def _resolve_max_level(issues: list[FinanceComplianceIssue]) -> str:
    """获取最高风险等级"""
    levels = [i.level for i in issues]
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "low"
