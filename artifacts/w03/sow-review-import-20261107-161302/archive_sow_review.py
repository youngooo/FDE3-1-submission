"""Archive verified SOW sources and revisions into the user's W03 workspace."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', default='.')
    args = parser.parse_args()
    root = Path(args.workspace).resolve()
    bundle = Path(__file__).resolve().parent
    if not (root / 'tools/w03.py').is_file() or not (root / 'docs/w03').is_dir():
        raise SystemExit('Not a W03 workspace: run from fde-agent-w03')

    audit_path = bundle / 'sow-review-source-check.json'
    audit = json.loads(audit_path.read_text(encoding='utf-8-sig'))
    sources = {}
    copies = []
    for entry in audit['files']:
        name = entry['name']
        if Path(name).name != name or '/' in name or '\\' in name:
            raise SystemExit('Unsafe source filename')
        raw = (bundle / name).read_bytes()
        if sha(raw) != entry['sha256']:
            raise SystemExit(f'Source hash mismatch: {name}')
        sources[name] = json.loads(raw)
        copies.append((Path('artifacts/w02/sources') / name, raw))
    transcript = next(v for k, v in sources.items() if k.endswith('-transcript.json'))
    public = next(v for k, v in sources.items() if k.endswith('-public.json'))
    keys = ('id', 'speaker', 'content')
    normalize = lambda msgs: [{k: m[k] for k in keys} for m in msgs]
    if transcript['meeting_id'] != public['meeting_id']:
        raise SystemExit('Meeting ID mismatch')
    if normalize(transcript['messages']) != normalize(
        [m for m in public['messages'] if m['speaker'] != 'system']
    ):
        raise SystemExit('Public/transcript message mismatch')
    for source_name, destination in (
        ('sow-review-source-check.json', 'artifacts/w03/sow-review/source_check.json'),
        ('sow_review_notes.md', 'docs/w03/sow_review_notes.md'),
    ):
        copies.append((Path(destination), (bundle / source_name).read_bytes()))
    snapshots = sorted(bundle.glob('sow.v0.*-*.md'))
    if len(snapshots) != 6:
        raise SystemExit(f'Expected six draft snapshots, found {len(snapshots)}')
    for path in snapshots:
        copies.append((Path('artifacts/w03/sow-review/versions') / path.name, path.read_bytes()))
    sow_raw = (bundle / 'sow.draft.md').read_bytes()
    if '版本：v0.7-draft' not in sow_raw.decode('utf-8'):
        raise SystemExit('Expected verified SOW v0.7')
    copies.append((Path('artifacts/w03/sow-review/versions/sow.v0.7-verified.md'), sow_raw))

    # Check every immutable destination before writing anything.
    for relative, raw in copies:
        dest = root / relative
        if dest.exists() and (not dest.is_file() or dest.read_bytes() != raw):
            raise SystemExit(f'Existing different content; nothing changed: {relative}')
    sow_dest = root / 'docs/w03/sow.md'
    if sow_dest.exists() and not sow_dest.is_file():
        raise SystemExit('sow.md is not a regular file')
    notes_path = root / 'docs/w03/interview_notes.md'
    notes_text = notes_path.read_text(encoding='utf-8') if notes_path.exists() else ''
    marker = '<!-- W03-SOW-REVIEW-04291 -->'
    appendix = '''

<!-- W03-SOW-REVIEW-04291 -->
## 本轮 SOW 回访归档补充（2026-11-07）

王经理同一会话的更新导出已核对并另名归档，旧记录保留；不是新增第五份独立角色访谈。
详见 [SOW 回访核查与修订记录](sow_review_notes.md)，以及 [当前范围草案](sow.md)。
本轮五条答复为 MSG-04266、MSG-04273、MSG-04277、MSG-04283、MSG-04291；公开版另含系统失败消息 MSG-04271。
这是新增 SOW 讨论的人工核查，不改变此前工作流七组、28 条候选的登记状态，也不表示重新运行提取或 apply。
范围与效果方案已有提出、反馈、修订和回应；六项付费日期依据、全部指标最终测试及正式批准仍未完成。
'''
    for relative, raw in copies:
        dest = root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(raw)
    backup = None
    if sow_dest.exists() and sow_dest.read_bytes() != sow_raw:
        backup = root / 'artifacts/w03/sow-backups' / (
            'sow-before-v07-' + datetime.now().strftime('%Y%m%d-%H%M%S')
            + '-' + uuid4().hex[:8] + '.md'
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(sow_dest.read_bytes())
    if not sow_dest.exists() or sow_dest.read_bytes() != sow_raw:
        sow_dest.write_bytes(sow_raw)
    if marker not in notes_text:
        notes_path.write_text(notes_text + appendix, encoding='utf-8')
    for relative, raw in copies:
        if (root / relative).read_bytes() != raw:
            raise SystemExit(f'Written file verification failed: {relative}')
    if sow_dest.read_bytes() != sow_raw:
        raise SystemExit('Written SOW verification failed')
    print(json.dumps({
        'status': 'ok', 'sow_version': 'v0.7-draft',
        'transcript_messages': len(transcript['messages']),
        'public_messages': len(public['messages']),
        'source_hashes_verified': True,
        'reply_ids': audit['reply_ids'],
        'sow': str(sow_dest), 'review_notes': str(root / 'docs/w03/sow_review_notes.md'),
        'previous_sow_backup': str(backup) if backup else None,
        'draft_snapshots_archived': len(snapshots),
        'model_called': False, 'workflow_restarted': False,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
