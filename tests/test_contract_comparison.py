"""Detect wire differences without treating documentation or ref names as changes."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

spec=importlib.util.spec_from_file_location('compare_contracts',Path(__file__).parents[1]/'tools/compare_contracts.py')
comparison=importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def contract():
    return {'openapi':'3.1.0','info':{'version':'test'},'components':{'schemas':{'Event':{'type':'object','properties':{'eventId':{'type':'string'},'description':{'type':'string'}},'required':['eventId']}},
            'securitySchemes':{'key':{'type':'http','scheme':'bearer'}}}, 'security':[{'key':[]}],
            'paths':{'/events':{'post':{'requestBody':{'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Event'}}}},'responses':{'201':{'description':'OK'}}}}}}


def test_documentation_and_component_ref_renames_do_not_change_wire_shape():
    left=contract();right=deepcopy(left)
    right['components']['schemas']['Renamed']=right['components']['schemas'].pop('Event')
    right['components']['schemas']['Renamed']['description']='Different description'
    right['paths']['/events']['post']['requestBody']['content']['application/json']['schema']['$ref']='#/components/schemas/Renamed'
    right['paths']['/events']['post']['responses']['201']['description']='Created'
    assert comparison.compare(left,right)['status']=='matching_shapes'


def test_missing_routes_and_event_field_names_are_reported():
    left=contract();right=deepcopy(left)
    right['paths']['/api/v1/events']=right['paths'].pop('/events')
    result=comparison.compare(left,right)
    assert result['status']=='differences'
    assert result['missing_from_right']==['POST /events']
    right=deepcopy(left);right['components']['schemas']['Event']['required']=['event_id']
    assert comparison.compare(left,right)['changed_operations'][0]['different_sections']==['request']


def test_property_named_description_is_not_dropped_as_documentation():
    left=contract();right=deepcopy(left)
    right['components']['schemas']['Event']['properties']['description']['type']='integer'
    assert comparison.compare(left,right)['status']=='differences'


def test_authentication_difference_is_detected():
    left=contract();right=deepcopy(left);right['security']=[]
    assert comparison.compare(left,right)['changed_operations'][0]['different_sections']==['security']


def test_missing_document_replaces_stale_matching_report(tmp_path):
    output=tmp_path/'result.json';output.write_text('{"status":"matching_shapes"}')
    assert comparison.main(['--left',str(tmp_path/'missing'),'--right',str(tmp_path/'missing2'),'--report',str(output)])==2
    assert json.loads(output.read_text())['status']=='blocked'
