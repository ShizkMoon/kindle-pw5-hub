from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .config import MetadataEnrichmentConfig, MetadataEnrichmentMode


@dataclass(frozen=True)
class MetadataClues:
    title: str
    author: str
    opf_identifier: str = ""
    existing_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetadataEvidence:
    id: str
    source: str
    url: str
    facts: dict[str, Any]
    confidence: float = 1.0


@dataclass(frozen=True)
class MetadataDecision:
    field: str
    old_value: Any
    new_value: Any
    action: str
    confidence: float
    evidence_ids: list[str]
    reason: str


@dataclass(frozen=True)
class MetadataResolution:
    decisions: list[MetadataDecision] = field(default_factory=list)
    conflicts: list[MetadataDecision] = field(default_factory=list)
    model: str = "static"


@dataclass
class MetadataReport:
    mode: str
    status: str
    evidence: list[MetadataEvidence] = field(default_factory=list)
    applied_decisions: list[MetadataDecision] = field(default_factory=list)
    reported_decisions: list[MetadataDecision] = field(default_factory=list)
    conflicts: list[MetadataDecision] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    koreader_guard: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.to_json())


class MetadataProvider(Protocol):
    def search(self, clues: MetadataClues) -> list[MetadataEvidence]:
        ...


class MetadataReasoner(Protocol):
    def resolve(self, clues: MetadataClues, evidence: list[MetadataEvidence]) -> MetadataResolution:
        ...


class MetadataEnricher:
    def __init__(self, config: MetadataEnrichmentConfig) -> None:
        self.config = config

    def decide(
        self,
        evidence: list[MetadataEvidence],
        resolution: MetadataResolution,
        *,
        koreader_guard: dict[str, Any] | None = None,
        errors: list[str] | None = None,
    ) -> MetadataReport:
        evidence_by_id = {item.id: item for item in evidence}
        applied: list[MetadataDecision] = []
        reported: list[MetadataDecision] = []
        conflicts = list(resolution.conflicts)

        for decision in resolution.decisions:
            action = decision.action.lower()
            if action == "block":
                conflicts.append(decision)
                continue
            if not self._can_apply(decision, evidence_by_id):
                reported.append(decision)
                continue
            applied.append(decision)

        status = "skipped"
        if conflicts:
            status = "blocked"
        elif applied:
            status = "applied"
        elif reported:
            status = "reported"

        return MetadataReport(
            mode=self.config.mode.value,
            status=status,
            evidence=evidence,
            applied_decisions=applied,
            reported_decisions=reported,
            conflicts=conflicts,
            errors=errors or [],
            koreader_guard=koreader_guard or {},
        )

    def skipped(self, reason: str) -> MetadataReport:
        return MetadataReport(
            mode=self.config.mode.value,
            status="skipped",
            errors=[reason],
        )

    def _can_apply(self, decision: MetadataDecision, evidence_by_id: dict[str, MetadataEvidence]) -> bool:
        if self.config.mode != MetadataEnrichmentMode.AGGRESSIVE:
            return False
        if decision.action.lower() != "apply":
            return False
        if decision.field == "cover" and not self.config.write_cover:
            return False
        if decision.field == "description" and not self.config.write_description:
            return False
        if decision.field == "subjects" and not self.config.write_subjects:
            return False
        if decision.confidence < self.config.auto_apply_min_confidence:
            return False
        if self.config.require_evidence_url:
            if not decision.evidence_ids:
                return False
            for evidence_id in decision.evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None or not evidence.url:
                    return False
        return True


def write_metadata_reports(report: MetadataReport, reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "metadata-report.json").write_text(report.to_json(), encoding="utf-8")
    (reports_dir / "metadata-report.md").write_text(_metadata_report_markdown(report), encoding="utf-8")


def _metadata_report_markdown(report: MetadataReport) -> str:
    lines = ["# Metadata enrichment report", ""]
    if report.status == "applied":
        fields = "、".join(decision.field for decision in report.applied_decisions)
        lines.append(f"已自动补全 {fields}。")
    elif report.status == "blocked":
        lines.append("元数据增强已阻断自动发布。")
    elif report.status == "reported":
        lines.append("元数据增强只生成候选报告，未自动写入。")
    else:
        lines.append("元数据增强已跳过。")
    if report.koreader_guard:
        location = report.koreader_guard.get("metadata_location", "")
        allowed = report.koreader_guard.get("live_publish_allowed", False)
        lines.append(f"KOReader metadata 模式：{location}；live publish allowed: {allowed}。")
    if report.applied_decisions:
        lines.extend(["", "## Applied"])
        for decision in report.applied_decisions:
            lines.append(f"- {decision.field}: {decision.old_value} -> {decision.new_value} ({decision.confidence:.2f})")
    if report.reported_decisions:
        lines.extend(["", "## Reported"])
        for decision in report.reported_decisions:
            lines.append(f"- {decision.field}: {decision.new_value} ({decision.reason})")
    if report.conflicts:
        lines.extend(["", "## Conflicts"])
        for decision in report.conflicts:
            lines.append(f"- {decision.field}: {decision.reason}")
    if report.errors:
        lines.extend(["", "## Errors"])
        for error in report.errors:
            lines.append(f"- {error}")
    return "\n".join(lines) + "\n"
