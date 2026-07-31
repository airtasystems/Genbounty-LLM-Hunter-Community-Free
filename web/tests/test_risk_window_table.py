"""Analysis window table + severity filter contracts."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RISK_JS = (_ROOT / "web/static/js/tabs/risk.js").read_text(encoding="utf-8")
_RISK_HTML = (_ROOT / "web/static/partials/tabs/risk.html").read_text(encoding="utf-8")
_STYLE = (_ROOT / "web/static/style.css").read_text(encoding="utf-8")

PAGE_SIZE = 50


def _filter_rows(rows: list[dict], selected: list[str]) -> list[dict]:
    """Mirror riskFilteredResults: empty selection = all levels."""
    if not selected:
        return list(rows)
    want = set(selected)
    return [r for r in rows if str(r.get("riskLevel") or "indeterminate") in want]


def _page_slice(rows: list[dict], page: int, page_size: int = PAGE_SIZE) -> list[dict]:
    page_count = max(1, (len(rows) + page_size - 1) // page_size) if rows else 1
    page = min(max(1, page), page_count)
    start = (page - 1) * page_size
    return rows[start : start + page_size]


def test_filter_empty_means_all_levels():
    rows = [
        {"riskLevel": "critical"},
        {"riskLevel": "high"},
        {"riskLevel": "low"},
    ]
    assert _filter_rows(rows, []) == rows
    assert len(_filter_rows(rows, ["high"])) == 1
    assert _filter_rows(rows, ["high"])[0]["riskLevel"] == "high"


def test_filter_multi_select_intersection():
    rows = [
        {"riskLevel": "critical"},
        {"riskLevel": "high"},
        {"riskLevel": "medium"},
        {"riskLevel": "low"},
        {"riskLevel": "indeterminate"},
    ]
    filtered = _filter_rows(rows, ["critical", "low"])
    assert [r["riskLevel"] for r in filtered] == ["critical", "low"]
    # Missing riskLevel treated as indeterminate
    rows2 = [{"riskLevel": ""}, {"riskLevel": "high"}]
    assert len(_filter_rows(rows2, ["indeterminate"])) == 1


def test_pagination_slice_math():
    rows = [{"i": i, "riskLevel": "high"} for i in range(120)]
    assert len(_page_slice(rows, 1)) == 50
    assert _page_slice(rows, 1)[0]["i"] == 0
    assert _page_slice(rows, 2)[0]["i"] == 50
    assert len(_page_slice(rows, 3)) == 20
    assert _page_slice(rows, 3)[0]["i"] == 100
    # Page clamp past end
    assert _page_slice(rows, 99)[0]["i"] == 100
    assert _page_slice([], 1) == []


def test_filter_then_paginate():
    rows = [{"riskLevel": "high" if i % 2 == 0 else "low", "i": i} for i in range(110)]
    filtered = _filter_rows(rows, ["high"])
    assert len(filtered) == 55
    page1 = _page_slice(filtered, 1)
    page2 = _page_slice(filtered, 2)
    assert len(page1) == 50
    assert len(page2) == 5
    assert all(r["riskLevel"] == "high" for r in page1 + page2)


def test_risk_js_window_branch_contracts():
    assert "const riskLevelFilter = ref([])" in _RISK_JS
    assert "RISK_TABLE_PAGE_SIZE = 50" in _RISK_JS
    assert "function toggleRiskLevelFilter" in _RISK_JS
    assert "const riskFilteredResults = computed" in _RISK_JS
    assert "const riskPagedResults = computed" in _RISK_JS
    assert "async function loadRiskResultsForMetricsWindow" in _RISK_JS
    assert "async function syncRiskTableToMetricsWindow" in _RISK_JS
    # last_run always pins to newest report; timed windows merge probe reports
    assert "if (windowId === 'last_run')" in _RISK_JS
    assert "await loadLatestRiskReport()" in _RISK_JS
    assert "loadRiskResultsForMetricsWindow(windowId)" in _RISK_JS
    # Live table append only in last_run; period windows still update severity tiles
    assert "_applyLiveRiskResultToPeriodMetrics" in _RISK_JS
    assert "function appendLiveRiskResult" in _RISK_JS
    assert "livePeriodMetricsCounts" in _RISK_JS
    # Report picker only reloads table when window is last_run
    assert "onSelectedRiskReportChange" in _RISK_JS
    assert "_metricsWindowId() !== 'last_run'" in _RISK_JS or (
        "windowId !== 'last_run'" in _RISK_JS
        and "onSelectedRiskReportChange" in _RISK_JS
    )
    # Row actions prefer row.reportPath
    assert "row?.reportPath || meta?.reportPath" in _RISK_JS
    assert "reportPath: String(reportPath || '').trim()" in _RISK_JS


def test_risk_html_and_css_contracts():
    assert "toggleRiskLevelFilter(l.id)" in _RISK_HTML
    assert "findings-metrics-chip--active" in _RISK_HTML
    assert "v-for=\"(r, i) in riskPagedResults\"" in _RISK_HTML
    assert "risk-table-pager" in _RISK_HTML
    assert "riskTableRangeLabel" in _RISK_HTML
    assert "RISK_TABLE_PAGE_SIZE" in _RISK_HTML
    assert "findings-metrics-chip--active" in _STYLE
    assert "cursor: pointer" in _STYLE
    assert ".risk-table-pager" in _STYLE
