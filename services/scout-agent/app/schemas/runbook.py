from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class SessionConfig(BaseModel):
    storage_state: str
    recheck_url: str
    on_expired: str = "notify_dispatcher"


class RunbookStep(BaseModel):
    id: str
    action: str
    # goto
    url: str | None = None
    wait_until: str = "domcontentloaded"  # douyin/yuntu poll constantly — networkidle never settles
    # click_then_select
    selector: str | None = None
    value: str | None = None
    # multi_select
    values_env: str | None = None
    # click_and_download
    save_to: str | None = None
    timeout: int = 30000
    # parse_csv
    file: str | None = None
    file_from: str | None = None
    schema_name: str | None = Field(None, alias="schema")
    write_to: str | None = None
    # screenshot
    # llm_vision
    image: str | None = None
    image_from: str | None = None
    prompt: str | None = None
    # invoke_anomaly_engine
    sku_filter_env: str | None = None
    # sub_runbook / foreach_focus_skus
    runbook: str | None = None
    # html_table
    table_selector: str | None = None
    # extract_5a_card
    card_selector: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


class RunbookDefinition(BaseModel):
    name: str
    schedule: str | None = None
    platform: str = "douyin"
    shop_id_env: str | None = None
    session: SessionConfig | None = None
    steps: list[RunbookStep] = []
    description: str = ""
    tags: list[str] = []


class RunbookSummary(BaseModel):
    id: str
    name: str
    platform: str
    schedule: str | None
    description: str
    tags: list[str]


class RunbookRunSummary(BaseModel):
    id: str
    runbook_name: str
    started_at: str
    ended_at: str | None
    status: str
    error: str | None
