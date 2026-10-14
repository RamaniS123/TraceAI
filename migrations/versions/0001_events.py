"""Initial event storage. Keep this migration independent of application models."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_events"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "events",
        sa.Column("event_id", sa.String(64, collation="C"), primary_key=True),
        sa.Column("interaction_id", sa.String(64, collation="C"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_at_text", sa.Text(), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("application_version", sa.String(64), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("char_length(event_id) BETWEEN 1 AND 64", name="event_id_length"),
        sa.CheckConstraint("char_length(interaction_id) BETWEEN 1 AND 64", name="interaction_id_length"),
        sa.CheckConstraint("char_length(model_version) BETWEEN 1 AND 64", name="model_version_length"),
        sa.CheckConstraint("char_length(application_version) BETWEEN 1 AND 64", name="application_version_length"),
        sa.CheckConstraint("event_type IN ('interaction.started','model.output_generated','review.completed','interaction.completed','interaction.stopped','record.corrected')", name="event_type_allowed"),
        sa.CheckConstraint("jsonb_typeof(data) = 'object'", name="data_object"),
    )
    op.create_index("ix_events_interaction_timeline", "events", ["interaction_id", "occurred_at", "event_id"])


def downgrade():
    # Explicitly destructive: run only against a disposable test database.
    op.drop_table("events")
