"""Phase 4: read-only timeline analysis and structural correction annotations.

Rules are provisional until pod reconciliation; see docs/phase-4-timeline.md.
Corrections remain visible records and do not overwrite the original timeline.
"""
from traceai.schemas import timestamp_key
from traceai.corrections import valid_correction_ids, target_id

STAGES = (
    'interaction.started',
    'model.output_generated',
    'review.completed',
)
RANK = {kind: index for index, kind in enumerate(STAGES)}
RANK.update({'interaction.completed': 3, 'interaction.stopped': 3})
TERMINAL = {'interaction.completed': 'completed', 'interaction.stopped': 'stopped'}


def build_interaction(interaction_id, records):
    """Recompute on every read without changing accepted records or receipt times.

    Equal instants use eventId for display only; they do not imply a sequence
    violation. At most one order warning per event and prerequisite type is
    emitted. Complexity is O(n log n) for sorting plus O(n) for analysis.
    """
    timed = sorted(((timestamp_key(event['occurredAt']), event) for event in records),
                   key=lambda item: (item[0], item[1]['eventId']))
    events = [event for _, event in timed]
    status = 'in_progress'
    latest = {}
    for instant, event in timed:
        kind = event['eventType']
        latest[kind] = instant
        if kind in TERMINAL:
            status = TERMINAL[kind]

    corrected = valid_correction_ids({event["eventId"]: event for event in events})
    warnings = []
    for instant, event in timed:
        kind = event['eventType']
        if kind == 'record.corrected':
            if event['eventId'] in corrected:
                warnings.append({
                    'code': 'CORRECTED_EVENT',
                    'message': 'A linked correction is recorded; the original event is retained.',
                    'eventId': event['eventId'],
                    'eventType': kind,
                    'correctsEventId': target_id(event),
                })
            continue
        if kind not in RANK:
            continue
        for prerequisite in STAGES[:RANK[kind]]:
            if prerequisite in latest and instant < latest[prerequisite]:
                warnings.append({
                    'code': 'OUT_OF_ORDER_EVENT',
                    'message': f'{kind} occurred before {prerequisite}.',
                    'eventId': event['eventId'],
                    'eventType': kind,
                })

    if status != 'in_progress':
        required = ['interaction.started']
        # A normal completion needs output. An aborted interaction need not have
        # produced output, unless it contains a review of that output.
        if 'interaction.completed' in latest or 'review.completed' in latest:
            required.append('model.output_generated')
        for kind in required:
            if kind not in latest:
                warnings.append({
                    'code': 'MISSING_EVENT',
                    'message': f'Finalized interaction is missing {kind}.',
                    'eventType': kind,
                })
    return {'interactionId': interaction_id, 'status': status, 'events': events, 'warnings': warnings}
