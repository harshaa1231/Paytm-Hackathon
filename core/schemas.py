"""Pydantic models for every LLM output. Invalid JSON never reaches the ledger."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class MatchAnswer(BaseModel):
    candidate_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=300)

    @field_validator("candidate_id", mode="before")
    @classmethod
    def _nullish(cls, v):
        if v in ("", "null", "None", "none"):
            return None
        return v


class RephraseAnswer(BaseModel):
    text: str = Field(min_length=3, max_length=320)


class ToneVerdict(BaseModel):
    numbers_match: bool
    fair_and_polite: bool
    reason: str = Field(default="", max_length=300)
