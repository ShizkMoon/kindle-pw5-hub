from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .config import TextCleaningConfig, TextCleaningMode


@dataclass(frozen=True)
class CleaningFinding:
    category: str
    severity: str
    location: str
    message: str
    confidence: float
    recommendation: str


@dataclass
class CleaningReport:
    mode: str
    status: str
    total_text_chars: int = 0
    sampled_text_chars: int = 0
    cost_plan: dict[str, Any] = field(default_factory=dict)
    findings: list[CleaningFinding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.to_json())


class CleaningAnalyzer(Protocol):
    def analyze(self, inspection: Any, budget: dict[str, Any]) -> list[CleaningFinding]:
        ...


class CleaningPlanner:
    def __init__(self, config: TextCleaningConfig) -> None:
        self.config = config

    def plan(self, inspection: Any, analyzer: CleaningAnalyzer | None = None) -> CleaningReport:
        total_chars = sum(int(getattr(chapter, "text_chars", 0)) for chapter in getattr(inspection, "chapters", []))
        sampled_chars = min(total_chars, self.config.max_input_chars)
        cost_plan = self._cost_plan(total_chars, sampled_chars)
        if self.config.mode == TextCleaningMode.OFF:
            return CleaningReport(
                mode=self.config.mode.value,
                status="skipped",
                total_text_chars=total_chars,
                sampled_text_chars=sampled_chars,
                cost_plan=cost_plan,
                errors=["text cleaning disabled"],
            )
        if analyzer is None:
            return CleaningReport(
                mode=self.config.mode.value,
                status="planned",
                total_text_chars=total_chars,
                sampled_text_chars=sampled_chars,
                cost_plan=cost_plan,
                errors=["cleaning analyzer not configured; no model calls were made"],
            )
        findings = analyzer.analyze(inspection, cost_plan)
        return CleaningReport(
            mode=self.config.mode.value,
            status="reported",
            total_text_chars=total_chars,
            sampled_text_chars=sampled_chars,
            cost_plan=cost_plan,
            findings=list(findings),
        )

    def skipped(self, reason: str) -> CleaningReport:
        return CleaningReport(
            mode=self.config.mode.value,
            status="skipped",
            cost_plan=self._cost_plan(0, 0),
            errors=[reason],
        )

    def _cost_plan(self, total_chars: int, sampled_chars: int) -> dict[str, Any]:
        if sampled_chars <= 0:
            estimated_tokens = 0
        else:
            estimated_tokens = max(1, math.ceil(sampled_chars / self.config.chars_per_token))
        estimated_cost = round(
            (estimated_tokens / 1000) * self.config.light_model_cny_per_1k_tokens,
            6,
        )
        return {
            "selected_route": self.config.selected_route,
            "escalation_route": self.config.escalation_route,
            "long_context_route": self.config.long_context_route,
            "enable_model_calls": self.config.enable_model_calls,
            "total_text_chars": total_chars,
            "sampled_text_chars": sampled_chars,
            "max_input_chars": self.config.max_input_chars,
            "estimated_input_tokens": estimated_tokens,
            "estimated_cost_cny": estimated_cost,
            "max_estimated_cost_cny": self.config.max_estimated_cost_cny,
            "within_budget": estimated_cost <= self.config.max_estimated_cost_cny,
        }


def write_cleaning_reports(report: CleaningReport, reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "cleaning-report.json").write_text(report.to_json(), encoding="utf-8")
    (reports_dir / "cleaning-report.md").write_text(_cleaning_report_markdown(report), encoding="utf-8")


def _cleaning_report_markdown(report: CleaningReport) -> str:
    lines = [
        "# Text cleaning report",
        "",
        f"Status: {report.status}",
        f"Mode: {report.mode}",
        f"Total text chars: {report.total_text_chars}",
        f"Sampled text chars: {report.sampled_text_chars}",
        "",
        "## Cost plan",
    ]
    for key, value in report.cost_plan.items():
        lines.append(f"- {key}: {value}")
    if report.findings:
        lines.extend(["", "## Findings"])
        for finding in report.findings:
            lines.append(
                f"- [{finding.severity}] {finding.category} {finding.location}: "
                f"{finding.message} ({finding.confidence:.2f}; {finding.recommendation})"
            )
    if report.errors:
        lines.extend(["", "## Errors"])
        for error in report.errors:
            lines.append(f"- {error}")
    return "\n".join(lines) + "\n"
