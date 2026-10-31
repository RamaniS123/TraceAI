"""REQ-09: structural correction rules, including invalid historical graphs."""
from copy import deepcopy
import pytest
from traceai.corrections import InvalidCorrection, validate_correction_link, valid_correction_ids

pytestmark = pytest.mark.phase4


def record(identifier, target=None, interaction='int-unit'):
    return {'eventId': identifier, 'interactionId': interaction,
            'eventType': 'record.corrected' if target is not None else 'model.output_generated',
            'data': {'correctsEventId': target, 'reason': 'Synthetic correction'} if target is not None else {}}


def test_chain_links_reach_original_without_mutating_any_record():
    items = [record('original'), record('first', 'original'), record('second', 'first')]
    index = {e['eventId']: e for e in items}
    before = deepcopy(index)
    assert validate_correction_link(record('third', 'second'), index.get) == 'second'
    assert valid_correction_ids(index) == {'first', 'second'}
    assert index == before


@pytest.mark.parametrize('items,new', [
    ([], record('new', 'absent')),
    ([], record('new', 'new')),
    ([record('other', interaction='different')], record('new', 'other')),
    ([record('old', 'absent')], record('new', 'old')),
    ([record('old', 'new')], record('new', 'old')),
    ([record('a', 'b'), record('b', 'a')], record('new', 'a')),
    ([record('a', 'b'), record('b', interaction='different')], record('new', 'a')),
])
def test_invalid_paths_are_rejected_including_cycles_and_legacy_bad_links(items, new):
    with pytest.raises(InvalidCorrection):
        validate_correction_link(new, {e['eventId']: e for e in items}.get)


def test_legacy_invalid_records_remain_visible_but_are_not_validated_annotations():
    items = [record('original'), record('valid', 'original'), record('self', 'self'),
             record('dangling', 'missing'), record('a', 'b'), record('b', 'a'),
             record('cross', 'original', interaction='other')]
    assert valid_correction_ids({e['eventId']: e for e in items}) == {'valid'}


def test_long_history_is_iterative_and_independent_of_input_order():
    items = [record('original')]
    for i in range(1100):
        items.append(record(f'correction-{i}', 'original' if i == 0 else f'correction-{i-1}'))
    index = {e['eventId']: e for e in reversed(items)}
    assert len(valid_correction_ids(index)) == 1100
    assert validate_correction_link(record('new', 'correction-1099'), index.get) == 'correction-1099'
