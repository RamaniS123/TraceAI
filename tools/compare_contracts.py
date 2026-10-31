#!/usr/bin/env python3
"""Offline OpenAPI wire-shape comparison; never rewrites contracts or sends data.

Descriptions/examples/component names are not wire behavior. Differences identify
items for pod review; matching shapes do not prove equivalent business semantics.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ANNOTATIONS = {'title','description','summary','example','examples','operationId','tags','externalDocs'}
MAPS = {'properties','patternProperties','$defs','definitions','content','headers'}
SETS = {'required','enum','allOf','anyOf','oneOf'}
METHODS = {'get','put','post','delete','options','head','patch','trace'}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def normalize(value, document, seen=(), named=False):
    if isinstance(value,list):
        return [normalize(item,document,seen) for item in value]
    if not isinstance(value,dict):
        return value
    if '$ref' in value:
        ref=value['$ref']
        if not isinstance(ref,str) or not ref.startswith('#/') or ref in seen:
            raise ValueError('Only acyclic local references are supported')
        resolved=document
        for token in ref[2:].split('/'):
            resolved=resolved[token.replace('~1','/').replace('~0','~')]
        base=normalize(resolved,document,(*seen,ref))
        siblings=normalize({k:v for k,v in value.items() if k!='$ref'},document,seen)
        # OpenAPI 3.1 schema siblings apply in addition to the referenced schema.
        return {'allOf':[base,siblings]} if siblings else base
    result={}
    for key,item in value.items():
        if not named and key in ANNOTATIONS:
            continue
        result[key]=normalize(item,document,seen,named=key in MAPS)
        if key in SETS and isinstance(result[key],list):
            result[key]=sorted(result[key],key=lambda v:json.dumps(v,sort_keys=True))
    return result


def operations(document):
    if not isinstance(document,dict) or not isinstance(document.get('paths'),dict) or not isinstance(document.get('openapi'),str):
        raise ValueError('Not an OpenAPI document')
    output={}
    for path,item in document['paths'].items():
        if not isinstance(path,str) or not isinstance(item,dict) or '$ref' in item:
            raise ValueError('Unsupported path item')
        names={name:f'p{index}' for index,name in enumerate(re.findall(r'\{([^{}]+)\}',path),1)}
        route=re.sub(r'\{([^{}]+)\}',lambda m:'{'+names[m[1]]+'}',path)
        for method,op in item.items():
            if method not in METHODS:
                continue
            parameters=normalize(item.get('parameters',[])+op.get('parameters',[]),document)
            for parameter in parameters:
                if parameter.get('in')=='path':
                    parameter['name']=names.get(parameter.get('name'),parameter.get('name'))
            security=[]
            schemes=document.get('components',{}).get('securitySchemes',{})
            for alternative in op.get('security',document.get('security',[])):
                security.append(sorted([{'scheme':normalize(schemes[name],document),'scopes':sorted(scopes)}
                                        for name,scopes in alternative.items()],key=digest))
            shape={'parameters':sorted(parameters,key=digest),
                   'request':normalize(op.get('requestBody'),document),
                   'responses':normalize(op.get('responses',{}),document,named=True),
                   'security':sorted(security,key=digest)}
            key=method.upper()+' '+route
            if key in output:
                raise ValueError('Ambiguous normalized route')
            output[key]={'operation':method.upper()+' '+path,'shape':shape}
    return output


def compare(left,right):
    a,b=operations(left),operations(right)
    shared=sorted(a.keys() & b.keys())
    changed=[]
    for key in shared:
        parts=[name for name in ('parameters','request','responses','security') if a[key]['shape'][name]!=b[key]['shape'][name]]
        if parts:
            changed.append({'left_operation':a[key]['operation'],'right_operation':b[key]['operation'],
                            'different_sections':parts})
    missing=[a[key]['operation'] for key in sorted(a.keys()-b.keys())]
    extra=[b[key]['operation'] for key in sorted(b.keys()-a.keys())]
    return {'status':'differences' if changed or missing or extra else 'matching_shapes',
            'assessment':'Static authored shapes only; business rules, AC inventories and live compatibility require separate agreement/testing.',
            'left_version':left.get('info',{}).get('version'), 'right_version':right.get('info',{}).get('version'),
            'left_fingerprint':digest(left),'right_fingerprint':digest(right),
            'left_operation_count':len(a),'right_operation_count':len(b),
            'missing_from_right':missing,'additional_on_right':extra,'changed_operations':changed}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--left',type=Path,required=True)
    parser.add_argument('--right',type=Path,required=True)
    parser.add_argument('--report',type=Path,default=Path('reports/contract-comparison.json'))
    args=parser.parse_args(argv)
    result={'status':'blocked'}
    try:
        result=compare(json.loads(args.left.read_text()),json.loads(args.right.read_text()))
    except (OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError):
        result['problem']='Provide two supported local OpenAPI JSON files; no live compatibility assessment was made.'
    result['checked_at']=datetime.now(timezone.utc).isoformat()
    try:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    except (OSError,ValueError):
        print('Could not write the comparison report.',file=sys.stderr)
        return 2
    print('Contract comparison: '+result['status'])
    if result['status']!='blocked':
        print(f"Operations: {result['left_operation_count']} / {result['right_operation_count']}; missing {len(result['missing_from_right'])}; additional {len(result['additional_on_right'])}; changed {len(result['changed_operations'])}")
    return {'matching_shapes':0,'differences':1,'blocked':2}[result['status']]


if __name__=='__main__':
    raise SystemExit(main())
