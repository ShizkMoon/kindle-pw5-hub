from __future__ import annotations

from dataclasses import dataclass, field

from .inspect import EpubInspection
from .models import BookManifest, UpdateDecision


@dataclass
class UpdateDiff:
    decision: UpdateDecision
    reasons: list[str] = field(default_factory=list)
    matched_existing_chapters: int = 0
    old_chapter_count: int = 0
    new_chapter_count: int = 0


def compare_for_update(
    old_manifest: BookManifest,
    new_manifest: BookManifest,
    old_inspection: EpubInspection,
    new_inspection: EpubInspection,
    fingerprint_threshold: float = 0.98,
) -> UpdateDiff:
    old_count = len(old_inspection.chapters)
    new_count = len(new_inspection.chapters)

    if old_manifest.canonical_id != new_manifest.canonical_id:
        return UpdateDiff(
            UpdateDecision.BLOCKED_RISKY,
            ["canonical_id mismatch"],
            old_chapter_count=old_count,
            new_chapter_count=new_count,
        )

    if new_count < old_count:
        return UpdateDiff(
            UpdateDecision.BLOCKED_RISKY,
            ["chapter count decreased"],
            old_chapter_count=old_count,
            new_chapter_count=new_count,
        )

    if old_count == 0:
        return UpdateDiff(
            UpdateDecision.BLOCKED_RISKY,
            ["old EPUB has no comparable chapters"],
            old_chapter_count=old_count,
            new_chapter_count=new_count,
        )

    matched = 0
    changed: list[str] = []
    for idx, old_chapter in enumerate(old_inspection.chapters):
        new_chapter = new_inspection.chapters[idx]
        old_item_id = getattr(old_chapter, "item_id", "")
        new_item_id = getattr(new_chapter, "item_id", "")
        fingerprint_same = old_chapter.fingerprint == new_chapter.fingerprint
        href_same = old_chapter.href == new_chapter.href
        item_id_same = not (old_item_id or new_item_id) or old_item_id == new_item_id

        if fingerprint_same and href_same and item_id_same:
            matched += 1
        else:
            if not fingerprint_same:
                changed.append(f"chapter {idx + 1} fingerprint changed")
            if not href_same:
                changed.append(f"chapter {idx + 1} href changed")
            if not item_id_same:
                changed.append(f"chapter {idx + 1} item_id changed")

    ratio = matched / old_count
    if changed:
        return UpdateDiff(
            UpdateDecision.BLOCKED_RISKY,
            [
                "existing chapter prefix changed",
                f"existing chapter fingerprint ratio {ratio:.2f} below required 1.00",
                f"diagnostic threshold was {fingerprint_threshold:.2f}",
                *changed,
            ],
            matched_existing_chapters=matched,
            old_chapter_count=old_count,
            new_chapter_count=new_count,
        )

    if new_count == old_count:
        return UpdateDiff(
            UpdateDecision.SAFE_METADATA,
            ["existing chapter fingerprints unchanged"],
            matched_existing_chapters=matched,
            old_chapter_count=old_count,
            new_chapter_count=new_count,
        )

    return UpdateDiff(
        UpdateDecision.SAFE_APPEND,
        ["new chapters appended after stable prefix"],
        matched_existing_chapters=matched,
        old_chapter_count=old_count,
        new_chapter_count=new_count,
    )
