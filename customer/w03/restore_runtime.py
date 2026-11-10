"""Restore the submitted runtime snapshot to its verified course baseline.

Default is a read-only preflight. --apply backs up changed target files first.
No model calls, database operations, environment files or service restarts.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import uuid


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or '\\' in relative:
        raise ValueError('UNSAFE_PATH: ' + relative)
    target = root.joinpath(rel).resolve()
    if not target.is_relative_to(root):
        raise ValueError('PATH_OUTSIDE_WORKSPACE: ' + relative)
    return target


def restore(workspace, bundle, apply=False):
    root = Path(workspace).resolve()
    bundle = Path(bundle).resolve()
    manifest = json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('kind') != 'w03_runtime_snapshot_v1':
        raise ValueError('UNKNOWN_MANIFEST')
    for entry in manifest['baseline_guards']:
        target = safe_path(root, entry['path'])
        if not target.is_file() or sha(target.read_bytes()) != entry['sha256']:
            raise ValueError('BASELINE_GUARD_MISMATCH: ' + entry['path'])
    pending = []
    plan = []
    seen = set()
    for entry in manifest['files']:
        relative = entry['path']
        if relative in seen:
            raise ValueError('DUPLICATE_MANIFEST_PATH')
        seen.add(relative)
        source = safe_path(bundle/'files', relative)
        raw = source.read_bytes()
        if sha(raw) != entry['sha256']:
            raise ValueError('SNAPSHOT_HASH_MISMATCH: ' + relative)
        if relative.endswith('.py'):
            compile(raw.decode('utf-8'), relative, 'exec')
        target = safe_path(root, relative)
        original = target.read_bytes() if target.is_file() else None
        before = sha(original) if original is not None else None
        if before == entry['sha256']:
            state = 'already_current'
        elif before == entry['baseline_sha256'] and not (target.exists() and not target.is_file()):
            state = 'ready'
            pending.append((relative, target, original, raw))
        else:
            raise ValueError('TARGET_VERSION_MISMATCH: ' + relative)
        plan.append({'path':relative,'state':state,'before_sha256':before,'after_sha256':entry['sha256']})
    result = {'status':'verified','applied':False,'files':plan,'model_called':False,'query_executed':False}
    if apply and pending:
        backup = root/'artifacts/w03'/('runtime-restore-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        backup.mkdir(parents=True,exist_ok=False)
        for relative,target,original,raw in pending:
            if original is not None:
                dest=backup/'before'/relative
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes(original)
        (backup/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
        for relative,target,original,raw in pending:
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(raw)
            if sha(target.read_bytes()) != sha(raw):
                raise ValueError('WRITE_VERIFICATION_FAILED: '+relative)
        result.update(status='restored',applied=True,backup=str(backup))
    elif apply:
        result['status']='already_current'
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--bundle',type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    try:
        value=restore(args.workspace,args.bundle or args.workspace/'artifacts/w03/runtime-customization-current',args.apply)
    except (OSError,ValueError,KeyError) as exc:
        print(json.dumps({'status':'error','code':str(exc)},ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(value,ensure_ascii=False,indent=2))
