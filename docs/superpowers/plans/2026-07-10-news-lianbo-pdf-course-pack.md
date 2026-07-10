# News Lianbo PDF Course Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily, additive morning/noon/evening News Lianbo course-pack pipeline that preserves every official program item, produces an illustrated Chinese PDF plus index and quality report, and sends only quality-approved files to Enterprise WeChat.

**Architecture:** The recurring Codex automation owns source research and additive manifest authoring; deterministic Python modules own schema validation, information coverage, teaching visuals, PDF rendering/inspection, version retention, indexing, and delivery. `course-manifest.json` is the only factual source for every derivative artifact, while the existing local notification service gains a narrowly scoped, path-safe Enterprise WeChat file endpoint.

**Tech Stack:** Python 3.11+, Pydantic 2, Pillow, ReportLab, pypdf, pdfplumber, Poppler, httpx, FastAPI, pytest, Docker Compose, Codex recurring automations.

---

**Approved Spec:** `docs/superpowers/specs/2026-07-10-news-lianbo-pdf-course-pack-design.md`

## File Map

Create these focused modules:

- `services/knowledge-engine/app/services/news_course/models.py`: canonical manifest, visual-review, build-report, delivery-report, and JSON I/O contracts.
- `services/knowledge-engine/app/services/news_course/quality.py`: deterministic pre-build and post-build hard gates, warnings, coverage calculation, and secret/unfinished-content scanning.
- `services/knowledge-engine/app/services/news_course/versioning.py`: morning-to-noon-to-evening transition rules and exact additive-content checks.
- `services/knowledge-engine/app/services/news_course/visuals.py`: deterministic teaching-diagram PNG rendering from verified manifest data.
- `services/knowledge-engine/app/services/news_course/markdown_export.py`: complete human-readable Markdown projection of the canonical manifest.
- `services/knowledge-engine/app/services/news_course/pdf_render.py`: A4 Flowables document construction, Chinese fonts, coverage page anchors, PDF naming, and page-size splitting.
- `services/knowledge-engine/app/services/news_course/pdf_inspection.py`: pypdf/pdfplumber checks, Poppler all-page rendering, blank-page checks, and contact-sheet construction.
- `services/knowledge-engine/app/services/news_course/builder.py`: preview/final two-pass build orchestration and visual-review hard gate.
- `services/knowledge-engine/app/services/news_course/course_index.py`: idempotent JSON/Markdown index updates and Sunday seven-day index PDF.
- `services/knowledge-engine/app/services/news_course/delivery.py`: local notify API calls, retry/fallback semantics, and all-parts delivery accounting.
- `services/knowledge-engine/app/services/wecom_webhook.py`: Webhook parsing, redaction, text sending, PDF upload, and file-message sending.
- `scripts/news_lianbo_course_pack.py`: thin `validate`, `build`, `deliver`, and `index` CLI.

Modify only these existing boundaries:

- `services/knowledge-engine/app/routers/notify.py`: delegate text delivery to the service and expose the restricted PDF endpoint.
- `services/knowledge-engine/tests/test_notify.py`: route contract and path-security tests.
- `docker-compose.yml`: mount `E:/agent/outputs/news-lianbo` read-only at `/app/data/news-lianbo`.
- Codex automation `automation-2`: preserve its three Beijing-time runs and replace its prompt with the approved structured workflow.

Create these tests and fixtures:

- `services/knowledge-engine/tests/news_course_fixtures.py`
- `services/knowledge-engine/tests/test_news_course_models.py`
- `services/knowledge-engine/tests/test_news_course_quality.py`
- `services/knowledge-engine/tests/test_news_course_versioning.py`
- `services/knowledge-engine/tests/test_news_course_visuals.py`
- `services/knowledge-engine/tests/test_news_course_pdf.py`
- `services/knowledge-engine/tests/test_news_course_builder.py`
- `services/knowledge-engine/tests/test_news_course_index.py`
- `services/knowledge-engine/tests/test_news_course_delivery.py`
- `services/knowledge-engine/tests/test_wecom_webhook.py`

## Execution Rules

- Start implementation in a dedicated worktree from commit `950725e`; use the `using-git-worktrees` skill before Task 1.
- The main checkout is intentionally dirty. Every commit below stages explicit paths only. Never run `git add -A`, `git add .`, `git reset --hard`, or `git checkout --`.
- Use the bundled runtime for course/PDF tests:

```powershell
$Python = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = 'E:\agent\omni\services\knowledge-engine'
$env:PATH = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin;' + $env:PATH
```

- The CLI must never read or print a Webhook. It talks only to `http://localhost:8002/api/v1/notify/*`.
- Use `18 * 1024 * 1024` bytes as the hard file-part ceiling.

### Task 1: Canonical Manifest Contract

**Files:**
- Create: `services/knowledge-engine/app/services/news_course/__init__.py`
- Create: `services/knowledge-engine/app/services/news_course/models.py`
- Create: `services/knowledge-engine/tests/news_course_fixtures.py`
- Create: `services/knowledge-engine/tests/test_news_course_models.py`

- [ ] **Step 1: Create the reusable manifest fixture factory**

Create `services/knowledge-engine/tests/news_course_fixtures.py` with this complete fixture:

```python
from __future__ import annotations

from datetime import date, datetime, timezone

from app.services.news_course.models import (
    CourseManifest,
    CourseSection,
    CoverageMapping,
    CoverageState,
    Lesson,
    NumericFact,
    ProgramItem,
    QualityState,
    ReviewBlock,
    SourceItem,
    VisualSpec,
    VisualItem,
)


def make_manifest(*, phase: str = "morning", version: str = "v1") -> CourseManifest:
    section_rows = [
        ("domestic", "国内政策主线", "P-D-001", "S-D-001"),
        ("international", "国际局势主线", "P-I-001", "S-I-001"),
        ("market_economy", "市场经济主线", "P-M-001", "S-M-001"),
    ]
    programs = [
        ProgramItem(
            item_id=program_id,
            title=headline,
            category=section,
            source_url=f"https://news.cctv.com/{program_id.lower()}.shtml",
            source_published_at=datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc),
            official=True,
        )
        for section, headline, program_id, _ in section_rows
    ]
    sources = []
    sections = []
    mappings = []
    for section, headline, program_id, source_id in section_rows:
        numeric = (
            [NumericFact(value=100, unit="点", period="2026-07-09 收盘", source_id=source_id)]
            if section == "market_economy"
            else []
        )
        sources.append(
            SourceItem(
                source_id=source_id,
                source_kind="program",
                section=section,
                publisher="央视网",
                title=headline,
                url=f"https://news.cctv.com/{source_id.lower()}.shtml",
                published_at=datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc),
                facts=[f"{headline}的已核验事实"],
                numeric_facts=numeric,
            )
        )
        lesson_id = f"L-{section.upper()}"
        sections.append(
            CourseSection(
                section=section,
                headline=headline,
                summary=f"{headline}摘要",
                lessons=[
                    Lesson(
                        lesson_id=lesson_id,
                        source_ids=[source_id],
                        fact_card=[f"{headline}的已核验事实"],
                        background=f"{headline}的背景说明",
                        why_it_matters=f"{headline}为何重要",
                        impact_chain=["事实发生", "政策或市场传导", "经营观察"],
                        interpretation=f"【解读】{headline}仍需结合后续官方数据观察。",
                        owner_view=f"【经营推演】关注其对食品、渠道与外贸的可能影响。",
                        visual_spec=VisualSpec(
                            visual_id=f"V-{section.upper()}",
                            kind="flow",
                            title=f"{headline}传导图",
                            caption="从事实到经营观察的教学图。",
                            source_ids=[source_id],
                            unit=None,
                            period="2026-07-09",
                            items=[
                                VisualItem(label="事实", detail="官方条目", source_id=source_id),
                                VisualItem(label="传导", detail="政策或市场路径", source_id=source_id),
                                VisualItem(label="观察", detail="后续验证点", source_id=source_id),
                            ],
                        ),
                    )
                ],
                appendix_item_ids=[],
            )
        )
        mappings.extend(
            [
                CoverageMapping(
                    entity_type="program_item",
                    entity_id=program_id,
                    destination="main",
                    section=section,
                    lesson_id=lesson_id,
                ),
                CoverageMapping(
                    entity_type="source_item",
                    entity_id=source_id,
                    destination="main",
                    section=section,
                    lesson_id=lesson_id,
                ),
            ]
        )
    return CourseManifest(
        schema_version="1.0",
        course_id="NL-20260709",
        news_date=date(2026, 7, 9),
        phase=phase,
        version=version,
        generated_at=datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
        main_thread="国内政策、国际局势与市场经济的共同影响",
        program_inventory=programs,
        source_items=sources,
        sections=sections,
        keywords=["政策", "国际", "市场"],
        owner_insights=["观察食品成本、渠道需求和外贸环境的后续变化。"],
        review=ReviewBlock(),
        coverage=CoverageState(mappings=mappings),
        quality=QualityState(),
    )
```

- [ ] **Step 2: Write schema tests that initially fail**

Create `services/knowledge-engine/tests/test_news_course_models.py`:

```python
from datetime import date

import pytest
from pydantic import ValidationError

from app.services.news_course.models import CourseManifest, read_manifest, write_manifest_atomic
from news_course_fixtures import make_manifest


def test_manifest_round_trip_preserves_contract(tmp_path):
    manifest = make_manifest()
    path = tmp_path / "course-manifest.json"

    write_manifest_atomic(path, manifest)
    loaded = read_manifest(path)

    assert loaded == manifest
    assert loaded.news_date == date(2026, 7, 9)
    assert [section.section for section in loaded.sections] == [
        "domestic",
        "international",
        "market_economy",
    ]


def test_phase_and_version_must_match():
    payload = make_manifest().model_dump(mode="json")
    payload["phase"] = "noon"
    payload["version"] = "final"

    with pytest.raises(ValidationError, match="phase/version mismatch"):
        CourseManifest.model_validate(payload)


def test_unknown_manifest_fields_are_rejected():
    payload = make_manifest().model_dump(mode="json")
    payload["unexpected"] = "not allowed"

    with pytest.raises(ValidationError):
        CourseManifest.model_validate(payload)
```

- [ ] **Step 3: Run the schema test and confirm the expected failure**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_models.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.services.news_course'`.

- [ ] **Step 4: Implement the canonical models and atomic JSON I/O**

Create `services/knowledge-engine/app/services/news_course/__init__.py`:

```python
"""Deterministic News Lianbo course-pack services."""
```

Create `services/knowledge-engine/app/services/news_course/models.py`:

```python
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SectionName = Literal["domestic", "international", "market_economy"]
PhaseName = Literal["morning", "noon", "evening"]
VersionName = Literal["v1", "v2", "final"]
VisualKind = Literal["flow", "timeline", "relationship", "bar", "comparison"]
PHASE_VERSION = {"morning": "v1", "noon": "v2", "evening": "final"}
SECTION_ORDER = ("domestic", "international", "market_economy")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NumericFact(StrictModel):
    value: str | int | float
    unit: Text
    period: Text
    source_id: Text


class ProgramItem(StrictModel):
    item_id: Text
    title: Text
    category: SectionName
    source_url: Text
    source_published_at: datetime
    official: bool


class SourceItem(StrictModel):
    source_id: Text
    source_kind: Literal["program", "official_supplement"]
    section: SectionName
    publisher: Text
    title: Text
    url: Text
    published_at: datetime
    facts: list[Text] = Field(min_length=1)
    numeric_facts: list[NumericFact] = Field(default_factory=list)


class VisualItem(StrictModel):
    label: Text
    detail: Text
    source_id: Text
    value: float | None = None


class VisualSpec(StrictModel):
    visual_id: Text
    kind: VisualKind
    title: Text
    caption: Text
    source_ids: list[Text] = Field(min_length=1)
    unit: str | None = None
    period: str | None = None
    items: list[VisualItem] = Field(min_length=2)


class Lesson(StrictModel):
    lesson_id: Text
    source_ids: list[Text] = Field(min_length=1)
    fact_card: list[Text] = Field(min_length=1)
    background: Text
    why_it_matters: Text
    impact_chain: list[Text] = Field(min_length=2)
    interpretation: Text
    owner_view: Text
    visual_spec: VisualSpec | None = None


class CourseSection(StrictModel):
    section: SectionName
    headline: Text
    summary: Text
    lessons: list[Lesson] = Field(min_length=1)
    appendix_item_ids: list[Text] = Field(default_factory=list)


class QuizItem(StrictModel):
    question: Text
    answer: Text
    criteria: Text


class ReviewBlock(StrictModel):
    memory_cards: list[Text] = Field(default_factory=list)
    quiz: list[QuizItem] = Field(default_factory=list)
    next_day_watch: list[Text] = Field(default_factory=list)


class CoverageMapping(StrictModel):
    entity_type: Literal["program_item", "source_item"]
    entity_id: Text
    destination: Literal["main", "appendix"]
    section: SectionName
    lesson_id: str | None = None
    pdf_page: int | None = Field(default=None, ge=1)


class CoverageState(StrictModel):
    mappings: list[CoverageMapping] = Field(default_factory=list)
    expected_count: int = Field(default=0, ge=0)
    covered_count: int = Field(default=0, ge=0)
    rate: float = Field(default=0.0, ge=0.0, le=1.0)
    unresolved_ids: list[str] = Field(default_factory=list)


class VisualReview(StrictModel):
    status: Literal["pending", "passed", "failed"] = "pending"
    inspected_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    reviewer: str | None = None
    reviewed_at: datetime | None = None


class QualityState(StrictModel):
    status: Literal["pending", "passed", "failed"] = "pending"
    hard_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    visual_review: VisualReview = Field(default_factory=VisualReview)


class CourseManifest(StrictModel):
    schema_version: Literal["1.0"]
    course_id: Text
    news_date: date
    phase: PhaseName
    version: VersionName
    generated_at: datetime
    main_thread: Text
    program_inventory: list[ProgramItem] = Field(min_length=1)
    source_items: list[SourceItem] = Field(min_length=1)
    sections: list[CourseSection] = Field(min_length=3)
    keywords: list[Text] = Field(default_factory=list)
    owner_insights: list[Text] = Field(default_factory=list)
    review: ReviewBlock = Field(default_factory=ReviewBlock)
    coverage: CoverageState = Field(default_factory=CoverageState)
    quality: QualityState = Field(default_factory=QualityState)

    @model_validator(mode="after")
    def validate_identity(self) -> "CourseManifest":
        if PHASE_VERSION[self.phase] != self.version:
            raise ValueError("phase/version mismatch")
        expected_course_id = f"NL-{self.news_date:%Y%m%d}"
        if self.course_id != expected_course_id:
            raise ValueError(f"course_id must be {expected_course_id}")
        section_names = [section.section for section in self.sections]
        if set(section_names) != set(SECTION_ORDER) or len(section_names) != len(SECTION_ORDER):
            raise ValueError("sections must contain domestic, international, market_economy exactly once")
        self.sections.sort(key=lambda item: SECTION_ORDER.index(item.section))
        return self


class PdfInspection(StrictModel):
    path: str
    page_count: int = Field(ge=1)
    extracted_headings: list[str]
    rendered_pages: list[str]
    contact_sheet: str
    blank_pages: list[int] = Field(default_factory=list)
    hard_failures: list[str] = Field(default_factory=list)


class BuildReport(StrictModel):
    manifest_path: str
    preview: bool
    pdf_paths: list[str]
    markdown_path: str | None = None
    visual_paths: list[str]
    inspections: list[PdfInspection]
    quality_path: str
    delivery_ready: bool
    hard_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DeliveryAttempt(StrictModel):
    kind: Literal["text", "file"]
    channel: str
    target: str
    ok: bool
    error_code: str | None = None


class DeliveryReport(StrictModel):
    text_sent: bool
    all_pdfs_sent: bool
    attempts: list[DeliveryAttempt]
    delivered_pdf_paths: list[str]


def read_manifest(path: str | Path) -> CourseManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return CourseManifest.model_validate(payload)


def write_json_atomic(path: str | Path, payload: dict) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def write_manifest_atomic(path: str | Path, manifest: CourseManifest) -> Path:
    return write_json_atomic(path, manifest.model_dump(mode="json"))
```

- [ ] **Step 5: Run the schema tests**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_models.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit the contract only**

```powershell
git add services/knowledge-engine/app/services/news_course/__init__.py services/knowledge-engine/app/services/news_course/models.py services/knowledge-engine/tests/news_course_fixtures.py services/knowledge-engine/tests/test_news_course_models.py
git commit -m "feat: add news course manifest contract"
```

### Task 2: Deterministic Manifest Quality Gate

**Files:**
- Create: `services/knowledge-engine/app/services/news_course/quality.py`
- Create: `services/knowledge-engine/tests/test_news_course_quality.py`

- [ ] **Step 1: Write the failing quality tests**

Create `services/knowledge-engine/tests/test_news_course_quality.py`:

```python
from datetime import date

from app.services.news_course.quality import apply_quality_report, check_manifest
from news_course_fixtures import make_manifest


def test_complete_manifest_passes_and_computes_full_coverage():
    manifest = make_manifest()

    report = check_manifest(manifest, expected_news_date=date(2026, 7, 9))

    assert report.status == "passed"
    assert report.coverage_rate == 1.0
    assert report.hard_failures == []


def test_unmapped_source_is_a_hard_failure():
    manifest = make_manifest()
    manifest.coverage.mappings = [
        mapping
        for mapping in manifest.coverage.mappings
        if not (mapping.entity_type == "source_item" and mapping.entity_id == "S-I-001")
    ]

    report = check_manifest(manifest, expected_news_date=date(2026, 7, 9))

    assert report.status == "failed"
    assert "unmapped:source_item:S-I-001" in report.hard_failures


def test_cross_source_numeric_fact_is_a_hard_failure():
    manifest = make_manifest()
    manifest.source_items[-1].numeric_facts[0].source_id = "S-NOT-FOUND"

    report = check_manifest(manifest, expected_news_date=date(2026, 7, 9))

    assert "numeric_fact_source_mismatch:S-M-001:S-NOT-FOUND" in report.hard_failures


def test_program_published_date_must_match_news_date_in_beijing():
    manifest = make_manifest()
    manifest.program_inventory[0].source_published_at = manifest.generated_at

    report = check_manifest(manifest, expected_news_date=date(2026, 7, 9))

    assert "program_date_mismatch:P-D-001" in report.hard_failures


def test_interpretation_cannot_introduce_an_unverified_number():
    manifest = make_manifest()
    manifest.sections[0].lessons[0].interpretation = "【解读】预计影响扩大 12%。"

    report = check_manifest(manifest, expected_news_date=date(2026, 7, 9))

    assert "unsourced_interpretation_number:L-DOMESTIC:12" in report.hard_failures


def test_unfinished_marker_and_webhook_shape_are_blocked():
    manifest = make_manifest()
    manifest.owner_insights = [
        "TO" + "DO",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?" + "key=" + "fake-test-key",
    ]

    report = check_manifest(manifest, expected_news_date=date(2026, 7, 9))

    assert "unfinished_or_secret_content" in report.hard_failures


def test_report_is_written_back_to_manifest():
    manifest = make_manifest()
    report = check_manifest(manifest, expected_news_date=date(2026, 7, 9))

    apply_quality_report(manifest, report)

    assert manifest.quality.status == "passed"
    assert manifest.coverage.expected_count == 6
    assert manifest.coverage.covered_count == 6
```

- [ ] **Step 2: Run the quality tests and confirm the expected failure**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_quality.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.services.news_course.quality'`.

- [ ] **Step 3: Implement all pre-build hard gates and soft warnings**

Create `services/knowledge-engine/app/services/news_course/quality.py`:

```python
from __future__ import annotations

import re
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from .models import CourseManifest, QualityState, StrictModel, VisualReview


FORBIDDEN_CONTENT = re.compile(
    r"(T[O]DO|T[B]D|F[I]XME|<[^>]*(?:占位|placeholder)[^>]*>|"
    r"qyapi\.weixin\.qq\.com/cgi-bin/webhook|(?:^|[?&])key=[A-Za-z0-9-]{8,})",
    re.IGNORECASE,
)
NUMBER_TOKEN = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")


class ManifestQualityReport(StrictModel):
    status: Literal["passed", "failed"]
    checks: dict[str, bool]
    hard_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    expected_count: int
    covered_count: int
    coverage_rate: float
    unresolved_ids: list[str] = Field(default_factory=list)


def _entity_key(entity_type: str, entity_id: str) -> str:
    return f"{entity_type}:{entity_id}"


def _numeric_aliases(value: str | int | float) -> set[str]:
    raw = str(value)
    aliases = {raw}
    try:
        parsed = float(raw)
    except ValueError:
        return aliases
    if parsed.is_integer():
        aliases.add(str(int(parsed)))
    return aliases


def check_manifest(
    manifest: CourseManifest,
    *,
    expected_news_date: date,
) -> ManifestQualityReport:
    failures: list[str] = []
    warnings = list(manifest.quality.warnings)
    checks: dict[str, bool] = {}

    checks["news_date"] = manifest.news_date == expected_news_date
    if not checks["news_date"]:
        failures.append(
            f"wrong_news_date:expected={expected_news_date.isoformat()}:actual={manifest.news_date.isoformat()}"
        )

    program_ids = [item.item_id for item in manifest.program_inventory]
    source_ids = [item.source_id for item in manifest.source_items]
    lesson_by_id = {
        lesson.lesson_id: (section.section, lesson)
        for section in manifest.sections
        for lesson in section.lessons
    }
    checks["unique_ids"] = (
        len(program_ids) == len(set(program_ids))
        and len(source_ids) == len(set(source_ids))
        and len(lesson_by_id)
        == sum(len(section.lessons) for section in manifest.sections)
    )
    if not checks["unique_ids"]:
        failures.append("duplicate_program_source_or_lesson_id")

    checks["official_program_inventory"] = bool(manifest.program_inventory) and all(
        item.official and item.source_url.startswith("https://")
        for item in manifest.program_inventory
    )
    if not checks["official_program_inventory"]:
        failures.append("program_inventory_not_official_or_empty")
    beijing = ZoneInfo("Asia/Shanghai")
    program_dates_valid = True
    for item in manifest.program_inventory:
        if item.source_published_at.astimezone(beijing).date() != manifest.news_date:
            program_dates_valid = False
            failures.append(f"program_date_mismatch:{item.item_id}")
    checks["program_dates"] = program_dates_valid
    checks["source_urls"] = all(
        item.url.startswith("https://") for item in manifest.source_items
    )
    if not checks["source_urls"]:
        failures.append("source_url_not_https")

    required_sections = {"domestic", "international", "market_economy"}
    present_sections = {section.section for section in manifest.sections if section.lessons}
    checks["three_sections"] = present_sections == required_sections
    if not checks["three_sections"]:
        failures.append("missing_required_course_section")

    source_id_set = set(source_ids)
    known_numeric_values = {
        alias
        for source in manifest.source_items
        for numeric in source.numeric_facts
        for alias in _numeric_aliases(numeric.value)
    }
    references_valid = True
    for source in manifest.source_items:
        for numeric_fact in source.numeric_facts:
            if numeric_fact.source_id != source.source_id:
                references_valid = False
                failures.append(
                    f"numeric_fact_source_mismatch:{source.source_id}:{numeric_fact.source_id}"
                )
    for section in manifest.sections:
        for lesson in section.lessons:
            for source_id in lesson.source_ids:
                if source_id not in source_id_set:
                    references_valid = False
                    failures.append(f"lesson_source_not_found:{lesson.lesson_id}:{source_id}")
            if not lesson.interpretation.startswith("【解读】"):
                references_valid = False
                failures.append(f"interpretation_not_labeled:{lesson.lesson_id}")
            if not lesson.owner_view.startswith("【经营推演】"):
                references_valid = False
                failures.append(f"owner_view_not_labeled:{lesson.lesson_id}")
            for text in (lesson.interpretation, lesson.owner_view):
                for numeric_token in NUMBER_TOKEN.findall(text):
                    if numeric_token not in known_numeric_values:
                        references_valid = False
                        failures.append(
                            f"unsourced_interpretation_number:"
                            f"{lesson.lesson_id}:{numeric_token}"
                        )
            if lesson.visual_spec:
                for source_id in lesson.visual_spec.source_ids:
                    if source_id not in source_id_set:
                        references_valid = False
                        failures.append(
                            f"visual_source_not_found:{lesson.visual_spec.visual_id}:{source_id}"
                        )
                if lesson.visual_spec.kind == "bar" and (
                    not lesson.visual_spec.unit or not lesson.visual_spec.period
                ):
                    references_valid = False
                    failures.append(
                        f"chart_unit_or_period_missing:{lesson.visual_spec.visual_id}"
                    )
    checks["fact_interpretation_source_separation"] = references_valid

    expected_keys = {
        *(_entity_key("program_item", item_id) for item_id in program_ids),
        *(_entity_key("source_item", source_id) for source_id in source_ids),
    }
    mapped_keys: set[str] = set()
    coverage_valid = True
    for mapping in manifest.coverage.mappings:
        key = _entity_key(mapping.entity_type, mapping.entity_id)
        if key in mapped_keys:
            coverage_valid = False
            failures.append(f"duplicate_mapping:{key}")
        mapped_keys.add(key)
        if mapping.destination == "main":
            section_and_lesson = lesson_by_id.get(mapping.lesson_id or "")
            if not section_and_lesson or section_and_lesson[0] != mapping.section:
                coverage_valid = False
                failures.append(f"invalid_main_destination:{key}")
    unresolved = sorted(expected_keys - mapped_keys)
    unexpected = sorted(mapped_keys - expected_keys)
    failures.extend(f"unmapped:{key}" for key in unresolved)
    failures.extend(f"mapping_target_not_found:{key}" for key in unexpected)
    covered_count = len(expected_keys & mapped_keys)
    expected_count = len(expected_keys)
    coverage_rate = covered_count / expected_count if expected_count else 0.0
    checks["coverage"] = (
        coverage_valid
        and not unresolved
        and not unexpected
        and coverage_rate == 1.0
    )

    serialized = manifest.model_dump_json()
    checks["no_unfinished_or_secret_content"] = FORBIDDEN_CONTENT.search(serialized) is None
    if not checks["no_unfinished_or_secret_content"]:
        failures.append("unfinished_or_secret_content")

    visual_count = sum(
        1
        for section in manifest.sections
        for lesson in section.lessons
        if lesson.visual_spec is not None
    )
    if visual_count < 4:
        warnings.append(f"visual_count_below_recommendation:{visual_count}")
    if not manifest.owner_insights:
        warnings.append("owner_relevance_not_found")

    failures = list(dict.fromkeys(failures))
    warnings = list(dict.fromkeys(warnings))
    return ManifestQualityReport(
        status="failed" if failures else "passed",
        checks=checks,
        hard_failures=failures,
        warnings=warnings,
        expected_count=expected_count,
        covered_count=covered_count,
        coverage_rate=coverage_rate,
        unresolved_ids=unresolved,
    )


def apply_quality_report(
    manifest: CourseManifest,
    report: ManifestQualityReport,
) -> None:
    visual_review = manifest.quality.visual_review
    manifest.quality = QualityState(
        status=report.status,
        hard_failures=report.hard_failures,
        warnings=report.warnings,
        visual_review=VisualReview.model_validate(visual_review.model_dump()),
    )
    manifest.coverage.expected_count = report.expected_count
    manifest.coverage.covered_count = report.covered_count
    manifest.coverage.rate = report.coverage_rate
    manifest.coverage.unresolved_ids = report.unresolved_ids
```

- [ ] **Step 4: Run the quality tests**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_quality.py -q
```

Expected: `7 passed`.

- [ ] **Step 5: Run contract and quality tests together**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_models.py services/knowledge-engine/tests/test_news_course_quality.py -q
```

Expected: `10 passed`.

- [ ] **Step 6: Commit the quality gate**

```powershell
git add services/knowledge-engine/app/services/news_course/quality.py services/knowledge-engine/tests/test_news_course_quality.py
git commit -m "feat: enforce news course quality gates"
```

### Task 3: Additive Morning/Noon/Evening Versioning

**Files:**
- Create: `services/knowledge-engine/app/services/news_course/versioning.py`
- Create: `services/knowledge-engine/tests/test_news_course_versioning.py`

- [ ] **Step 1: Write transition and information-retention tests**

Create `services/knowledge-engine/tests/test_news_course_versioning.py`:

```python
import pytest

from app.services.news_course.versioning import assert_additive_transition
from news_course_fixtures import make_manifest


def _noon_from_morning():
    morning = make_manifest()
    noon = make_manifest(phase="noon", version="v2")
    noon.keywords.append("午间深挖")
    noon.owner_insights.append("午间新增经营观察。")
    extra_lesson = noon.sections[0].lessons[0].model_copy(deep=True)
    extra_lesson.lesson_id = "L-DOMESTIC-DEEP"
    extra_lesson.background = "午间新增的深度背景，原有课程条目保持不变。"
    noon.sections[0].lessons.append(extra_lesson)
    return morning, noon


def test_noon_can_only_append_new_material():
    morning, noon = _noon_from_morning()

    assert_additive_transition(morning, noon)


def test_removing_a_program_item_is_rejected():
    morning, noon = _noon_from_morning()
    noon.program_inventory.pop()

    with pytest.raises(ValueError, match="removed_program_item:P-M-001"):
        assert_additive_transition(morning, noon)


def test_rewriting_an_existing_fact_is_rejected():
    morning, noon = _noon_from_morning()
    noon.source_items[0].facts[0] = "改写后的事实"

    with pytest.raises(ValueError, match="changed_source_item:S-D-001"):
        assert_additive_transition(morning, noon)


def test_invalid_phase_jump_is_rejected():
    morning = make_manifest()
    evening = make_manifest(phase="evening", version="final")

    with pytest.raises(ValueError, match="invalid_phase_transition:morning->evening"):
        assert_additive_transition(morning, evening)
```

- [ ] **Step 2: Run the versioning tests and confirm the expected failure**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_versioning.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.services.news_course.versioning'`.

- [ ] **Step 3: Implement strict additive transition checks**

Create `services/knowledge-engine/app/services/news_course/versioning.py`:

```python
from __future__ import annotations

from collections.abc import Iterable

from .models import CourseManifest


NEXT_PHASE = {"morning": "noon", "noon": "evening"}


def _dump(value) -> dict:
    return value.model_dump(mode="json")


def _indexed(items: Iterable, key: str) -> dict[str, object]:
    return {getattr(item, key): item for item in items}


def _contains_all(previous: list, current: list) -> bool:
    current_values = [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        for item in current
    ]
    return all(
        (item.model_dump(mode="json") if hasattr(item, "model_dump") else item)
        in current_values
        for item in previous
    )


def transition_errors(
    previous: CourseManifest,
    current: CourseManifest,
) -> list[str]:
    errors: list[str] = []
    expected_phase = NEXT_PHASE.get(previous.phase)
    if current.phase != expected_phase:
        errors.append(f"invalid_phase_transition:{previous.phase}->{current.phase}")
    if previous.course_id != current.course_id:
        errors.append("course_id_changed")
    if previous.news_date != current.news_date:
        errors.append("news_date_changed")

    for label, previous_items, current_items, key in [
        (
            "program_item",
            previous.program_inventory,
            current.program_inventory,
            "item_id",
        ),
        ("source_item", previous.source_items, current.source_items, "source_id"),
    ]:
        current_by_id = _indexed(current_items, key)
        for previous_item in previous_items:
            item_id = getattr(previous_item, key)
            current_item = current_by_id.get(item_id)
            if current_item is None:
                errors.append(f"removed_{label}:{item_id}")
            elif _dump(previous_item) != _dump(current_item):
                errors.append(f"changed_{label}:{item_id}")

    current_sections = _indexed(current.sections, "section")
    for previous_section in previous.sections:
        current_section = current_sections.get(previous_section.section)
        if current_section is None:
            errors.append(f"removed_section:{previous_section.section}")
            continue
        if previous_section.headline != current_section.headline:
            errors.append(f"changed_section_headline:{previous_section.section}")
        if previous_section.summary != current_section.summary:
            errors.append(f"changed_section_summary:{previous_section.section}")
        current_lessons = _indexed(current_section.lessons, "lesson_id")
        for previous_lesson in previous_section.lessons:
            current_lesson = current_lessons.get(previous_lesson.lesson_id)
            if current_lesson is None:
                errors.append(f"removed_lesson:{previous_lesson.lesson_id}")
            elif _dump(previous_lesson) != _dump(current_lesson):
                errors.append(f"changed_lesson:{previous_lesson.lesson_id}")
        if not set(previous_section.appendix_item_ids).issubset(
            current_section.appendix_item_ids
        ):
            errors.append(f"removed_appendix_item:{previous_section.section}")

    previous_mapping_by_key = {
        (item.entity_type, item.entity_id): item
        for item in previous.coverage.mappings
    }
    current_mapping_by_key = {
        (item.entity_type, item.entity_id): item
        for item in current.coverage.mappings
    }
    for key, previous_mapping in previous_mapping_by_key.items():
        current_mapping = current_mapping_by_key.get(key)
        if current_mapping is None:
            errors.append(f"removed_coverage_mapping:{key[0]}:{key[1]}")
            continue
        previous_value = previous_mapping.model_dump(mode="json", exclude={"pdf_page"})
        current_value = current_mapping.model_dump(mode="json", exclude={"pdf_page"})
        if previous_value != current_value:
            errors.append(f"changed_coverage_mapping:{key[0]}:{key[1]}")

    if not _contains_all(previous.keywords, current.keywords):
        errors.append("removed_keyword")
    if not _contains_all(previous.owner_insights, current.owner_insights):
        errors.append("removed_owner_insight")
    if not _contains_all(previous.review.memory_cards, current.review.memory_cards):
        errors.append("removed_memory_card")
    if not _contains_all(previous.review.quiz, current.review.quiz):
        errors.append("removed_quiz_item")
    if not _contains_all(previous.review.next_day_watch, current.review.next_day_watch):
        errors.append("removed_next_day_watch")
    return list(dict.fromkeys(errors))


def assert_additive_transition(
    previous: CourseManifest,
    current: CourseManifest,
) -> None:
    errors = transition_errors(previous, current)
    if errors:
        raise ValueError(";".join(errors))
```

- [ ] **Step 4: Run the versioning tests**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_versioning.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Add the evening-learning hard gate**

Append this test to `services/knowledge-engine/tests/test_news_course_quality.py`:

```python
def test_evening_final_requires_memory_quiz_answers_and_next_day_watch():
    manifest = make_manifest(phase="evening", version="final")

    report = check_manifest(manifest, expected_news_date=date(2026, 7, 9))

    assert "evening_review_incomplete" in report.hard_failures
```

Add this block in `check_manifest`, immediately before the unfinished-content scan:

```python
    if manifest.phase == "evening":
        evening_complete = bool(
            manifest.review.memory_cards
            and manifest.review.quiz
            and manifest.review.next_day_watch
        )
        checks["evening_review"] = evening_complete
        if not evening_complete:
            failures.append("evening_review_incomplete")
```

- [ ] **Step 6: Run versioning and quality tests together**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_versioning.py services/knowledge-engine/tests/test_news_course_quality.py -q
```

Expected: `12 passed`.

- [ ] **Step 7: Commit additive versioning**

```powershell
git add services/knowledge-engine/app/services/news_course/versioning.py services/knowledge-engine/app/services/news_course/quality.py services/knowledge-engine/tests/test_news_course_versioning.py services/knowledge-engine/tests/test_news_course_quality.py
git commit -m "feat: enforce additive news course versions"
```

### Task 4: Deterministic Teaching Visuals

**Files:**
- Create: `services/knowledge-engine/app/services/news_course/visuals.py`
- Create: `services/knowledge-engine/tests/test_news_course_visuals.py`

- [ ] **Step 1: Write visual rendering tests**

Create `services/knowledge-engine/tests/test_news_course_visuals.py`:

```python
from PIL import Image, ImageChops

from app.services.news_course.visuals import render_manifest_visuals
from news_course_fixtures import make_manifest


def test_manifest_visuals_are_nonblank_and_stable_size(tmp_path):
    manifest = make_manifest()

    paths = render_manifest_visuals(manifest, tmp_path)

    assert len(paths) == 3
    assert [path.name for path in paths] == [
        "V-DOMESTIC.png",
        "V-INTERNATIONAL.png",
        "V-MARKET_ECONOMY.png",
    ]
    for path in paths:
        with Image.open(path).convert("RGB") as image:
            assert image.size == (1600, 900)
            white = Image.new("RGB", image.size, "white")
            assert ImageChops.difference(image, white).getbbox() is not None


def test_numeric_chart_requires_values_but_uses_verified_source_ids(tmp_path):
    manifest = make_manifest()
    spec = manifest.sections[-1].lessons[0].visual_spec
    spec.kind = "bar"
    spec.unit = "点"
    spec.period = "2026-07-09 收盘"
    spec.items[0].value = 98.0
    spec.items[1].value = 100.0
    spec.items[2].value = 102.0

    paths = render_manifest_visuals(manifest, tmp_path)

    assert (tmp_path / "V-MARKET_ECONOMY.png") in paths
```

- [ ] **Step 2: Run the visual tests and confirm the expected failure**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_visuals.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.services.news_course.visuals'`.

- [ ] **Step 3: Implement font resolution and diagram rendering**

Create `services/knowledge-engine/app/services/news_course/visuals.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import CourseManifest, VisualSpec


WIDTH = 1600
HEIGHT = 900
INK = "#17202A"
BLUE = "#2563EB"
GREEN = "#138A72"
RED = "#C2413B"
GOLD = "#D49A18"
PALETTE = [BLUE, GREEN, RED, GOLD]


def resolve_font_path() -> Path:
    configured = os.environ.get("NEWS_COURSE_FONT", "").strip()
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = [
        Path(configured) if configured else None,
        windir / "Fonts" / "simhei.ttf",
        windir / "Fonts" / "msyh.ttc",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise RuntimeError("Chinese font not found; set NEWS_COURSE_FONT")


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(resolve_font_path()), size=size)


def _wrapped_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    *,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    line_gap: int = 8,
) -> int:
    x, y = xy
    for line in _wrapped_lines(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + line_gap
    return y


def _draw_header(draw: ImageDraw.ImageDraw, spec: VisualSpec) -> None:
    draw.rectangle((0, 0, WIDTH, 170), fill="#F4F7FB")
    draw.text((70, 38), spec.title, font=_font(52), fill=INK)
    metadata = (
        f"统计期：{spec.period or '见正文'}    "
        f"单位：{spec.unit or '不适用'}    "
        f"来源：{', '.join(spec.source_ids)}"
    )
    draw.text((72, 112), metadata, font=_font(24), fill="#4B5563")


def _draw_flow(draw: ImageDraw.ImageDraw, spec: VisualSpec) -> None:
    count = len(spec.items)
    gap = 42
    box_width = (WIDTH - 140 - gap * (count - 1)) // count
    top = 260
    for index, item in enumerate(spec.items):
        left = 70 + index * (box_width + gap)
        color = PALETTE[index % len(PALETTE)]
        draw.rounded_rectangle(
            (left, top, left + box_width, top + 350),
            radius=8,
            fill="#FFFFFF",
            outline=color,
            width=5,
        )
        draw.rectangle((left, top, left + box_width, top + 18), fill=color)
        draw.text((left + 28, top + 52), item.label, font=_font(34), fill=INK)
        _draw_text_block(
            draw,
            xy=(left + 28, top + 120),
            text=item.detail,
            font=_font(27),
            fill="#374151",
            max_width=box_width - 56,
        )
        draw.text(
            (left + 28, top + 292),
            f"[{item.source_id}]",
            font=_font(22),
            fill=color,
        )
        if index < count - 1:
            arrow_y = top + 175
            start_x = left + box_width + 8
            end_x = left + box_width + gap - 8
            draw.line((start_x, arrow_y, end_x, arrow_y), fill=INK, width=5)
            draw.polygon(
                [(end_x, arrow_y), (end_x - 18, arrow_y - 12), (end_x - 18, arrow_y + 12)],
                fill=INK,
            )


def _draw_bar(draw: ImageDraw.ImageDraw, spec: VisualSpec) -> None:
    values = [item.value for item in spec.items]
    if any(value is None for value in values):
        raise ValueError(f"bar visual requires values:{spec.visual_id}")
    numeric_values = [float(value) for value in values if value is not None]
    maximum = max(numeric_values) or 1.0
    left = 320
    top = 235
    row_height = 145
    max_bar_width = 1040
    for index, item in enumerate(spec.items):
        y = top + index * row_height
        draw.text((70, y + 20), item.label, font=_font(30), fill=INK)
        bar_width = int(max_bar_width * float(item.value or 0) / maximum)
        color = PALETTE[index % len(PALETTE)]
        draw.rectangle((left, y, left + bar_width, y + 72), fill=color)
        draw.text(
            (left + bar_width + 18, y + 15),
            f"{item.value:g} {spec.unit}",
            font=_font(28),
            fill=INK,
        )
        draw.text((left, y + 88), f"[{item.source_id}]", font=_font(20), fill="#6B7280")


def render_visual(spec: VisualSpec, output_path: str | Path) -> Path:
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    _draw_header(draw, spec)
    if spec.kind in {"bar", "comparison"} and any(
        item.value is not None for item in spec.items
    ):
        _draw_bar(draw, spec)
    else:
        _draw_flow(draw, spec)
    draw.rectangle((0, HEIGHT - 110, WIDTH, HEIGHT), fill="#F8FAFC")
    _draw_text_block(
        draw,
        xy=(70, HEIGHT - 84),
        text=f"图解：{spec.caption}",
        font=_font(25),
        fill="#374151",
        max_width=WIDTH - 140,
        line_gap=4,
    )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG", optimize=True)
    return target


def render_manifest_visuals(
    manifest: CourseManifest,
    output_dir: str | Path,
) -> list[Path]:
    directory = Path(output_dir)
    paths: list[Path] = []
    seen: set[str] = set()
    for section in manifest.sections:
        for lesson in section.lessons:
            spec = lesson.visual_spec
            if not spec or spec.visual_id in seen:
                continue
            seen.add(spec.visual_id)
            paths.append(render_visual(spec, directory / f"{spec.visual_id}.png"))
    return paths
```

- [ ] **Step 4: Run the visual tests**

Run:

```powershell
$env:NEWS_COURSE_FONT = 'C:\Windows\Fonts\simhei.ttf'
& $Python -m pytest services/knowledge-engine/tests/test_news_course_visuals.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Inspect one generated teaching visual**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_visuals.py::test_manifest_visuals_are_nonblank_and_stable_size -q --basetemp E:\agent\outputs\news-lianbo-test
```

Open the generated `V-DOMESTIC.png` with `view_image`. Verify: title, source ID, period, three readable blocks, no clipped text, and no decorative news photography.

- [ ] **Step 6: Commit teaching visuals**

```powershell
git add services/knowledge-engine/app/services/news_course/visuals.py services/knowledge-engine/tests/test_news_course_visuals.py
git commit -m "feat: render news course teaching visuals"
```

### Task 5: A4 Chinese PDF Renderer and Coverage Page Anchors

**Files:**
- Create: `services/knowledge-engine/app/services/news_course/pdf_render.py`
- Create: `services/knowledge-engine/tests/test_news_course_pdf.py`

- [ ] **Step 1: Write the renderer test**

Create `services/knowledge-engine/tests/test_news_course_pdf.py` with the first test:

```python
from pypdf import PdfReader

from app.services.news_course.pdf_render import phase_pdf_name, render_course_pdf
from app.services.news_course.visuals import render_manifest_visuals
from news_course_fixtures import make_manifest


def test_rendered_pdf_contains_all_sections_and_page_anchors(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_COURSE_FONT", r"C:\Windows\Fonts\simhei.ttf")
    manifest = make_manifest()
    visual_paths = render_manifest_visuals(manifest, tmp_path / "visuals")
    visuals = {path.stem: path for path in visual_paths}
    output = tmp_path / phase_pdf_name(manifest)

    page_map = render_course_pdf(manifest, visuals, output)

    assert output.is_file()
    assert len(PdfReader(str(output)).pages) >= 7
    assert set(page_map) == {
        "program_item:P-D-001",
        "program_item:P-I-001",
        "program_item:P-M-001",
        "source_item:S-D-001",
        "source_item:S-I-001",
        "source_item:S-M-001",
    }
    assert all(mapping.pdf_page for mapping in manifest.coverage.mappings)
```

- [ ] **Step 2: Run the renderer test and confirm the expected failure**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_pdf.py::test_rendered_pdf_contains_all_sections_and_page_anchors -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.services.news_course.pdf_render'`.

- [ ] **Step 3: Implement the Flowables renderer**

Create `services/knowledge-engine/app/services/news_course/pdf_render.py`:

```python
from __future__ import annotations

from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import CourseManifest
from .visuals import resolve_font_path


SECTION_TITLES = {
    "domestic": "第一部分 国内新闻",
    "international": "第二部分 国际新闻",
    "market_economy": "第三部分 股市与经济",
}
PHASE_LABELS = {
    "morning": "早间-v1",
    "noon": "午间-v2",
    "evening": "晚间-Final",
}


class CoverageAnchor(Flowable):
    def __init__(self, key: str, page_map: dict[str, int]) -> None:
        super().__init__()
        self.key = key
        self.page_map = page_map
        self.width = 0
        self.height = 0

    def draw(self) -> None:
        self.page_map[self.key] = self.canv.getPageNumber()


def phase_pdf_name(manifest: CourseManifest, *, preview: bool = False) -> str:
    phase_label = PHASE_LABELS[manifest.phase]
    suffix = "-预览" if preview else ""
    return f"{manifest.news_date.isoformat()}-新闻课程-{phase_label}{suffix}.pdf"


def _register_font() -> str:
    name = "NewsCourseCN"
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(resolve_font_path())))
    return name


def _styles(font_name: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "NewsBody",
        parent=base["BodyText"],
        fontName=font_name,
        fontSize=10.5,
        leading=17,
        textColor=colors.HexColor("#1F2937"),
        wordWrap="CJK",
        spaceAfter=6,
    )
    return {
        "cover": ParagraphStyle(
            "NewsCover",
            parent=body,
            fontSize=25,
            leading=34,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#17202A"),
            spaceAfter=16,
        ),
        "h1": ParagraphStyle(
            "NewsH1",
            parent=body,
            fontSize=18,
            leading=25,
            textColor=colors.HexColor("#174EA6"),
            spaceBefore=8,
            spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "NewsH2",
            parent=body,
            fontSize=14,
            leading=21,
            textColor=colors.HexColor("#136F63"),
            spaceBefore=7,
            spaceAfter=8,
        ),
        "label": ParagraphStyle(
            "NewsLabel",
            parent=body,
            fontSize=11,
            leading=17,
            textColor=colors.HexColor("#9A3412"),
            spaceBefore=5,
            spaceAfter=3,
        ),
        "body": body,
        "small": ParagraphStyle(
            "NewsSmall",
            parent=body,
            fontSize=8.5,
            leading=13,
            textColor=colors.HexColor("#4B5563"),
        ),
    }


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _page_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("NewsCourseCN", 8)
    canvas.setFillColor(colors.HexColor("#6B7280"))
    canvas.drawString(18 * mm, 11 * mm, "新闻联播每日精读课程")
    canvas.drawRightString(192 * mm, 11 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def _anchor_story(
    manifest: CourseManifest,
    page_map: dict[str, int],
    *,
    destination: str,
    lesson_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> list[Flowable]:
    anchors: list[Flowable] = []
    for mapping in manifest.coverage.mappings:
        if mapping.destination != destination:
            continue
        if lesson_id is not None and mapping.lesson_id == lesson_id:
            anchors.append(
                CoverageAnchor(
                    f"{mapping.entity_type}:{mapping.entity_id}",
                    page_map,
                )
            )
        elif (
            entity_type is not None
            and entity_id is not None
            and mapping.entity_type == entity_type
            and mapping.entity_id == entity_id
        ):
            anchors.append(
                CoverageAnchor(
                    f"{mapping.entity_type}:{mapping.entity_id}",
                    page_map,
                )
            )
    return anchors


def _lesson_story(manifest, lesson, styles, visuals, page_map):
    story: list[Flowable] = []
    story.extend(
        _anchor_story(
            manifest,
            page_map,
            destination="main",
            lesson_id=lesson.lesson_id,
        )
    )
    story.append(_paragraph(lesson.lesson_id, styles["small"]))
    story.append(_paragraph("事实卡", styles["label"]))
    for fact in lesson.fact_card:
        story.append(_paragraph(f"• {fact}", styles["body"]))
    story.append(_paragraph("背景说明", styles["label"]))
    story.append(_paragraph(lesson.background, styles["body"]))
    story.append(_paragraph("为什么重要", styles["label"]))
    story.append(_paragraph(lesson.why_it_matters, styles["body"]))
    story.append(_paragraph("影响链", styles["label"]))
    story.append(_paragraph(" → ".join(lesson.impact_chain), styles["body"]))
    if lesson.visual_spec and lesson.visual_spec.visual_id in visuals:
        image_path = visuals[lesson.visual_spec.visual_id]
        story.append(Spacer(1, 4 * mm))
        story.append(Image(str(image_path), width=174 * mm, height=97.875 * mm))
        story.append(_paragraph(lesson.visual_spec.caption, styles["small"]))
    story.append(_paragraph(lesson.interpretation, styles["body"]))
    story.append(_paragraph(lesson.owner_view, styles["body"]))
    story.append(Spacer(1, 6 * mm))
    return story


def render_course_pdf(
    manifest: CourseManifest,
    visuals: dict[str, Path],
    output_path: str | Path,
) -> dict[str, int]:
    font_name = _register_font()
    styles = _styles(font_name)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    page_map: dict[str, int] = {}
    story: list[Flowable] = [
        Spacer(1, 28 * mm),
        _paragraph("新闻联播每日精读课程", styles["cover"]),
        _paragraph(
            f"{manifest.news_date.isoformat()} · {PHASE_LABELS[manifest.phase]}",
            styles["cover"],
        ),
        Spacer(1, 10 * mm),
        _paragraph(f"今日主线：{manifest.main_thread}", styles["h1"]),
    ]
    navigation = [
        ["国内新闻", manifest.sections[0].summary],
        ["国际新闻", manifest.sections[1].summary],
        ["股市与经济", manifest.sections[2].summary],
    ]
    table = Table(
        [
            [_paragraph(left, styles["h2"]), _paragraph(right, styles["body"])]
            for left, right in navigation
        ],
        colWidths=[42 * mm, 130 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F5F9")),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([table, PageBreak()])

    for section in manifest.sections:
        story.append(_paragraph(SECTION_TITLES[section.section], styles["h1"]))
        story.append(_paragraph(section.headline, styles["h2"]))
        story.append(_paragraph(section.summary, styles["body"]))
        for lesson in section.lessons:
            story.extend(_lesson_story(manifest, lesson, styles, visuals, page_map))
        story.append(PageBreak())

    story.append(_paragraph("老板视角与经营映射", styles["h1"]))
    if manifest.owner_insights:
        for insight in manifest.owner_insights:
            story.append(_paragraph(f"• {insight}", styles["body"]))
    else:
        story.append(_paragraph("本期暂无强相关经营映射。", styles["body"]))
    story.append(_paragraph("复盘与答案", styles["h1"]))
    for card in manifest.review.memory_cards:
        story.append(_paragraph(f"记忆卡：{card}", styles["body"]))
    for index, quiz in enumerate(manifest.review.quiz, 1):
        story.append(_paragraph(f"{index}. {quiz.question}", styles["h2"]))
        story.append(_paragraph(f"参考答案：{quiz.answer}", styles["body"]))
        story.append(_paragraph(f"判断标准：{quiz.criteria}", styles["small"]))
    for watch in manifest.review.next_day_watch:
        story.append(_paragraph(f"下一日观察：{watch}", styles["body"]))
    if not (
        manifest.review.memory_cards
        or manifest.review.quiz
        or manifest.review.next_day_watch
    ):
        story.append(_paragraph("完整复盘与答案将在晚间 Final 追加。", styles["body"]))
    story.append(PageBreak())

    story.append(_paragraph("完整新闻条目附录", styles["h1"]))
    for item in manifest.program_inventory:
        story.extend(
            _anchor_story(
                manifest,
                page_map,
                destination="appendix",
                entity_type="program_item",
                entity_id=item.item_id,
            )
        )
        story.append(_paragraph(f"{item.item_id} · {item.title}", styles["h2"]))
        story.append(
            _paragraph(
                f"分类：{item.category}；官方：{'是' if item.official else '否'}；"
                f"来源：{item.source_url}",
                styles["small"],
            )
        )
    story.append(PageBreak())

    story.append(_paragraph("来源与质量检查", styles["h1"]))
    for source in manifest.source_items:
        story.extend(
            _anchor_story(
                manifest,
                page_map,
                destination="appendix",
                entity_type="source_item",
                entity_id=source.source_id,
            )
        )
        story.append(
            _paragraph(
                f"{source.source_id} · {source.publisher} · {source.title}",
                styles["h2"],
            )
        )
        story.append(_paragraph(source.url, styles["small"]))
        for fact in source.facts:
            story.append(_paragraph(f"• {fact}", styles["body"]))
        for numeric in source.numeric_facts:
            story.append(
                _paragraph(
                    f"数字：{numeric.value} {numeric.unit}；统计期：{numeric.period}；"
                    f"来源：{numeric.source_id}",
                    styles["body"],
                )
            )
    story.append(_paragraph(f"质量状态：{manifest.quality.status}", styles["h2"]))
    for failure in manifest.quality.hard_failures:
        story.append(_paragraph(f"硬失败：{failure}", styles["body"]))
    for warning in manifest.quality.warnings:
        story.append(_paragraph(f"警告：{warning}", styles["body"]))
    story.append(
        _paragraph(
            f"覆盖率：{manifest.coverage.covered_count}/"
            f"{manifest.coverage.expected_count} = {manifest.coverage.rate:.0%}",
            styles["body"],
        )
    )
    story.append(
        _paragraph(
            f"视觉检查：{manifest.quality.visual_review.status}",
            styles["body"],
        )
    )
    story.append(
        _paragraph(
            "企业微信送达：构建时待发送；最终结果见 delivery JSON 与课程索引。",
            styles["body"],
        )
    )

    document = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"{manifest.news_date.isoformat()} 新闻联播每日精读课程",
        author="omni",
    )
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    for mapping in manifest.coverage.mappings:
        mapping.pdf_page = page_map.get(f"{mapping.entity_type}:{mapping.entity_id}")
    return page_map
```

- [ ] **Step 4: Run the renderer test**

Run:

```powershell
$env:NEWS_COURSE_FONT = 'C:\Windows\Fonts\simhei.ttf'
& $Python -m pytest services/knowledge-engine/tests/test_news_course_pdf.py::test_rendered_pdf_contains_all_sections_and_page_anchors -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit the PDF renderer**

```powershell
git add services/knowledge-engine/app/services/news_course/pdf_render.py services/knowledge-engine/tests/test_news_course_pdf.py
git commit -m "feat: render news course PDF"
```

### Task 6: PDF Text, Pixel, Contact-Sheet, and Size Inspection

**Files:**
- Create: `services/knowledge-engine/app/services/news_course/pdf_inspection.py`
- Modify: `services/knowledge-engine/tests/test_news_course_pdf.py`

- [ ] **Step 1: Add failing inspection and splitting tests**

Append to `services/knowledge-engine/tests/test_news_course_pdf.py`:

```python
from reportlab.pdfgen import canvas

from app.services.news_course.pdf_inspection import (
    REQUIRED_HEADINGS,
    inspect_pdf,
    split_pdf_by_size,
)


def test_pdf_text_and_every_rendered_page_pass_inspection(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_COURSE_FONT", r"C:\Windows\Fonts\simhei.ttf")
    monkeypatch.setenv(
        "NEWS_COURSE_PDFTOPPM",
        (
            r"C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime"
            r"\dependencies\native\poppler\Library\bin\pdftoppm.exe"
        ),
    )
    manifest = make_manifest()
    visual_paths = render_manifest_visuals(manifest, tmp_path / "visuals")
    output = tmp_path / phase_pdf_name(manifest)
    render_course_pdf(
        manifest,
        {path.stem: path for path in visual_paths},
        output,
    )

    inspection = inspect_pdf(output, tmp_path / "rendered")

    assert inspection.hard_failures == []
    assert inspection.page_count == len(inspection.rendered_pages)
    assert set(REQUIRED_HEADINGS).issubset(inspection.extracted_headings)
    assert (tmp_path / "rendered" / "contact-sheet.png").is_file()


def test_oversized_pdf_is_split_without_losing_pages(tmp_path):
    source = tmp_path / "oversized.pdf"
    pdf = canvas.Canvas(str(source))
    for page_number in range(1, 9):
        pdf.drawString(72, 720, f"page {page_number}")
        pdf.showPage()
    pdf.save()

    parts = split_pdf_by_size(
        source,
        max_bytes=max(source.stat().st_size * 3 // 4, 1024),
    )

    assert len(parts) >= 2
    assert sum(len(PdfReader(str(part)).pages) for part in parts) == 8
    assert all(part.stat().st_size <= max(source.stat().st_size * 3 // 4, 1024) for part in parts)


def test_long_links_and_large_appendix_render_without_blank_pages(tmp_path, monkeypatch):
    from app.services.news_course.models import CoverageMapping

    monkeypatch.setenv("NEWS_COURSE_FONT", r"C:\Windows\Fonts\simhei.ttf")
    monkeypatch.setenv(
        "NEWS_COURSE_PDFTOPPM",
        (
            r"C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime"
            r"\dependencies\native\poppler\Library\bin\pdftoppm.exe"
        ),
    )
    manifest = make_manifest()
    for index in range(40):
        program = manifest.program_inventory[0].model_copy(deep=True)
        program.item_id = f"P-APP-{index:03d}"
        program.title = f"附录压力条目 {index} " + ("长标题" * 20)
        program.source_url = (
            "https://news.cctv.com/verified/"
            + ("long-path-" * 12)
            + f"{index}.shtml"
        )
        source = manifest.source_items[0].model_copy(deep=True)
        source.source_id = f"S-APP-{index:03d}"
        source.source_kind = "official_supplement"
        source.title = program.title
        source.url = program.source_url
        source.facts = ["已核验附录事实。" * 30]
        source.numeric_facts = []
        manifest.program_inventory.append(program)
        manifest.source_items.append(source)
        manifest.coverage.mappings.extend(
            [
                CoverageMapping(
                    entity_type="program_item",
                    entity_id=program.item_id,
                    destination="appendix",
                    section="domestic",
                ),
                CoverageMapping(
                    entity_type="source_item",
                    entity_id=source.source_id,
                    destination="appendix",
                    section="domestic",
                ),
            ]
        )
    visuals = {
        path.stem: path
        for path in render_manifest_visuals(manifest, tmp_path / "visuals")
    }
    output = tmp_path / "stress.pdf"
    render_course_pdf(manifest, visuals, output)

    inspection = inspect_pdf(output, tmp_path / "stress-render")

    assert inspection.page_count >= 12
    assert inspection.blank_pages == []
    assert inspection.hard_failures == []
```

- [ ] **Step 2: Run the new tests and confirm the expected failure**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_pdf.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.services.news_course.pdf_inspection'`.

- [ ] **Step 3: Implement PDF inspection and byte-safe splitting**

Create `services/knowledge-engine/app/services/news_course/pdf_inspection.py`:

```python
from __future__ import annotations

import io
import os
import shutil
import subprocess
from pathlib import Path

import pdfplumber
from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter

from .models import PdfInspection


REQUIRED_HEADINGS = [
    "第一部分 国内新闻",
    "第二部分 国际新闻",
    "第三部分 股市与经济",
    "老板视角与经营映射",
    "复盘与答案",
    "完整新闻条目附录",
    "来源与质量检查",
]


def resolve_pdftoppm() -> str:
    configured = os.environ.get("NEWS_COURSE_PDFTOPPM", "").strip()
    executable = configured or shutil.which("pdftoppm")
    if not executable or not Path(executable).is_file():
        raise RuntimeError("Poppler pdftoppm not found; set NEWS_COURSE_PDFTOPPM")
    return executable


def _nonwhite_ratio(path: Path) -> float:
    with Image.open(path).convert("L") as image:
        white = Image.new("L", image.size, 255)
        difference = ImageChops.difference(image, white)
        histogram = difference.histogram()
        changed = sum(histogram[1:])
        return changed / (image.width * image.height)


def _contact_sheet(page_paths: list[Path], output_path: Path) -> Path:
    if not page_paths:
        Image.new("RGB", (960, 240), "white").save(output_path, format="PNG")
        return output_path
    columns = 3
    thumb_width = 300
    gap = 18
    thumbs: list[Image.Image] = []
    for path in page_paths:
        with Image.open(path).convert("RGB") as image:
            thumb = image.copy()
            thumb.thumbnail((thumb_width, 430))
            thumbs.append(thumb)
    rows = (len(thumbs) + columns - 1) // columns
    row_height = max(image.height for image in thumbs) + gap
    sheet = Image.new(
        "RGB",
        (columns * (thumb_width + gap) + gap, rows * row_height + gap),
        "white",
    )
    for index, thumb in enumerate(thumbs):
        x = gap + (index % columns) * (thumb_width + gap)
        y = gap + (index // columns) * row_height
        sheet.paste(thumb, (x, y))
    sheet.save(output_path, format="PNG", optimize=True)
    return output_path


def inspect_pdf(
    pdf_path: str | Path,
    render_dir: str | Path,
) -> PdfInspection:
    source = Path(pdf_path)
    output_dir = Path(render_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_page in output_dir.glob("page-*.png"):
        stale_page.unlink()
    stale_contact_sheet = output_dir / "contact-sheet.png"
    if stale_contact_sheet.exists():
        stale_contact_sheet.unlink()
    failures: list[str] = []
    try:
        reader = PdfReader(str(source))
        page_count = len(reader.pages)
    except Exception as exc:
        raise ValueError(f"pdf_open_failed:{exc.__class__.__name__}") from exc
    if page_count == 0:
        raise ValueError("pdf_has_zero_pages")

    with pdfplumber.open(str(source)) as pdf:
        extracted_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    extracted_headings = [heading for heading in REQUIRED_HEADINGS if heading in extracted_text]
    missing_headings = sorted(set(REQUIRED_HEADINGS) - set(extracted_headings))
    failures.extend(f"missing_pdf_heading:{heading}" for heading in missing_headings)

    prefix = output_dir / "page"
    completed = subprocess.run(
        [
            resolve_pdftoppm(),
            "-png",
            "-r",
            "144",
            str(source),
            str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        failures.append(f"poppler_render_failed:{completed.returncode}")
    page_paths = sorted(
        output_dir.glob("page-*.png"),
        key=lambda path: int(path.stem.rsplit("-", 1)[1]),
    )
    if len(page_paths) != page_count:
        failures.append(f"rendered_page_count_mismatch:{len(page_paths)}:{page_count}")
    blank_pages = [
        index
        for index, path in enumerate(page_paths, 1)
        if _nonwhite_ratio(path) < 0.001
    ]
    failures.extend(f"blank_pdf_page:{page}" for page in blank_pages)
    contact_sheet = _contact_sheet(page_paths, output_dir / "contact-sheet.png")
    return PdfInspection(
        path=str(source.resolve()),
        page_count=page_count,
        extracted_headings=extracted_headings,
        rendered_pages=[str(path.resolve()) for path in page_paths],
        contact_sheet=str(contact_sheet.resolve()),
        blank_pages=blank_pages,
        hard_failures=list(dict.fromkeys(failures)),
    )


def _writer_bytes(reader: PdfReader, start: int, end: int) -> bytes:
    writer = PdfWriter()
    for page_index in range(start, end):
        writer.add_page(reader.pages[page_index])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def split_pdf_by_size(
    pdf_path: str | Path,
    *,
    max_bytes: int,
) -> list[Path]:
    source = Path(pdf_path)
    if source.stat().st_size <= max_bytes:
        return [source]
    reader = PdfReader(str(source))
    parts: list[Path] = []
    start = 0
    part_number = 1
    while start < len(reader.pages):
        best_end: int | None = None
        best_bytes: bytes | None = None
        for end in range(start + 1, len(reader.pages) + 1):
            candidate = _writer_bytes(reader, start, end)
            if len(candidate) > max_bytes:
                break
            best_end = end
            best_bytes = candidate
        if best_end is None or best_bytes is None:
            raise ValueError(f"single_pdf_page_exceeds_limit:{start + 1}")
        target = source.with_name(f"{source.stem}-part-{part_number}.pdf")
        target.write_bytes(best_bytes)
        parts.append(target)
        start = best_end
        part_number += 1
    if sum(len(PdfReader(str(part)).pages) for part in parts) != len(reader.pages):
        raise ValueError("pdf_split_page_conservation_failed")
    return parts
```

- [ ] **Step 4: Run all PDF tests**

Run:

```powershell
$env:NEWS_COURSE_FONT = 'C:\Windows\Fonts\simhei.ttf'
$env:NEWS_COURSE_PDFTOPPM = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe'
& $Python -m pytest services/knowledge-engine/tests/test_news_course_pdf.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Render and visually inspect all fixture pages**

Use `view_image` on the generated `contact-sheet.png`, then open the cover, all three section-open pages, appendix page, and quality page. Verify no clipping, overlap, black boxes, missing Chinese glyphs, or unreadably small labels.

- [ ] **Step 6: Commit PDF inspection**

```powershell
git add services/knowledge-engine/app/services/news_course/pdf_inspection.py services/knowledge-engine/tests/test_news_course_pdf.py
git commit -m "feat: inspect and split news course PDFs"
```

### Task 7: Two-Pass Package Builder and Visual-Review Hard Gate

**Files:**
- Create: `services/knowledge-engine/app/services/news_course/markdown_export.py`
- Create: `services/knowledge-engine/app/services/news_course/builder.py`
- Create: `services/knowledge-engine/tests/test_news_course_builder.py`
- Modify: `services/knowledge-engine/app/services/news_course/pdf_inspection.py`

- [ ] **Step 1: Allow split-part inspection to defer heading completeness to the aggregate**

Change the `inspect_pdf` signature in `pdf_inspection.py` to:

```python
def inspect_pdf(
    pdf_path: str | Path,
    render_dir: str | Path,
    *,
    required_headings: list[str] | None = None,
) -> PdfInspection:
```

Replace the heading calculation with:

```python
    headings_to_check = REQUIRED_HEADINGS if required_headings is None else required_headings
    extracted_headings = [
        heading for heading in headings_to_check if heading in extracted_text
    ]
    missing_headings = sorted(set(headings_to_check) - set(extracted_headings))
```

- [ ] **Step 2: Implement the complete Markdown projection**

Create `services/knowledge-engine/app/services/news_course/markdown_export.py`:

```python
from __future__ import annotations

from pathlib import Path

from .models import CourseManifest


SECTION_TITLES = {
    "domestic": "第一部分 国内新闻",
    "international": "第二部分 国际新闻",
    "market_economy": "第三部分 股市与经济",
}


def render_course_markdown(
    manifest: CourseManifest,
    output_path: str | Path,
) -> Path:
    lines = [
        f"# {manifest.news_date.isoformat()} 新闻联播每日精读课程",
        "",
        f"- 阶段：{manifest.phase} / {manifest.version}",
        f"- 今日主线：{manifest.main_thread}",
        f"- 节目条目：{len(manifest.program_inventory)}",
        f"- 来源条目：{len(manifest.source_items)}",
        "",
    ]
    for section in manifest.sections:
        lines.extend(
            [
                f"## {SECTION_TITLES[section.section]}",
                "",
                f"**本部分主线：** {section.headline}",
                "",
                section.summary,
                "",
            ]
        )
        for lesson in section.lessons:
            lines.extend(
                [
                    f"### {lesson.lesson_id}",
                    "",
                    "#### 事实卡",
                    *[f"- {fact}" for fact in lesson.fact_card],
                    "",
                    "#### 背景说明",
                    lesson.background,
                    "",
                    "#### 为什么重要",
                    lesson.why_it_matters,
                    "",
                    "#### 影响链",
                    " → ".join(lesson.impact_chain),
                    "",
                ]
            )
            if lesson.visual_spec:
                lines.extend(
                    [
                        f"#### 教学图：{lesson.visual_spec.title}",
                        f"![{lesson.visual_spec.title}](visuals/{lesson.visual_spec.visual_id}.png)",
                        "",
                        (
                            f"图解：{lesson.visual_spec.caption}；"
                            f"统计期：{lesson.visual_spec.period or '不适用'}；"
                            f"来源：{', '.join(lesson.visual_spec.source_ids)}"
                        ),
                        "",
                    ]
                )
            lines.extend([lesson.interpretation, "", lesson.owner_view, ""])
    lines.extend(["## 老板视角与经营映射", ""])
    lines.extend(f"- {item}" for item in manifest.owner_insights)
    if not manifest.owner_insights:
        lines.append("- 本期暂无强相关经营映射。")
    lines.extend(["", "## 复盘与答案", ""])
    lines.extend(f"- 记忆卡：{item}" for item in manifest.review.memory_cards)
    for index, quiz in enumerate(manifest.review.quiz, 1):
        lines.extend(
            [
                f"### {index}. {quiz.question}",
                f"- 参考答案：{quiz.answer}",
                f"- 判断标准：{quiz.criteria}",
                "",
            ]
        )
    lines.extend(f"- 下一日观察：{item}" for item in manifest.review.next_day_watch)
    lines.extend(["", "## 完整新闻条目附录", ""])
    for item in manifest.program_inventory:
        lines.extend(
            [
                f"### {item.item_id} · {item.title}",
                (
                    f"- 分类：{item.category}；官方：{'是' if item.official else '否'}；"
                    f"发布时间：{item.source_published_at.isoformat()}"
                ),
                f"- 来源：{item.source_url}",
                "",
            ]
        )
    lines.extend(["## 来源与质量检查", ""])
    for source in manifest.source_items:
        lines.extend(
            [
                f"### {source.source_id} · {source.publisher} · {source.title}",
                f"- 类型：{source.source_kind}",
                f"- 来源：{source.url}",
                *[f"- 事实：{fact}" for fact in source.facts],
            ]
        )
        lines.extend(
            (
                f"- 数字：{numeric.value} {numeric.unit}；统计期：{numeric.period}；"
                f"来源：{numeric.source_id}"
            )
            for numeric in source.numeric_facts
        )
        lines.append("")
    lines.extend(
        [
            f"- 质量状态：{manifest.quality.status}",
            (
                f"- 覆盖率：{manifest.coverage.covered_count}/"
                f"{manifest.coverage.expected_count} = {manifest.coverage.rate:.0%}"
            ),
            f"- 视觉检查：{manifest.quality.visual_review.status}",
            "- 企业微信送达：构建时待发送；最终结果见 delivery JSON 与课程索引。",
        ]
    )
    lines.extend(f"- 硬失败：{item}" for item in manifest.quality.hard_failures)
    lines.extend(f"- 警告：{item}" for item in manifest.quality.warnings)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target
```

- [ ] **Step 3: Write preview/final builder tests**

Create `services/knowledge-engine/tests/test_news_course_builder.py`:

```python
from datetime import datetime, timezone

import pytest

from app.services.news_course.builder import build_course_package
from app.services.news_course.models import (
    VisualReview,
    write_json_atomic,
    write_manifest_atomic,
)
from news_course_fixtures import make_manifest


def _configure_runtime(monkeypatch):
    monkeypatch.setenv("NEWS_COURSE_FONT", r"C:\Windows\Fonts\simhei.ttf")
    monkeypatch.setenv(
        "NEWS_COURSE_PDFTOPPM",
        (
            r"C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime"
            r"\dependencies\native\poppler\Library\bin\pdftoppm.exe"
        ),
    )


def test_preview_build_creates_contact_sheet_but_is_not_deliverable(tmp_path, monkeypatch):
    _configure_runtime(monkeypatch)
    manifest_path = tmp_path / "course-manifest.json"
    write_manifest_atomic(manifest_path, make_manifest())

    report = build_course_package(manifest_path, tmp_path, preview=True)

    assert report.preview is True
    assert report.delivery_ready is False
    assert report.hard_failures == []
    assert report.markdown_path is not None
    markdown = (tmp_path / "course-morning.md").read_text(encoding="utf-8")
    assert "第一部分 国内新闻" in markdown
    assert "完整新闻条目附录" in markdown
    assert all(inspection.contact_sheet for inspection in report.inspections)


def test_final_build_refuses_missing_visual_review(tmp_path, monkeypatch):
    _configure_runtime(monkeypatch)
    manifest_path = tmp_path / "course-manifest.json"
    write_manifest_atomic(manifest_path, make_manifest())

    with pytest.raises(ValueError, match="visual_review_not_passed"):
        build_course_package(manifest_path, tmp_path, preview=False)


def test_final_build_is_deliverable_after_passed_visual_review(tmp_path, monkeypatch):
    _configure_runtime(monkeypatch)
    manifest_path = tmp_path / "course-manifest.json"
    review_path = tmp_path / "visual-review.json"
    write_manifest_atomic(manifest_path, make_manifest())
    review = VisualReview(
        status="passed",
        inspected_files=["contact-sheet.png", "page-1.png", "page-3.png"],
        notes=["无裁切、重叠、黑框或乱码。"],
        reviewer="codex_multimodal",
        reviewed_at=datetime.now(timezone.utc),
    )
    write_json_atomic(review_path, review.model_dump(mode="json"))

    report = build_course_package(
        manifest_path,
        tmp_path,
        preview=False,
        visual_review_path=review_path,
    )

    assert report.delivery_ready is True
    assert report.hard_failures == []
    assert all(path.endswith(".pdf") for path in report.pdf_paths)
```

- [ ] **Step 4: Run builder tests and confirm the expected failure**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_builder.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.services.news_course.builder'`.

- [ ] **Step 5: Implement preview/final orchestration**

Create `services/knowledge-engine/app/services/news_course/builder.py`:

```python
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from PIL import Image

from .markdown_export import render_course_markdown
from .models import (
    BuildReport,
    VisualReview,
    read_manifest,
    write_json_atomic,
    write_manifest_atomic,
)
from .pdf_inspection import REQUIRED_HEADINGS, inspect_pdf, split_pdf_by_size
from .pdf_render import phase_pdf_name, render_course_pdf
from .quality import apply_quality_report, check_manifest
from .versioning import assert_additive_transition
from .visuals import render_manifest_visuals


MAX_PDF_BYTES = 18 * 1024 * 1024


def _load_visual_review(path: str | Path | None) -> VisualReview:
    if path is None:
        return VisualReview()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return VisualReview.model_validate(payload)


def _optimize_visuals(
    visual_paths: list[Path],
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    optimized: dict[str, Path] = {}
    for source in visual_paths:
        target = output_dir / f"{source.stem}.jpg"
        with Image.open(source).convert("RGB") as image:
            image.save(target, format="JPEG", quality=82, optimize=True)
        optimized[source.stem] = target
    return optimized


def build_course_package(
    manifest_path: str | Path,
    output_dir: str | Path,
    *,
    preview: bool,
    visual_review_path: str | Path | None = None,
    previous_manifest_path: str | Path | None = None,
    expected_news_date: date | None = None,
) -> BuildReport:
    manifest_path = Path(manifest_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(manifest_path)
    expected = expected_news_date or manifest.news_date
    if previous_manifest_path:
        assert_additive_transition(read_manifest(previous_manifest_path), manifest)

    prebuild = check_manifest(manifest, expected_news_date=expected)
    if prebuild.hard_failures:
        apply_quality_report(manifest, prebuild)
        write_manifest_atomic(manifest_path, manifest)
        raise ValueError(";".join(prebuild.hard_failures))

    visual_review = _load_visual_review(visual_review_path)
    if not preview and visual_review.status != "passed":
        raise ValueError("visual_review_not_passed")
    manifest.quality.visual_review = visual_review
    apply_quality_report(manifest, prebuild)
    manifest.quality.visual_review = visual_review

    visual_paths = render_manifest_visuals(manifest, output_dir / "visuals")
    markdown_path = render_course_markdown(
        manifest,
        output_dir / f"course-{manifest.phase}.md",
    )
    visual_map = {path.stem: path for path in visual_paths}
    pdf_path = output_dir / phase_pdf_name(manifest, preview=preview)
    for stale_part in output_dir.glob(f"{pdf_path.stem}-part-*.pdf"):
        stale_part.unlink()
    if pdf_path.exists():
        pdf_path.unlink()
    render_course_pdf(manifest, visual_map, pdf_path)

    if pdf_path.stat().st_size > MAX_PDF_BYTES:
        optimized_map = _optimize_visuals(visual_paths, output_dir / "visuals-optimized")
        pdf_path.unlink()
        render_course_pdf(manifest, optimized_map, pdf_path)

    pdf_paths = split_pdf_by_size(pdf_path, max_bytes=MAX_PDF_BYTES)
    if pdf_paths != [pdf_path] and pdf_path.exists():
        pdf_path.unlink()

    inspections = []
    for index, part_path in enumerate(pdf_paths, 1):
        inspection = inspect_pdf(
            part_path,
            output_dir / "render-pages" / f"part-{index}",
            required_headings=[] if len(pdf_paths) > 1 else None,
        )
        inspections.append(inspection)

    failures = [
        failure
        for inspection in inspections
        for failure in inspection.hard_failures
    ]
    if len(pdf_paths) > 1:
        all_text = ""
        for part_path in pdf_paths:
            import pdfplumber

            with pdfplumber.open(str(part_path)) as pdf:
                all_text += "\n".join(page.extract_text() or "" for page in pdf.pages)
        failures.extend(
            f"missing_pdf_heading:{heading}"
            for heading in REQUIRED_HEADINGS
            if heading not in all_text
        )
    failures.extend(
        f"pdf_part_invalid:{path.name}"
        for path in pdf_paths
        if not path.is_file()
        or path.stat().st_size == 0
        or path.stat().st_size > MAX_PDF_BYTES
    )
    if not preview and visual_review.status != "passed":
        failures.append("visual_review_not_passed")
    failures = list(dict.fromkeys(failures))
    manifest.quality.hard_failures = failures
    manifest.quality.status = "failed" if failures else "passed"
    write_manifest_atomic(manifest_path, manifest)

    quality_path = output_dir / f"quality-{manifest.phase}.json"
    report = BuildReport(
        manifest_path=str(manifest_path.resolve()),
        preview=preview,
        pdf_paths=[str(path.resolve()) for path in pdf_paths],
        markdown_path=str(markdown_path.resolve()),
        visual_paths=[str(path.resolve()) for path in visual_paths],
        inspections=inspections,
        quality_path=str(quality_path.resolve()),
        delivery_ready=(not preview and not failures and visual_review.status == "passed"),
        hard_failures=failures,
        warnings=manifest.quality.warnings,
    )
    write_json_atomic(
        quality_path,
        {
            "manifest_quality": manifest.quality.model_dump(mode="json"),
            "coverage": manifest.coverage.model_dump(mode="json"),
            "build_report": report.model_dump(mode="json"),
        },
    )
    return report
```

- [ ] **Step 6: Run builder tests**

Run:

```powershell
$env:NEWS_COURSE_FONT = 'C:\Windows\Fonts\simhei.ttf'
$env:NEWS_COURSE_PDFTOPPM = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe'
& $Python -m pytest services/knowledge-engine/tests/test_news_course_builder.py -q
```

Expected: `3 passed`.

- [ ] **Step 7: Run all course tests built so far**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_models.py services/knowledge-engine/tests/test_news_course_quality.py services/knowledge-engine/tests/test_news_course_versioning.py services/knowledge-engine/tests/test_news_course_visuals.py services/knowledge-engine/tests/test_news_course_pdf.py services/knowledge-engine/tests/test_news_course_builder.py -q
```

Expected: `24 passed`.

- [ ] **Step 8: Commit the two-pass builder**

```powershell
git add services/knowledge-engine/app/services/news_course/markdown_export.py services/knowledge-engine/app/services/news_course/builder.py services/knowledge-engine/app/services/news_course/pdf_inspection.py services/knowledge-engine/tests/test_news_course_builder.py
git commit -m "feat: gate news course PDF delivery"
```

### Task 8: Idempotent Course Index and Sunday Seven-Day PDF

**Files:**
- Create: `services/knowledge-engine/app/services/news_course/course_index.py`
- Create: `services/knowledge-engine/tests/test_news_course_index.py`

- [ ] **Step 1: Write index upsert and weekly PDF tests**

Create `services/knowledge-engine/tests/test_news_course_index.py`:

```python
import json
from datetime import date, timedelta

from app.services.news_course.course_index import (
    CourseIndexEntry,
    render_weekly_index_pdf,
    upsert_course_index,
)
from app.services.news_course.models import BuildReport, DeliveryReport, PdfInspection
from news_course_fixtures import make_manifest


def _build_report(tmp_path, filename):
    pdf_path = tmp_path / filename
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return BuildReport(
        manifest_path=str(tmp_path / "course-manifest.json"),
        preview=False,
        pdf_paths=[str(pdf_path)],
        visual_paths=["visual-1.png", "visual-2.png", "visual-3.png"],
        inspections=[
            PdfInspection(
                path=str(pdf_path),
                page_count=12,
                extracted_headings=["第一部分 国内新闻"],
                rendered_pages=["page-1.png"],
                contact_sheet="contact-sheet.png",
            )
        ],
        quality_path=str(tmp_path / "quality.json"),
        delivery_ready=True,
    )


def _delivery_report(pdf_path):
    return DeliveryReport(
        text_sent=True,
        all_pdfs_sent=True,
        attempts=[],
        delivered_pdf_paths=[str(pdf_path)],
    )


def test_upsert_is_idempotent_and_preserves_phase_pdf_arrays(tmp_path):
    index_path = tmp_path / "course-index.json"
    markdown_path = tmp_path / "课程索引.md"
    morning = make_manifest()
    morning_build = _build_report(tmp_path, "morning.pdf")

    upsert_course_index(
        index_path,
        markdown_path,
        morning,
        morning_build,
        _delivery_report(morning_build.pdf_paths[0]),
    )
    upsert_course_index(
        index_path,
        markdown_path,
        morning,
        morning_build,
        _delivery_report(morning_build.pdf_paths[0]),
    )

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(payload["courses"]) == 1
    assert payload["courses"][0]["morning_pdfs"] == [str(tmp_path / "morning.pdf")]

    noon = make_manifest(phase="noon", version="v2")
    noon_build = _build_report(tmp_path, "noon.pdf")
    upsert_course_index(
        index_path,
        markdown_path,
        noon,
        noon_build,
        _delivery_report(noon_build.pdf_paths[0]),
    )
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["courses"][0]["morning_pdfs"]
    assert payload["courses"][0]["noon_pdfs"]


def test_weekly_index_pdf_renders_seven_final_courses(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_COURSE_FONT", r"C:\Windows\Fonts\simhei.ttf")
    entries = []
    start = date(2026, 7, 3)
    for offset in range(7):
        day = start + timedelta(days=offset)
        entries.append(
            CourseIndexEntry(
                course_id=f"NL-{day:%Y%m%d}",
                news_date=day,
                main_thread=f"{day.isoformat()} 主线",
                domestic_topics=["国内"],
                international_topics=["国际"],
                market_economy_topics=["经济"],
                keywords=["政策", "市场"],
                final_pdfs=[f"{day.isoformat()}-Final.pdf"],
                source_count=12,
                program_item_count=10,
                coverage_rate=1.0,
                page_count=18,
                visual_count=5,
                quality_status="passed",
                wecom_text_sent=True,
                wecom_pdf_sent=True,
            )
        )

    output = render_weekly_index_pdf(entries, tmp_path / "weekly.pdf")

    assert output.is_file()
    assert output.stat().st_size > 0
```

- [ ] **Step 2: Run index tests and confirm the expected failure**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_index.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.services.news_course.course_index'`.

- [ ] **Step 3: Implement the canonical index, Markdown view, and weekly PDF**

Create `services/knowledge-engine/app/services/news_course/course_index.py`:

```python
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import (
    BuildReport,
    CourseManifest,
    DeliveryReport,
    StrictModel,
    write_json_atomic,
)
from .visuals import resolve_font_path


class CourseIndexEntry(StrictModel):
    course_id: str
    news_date: date
    main_thread: str
    domestic_topics: list[str] = Field(default_factory=list)
    international_topics: list[str] = Field(default_factory=list)
    market_economy_topics: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    morning_pdfs: list[str] = Field(default_factory=list)
    noon_pdfs: list[str] = Field(default_factory=list)
    final_pdfs: list[str] = Field(default_factory=list)
    source_count: int
    program_item_count: int
    coverage_rate: float
    page_count: int
    visual_count: int
    quality_status: str
    warnings: list[str] = Field(default_factory=list)
    wecom_text_sent: bool
    wecom_pdf_sent: bool


def _load_entries(path: Path) -> list[CourseIndexEntry]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [CourseIndexEntry.model_validate(item) for item in payload.get("courses", [])]


def _topics(manifest: CourseManifest, section_name: str) -> list[str]:
    section = next(item for item in manifest.sections if item.section == section_name)
    return [section.headline, *(lesson.why_it_matters for lesson in section.lessons)]


def _markdown(entries: list[CourseIndexEntry]) -> str:
    lines = [
        "# 新闻联播课程索引",
        "",
        "| 日期 | 今日主线 | 国内 | 国际 | 股市与经济 | 质量 | Final |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in sorted(entries, key=lambda item: item.news_date, reverse=True):
        lines.append(
            "| "
            + " | ".join(
                [
                    entry.news_date.isoformat(),
                    entry.main_thread.replace("|", "｜"),
                    "；".join(entry.domestic_topics[:2]).replace("|", "｜"),
                    "；".join(entry.international_topics[:2]).replace("|", "｜"),
                    "；".join(entry.market_economy_topics[:2]).replace("|", "｜"),
                    entry.quality_status,
                    "<br>".join(entry.final_pdfs) if entry.final_pdfs else "待晚间",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def upsert_course_index(
    index_path: str | Path,
    markdown_path: str | Path,
    manifest: CourseManifest,
    build: BuildReport,
    delivery: DeliveryReport,
) -> CourseIndexEntry:
    index_path = Path(index_path)
    entries = _load_entries(index_path)
    existing = next(
        (entry for entry in entries if entry.course_id == manifest.course_id),
        None,
    )
    phase_field = {
        "morning": "morning_pdfs",
        "noon": "noon_pdfs",
        "evening": "final_pdfs",
    }[manifest.phase]
    phase_paths = [str(Path(path)) for path in build.pdf_paths]
    page_count = sum(item.page_count for item in build.inspections)
    values = {
        "course_id": manifest.course_id,
        "news_date": manifest.news_date,
        "main_thread": manifest.main_thread,
        "domestic_topics": _topics(manifest, "domestic"),
        "international_topics": _topics(manifest, "international"),
        "market_economy_topics": _topics(manifest, "market_economy"),
        "keywords": manifest.keywords,
        "morning_pdfs": existing.morning_pdfs if existing else [],
        "noon_pdfs": existing.noon_pdfs if existing else [],
        "final_pdfs": existing.final_pdfs if existing else [],
        "source_count": len(manifest.source_items),
        "program_item_count": len(manifest.program_inventory),
        "coverage_rate": manifest.coverage.rate,
        "page_count": page_count,
        "visual_count": len(build.visual_paths),
        "quality_status": manifest.quality.status,
        "warnings": manifest.quality.warnings,
        "wecom_text_sent": delivery.text_sent,
        "wecom_pdf_sent": delivery.all_pdfs_sent,
    }
    values[phase_field] = phase_paths
    entry = CourseIndexEntry.model_validate(values)
    entries = [item for item in entries if item.course_id != entry.course_id]
    entries.append(entry)
    entries.sort(key=lambda item: item.news_date)
    write_json_atomic(
        index_path,
        {
            "schema_version": "1.0",
            "courses": [item.model_dump(mode="json") for item in entries],
        },
    )
    markdown_target = Path(markdown_path)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    temporary = markdown_target.with_suffix(markdown_target.suffix + ".tmp")
    temporary.write_text(_markdown(entries), encoding="utf-8")
    temporary.replace(markdown_target)
    return entry


def render_weekly_index_pdf(
    entries: list[CourseIndexEntry],
    output_path: str | Path,
) -> Path:
    if len(entries) != 7 or any(not entry.final_pdfs for entry in entries):
        raise ValueError("weekly_index_requires_seven_final_courses")
    font_name = "NewsCourseIndexCN"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, str(resolve_font_path())))
    body = ParagraphStyle(
        "IndexBody",
        fontName=font_name,
        fontSize=8.5,
        leading=13,
        wordWrap="CJK",
    )
    heading = ParagraphStyle(
        "IndexHeading",
        parent=body,
        fontSize=20,
        leading=28,
        textColor=colors.HexColor("#174EA6"),
        spaceAfter=12,
    )
    story = [
        Paragraph("最近七天新闻联播课程索引", heading),
        Paragraph(
            f"{entries[0].news_date.isoformat()} 至 {entries[-1].news_date.isoformat()}",
            body,
        ),
        Spacer(1, 6 * mm),
    ]
    rows = [["日期", "主线", "国内/国际/经济", "质量", "Final"]]
    for entry in entries:
        topics = " / ".join(
            [
                entry.domestic_topics[0],
                entry.international_topics[0],
                entry.market_economy_topics[0],
            ]
        )
        rows.append(
            [
                entry.news_date.isoformat(),
                Paragraph(entry.main_thread, body),
                Paragraph(topics, body),
                entry.quality_status,
                Paragraph("<br/>".join(entry.final_pdfs), body),
            ]
        )
    table = Table(rows, colWidths=[22 * mm, 38 * mm, 64 * mm, 17 * mm, 44 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF8")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C2D1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([table, PageBreak(), Paragraph("连续观察线索", heading)])
    for entry in entries:
        story.append(
            Paragraph(
                f"{entry.news_date.isoformat()}：{'、'.join(entry.keywords)}；"
                f"来源 {entry.source_count}；节目条目 {entry.program_item_count}；"
                f"覆盖率 {entry.coverage_rate:.0%}",
                body,
            )
        )
        story.append(Spacer(1, 3 * mm))
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(target),
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    ).build(story)
    return target
```

- [ ] **Step 4: Run index tests**

Run:

```powershell
$env:NEWS_COURSE_FONT = 'C:\Windows\Fonts\simhei.ttf'
& $Python -m pytest services/knowledge-engine/tests/test_news_course_index.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit course indexing**

```powershell
git add services/knowledge-engine/app/services/news_course/course_index.py services/knowledge-engine/tests/test_news_course_index.py
git commit -m "feat: index news course PDFs"
```

### Task 9: Secure Enterprise WeChat PDF Upload and File Message

**Files:**
- Create: `services/knowledge-engine/app/services/wecom_webhook.py`
- Create: `services/knowledge-engine/tests/test_wecom_webhook.py`
- Modify: `services/knowledge-engine/app/routers/notify.py`
- Modify: `services/knowledge-engine/tests/test_notify.py`
- Modify: `docker-compose.yml:236-278`

- [ ] **Step 1: Write Webhook protocol and secret-redaction tests**

Create `services/knowledge-engine/tests/test_wecom_webhook.py`:

```python
import json

import httpx
import pytest

from app.services.wecom_webhook import (
    MAX_FILE_BYTES,
    FileValidationError,
    build_upload_url,
    resolve_news_pdf,
    send_file,
)


TEST_WEBHOOK = (
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?"
    + "key="
    + "fake-test-key-12345678"
)


def test_build_upload_url_uses_same_key_without_exposing_it_elsewhere():
    upload_url = build_upload_url(TEST_WEBHOOK)

    assert upload_url.startswith(
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?"
    )
    assert "type=file" in upload_url
    assert "fake-test-key-12345678" in upload_url


@pytest.mark.asyncio
async def test_send_file_uploads_then_sends_file_message(tmp_path, monkeypatch):
    pdf_path = tmp_path / "course.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    monkeypatch.setenv("WECOM_WEBHOOKS", f"daily={TEST_WEBHOOK}")
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/upload_media"):
            assert request.url.params["type"] == "file"
            assert request.headers["content-type"].startswith("multipart/form-data")
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "media_id": "media-1"},
            )
        payload = json.loads(request.content.decode("utf-8"))
        assert payload == {"msgtype": "file", "file": {"media_id": "media-1"}}
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_file("daily", pdf_path, client=client)

    assert result == {"ok": True, "upload_ok": True, "send_ok": True}
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_network_error_result_does_not_contain_webhook_key(tmp_path, monkeypatch):
    pdf_path = tmp_path / "course.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    monkeypatch.setenv("WECOM_WEBHOOKS", f"daily={TEST_WEBHOOK}")

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network failed", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_file("daily", pdf_path, client=client)

    assert result["ok"] is False
    assert result["error_code"] == "network_error"
    assert "fake-test-key-12345678" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upload_payload", "expected_error"),
    [
        ({"errcode": 40001, "errmsg": "invalid credential"}, "upload_api_error"),
        ({"errcode": 0, "errmsg": "ok"}, "upload_media_id_missing"),
    ],
)
async def test_upload_api_failures_are_not_reported_as_sent(
    tmp_path,
    monkeypatch,
    upload_payload,
    expected_error,
):
    pdf_path = tmp_path / "course.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    monkeypatch.setenv("WECOM_WEBHOOKS", f"daily={TEST_WEBHOOK}")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=upload_payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_file("daily", pdf_path, client=client)

    assert result["ok"] is False
    assert result["send_ok"] is False
    assert result["error_code"] == expected_error


@pytest.mark.asyncio
async def test_file_message_api_failure_keeps_upload_and_send_status_separate(
    tmp_path,
    monkeypatch,
):
    pdf_path = tmp_path / "course.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    monkeypatch.setenv("WECOM_WEBHOOKS", f"daily={TEST_WEBHOOK}")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/upload_media"):
            return httpx.Response(
                200,
                json={"errcode": 0, "errmsg": "ok", "media_id": "media-1"},
            )
        return httpx.Response(200, json={"errcode": 45009, "errmsg": "rate limit"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_file("daily", pdf_path, client=client)

    assert result == {
        "ok": False,
        "upload_ok": True,
        "send_ok": False,
        "error_code": "send_api_error",
        "errcode": 45009,
    }


def test_pdf_path_validation_rejects_unsafe_or_invalid_files(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    valid = root / "course.pdf"
    valid.write_bytes(b"%PDF-1.4\n%%EOF\n")
    assert resolve_news_pdf("course.pdf", root=root) == valid.resolve()

    with pytest.raises(FileValidationError, match="absolute_path_not_allowed"):
        resolve_news_pdf(str(valid.resolve()), root=root)
    with pytest.raises(FileValidationError, match="path_traversal"):
        resolve_news_pdf("../course.pdf", root=root)
    text_file = root / "course.txt"
    text_file.write_text("not pdf", encoding="utf-8")
    with pytest.raises(FileValidationError, match="pdf_extension_required"):
        resolve_news_pdf("course.txt", root=root)
    empty = root / "empty.pdf"
    empty.touch()
    with pytest.raises(FileValidationError, match="empty_pdf"):
        resolve_news_pdf("empty.pdf", root=root)
    invalid_pdf = root / "invalid.pdf"
    invalid_pdf.write_text("not a real pdf", encoding="utf-8")
    with pytest.raises(FileValidationError, match="invalid_pdf_header"):
        resolve_news_pdf("invalid.pdf", root=root)
    oversized = root / "oversized.pdf"
    with oversized.open("wb") as handle:
        handle.seek(MAX_FILE_BYTES)
        handle.write(b"x")
    with pytest.raises(FileValidationError, match="pdf_too_large"):
        resolve_news_pdf("oversized.pdf", root=root)
```

- [ ] **Step 2: Run the protocol tests and confirm the expected failure**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_wecom_webhook.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.services.wecom_webhook'`.

- [ ] **Step 3: Implement Webhook parsing, path validation, upload, and send**

Create `services/knowledge-engine/app/services/wecom_webhook.py`:

```python
from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx


logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 18 * 1024 * 1024
DEFAULT_NEWS_ROOT = Path("/app/data/news-lianbo")


class FileValidationError(ValueError):
    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def load_wecom_webhooks() -> dict[str, str]:
    raw = os.environ.get("WECOM_WEBHOOKS", "").strip()
    webhooks: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        channel, url = pair.split("=", 1)
        if channel.strip() and url.strip():
            webhooks[channel.strip()] = url.strip()
    return webhooks


def _channel_webhook(channel: str) -> str | None:
    webhooks = load_wecom_webhooks()
    if not webhooks:
        return None
    return webhooks.get(channel) or next(iter(webhooks.values()))


def build_upload_url(webhook_url: str) -> str:
    parsed = urlsplit(webhook_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "qyapi.weixin.qq.com"
        or parsed.path != "/cgi-bin/webhook/send"
    ):
        raise ValueError("invalid_wecom_webhook")
    key_values = parse_qs(parsed.query).get("key", [])
    if len(key_values) != 1 or not key_values[0]:
        raise ValueError("wecom_webhook_key_missing")
    return urlunsplit(
        (
            "https",
            "qyapi.weixin.qq.com",
            "/cgi-bin/webhook/upload_media",
            urlencode({"key": key_values[0], "type": "file"}),
            "",
        )
    )


def resolve_news_pdf(
    relative_path: str,
    *,
    root: str | Path | None = None,
) -> Path:
    raw_path = Path(relative_path)
    if raw_path.is_absolute():
        raise FileValidationError("absolute_path_not_allowed")
    configured_root = root or os.environ.get("NEWS_LIANBO_ROOT") or DEFAULT_NEWS_ROOT
    root_path = Path(configured_root).resolve()
    candidate = (root_path / raw_path).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise FileValidationError("path_traversal") from exc
    if candidate.suffix.lower() != ".pdf":
        raise FileValidationError("pdf_extension_required")
    if not candidate.is_file():
        raise FileValidationError("pdf_not_found", status_code=404)
    size = candidate.stat().st_size
    if size == 0:
        raise FileValidationError("empty_pdf")
    if size > MAX_FILE_BYTES:
        raise FileValidationError("pdf_too_large", status_code=413)
    with candidate.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise FileValidationError("invalid_pdf_header")
    return candidate


async def _post_json(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
) -> dict:
    response = await client.post(url, json=payload)
    response.raise_for_status()
    return response.json()


async def send_text(
    channel: str,
    content: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    webhook = _channel_webhook(channel)
    if not webhook:
        return {
            "ok": False,
            "skipped": True,
            "reason": "WECOM_WEBHOOKS_not_configured",
        }
    owned_client = client is None
    active_client = client or httpx.AsyncClient(timeout=10.0)
    try:
        data = await _post_json(
            active_client,
            webhook,
            {"msgtype": "text", "text": {"content": content}},
        )
    except Exception as exc:
        logger.warning("wecom text send failed: %s", exc.__class__.__name__)
        return {"ok": False, "skipped": False, "error_code": "network_error"}
    finally:
        if owned_client:
            await active_client.aclose()
    if data.get("errcode") != 0:
        return {
            "ok": False,
            "skipped": False,
            "error_code": "wecom_api_error",
            "errcode": data.get("errcode"),
        }
    return {"ok": True}


async def send_file(
    channel: str,
    pdf_path: str | Path,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict:
    webhook = _channel_webhook(channel)
    if not webhook:
        return {
            "ok": False,
            "skipped": True,
            "reason": "WECOM_WEBHOOKS_not_configured",
        }
    path = Path(pdf_path)
    upload_url = build_upload_url(webhook)
    owned_client = client is None
    active_client = client or httpx.AsyncClient(timeout=30.0)
    try:
        upload = await active_client.post(
            upload_url,
            files={"media": (path.name, path.read_bytes(), "application/pdf")},
        )
        upload.raise_for_status()
        upload_data = upload.json()
        media_id = upload_data.get("media_id")
        if upload_data.get("errcode") != 0:
            return {
                "ok": False,
                "upload_ok": False,
                "send_ok": False,
                "error_code": "upload_api_error",
                "errcode": upload_data.get("errcode"),
            }
        if not media_id:
            return {
                "ok": False,
                "upload_ok": False,
                "send_ok": False,
                "error_code": "upload_media_id_missing",
            }
        send_data = await _post_json(
            active_client,
            webhook,
            {"msgtype": "file", "file": {"media_id": media_id}},
        )
    except Exception as exc:
        logger.warning("wecom file send failed: %s", exc.__class__.__name__)
        return {
            "ok": False,
            "upload_ok": False,
            "send_ok": False,
            "error_code": "network_error",
        }
    finally:
        if owned_client:
            await active_client.aclose()
    if send_data.get("errcode") != 0:
        return {
            "ok": False,
            "upload_ok": True,
            "send_ok": False,
            "error_code": "send_api_error",
            "errcode": send_data.get("errcode"),
        }
    return {"ok": True, "upload_ok": True, "send_ok": True}
```

- [ ] **Step 4: Run protocol tests**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_wecom_webhook.py -q
```

Expected: `7 passed`.

- [ ] **Step 5: Write notify route tests**

Replace `services/knowledge-engine/tests/test_notify.py` with:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.routers import notify


@pytest.mark.asyncio
async def test_notify_message_forwards_complete_content_without_human_gate(monkeypatch):
    sent = {}

    async def fake_post_wecom(channel: str, content: str) -> dict:
        sent["channel"] = channel
        sent["content"] = content
        return {"ok": True}

    monkeypatch.setattr(notify, "_post_wecom", fake_post_wecom)
    content = "daily-news\n" + ("complete-content-" * 80)
    result = await notify.notify_message(
        notify.MessageNotify(channel="daily", content=content)
    )

    assert result == {"ok": True, "detail": {"ok": True}}
    assert sent == {"channel": "daily", "content": content}


def test_notify_file_accepts_only_pdf_below_news_root(tmp_path, monkeypatch):
    root = tmp_path / "news"
    day = root / "2026-07-09"
    day.mkdir(parents=True)
    pdf = day / "course.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    monkeypatch.setenv("NEWS_LIANBO_ROOT", str(root))

    async def fake_send_file(channel, path):
        assert channel == "daily"
        assert path == pdf.resolve()
        return {"ok": True, "upload_ok": True, "send_ok": True}

    monkeypatch.setattr(notify, "send_file", fake_send_file)
    app = FastAPI()
    app.include_router(notify.router)
    client = TestClient(app)

    response = client.post(
        "/api/v1/notify/file",
        json={"channel": "daily", "relative_path": "2026-07-09/course.pdf"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_notify_file_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_LIANBO_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(notify.router)
    client = TestClient(app)

    response = client.post(
        "/api/v1/notify/file",
        json={"channel": "daily", "relative_path": "../outside.pdf"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "path_traversal"
```

- [ ] **Step 6: Replace the notify router with service delegation and the file endpoint**

Replace `services/knowledge-engine/app/routers/notify.py` with:

```python
"""Local notification endpoints for task, message, gate, and course PDF delivery."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.wecom_webhook import (
    FileValidationError,
    load_wecom_webhooks,
    resolve_news_pdf,
    send_file,
    send_text,
)


router = APIRouter(prefix="/api/v1/notify", tags=["notify"])


class TaskDoneNotify(BaseModel):
    session_id: str
    session_title: Optional[str] = None
    duration_ms: int = 0
    total_cost_usd: float = 0.0
    summary: Optional[str] = Field(default=None, description="任务最后一条消息摘要")
    channel: str = "task_done"


class MessageNotify(BaseModel):
    channel: str = Field(default="daily", min_length=1)
    content: str = Field(min_length=1)


class FileNotify(BaseModel):
    channel: str = Field(default="daily", min_length=1)
    relative_path: str = Field(min_length=1)


class HumanGateNotify(BaseModel):
    gate_id: str
    tool_name: str
    summary: str
    channel: str = "human_gate"


async def _post_wecom(channel: str, content: str) -> dict:
    return await send_text(channel, content)


def _format_duration(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    seconds = ms // 1000
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


@router.post("/task-done")
async def notify_task_done(body: TaskDoneNotify):
    title = body.session_title or body.session_id[:8]
    cost = f"${body.total_cost_usd:.4f}" if body.total_cost_usd else "—"
    lines = [
        "omni 任务完成",
        f"会话: {title}",
        f"用时: {_format_duration(body.duration_ms)}",
        f"花费: {cost}",
    ]
    if body.summary:
        lines.append(f"摘要: {body.summary[:200]}")
    result = await _post_wecom(body.channel, "\n".join(lines))
    return {"ok": result.get("ok", False), "detail": result}


@router.post("/message")
async def notify_message(body: MessageNotify):
    result = await _post_wecom(body.channel, body.content)
    return {"ok": result.get("ok", False), "detail": result}


@router.post("/file")
async def notify_file(body: FileNotify):
    try:
        pdf_path = resolve_news_pdf(body.relative_path)
    except FileValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    result = await send_file(body.channel, pdf_path)
    return {"ok": result.get("ok", False), "detail": result}


@router.post("/human-gate")
async def notify_human_gate(body: HumanGateNotify):
    content = (
        "需要你点头\n"
        f"工具: {body.tool_name}\n"
        f"摘要: {body.summary[:300]}\n"
        f"gate_id: {body.gate_id[:8]}"
    )
    result = await _post_wecom(body.channel, content)
    return {"ok": result.get("ok", False), "detail": result}


@router.get("/health")
async def notify_health():
    return {
        "ok": True,
        "channels_configured": sorted(load_wecom_webhooks()),
        "news_lianbo_root": "configured",
    }
```

- [ ] **Step 7: Add the read-only course-output mount**

Under `knowledge-engine.environment` in `docker-compose.yml`, add:

```yaml
      NEWS_LIANBO_ROOT: "${NEWS_LIANBO_ROOT:-/app/data/news-lianbo}"
```

Under `knowledge-engine.volumes`, add:

```yaml
      - "E:/agent/outputs/news-lianbo:/app/data/news-lianbo:ro"
```

- [ ] **Step 8: Run notification tests**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_wecom_webhook.py services/knowledge-engine/tests/test_notify.py services/knowledge-engine/tests/test_mcp_agent_extras.py -q
```

Expected: all selected tests pass; the existing MCP Webhook parser tests remain green.

- [ ] **Step 9: Validate Compose and restart only the knowledge engine**

Run:

```powershell
docker compose config --quiet
docker compose up -d --build knowledge-engine
docker exec omni-knowledge-engine python -m pytest tests/test_wecom_webhook.py tests/test_notify.py -q
```

Expected: Compose validation exits `0`; container tests pass.

- [ ] **Step 10: Verify health without printing Webhook values**

Run:

```powershell
Invoke-RestMethod http://localhost:8002/api/v1/notify/health | ConvertTo-Json -Depth 4
```

Expected: `channels_configured` includes `daily` and `alert`; output contains no URL and no key.

- [ ] **Step 11: Commit the notification boundary**

```powershell
git add services/knowledge-engine/app/services/wecom_webhook.py services/knowledge-engine/app/routers/notify.py services/knowledge-engine/tests/test_wecom_webhook.py services/knowledge-engine/tests/test_notify.py docker-compose.yml
git commit -m "feat: send course PDFs to enterprise wechat"
```

### Task 10: Local Delivery Client with Retry and All-Parts Accounting

**Files:**
- Create: `services/knowledge-engine/app/services/news_course/delivery.py`
- Create: `services/knowledge-engine/tests/test_news_course_delivery.py`
- Modify: `services/knowledge-engine/app/services/news_course/course_index.py`

- [ ] **Step 1: Write delivery refusal, retry, and completeness tests**

Create `services/knowledge-engine/tests/test_news_course_delivery.py`:

```python
import json

import httpx
import pytest

from app.services.news_course.delivery import deliver_course_package
from app.services.news_course.models import BuildReport, PdfInspection
from news_course_fixtures import make_manifest


def _build_report(tmp_path, *, ready=True):
    first = tmp_path / "2026-07-09" / "part-1.pdf"
    second = tmp_path / "2026-07-09" / "part-2.pdf"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"%PDF-1.4\npart1\n%%EOF\n")
    second.write_bytes(b"%PDF-1.4\npart2\n%%EOF\n")
    return BuildReport(
        manifest_path=str(tmp_path / "course-manifest.json"),
        preview=False,
        pdf_paths=[str(first), str(second)],
        visual_paths=["v1.png", "v2.png", "v3.png"],
        inspections=[
            PdfInspection(
                path=str(first),
                page_count=5,
                extracted_headings=[],
                rendered_pages=["p1.png"],
                contact_sheet="c1.png",
            ),
            PdfInspection(
                path=str(second),
                page_count=4,
                extracted_headings=[],
                rendered_pages=["p2.png"],
                contact_sheet="c2.png",
            ),
        ],
        quality_path=str(tmp_path / "quality.json"),
        delivery_ready=ready,
    )


def test_delivery_refuses_unapproved_build(tmp_path):
    with pytest.raises(ValueError, match="build_not_delivery_ready"):
        deliver_course_package(
            make_manifest(),
            _build_report(tmp_path, ready=False),
            output_root=tmp_path,
            notify_base_url="http://notify.test",
        )


def test_delivery_retries_failed_file_on_alert_and_counts_all_parts(tmp_path):
    build = _build_report(tmp_path)
    file_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal file_attempts
        payload = json.loads(request.content.decode("utf-8"))
        if request.url.path.endswith("/message"):
            return httpx.Response(200, json={"ok": True, "detail": {"ok": True}})
        file_attempts += 1
        if file_attempts == 1:
            assert payload["channel"] == "daily"
            return httpx.Response(200, json={"ok": False, "detail": {"ok": False}})
        return httpx.Response(200, json={"ok": True, "detail": {"ok": True}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = deliver_course_package(
            make_manifest(),
            build,
            output_root=tmp_path,
            notify_base_url="http://notify.test",
            client=client,
        )

    assert report.text_sent is True
    assert report.all_pdfs_sent is True
    assert len(report.delivered_pdf_paths) == 2
    assert any(attempt.channel == "alert" for attempt in report.attempts)
```

- [ ] **Step 2: Run delivery tests and confirm the expected failure**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_delivery.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.services.news_course.delivery'`.

- [ ] **Step 3: Implement delivery through the local notify API only**

Create `services/knowledge-engine/app/services/news_course/delivery.py`:

```python
from __future__ import annotations

from pathlib import Path

import httpx

from .models import (
    BuildReport,
    CourseManifest,
    DeliveryAttempt,
    DeliveryReport,
)


def _summary(manifest: CourseManifest, build: BuildReport) -> str:
    section_lines = [
        f"国内：{next(item for item in manifest.sections if item.section == 'domestic').summary}",
        f"国际：{next(item for item in manifest.sections if item.section == 'international').summary}",
        f"股市与经济：{next(item for item in manifest.sections if item.section == 'market_economy').summary}",
    ]
    return "\n".join(
        [
            f"【新闻联播精读】{manifest.news_date.isoformat()} {manifest.version}",
            f"今日主线：{manifest.main_thread}",
            *section_lines,
            (
                f"节目条目 {len(manifest.program_inventory)}；来源 {len(manifest.source_items)}；"
                f"覆盖率 {manifest.coverage.rate:.0%}；PDF {len(build.pdf_paths)} 卷。"
            ),
        ]
    )


def _post(
    client: httpx.Client,
    url: str,
    payload: dict,
) -> tuple[bool, str | None]:
    try:
        response = client.post(url, json=payload, timeout=30.0)
        response.raise_for_status()
        body = response.json()
    except Exception:
        return False, "notify_network_error"
    return bool(body.get("ok")), None if body.get("ok") else "notify_rejected"


def deliver_course_package(
    manifest: CourseManifest,
    build: BuildReport,
    *,
    output_root: str | Path,
    notify_base_url: str,
    extra_pdf_paths: list[str | Path] | None = None,
    client: httpx.Client | None = None,
) -> DeliveryReport:
    if not build.delivery_ready or build.preview or build.hard_failures:
        raise ValueError("build_not_delivery_ready")
    root = Path(output_root).resolve()
    requested_paths = [Path(path).resolve() for path in build.pdf_paths]
    requested_paths.extend(Path(path).resolve() for path in (extra_pdf_paths or []))
    relative_paths: list[str] = []
    for path in requested_paths:
        try:
            relative_paths.append(path.relative_to(root).as_posix())
        except ValueError as exc:
            raise ValueError(f"pdf_outside_output_root:{path.name}") from exc

    owned_client = client is None
    active_client = client or httpx.Client()
    attempts: list[DeliveryAttempt] = []
    delivered: list[str] = []
    try:
        text_ok = False
        for channel in ("daily", "alert"):
            ok, error_code = _post(
                active_client,
                f"{notify_base_url.rstrip('/')}/api/v1/notify/message",
                {"channel": channel, "content": _summary(manifest, build)},
            )
            attempts.append(
                DeliveryAttempt(
                    kind="text",
                    channel=channel,
                    target="summary",
                    ok=ok,
                    error_code=error_code,
                )
            )
            if ok:
                text_ok = True
                break

        for relative_path, absolute_path in zip(relative_paths, requested_paths):
            sent = False
            for channel in ("daily", "alert"):
                ok, error_code = _post(
                    active_client,
                    f"{notify_base_url.rstrip('/')}/api/v1/notify/file",
                    {"channel": channel, "relative_path": relative_path},
                )
                attempts.append(
                    DeliveryAttempt(
                        kind="file",
                        channel=channel,
                        target=relative_path,
                        ok=ok,
                        error_code=error_code,
                    )
                )
                if ok:
                    delivered.append(str(absolute_path))
                    sent = True
                    break
            if not sent:
                continue
    finally:
        if owned_client:
            active_client.close()
    return DeliveryReport(
        text_sent=text_ok,
        all_pdfs_sent=len(delivered) == len(requested_paths),
        attempts=attempts,
        delivered_pdf_paths=delivered,
    )
```

- [ ] **Step 4: Make index delivery input optional for the Sunday pre-delivery pass**

In `course_index.py`, change the `upsert_course_index` parameter to:

```python
    delivery: DeliveryReport | None = None,
```

Replace the two delivery fields in `values` with:

```python
        "wecom_text_sent": (
            delivery.text_sent
            if delivery is not None
            else (existing.wecom_text_sent if existing else False)
        ),
        "wecom_pdf_sent": (
            delivery.all_pdfs_sent
            if delivery is not None
            else (existing.wecom_pdf_sent if existing else False)
        ),
```

Expose a public reader after `_load_entries`:

```python
def load_course_index(path: str | Path) -> list[CourseIndexEntry]:
    return _load_entries(Path(path))
```

- [ ] **Step 5: Run delivery and index tests**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_delivery.py services/knowledge-engine/tests/test_news_course_index.py -q
```

Expected: `4 passed`.

- [ ] **Step 6: Commit delivery accounting**

```powershell
git add services/knowledge-engine/app/services/news_course/delivery.py services/knowledge-engine/app/services/news_course/course_index.py services/knowledge-engine/tests/test_news_course_delivery.py
git commit -m "feat: deliver complete news course package"
```

### Task 11: Thin Course-Pack CLI

**Files:**
- Create: `scripts/news_lianbo_course_pack.py`
- Create: `services/knowledge-engine/tests/test_news_course_cli.py`

- [ ] **Step 1: Write CLI validation and refusal tests**

Create `services/knowledge-engine/tests/test_news_course_cli.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

from app.services.news_course.models import write_manifest_atomic
from news_course_fixtures import make_manifest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "news_lianbo_course_pack.py"


def test_validate_command_returns_machine_readable_success(tmp_path):
    manifest_path = tmp_path / "course-manifest.json"
    write_manifest_atomic(manifest_path, make_manifest())

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate",
            "--manifest",
            str(manifest_path),
            "--expected-news-date",
            "2026-07-09",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["status"] == "passed"


def test_validate_command_returns_two_for_incomplete_coverage(tmp_path):
    manifest = make_manifest()
    manifest.coverage.mappings.pop()
    manifest_path = tmp_path / "course-manifest.json"
    write_manifest_atomic(manifest_path, manifest)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate",
            "--manifest",
            str(manifest_path),
            "--expected-news-date",
            "2026-07-09",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "failed"
```

- [ ] **Step 2: Run CLI tests and confirm the expected failure**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_cli.py -q
```

Expected: both tests fail because `scripts/news_lianbo_course_pack.py` does not exist.

- [ ] **Step 3: Implement all four CLI subcommands**

Create `scripts/news_lianbo_course_pack.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = REPO_ROOT / "services" / "knowledge-engine"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.services.news_course.builder import build_course_package
from app.services.news_course.course_index import (
    load_course_index,
    render_weekly_index_pdf,
    upsert_course_index,
)
from app.services.news_course.delivery import deliver_course_package
from app.services.news_course.models import (
    BuildReport,
    DeliveryReport,
    read_manifest,
    write_json_atomic,
)
from app.services.news_course.quality import apply_quality_report, check_manifest
from app.services.news_course.versioning import assert_additive_transition


def _read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def command_validate(args: argparse.Namespace) -> int:
    manifest = read_manifest(args.manifest)
    if args.previous_manifest:
        assert_additive_transition(read_manifest(args.previous_manifest), manifest)
    report = check_manifest(
        manifest,
        expected_news_date=date.fromisoformat(args.expected_news_date),
    )
    apply_quality_report(manifest, report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False))
    return 0 if report.status == "passed" else 2


def command_build(args: argparse.Namespace) -> int:
    report = build_course_package(
        args.manifest,
        args.output_dir,
        preview=args.preview,
        visual_review_path=args.visual_review,
        previous_manifest_path=args.previous_manifest,
        expected_news_date=date.fromisoformat(args.expected_news_date),
    )
    report_path = Path(args.output_dir) / (
        "build-preview.json" if args.preview else f"build-{read_manifest(args.manifest).phase}.json"
    )
    write_json_atomic(report_path, report.model_dump(mode="json"))
    print(
        json.dumps(
            {"build_report": str(report_path.resolve()), **report.model_dump(mode="json")},
            ensure_ascii=False,
        )
    )
    return 0 if not report.hard_failures else 2


def command_deliver(args: argparse.Namespace) -> int:
    manifest = read_manifest(args.manifest)
    build = BuildReport.model_validate(_read_json(args.build_report))
    report = deliver_course_package(
        manifest,
        build,
        output_root=args.output_root,
        notify_base_url=args.notify_base_url,
        extra_pdf_paths=args.extra_pdf,
    )
    report_path = Path(args.output_dir) / f"delivery-{manifest.phase}.json"
    write_json_atomic(report_path, report.model_dump(mode="json"))
    quality_payload = _read_json(build.quality_path)
    quality_payload["delivery_report"] = report.model_dump(mode="json")
    write_json_atomic(build.quality_path, quality_payload)
    print(
        json.dumps(
            {"delivery_report": str(report_path.resolve()), **report.model_dump(mode="json")},
            ensure_ascii=False,
        )
    )
    return 0 if report.text_sent and report.all_pdfs_sent else 3


def command_index(args: argparse.Namespace) -> int:
    manifest = read_manifest(args.manifest)
    build = BuildReport.model_validate(_read_json(args.build_report))
    delivery = (
        DeliveryReport.model_validate(_read_json(args.delivery_report))
        if args.delivery_report
        else None
    )
    root = Path(args.output_root)
    entry = upsert_course_index(
        root / "course-index.json",
        root / "课程索引.md",
        manifest,
        build,
        delivery,
    )
    weekly_path = None
    if args.weekly:
        entries = [
            item
            for item in load_course_index(root / "course-index.json")
            if item.final_pdfs
        ][-7:]
        weekly_path = render_weekly_index_pdf(
            entries,
            root / f"{manifest.news_date.isoformat()}-最近七天课程索引.pdf",
        )
    print(
        json.dumps(
            {
                "entry": entry.model_dump(mode="json"),
                "weekly_pdf": str(weekly_path.resolve()) if weekly_path else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news_lianbo_course_pack")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", required=True)
    validate.add_argument("--expected-news-date", required=True)
    validate.add_argument("--previous-manifest")
    validate.set_defaults(func=command_validate)

    build = subparsers.add_parser("build")
    build.add_argument("--manifest", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--expected-news-date", required=True)
    build.add_argument("--previous-manifest")
    build.add_argument("--visual-review")
    build.add_argument("--preview", action="store_true")
    build.set_defaults(func=command_build)

    deliver = subparsers.add_parser("deliver")
    deliver.add_argument("--manifest", required=True)
    deliver.add_argument("--build-report", required=True)
    deliver.add_argument("--output-root", required=True)
    deliver.add_argument("--output-dir", required=True)
    deliver.add_argument("--notify-base-url", default="http://localhost:8002")
    deliver.add_argument("--extra-pdf", action="append", default=[])
    deliver.set_defaults(func=command_deliver)

    index = subparsers.add_parser("index")
    index.add_argument("--manifest", required=True)
    index.add_argument("--build-report", required=True)
    index.add_argument("--delivery-report")
    index.add_argument("--output-root", required=True)
    index.add_argument("--weekly", action="store_true")
    index.set_defaults(func=command_index)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error_code": str(exc).split(";", 1)[0]},
                ensure_ascii=False,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_cli.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Run a fixture preview and final build through the CLI**

Run these commands after writing a passed `visual-review.json` matching the Task 7 schema:

```powershell
& $Python scripts/news_lianbo_course_pack.py validate --manifest E:\agent\outputs\news-lianbo-test\course-manifest.json --expected-news-date 2026-07-09
& $Python scripts/news_lianbo_course_pack.py build --manifest E:\agent\outputs\news-lianbo-test\course-manifest.json --output-dir E:\agent\outputs\news-lianbo-test\2026-07-09 --expected-news-date 2026-07-09 --preview
& $Python scripts/news_lianbo_course_pack.py build --manifest E:\agent\outputs\news-lianbo-test\course-manifest.json --output-dir E:\agent\outputs\news-lianbo-test\2026-07-09 --expected-news-date 2026-07-09 --visual-review E:\agent\outputs\news-lianbo-test\2026-07-09\visual-review.json
```

Expected: validation returns `status=passed`; preview returns `delivery_ready=false`; final returns `delivery_ready=true`.

- [ ] **Step 6: Commit the CLI**

```powershell
git add scripts/news_lianbo_course_pack.py services/knowledge-engine/tests/test_news_course_cli.py
git commit -m "feat: add news course pack CLI"
```

### Task 12: Update the Recurring Automation and Run a Real End-to-End Rehearsal

**Files:**
- Update through Codex app tool: automation `automation-2`
- Runtime outputs: `E:/agent/outputs/news-lianbo/`
- Read migration sample: `C:/Users/Administrator/Documents/Codex/2026-07-10/banbg/outputs/news-lianbo/2026-07-09-新闻联播-早.md`

- [ ] **Step 1: Inspect the current automation and preserve its schedule**

Call `codex_app__automation_update` in `view` mode for `automation-2`. Preserve the existing three Beijing-time runs, `ACTIVE` status, model, reasoning effort, and local execution environment. Change only its name, prompt, and workspace to:

- Name: `每日新闻联播PDF精读（早中晚）`
- Workspace: `E:\agent`

Do not print or place the raw recurrence expression in the plan, chat, or logs.

- [ ] **Step 2: Replace the automation prompt with this complete workflow**

Use the following prompt verbatim:

```text
你是“新闻联播每日精读课程”编排员。每天北京时间 07:30、12:30、21:30 运行，学习对象始终是前一天的中国《新闻联播》。最终产物是图文结合、信息不丢失的 A4 PDF 教材，并通过本机通知服务发送到企业微信。禁止读取、输出或记录企业微信 Webhook。

固定路径：
- 仓库：E:\agent\omni
- 输出根目录：E:\agent\outputs\news-lianbo
- Python：C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
- Poppler：C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe
- 中文字体：C:\Windows\Fonts\simhei.ttf
- 通知服务：http://localhost:8002

一、日期和阶段
1. 使用 Asia/Shanghai 计算“今天”和“前一天”的绝对日期，news_date 必须是前一天。
2. 07:30 运行写 phase=morning、version=v1。
3. 12:30 运行写 phase=noon、version=v2。
4. 21:30 运行写 phase=evening、version=final。
5. 每日目录为 E:\agent\outputs\news-lianbo\YYYY-MM-DD。
6. 三阶段 manifest 分别保存为 course-manifest-morning.json、course-manifest-noon.json、course-manifest-evening.json。午间必须以前一阶段 morning manifest 做只增不减校验；晚间必须以前一阶段 noon manifest 做只增不减校验。

二、联网查证
1. 必须联网。先找到能够代表当天完整节目的央视官方节目页、文字实录或节目单，再建立完整 program_inventory。
2. 国内新闻优先 CCTV、央视网、央视频、央视新闻；背景补充优先中国政府网、国务院部门官网、新华社、人民网和地方政府官网。
3. 国际新闻以节目国际条目为主；补充优先外交部、联合国、国际组织、相关国家政府或监管机构官网。
4. 股市与经济以节目经济主线为主；补充优先人民银行、国家统计局、证监会、财政部、商务部、外汇局、上交所、深交所、港交所及官方指数编制机构。
5. 内地、港股和主要海外代表性指数只使用官方收盘数据。休市或官方数据未发布时明确记录 warning，不用媒体估算补空。
6. 每个 source_item 都要保存 publisher、title、url、published_at、facts。每个数字都放入 numeric_facts，并携带 value、unit、period、source_id。
7. 事实只写进 fact_card；interpretation 必须以【解读】开头；owner_view 必须以【经营推演】开头。股市与经济不提供投资建议。

三、三部分课程
1. sections 必须且只能包含 domestic、international、market_economy。
2. 每个重点 lesson 必须包含 lesson_id、source_ids、fact_card、background、why_it_matters、impact_chain、interpretation、owner_view、visual_spec。
3. 教学图只使用 manifest 中已核验的事实和数字。优先流程图、时间线、关系图、数据图和对比图，不抓默认新闻摄影图。
4. 每张 visual_spec 必须有 visual_id、kind、title、caption、source_ids、period、items；数据图还必须有 unit 和每项 value。
5. 每个 program_inventory.item_id 和每个 source_items.source_id 都必须有且只有一个 coverage mapping。重点条目映射到 main 和 lesson_id；未展开条目映射到 appendix。覆盖率必须为 100%。
6. 国内和国际都必须完整覆盖。股市与经济要明确区分 source_kind=program 与 source_kind=official_supplement。

四、阶段增补
1. 早间 v1：建立三部分全景、完整节目清单、100% 去向、第一轮教学图和完整附录。
2. 午间 v2：原有 program、source、lesson、coverage、关键词和经营观察不得删除或改写；用新 ID 追加国内、国际、经济各自最重要条目的深度拆解。
3. 晚间 Final：保留午间全部内容，追加 memory_cards、8 至 12 道 quiz（每题含 answer 和 criteria）以及 next_day_watch。
4. 不逐字抄写整篇节目稿，但节目清单中的每条事实摘要和来源不得丢失。

五、构建与视觉检查
1. 设置 NEWS_COURSE_FONT 和 NEWS_COURSE_PDFTOPPM 后，先运行 validate。失败时重新核验缺失来源并修正 manifest，再重试一次。
2. validate 第二次仍失败：调用 POST http://localhost:8002/api/v1/notify/message，channel=alert，发送日期、阶段、失败码和本地 manifest 路径；停止，不得调用文件接口。
3. validate 通过后运行 build --preview。它会生成预览 PDF、全部页面 PNG 和联系表。
4. 使用 view_image 检查每个联系表，以及封面、国内首页、国际首页、股市与经济首页、完整附录首页和质量页。逐项判断中文字体、裁切、重叠、黑框、乱码、图文对应和可读性。
5. 视觉检查通过后，用 apply_patch 创建 visual-review.json，字段必须是：
   status=passed
   inspected_files=实际检查的绝对路径列表
   notes=实际检查结论
   reviewer=codex_multimodal
   reviewed_at=带时区 ISO 时间
6. 视觉检查失败时写 status=failed，修正 manifest 或 visual_spec 后重新构建预览并再检查一次。第二次仍失败则通过 alert 发送失败提醒，停止，不发 PDF。
7. 使用 visual-review.json 运行正式 build。只有返回 delivery_ready=true、hard_failures 为空、每个 PDF 分卷不超过 18 MiB 才能交付。

六、索引与发送
1. 正常阶段：正式 build 后运行 deliver；只有文字和全部 PDF 分卷都成功才算送达。随后运行 index 并传 delivery report。
2. 周日 evening：正式 build 后先运行一次 index --weekly 生成最近七天课程索引 PDF；deliver 时把该周索引作为 extra-pdf，发送顺序必须是当日晚间 Final 全部分卷在前、周索引在后；最后再次运行 index 并传真实 delivery report。
3. deliver 失败会先 daily、后 alert 各尝试一次。仍失败时保留本地文件并报告 PDF 未送达，禁止把索引标成成功。
4. 企业微信群文字摘要只写日期、版本、今日主线、国内一句、国际一句、经济一句、节目条目数、来源数、覆盖率和 PDF 卷数；完整内容全部在 PDF。

七、完成汇报
最终回复必须包含：
- news_date、phase、version
- program_item_count、source_count、coverage_rate
- 三部分 lesson 数
- PDF 路径、分卷数、总页数、教学图数
- 质量状态、warning
- 企业微信文字送达和全部 PDF 送达状态
- 周日时附周索引 PDF 路径

任何输出、日志、PDF、JSON、Markdown 和错误消息都不得包含 Webhook URL、key、内部工具 token、未完成标记或虚构来源。
```

- [ ] **Step 3: Save the automation update**

Call `codex_app__automation_update` for `automation-2` with the preserved scheduling/runtime fields, the name and workspace above, and the exact prompt. View it once more and confirm the card still shows three daily runs at 07:30, 12:30, and 21:30 Beijing time.

- [ ] **Step 4: Rehearse the historical morning migration sample**

Use the existing `2026-07-09-新闻联播-早.md` as a discovery aid, but re-open and verify its cited official pages before putting facts into the manifest. Create:

```text
E:\agent\outputs\news-lianbo\2026-07-09\course-manifest-morning.json
```

Run:

```powershell
$env:NEWS_COURSE_FONT = 'C:\Windows\Fonts\simhei.ttf'
$env:NEWS_COURSE_PDFTOPPM = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe'
& $Python E:\agent\omni\scripts\news_lianbo_course_pack.py validate --manifest E:\agent\outputs\news-lianbo\2026-07-09\course-manifest-morning.json --expected-news-date 2026-07-09
& $Python E:\agent\omni\scripts\news_lianbo_course_pack.py build --manifest E:\agent\outputs\news-lianbo\2026-07-09\course-manifest-morning.json --output-dir E:\agent\outputs\news-lianbo\2026-07-09 --expected-news-date 2026-07-09 --preview
```

Expected: validation passes at 100% coverage; preview creates all page PNGs and at least one contact sheet.

- [ ] **Step 5: Perform the visual review and build the historical final file**

Inspect the preview artifacts with `view_image`, create the concrete `visual-review.json`, then run:

```powershell
& $Python E:\agent\omni\scripts\news_lianbo_course_pack.py build --manifest E:\agent\outputs\news-lianbo\2026-07-09\course-manifest-morning.json --output-dir E:\agent\outputs\news-lianbo\2026-07-09 --expected-news-date 2026-07-09 --visual-review E:\agent\outputs\news-lianbo\2026-07-09\visual-review.json
```

Expected: a stable morning PDF name, `delivery_ready=true`, no hard failures, all pages rendered, and every part at or below 18 MiB.

- [ ] **Step 6: Send one real text-plus-PDF integration message**

Run:

```powershell
& $Python E:\agent\omni\scripts\news_lianbo_course_pack.py deliver --manifest E:\agent\outputs\news-lianbo\2026-07-09\course-manifest-morning.json --build-report E:\agent\outputs\news-lianbo\2026-07-09\build-morning.json --output-root E:\agent\outputs\news-lianbo --output-dir E:\agent\outputs\news-lianbo\2026-07-09 --notify-base-url http://localhost:8002
```

Expected: `text_sent=true`, `all_pdfs_sent=true`, and the Enterprise WeChat group visibly receives the concise summary followed by every PDF part.

- [ ] **Step 7: Update the course index with the actual delivery result**

Run:

```powershell
& $Python E:\agent\omni\scripts\news_lianbo_course_pack.py index --manifest E:\agent\outputs\news-lianbo\2026-07-09\course-manifest-morning.json --build-report E:\agent\outputs\news-lianbo\2026-07-09\build-morning.json --delivery-report E:\agent\outputs\news-lianbo\2026-07-09\delivery-morning.json --output-root E:\agent\outputs\news-lianbo
```

Expected: `course-index.json` contains one `NL-20260709` record, `课程索引.md` contains the date, and rerunning the command does not create a duplicate.

### Task 13: Final Verification and Review

**Files:**
- Verify every file listed in the File Map.
- Do not modify unrelated dirty files.

- [ ] **Step 1: Run the complete focused suite**

Run:

```powershell
& $Python -m pytest services/knowledge-engine/tests/test_news_course_models.py services/knowledge-engine/tests/test_news_course_quality.py services/knowledge-engine/tests/test_news_course_versioning.py services/knowledge-engine/tests/test_news_course_visuals.py services/knowledge-engine/tests/test_news_course_pdf.py services/knowledge-engine/tests/test_news_course_builder.py services/knowledge-engine/tests/test_news_course_index.py services/knowledge-engine/tests/test_news_course_delivery.py services/knowledge-engine/tests/test_news_course_cli.py services/knowledge-engine/tests/test_wecom_webhook.py services/knowledge-engine/tests/test_notify.py services/knowledge-engine/tests/test_mcp_agent_extras.py -q
```

Expected: all selected tests pass with zero failures.

- [ ] **Step 2: Run container and Compose checks**

Run:

```powershell
docker compose config --quiet
docker exec omni-knowledge-engine python -m pytest tests/test_notify.py tests/test_wecom_webhook.py -q
docker exec omni-knowledge-engine bash -c "cd /app && PYTHONPATH=/app python -m app.mcp.doctor"
```

Expected: Compose exits `0`; notification tests pass; doctor reports all registered tools healthy.

- [ ] **Step 3: Reinspect the real rendered artifact**

Render every real PDF part to a fresh verification directory with Poppler. Use `view_image` on every contact sheet and the required representative pages. Confirm:

- nonblank cover and all section openers;
- no overlapping or clipped text;
- Chinese glyphs are intact;
- every teaching visual cites source IDs and period;
- the appendix lists every program item;
- the source/quality page shows 100% coverage and passed visual review.

- [ ] **Step 4: Scan generated artifacts for leakage and unfinished content**

Run:

```powershell
rg -n "T[O]DO|T[B]D|F[I]XME|qyapi\.weixin\.qq\.com/cgi-bin/webhook|[?&]key=[A-Za-z0-9-]{8,}" E:\agent\outputs\news-lianbo
```

Expected: no matches.

- [ ] **Step 5: Check diff hygiene**

Run:

```powershell
git diff --check
git status --short
git log --oneline -13
```

Expected: `git diff --check` is clean; status contains no accidental generated PDFs or output files; the feature commits are scoped to the paths in this plan.

- [ ] **Step 6: Request code review**

Use the `requesting-code-review` skill. Review against the approved spec, with special attention to:

- additive version integrity;
- 100% program/source mapping;
- visual review actually blocking delivery;
- aggregate heading checks after PDF splitting;
- path traversal and file-size protection;
- no Webhook/key leakage;
- Sunday ordering and index idempotency.

- [ ] **Step 7: Fix every blocking review finding and rerun Steps 1-5**

Only claim completion after the focused suite, container checks, visual inspection, real Enterprise WeChat receipt, and leakage scan all pass.

## Requirement-to-Task Trace

| Approved requirement | Implemented by |
|---|---|
| Canonical structured fact base | Task 1 |
| Complete official program list, three sections, source/numeric contracts | Tasks 1-2 |
| 100% item/source destinations and fact/interpretation separation | Task 2 |
| Morning/noon/evening only-add behavior | Task 3 |
| Teaching diagrams from verified facts and data | Task 4 |
| A4 Chinese textbook PDF and complete appendix | Task 5 |
| All-page render, text extraction, contact sheet, <=18 MiB parts | Tasks 6-7 |
| Human visual inspection before send | Task 7 and Task 12 |
| Daily index and Sunday seven-day PDF | Task 8 and Task 12 |
| Safe Enterprise WeChat PDF delivery | Tasks 9-10 |
| Four-command CLI | Task 11 |
| Three recurring daily runs, official browsing, retry/alert behavior | Task 12 |
| End-to-end test and no-secret verification | Tasks 12-13 |
