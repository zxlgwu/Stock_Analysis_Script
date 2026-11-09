"""Structured outputs validated before anything is stored."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MaterialityItem(BaseModel):
    cluster_id: str
    material: bool
    category: str
    reason: str


class MaterialityBatch(BaseModel):
    items: list[MaterialityItem]


class Impact(BaseModel):
    ticker: str
    relation: Literal["direct", "competitor", "supplier", "customer", "macro_exposure"]
    direction: Literal["positive", "negative", "neutral"]
    affected_revenue_line: str
    est_revenue_impact_pct: float
    horizon: Literal["mid", "long"]
    confidence: float = Field(ge=0, le=1)
    already_priced_in: Literal["likely", "partially", "unlikely"]
    reasoning: str
    key_uncertainties: list[str] = Field(default_factory=list)


class Channel(BaseModel):
    """One step in how a story spreads: who is hit, through which mechanism."""

    target: str
    kind: Literal["company", "industry"]
    order: int = Field(ge=1, le=3)
    relation: Literal["direct", "competitor", "supplier", "customer", "macro_exposure"]
    direction: Literal["positive", "negative", "mixed"]
    mechanism: str

    @field_validator("kind", "relation", "direction", mode="before")
    @classmethod
    def _lower_enums(cls, value):
        return value.lower().strip() if isinstance(value, str) else value

    @field_validator("order", mode="before")
    @classmethod
    def _order_int(cls, value):
        return int(value)


class ImpactMap(BaseModel):
    relevant: bool
    event_summary: str
    channels: list[Channel] = Field(default_factory=list, max_length=8)

    @field_validator("channels", mode="before")
    @classmethod
    def _cap_channels(cls, value):
        return value[:8] if isinstance(value, list) else value


class EventAnalysis(BaseModel):
    cluster_id: str
    event_summary: str
    event_type: str
    impacts: list[Impact]


class ThesisResult(BaseModel):
    ticker: str
    thesis: str
    bear_case: str
    risks: list[str]
    invalidation: str
