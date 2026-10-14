"""Strict public event validation and exact timestamp ordering."""
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Short = Annotated[str, Field(min_length=1, max_length=64)]
UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$", re.ASCII)


def timestamp_key(value: str) -> Decimal:
    """Order arbitrary fractional precision without PostgreSQL's microsecond rounding."""
    if not UTC_TIMESTAMP.fullmatch(value):
        raise ValueError("must use RFC 3339 UTC format")
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    seconds = instant.toordinal() * 86400 + instant.hour * 3600 + instant.minute * 60 + instant.second
    fraction = value[19:].split("+")[0].removesuffix("Z").lstrip(".") or "0"
    return Decimal(f"{seconds}.{fraction}")


class EventInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    eventId: Short
    interactionId: Short
    eventType: Literal[
        "interaction.started", "model.output_generated", "review.completed",
        "interaction.completed", "interaction.stopped", "record.corrected",
    ]
    occurredAt: str
    modelVersion: Short
    applicationVersion: Short
    data: dict[str, Any]

    @field_validator("occurredAt")
    @classmethod
    def utc_timestamp(cls, value):
        timestamp_key(value)
        return value

    @model_validator(mode="after")
    def event_specific_data(self):
        data = self.data
        if self.eventType == "review.completed":
            if not isinstance(data.get("reviewerId"), str):
                raise ValueError("data.reviewerId must be a string")
            if data.get("action") not in ("accept", "override", "reject", "escalate"):
                raise ValueError("data.action must be a supported review action")
        if self.eventType in ("review.completed", "record.corrected"):
            reason = data.get("reason")
            if not isinstance(reason, str) or not 1 <= len(reason) <= 500:
                raise ValueError("data.reason must be a string of 1–500 characters")
        if self.eventType == "record.corrected":
            target = data.get("correctsEventId")
            if not isinstance(target, str) or not 1 <= len(target) <= 64:
                raise ValueError("data.correctsEventId must be a string of 1–64 characters")
        return self


class ResetRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def confirmation(cls, value):
        if value is not True:
            raise ValueError("confirmation must be true")
        return value
