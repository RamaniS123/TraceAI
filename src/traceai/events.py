"""Transactional storage, exact duplicate comparison, and interaction assembly."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from traceai.errors import APIError
from traceai.corrections import InvalidCorrection, validate_correction_link
from traceai.models import Event
from traceai.schemas import timestamp_key
from traceai.timeline import build_interaction
from traceai.reports import build_audit_report


def public_event(row):
    return {"eventId": row["event_id"], "interactionId": row["interaction_id"],
            "eventType": row["event_type"], "occurredAt": row["occurred_at_text"],
            "modelVersion": row["model_version"], "applicationVersion": row["application_version"],
            "data": row["data"]}


def canonical(value):
    # Python considers True == 1; JSON booleans and numbers must stay distinct.
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, Decimal)):
        return ("number", Decimal(value))
    if isinstance(value, dict):
        return ("object", tuple((key, canonical(item)) for key, item in sorted(value.items())))
    if isinstance(value, list):
        return ("array", tuple(canonical(item) for item in value))
    return (type(value).__name__, value)


def comparable(event):
    return canonical({**event, "occurredAt": timestamp_key(event["occurredAt"])})


def store_event(engine, event):
    values = dict(event_id=event["eventId"], interaction_id=event["interactionId"],
                  event_type=event["eventType"], occurred_at=datetime.fromisoformat(event["occurredAt"].replace("Z", "+00:00")),
                  occurred_at_text=event["occurredAt"], model_version=event["modelVersion"],
                  application_version=event["applicationVersion"], data=event["data"])
    with engine.begin() as connection:
        inserted = connection.execute(insert(Event).values(**values).on_conflict_do_nothing(index_elements=["event_id"]).returning(Event.event_id)).scalar_one_or_none()
        if inserted is None:
            stored = connection.execute(select(Event.__table__).where(Event.event_id == event["eventId"])).mappings().one()
            if comparable(public_event(stored)) != comparable(event):
                raise APIError(409, "EVENT_CONFLICT", "Event ID is already associated with different content.")
        elif event['eventType'] == 'record.corrected':
            def lookup(identifier):
                # The insertion and these key-share locks keep reset/deletion from
                # breaking a validated link before this transaction commits.
                row = connection.execute(
                    select(Event.__table__).where(Event.event_id == identifier)
                    .with_for_update(read=True, key_share=True)
                ).mappings().first()
                return public_event(row) if row is not None else None
            try:
                validate_correction_link(event, lookup)
            except InvalidCorrection:
                # Same response for missing, cross-interaction, and cyclic targets.
                # Raising inside engine.begin rolls back the new correction row.
                raise APIError(422, 'INVALID_CORRECTION',
                               'Correction must link to an existing, acyclic event history in the same interaction.') from None

    return {"eventId": event["eventId"], "interactionId": event["interactionId"], "stored": True, "duplicate": inserted is None}


def get_interaction(engine, interaction_id):
    with engine.connect() as connection:
        rows = connection.execute(select(Event.__table__).where(Event.interaction_id == interaction_id)).mappings().all()
    if not rows:
        raise APIError(404, "INTERACTION_NOT_FOUND", "Interaction was not found.")
    return build_interaction(interaction_id, (public_event(row) for row in rows))


def get_audit_report(engine, interaction_id):
    # One SELECT provides the single snapshot used by every report section.
    return build_audit_report(get_interaction(engine, interaction_id))


def reset_events(engine):
    with engine.begin() as connection:
        # Serialize reset with concurrent writers so the successful transaction is empty.
        connection.execute(text("LOCK TABLE events IN EXCLUSIVE MODE"))
        connection.execute(delete(Event))
    return {"reset": True, "remainingEvents": 0, "remainingInteractions": 0}
