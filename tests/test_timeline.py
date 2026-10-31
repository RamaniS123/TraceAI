"""REQ-03: pure analysis of immutable event histories, independent of HTTP order."""
from copy import deepcopy
import pytest

from traceai.timeline import build_interaction

pytestmark = pytest.mark.phase4


def event(kind, seconds=0, identifier=None, **changes):
    return {'eventId': identifier or kind, 'interactionId': 'int-unit', 'eventType': kind,
            'occurredAt': f'2026-10-30T10:00:{seconds:02d}Z', 'modelVersion': 'model-1',
            'applicationVersion': 'app-1', 'data': {}, **changes}


def warnings(records):
    return build_interaction('int-unit', records)['warnings']


def test_complete_interaction_with_optional_review_has_no_warning():
    for review in ([], [event('review.completed', 2)]):
        assert warnings([event('interaction.completed', 3), *review,
                         event('interaction.started'), event('model.output_generated', 1)]) == []


@pytest.mark.parametrize('kind', ['model.output_generated', 'review.completed', 'record.corrected'])
def test_open_interaction_does_not_prematurely_report_missing_events(kind):
    assert warnings([event(kind)]) == []


def test_missing_warnings_wait_for_finalization_then_follow_lifecycle_order():
    result = warnings([event('interaction.completed')])
    assert [w['code'] for w in result] == ['MISSING_EVENT', 'MISSING_EVENT']
    assert [w['eventType'] for w in result] == ['interaction.started', 'model.output_generated']
    assert all('eventId' not in w for w in result)


def test_stopped_interaction_can_end_before_output():
    assert warnings([event('interaction.started'), event('interaction.stopped', 1)]) == []


def test_stopped_review_requires_the_output_it_reviews_after_finalization():
    result = warnings([event('interaction.started'), event('review.completed', 1), event('interaction.stopped', 2)])
    assert result == [{'code': 'MISSING_EVENT', 'message': 'Finalized interaction is missing model.output_generated.', 'eventType': 'model.output_generated'}]


def test_semantic_sequence_warning_is_attached_to_premature_event():
    result = warnings([event('model.output_generated', 0, 'output'), event('interaction.started', 1), event('interaction.completed', 2)])
    assert result == [{'code': 'OUT_OF_ORDER_EVENT', 'message': 'model.output_generated occurred before interaction.started.', 'eventId': 'output', 'eventType': 'model.output_generated'}]


def test_all_sequence_violations_are_reported_before_missing_events():
    records = [event('interaction.completed', 0, 'terminal'), event('review.completed', 1, 'review'), event('model.output_generated', 2, 'output')]
    result = warnings(records)
    assert [(w['eventId'], w['message']) for w in result[:-1]] == [
        ('terminal', 'interaction.completed occurred before model.output_generated.'),
        ('terminal', 'interaction.completed occurred before review.completed.'),
        ('review', 'review.completed occurred before model.output_generated.'),
    ]
    assert result[-1]['code'] == 'MISSING_EVENT'
    assert result[-1]['eventType'] == 'interaction.started'


def test_late_events_resolve_missing_warnings_without_mutating_original_records():
    records = [event('interaction.completed', 3)]
    snapshot = deepcopy(records)
    assert len(warnings(records)) == 2
    assert warnings([*records, event('interaction.started'), event('model.output_generated', 1)]) == []
    assert records == snapshot
    assert len(warnings(records)) == 2  # Results are independent and uncached.


def test_late_prerequisite_with_wrong_timestamp_replaces_missing_with_order_warning():
    records = [event('interaction.completed', 2), event('interaction.started', 0)]
    assert warnings(records)[0]['code'] == 'MISSING_EVENT'
    result = warnings([*records, event('model.output_generated', 3)])
    assert len(result) == 1 and result[0]['code'] == 'OUT_OF_ORDER_EVENT'
    assert result[0]['eventType'] == 'interaction.completed'


def test_equal_instants_only_use_event_id_for_display_not_warning_detection():
    records = [event('interaction.started', identifier='z'), event('model.output_generated', identifier='a'), event('interaction.completed', identifier='b')]
    result = build_interaction('int-unit', records)
    assert [e['eventId'] for e in result['events']] == ['a', 'b', 'z']
    assert result['warnings'] == []


def test_submicrosecond_precision_is_used_for_sequence_detection():
    records = [event('interaction.started', occurredAt='2026-10-30T10:00:00.0000002Z'),
               event('model.output_generated', occurredAt='2026-10-30T10:00:00.0000001+00:00')]
    assert len(warnings(records)) == 1


def test_corrections_are_visible_but_do_not_rewrite_lifecycle_in_this_increment():
    original = event('interaction.completed', 2)
    correction = event('record.corrected', 1, data={'correctsEventId': original['eventId'], 'reason': 'synthetic'})
    result = build_interaction('int-unit', [original, correction])
    assert [w['eventType'] for w in result['warnings']] == ['interaction.started', 'model.output_generated']
    assert correction in result['events'] and original in result['events']


def test_warning_order_is_independent_of_input_order_and_no_warning_is_duplicated():
    records = [event('interaction.completed', 0), event('review.completed', 1),
               event('model.output_generated', 2), event('interaction.started', 3)]
    assert warnings(records) == warnings(list(reversed(records)))
    assert len({(w['code'], w.get('eventId'), w['message']) for w in warnings(records)}) == len(warnings(records))


def test_status_still_uses_latest_terminal_without_creating_warning_statuses():
    result = build_interaction('int-unit', [event('interaction.stopped', 2), event('interaction.completed', 1)])
    assert result['status'] == 'stopped'
