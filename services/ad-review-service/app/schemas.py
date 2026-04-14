from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    name: str = Field(min_length=1)
    sku: str | None = None
    price: float | None = None
    margin_rate: float | None = None
    category: str | None = None
    description: str = ""


class ProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    price: float | None = None
    margin_rate: float | None = None
    category: str | None = None
    description: str | None = None


class CampaignCreate(BaseModel):
    product_id: str | None = None
    product_name: str = Field(min_length=1)
    product_sku: str | None = None
    product_price: float | None = None
    product_margin_rate: float | None = None
    name: str = Field(min_length=1)
    start_date: date
    end_date: date
    total_budget: float | None = None


class CampaignUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    total_budget: float | None = None
    total_cost: float | None = None
    status: str | None = None


class AudiencePackCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    tags: list[str] = []
    targeting_method_text: str = ""
    audience_profile_text: str = ""


class AudiencePackUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    targeting_method_text: str | None = None
    audience_profile_text: str | None = None


class MaterialGroupCreate(BaseModel):
    style_label: str = Field(min_length=1)
    video_purpose: str = "seeding"
    description: str = ""


class MaterialGroupUpdate(BaseModel):
    style_label: str | None = None
    video_purpose: str | None = None
    description: str | None = None


class MaterialUpdate(BaseModel):
    name: str | None = None
    video_analysis_id: str | None = None
    iteration_note: str | None = None
    group_id: str | None = None
    change_tags: list[str] | None = None


class MaterialBatchGroup(BaseModel):
    material_ids: list[str] = Field(min_length=1)
    group_id: str | None = None


class MaterialLinkVideo(BaseModel):
    """video_analysis_id 传 null 表示解除关联。"""
    video_analysis_id: str | None


class MaterialLinkParent(BaseModel):
    parent_material_id: str
    iteration_note: str = ""
    change_tags: list[str] = []


class ReviewLogUpdate(BaseModel):
    content_md: str
    experience_tags: list[str] = []


class GenerateReviewSseChunk(BaseModel):
    type: str
    content: str = ""
    review_log_id: str = ""
