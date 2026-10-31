"""REQ-06: audit sections are complete, stable, and never rewrite submitted history."""
from copy import deepcopy
from decimal import Decimal
import pytest
from traceai.timeline import build_interaction
from traceai.reports import build_audit_report, DISCLAIMER

pytestmark = pytest.mark.phase4


def event(identifier, kind='interaction.started', second=0, data=None, **extra):
    return {'eventId':identifier,'interactionId':'int-report','eventType':kind,
            'occurredAt':f'2026-10-30T12:00:{second:02d}Z','modelVersion':'model-b',
            'applicationVersion':'app-b','data':data or {},**extra}


def test_report_includes_every_record_version_review_and_correction_without_mutation():
    start=event('start')
    output=event('output','model.output_generated',1,{'score':Decimal('0.1234567890123456789')},modelVersion='model-a')
    review=event('review','review.completed',2,{'reviewerId':'reviewer-1','action':'override','reason':'  Synthetic reason  '},applicationVersion='app-a')
    correction=event('correction','record.corrected',3,{'correctsEventId':'review','reason':'Synthetic clarification'})
    end=event('end','interaction.completed',4)
    view=build_interaction('int-report',[end,correction,output,start,review]);before=deepcopy(view)
    report=build_audit_report(view)
    assert report['events']==[start,output,review,correction,end]
    assert report['modelVersions']==['model-a','model-b']
    assert report['applicationVersions']==['app-a','app-b']
    assert report['metadata']=={'eventCount':5,'firstOccurredAt':start['occurredAt'],'lastOccurredAt':end['occurredAt']}
    assert report['reviewActions']==[{'eventId':'review','reviewerId':'reviewer-1','action':'override','reason':'  Synthetic reason  ','occurredAt':review['occurredAt']}]
    assert report['corrections']==[{'eventId':'correction','correctsEventId':'review','reason':'Synthetic clarification','occurredAt':correction['occurredAt'],'linkValid':True}]
    assert report['warnings']==view['warnings'] and report['status']=='completed'
    assert report['events'][1]['data']['score']==Decimal('0.1234567890123456789')
    assert report['disclaimer']==DISCLAIMER
    assert view==before and build_audit_report(view)==report


def test_report_for_incomplete_history_keeps_warnings_and_empty_review_lists():
    end=event('end','interaction.completed',4)
    view=build_interaction('int-report',[end]);report=build_audit_report(view)
    assert report['events']==[end] and report['metadata']['eventCount']==1
    assert [w['eventType'] for w in report['warnings']]==['interaction.started','model.output_generated']
    assert report['reviewActions']==report['corrections']==[]


def test_report_marks_legacy_invalid_links_without_suppressing_the_records():
    records=[event('a','record.corrected',1,{'correctsEventId':'b','reason':'Legacy synthetic record'}),
             event('b','record.corrected',2,{'correctsEventId':'a','reason':'Legacy synthetic record'})]
    report=build_audit_report(build_interaction('int-report',records))
    assert report['events']==records
    assert all(c['linkValid'] is False for c in report['corrections'])
    assert report['warnings']==[]


def test_report_does_not_replace_original_review_with_a_correction_suggestion():
    original=event('review','review.completed',0,{'reviewerId':'','action':'accept','reason':'   '})
    correction=event('correction','record.corrected',1,{'correctsEventId':'review','reason':'Synthetic change request','suggestedAction':'reject'})
    report=build_audit_report(build_interaction('int-report',[original,correction]))
    assert report['reviewActions'][0]['action']=='accept'
    assert report['reviewActions'][0]['reviewerId']==''
    assert report['reviewActions'][0]['reason']=='   '
    assert report['events'][1]['data']['suggestedAction']=='reject'
