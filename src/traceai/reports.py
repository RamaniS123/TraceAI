"""Deterministic audit presentation of submitted records, not a compliance verdict."""
from traceai.corrections import valid_correction_ids

DISCLAIMER = (
    'This report supports review of submitted event records. '
    'It does not certify legal compliance or evaluate AI outputs or human decisions.'
)


def build_audit_report(view):
    """Build every section from the same interaction snapshot, without rewriting it.

    Ordering/warnings come from the shared timeline function. No generated report
    ID or wall-clock timestamp is added, so unchanged history yields identical JSON.
    Legacy accepted review fields remain unchanged, even if new input is stricter.
    """
    events = view['events']
    valid_links = valid_correction_ids({event['eventId']: event for event in events})
    reviews = []
    corrections = []
    for event in events:
        data = event['data']
        if event['eventType'] == 'review.completed':
            reviews.append({
                'eventId': event['eventId'],
                'reviewerId': data['reviewerId'],
                'action': data['action'],
                'reason': data['reason'],
                'occurredAt': event['occurredAt'],
            })
        elif event['eventType'] == 'record.corrected':
            corrections.append({
                'eventId': event['eventId'],
                'correctsEventId': data['correctsEventId'],
                'reason': data['reason'],
                'occurredAt': event['occurredAt'],
                'linkValid': event['eventId'] in valid_links,
            })
    return {
        'interactionId': view['interactionId'],
        'status': view['status'],
        'metadata': {
            'eventCount': len(events),
            'firstOccurredAt': events[0]['occurredAt'],
            'lastOccurredAt': events[-1]['occurredAt'],
        },
        'modelVersions': sorted({event['modelVersion'] for event in events}),
        'applicationVersions': sorted({event['applicationVersion'] for event in events}),
        'events': events,
        'warnings': view['warnings'],
        'reviewActions': reviews,
        'corrections': corrections,
        'disclaimer': DISCLAIMER,
    }
