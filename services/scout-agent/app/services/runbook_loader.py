from __future__ import annotations

from pathlib import Path

import yaml

from app.config import settings
from app.schemas.runbook import RunbookDefinition, RunbookSummary

_RUNBOOKS_DIR = Path(settings.runbooks_dir)


def _runbook_id(path: Path) -> str:
    """Returns relative path without extension as the runbook ID, e.g. 'compass/home'."""
    rel = path.relative_to(_RUNBOOKS_DIR)
    return str(rel.with_suffix("")).replace("\\", "/")


def load_all() -> list[tuple[str, RunbookDefinition]]:
    result = []
    for path in sorted(_RUNBOOKS_DIR.rglob("*.yaml")):
        rb_id = _runbook_id(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        rb = RunbookDefinition.model_validate(raw)
        result.append((rb_id, rb))
    return result


def load_one(rb_id: str) -> RunbookDefinition:
    path = _RUNBOOKS_DIR / (rb_id + ".yaml")
    if not path.exists():
        raise FileNotFoundError(f"Runbook not found: {rb_id}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return RunbookDefinition.model_validate(raw)


def list_summaries() -> list[RunbookSummary]:
    result = []
    for rb_id, rb in load_all():
        result.append(RunbookSummary(
            id=rb_id,
            name=rb.name,
            platform=rb.platform,
            schedule=rb.schedule,
            description=rb.description,
            tags=rb.tags,
        ))
    return result
