"""Immutable event storage; interaction membership is derived from events."""
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from traceai.db import Base

EVENT_TYPES = (
    "interaction.started", "model.output_generated", "review.completed",
    "interaction.completed", "interaction.stopped", "record.corrected",
)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("char_length(event_id) BETWEEN 1 AND 64", name="event_id_length"),
        CheckConstraint("char_length(interaction_id) BETWEEN 1 AND 64", name="interaction_id_length"),
        CheckConstraint("char_length(model_version) BETWEEN 1 AND 64", name="model_version_length"),
        CheckConstraint("char_length(application_version) BETWEEN 1 AND 64", name="application_version_length"),
        CheckConstraint("event_type IN (" + ",".join(repr(t) for t in EVENT_TYPES) + ")", name="event_type_allowed"),
        CheckConstraint("jsonb_typeof(data) = 'object'", name="data_object"),
        Index("ix_events_interaction_timeline", "interaction_id", "occurred_at", "event_id"),
    )

    event_id: Mapped[str] = mapped_column(String(64, collation="C"), primary_key=True)
    interaction_id: Mapped[str] = mapped_column(String(64, collation="C"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Keep the exact RFC3339 text; PostgreSQL timestamps alone lose original spelling.
    occurred_at_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    application_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
