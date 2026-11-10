"""Replay only answer generation using immutable, previously executed query results."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

DEFAULT_IDS = ['single_discount_cents','single_first_order_count','single_first_buyer_count',
               'single_avg_buyer_value','monthly_jul_aug','aug_cancelled_zero_denominator']


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace',type=Path,default=Path('.'))
    ap.add_argument('--project',type=Path,required=True)
    ap.add_argument('--report',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--all-ok',action='store_true')
    args=ap.parse_args()
    root=args.workspace.resolve();sys.path.insert(0,str(root/'platform'))
    from fde_product.metrics.common import call_json,read,dump
    from fde_product.metrics.answer_display_facts import build_answer_display_facts
    source_raw=args.report.read_bytes();source=json.loads(source_raw)
    indexed={c['id']:c for c in source['cases']}
    if len(indexed)!=len(source['cases']):raise ValueError('DUPLICATE_CASE_IDS')
    ids=[c['id'] for c in source['cases'] if c['actual']['status']=='ok'] if args.all_ok else DEFAULT_IDS
    dataset=read(args.project/'dataset.json');catalog=read(args.project/'catalog.json');scope=read(args.project/'scope.json')
    expected_data_hash=sha(json.dumps({k:v for k,v in dataset.items() if k!='library_sha256'},sort_keys=True).encode())
    prompt_path=root/'product/w03_answer_prompt.txt';prompt_raw=prompt_path.read_bytes();prompt=prompt_raw.decode('utf-8')
    if '[W03_DISPLAY_FACTS_V1]' not in prompt:raise ValueError('DISPLAY_PROMPT_PATCH_MISSING')
    plans=[]
    for key in ids:
        case=indexed[key];actual=case['actual']
        if not case['comparison']['passed'] or actual['status']!='ok':raise ValueError('SOURCE_QUERY_NOT_PASSED: '+key)
        if (actual['data_version'],actual['data_sha256'],actual['catalog_sha256'])!=(dataset['id'],expected_data_hash,dataset['library_sha256']):raise ValueError('SOURCE_PROJECT_MISMATCH: '+key)
        # Match the live Agent's answer payload: old result decoration was added after answering.
        result={k:deepcopy(actual[k]) for k in ('status','intent','columns','rows','seconds','units','data_version','data_sha256','catalog_sha256') if k in actual}
        definitions=[x for x in catalog if x['id'] in actual['intent']['metrics']]
        payload={'question':case['question'],'customer_context':scope,'data_context':dataset,'result':result,'definitions':definitions,'answer_display_facts':build_answer_display_facts(result,definitions)}
        plans.append((case,payload))
    args.output.mkdir(parents=True,exist_ok=False)
    report={'kind':'answer_only_replay','source_report':str(args.report.resolve()),'source_report_sha256':sha(source_raw),
            'answer_prompt_sha256':sha(prompt_raw),'helper_sha256':sha((root/'platform/fde_product/metrics/answer_display_facts.py').read_bytes()),
            'script_sha256':sha(Path(__file__).read_bytes()),'query_reexecuted':False,'intent_model_called':False,
            'answer_model_called':True,'complete':False,'total':len(plans),'generated':0,
            'answer_semantic_review':'pending','cases':[]}
    out=args.output/'answer_replay_report.json';dump(out,report)
    for case,payload in plans:
        key=case['id'];folder=args.output/key;folder.mkdir()
        dump(folder/'input.json',payload)
        item={'id':key,'question':case['question'],'source_trace_id':case['actual'].get('trace_id'),
              'source_structured_comparison':case['comparison'],'result':payload['result'],'answer_display_facts':payload['answer_display_facts'],
              'source_answer':case['actual'].get('answer'),'answer_semantic_review':'pending'}
        print('ANSWER',key,flush=True)
        try:
            reply=call_json(prompt,payload,folder/'answer-trace.json')
            if not isinstance(reply.get('answer'),str) or not reply['answer'].strip():raise ValueError('ANSWER_TEXT_REQUIRED')
            item.update(generation_status='ok',answer=reply['answer'])
            report['generated']+=1
        except Exception as exc:
            item.update(generation_status='error',code=getattr(exc,'code',str(exc) if isinstance(exc,ValueError) else type(exc).__name__))
        trace=read(folder/'answer-trace.json') if (folder/'answer-trace.json').exists() else {}
        item['model_usage']=trace.get('usage',{})
        report['cases'].append(item);dump(out,report)
        if item['generation_status']=='error':
            print('Stopped after answer-call error; saved completed records.',flush=True);break
    report['complete']=len(report['cases'])==len(plans)
    report['source_report_unchanged']=sha(args.report.read_bytes())==report['source_report_sha256']
    dump(out,report)
    print(json.dumps({k:report[k] for k in ('complete','generated','total','query_reexecuted','answer_semantic_review','source_report_unchanged')},ensure_ascii=False,indent=2))
    print('report: '+str(out.resolve()))


if __name__=='__main__':
    main()
