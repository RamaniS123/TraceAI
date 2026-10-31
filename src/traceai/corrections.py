"""Structural correction links; records never replace or edit their predecessors."""


class InvalidCorrection(ValueError):
    """No target details are exposed when a link cannot be validated."""


def target_id(event):
    target = event.get('data', {}).get('correctsEventId')
    if not isinstance(target, str) or not 1 <= len(target) <= 64:
        raise InvalidCorrection()
    return target


def validate_correction_link(event, lookup):
    """Require an existing same-interaction acyclic path to an original event.

    lookup is transaction-bound and locks referenced records when used for writes.
    Timestamp order is deliberately not used: a correction may explain a bad clock.
    """
    first = current = target_id(event)
    seen = {event['eventId']}
    while True:
        if current in seen:
            raise InvalidCorrection()
        seen.add(current)
        original = lookup(current)
        if original is None or original['interactionId'] != event['interactionId']:
            raise InvalidCorrection()
        if original['eventType'] != 'record.corrected':
            return first
        current = target_id(original)


def valid_correction_ids(events_by_id):
    """Memoized structural checks for historical records, including legacy bad links.

    Old records are kept visible; dangling, cross-interaction, or cyclic legacy
    links are not labelled as valid corrections. Each node is resolved once.
    """
    resolved = {}
    for identifier, event in events_by_id.items():
        if event['eventType'] != 'record.corrected' or identifier in resolved:
            continue
        current = identifier
        chain = []
        seen = set()
        valid = False
        while True:
            node = events_by_id.get(current)
            if node is None or node['interactionId'] != event['interactionId'] or current in seen:
                break
            if current in resolved:
                valid = resolved[current]
                break
            if node['eventType'] != 'record.corrected':
                valid = True
                break
            seen.add(current)
            chain.append(current)
            try:
                current = target_id(node)
            except InvalidCorrection:
                break
        for item in chain:
            resolved[item] = valid
    return {identifier for identifier, valid in resolved.items() if valid}
