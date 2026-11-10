"""Import the verified course large-data ZIP without replacing different data."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

ARCHIVE_SHA256 = '65cfec01f4091b037e5d9f809d98585593e3303c269aa43fbf395c1ba33d0dcb'
FILES = ('manifest.json', 'orders.csv', 'members.csv', 'stores.csv', 'cards.csv')
COUNTS = {'members': 30000, 'orders': 300000, 'stores': 24, 'cards': 38891}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(archive):
    archive_hash = digest(archive.read_bytes())
    if archive_hash != ARCHIVE_SHA256:
        raise ValueError('ARCHIVE_HASH_MISMATCH: no files extracted')
    with ZipFile(archive) as z:
        wanted = ['large/' + name for name in FILES]
        if sorted(z.namelist()) != sorted(wanted):
            raise ValueError('UNEXPECTED_ARCHIVE_CONTENTS')
        payloads = {name: z.read('large/' + name) for name in FILES}
    manifest = json.loads(payloads['manifest.json'])
    if manifest['id'] != 'qinghe-w03-20260923-large' or manifest['counts'] != COUNTS:
        raise ValueError('UNEXPECTED_DATASET')
    if manifest['coverage'] != ['2024-09-01', '2026-09-01'] or manifest['timezone'] != 'Asia/Shanghai':
        raise ValueError('UNEXPECTED_DATA_SCOPE')
    actual_counts, hashes = {}, {}
    for name in FILES[1:]:
        raw = payloads[name]
        hashes[name] = digest(raw)
        if hashes[name] != manifest['sha256'][name]:
            raise ValueError('CSV_HASH_MISMATCH: ' + name)
        reader = csv.reader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
        if not next(reader, None):
            raise ValueError('MISSING_CSV_HEADER: ' + name)
        count = sum(1 for _ in reader)
        actual_counts[name[:-4]] = count
        if count != COUNTS[name[:-4]]:
            raise ValueError('CSV_ROW_COUNT_MISMATCH: ' + name)
    return payloads, manifest, hashes, actual_counts, archive_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', dest='archive', type=Path, required=True)
    parser.add_argument('--dest', type=Path, default=Path('materials/data/large'))
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise SystemExit('REPORT_ALREADY_EXISTS: choose a new report path')
    payloads, manifest, hashes, counts, archive_hash = inspect(args.archive)
    if args.dest.exists() and not args.dest.is_dir():
        raise SystemExit('DESTINATION_IS_NOT_A_DIRECTORY')
    for name, raw in payloads.items():
        target = args.dest / name
        if target.exists() and (not target.is_file() or target.read_bytes() != raw):
            raise SystemExit('EXISTING_DIFFERENT_FILE: ' + str(target))
    args.dest.mkdir(parents=True, exist_ok=True)
    for name, raw in payloads.items():
        target = args.dest / name
        if not target.exists():
            target.write_bytes(raw)
        if digest(target.read_bytes()) != digest(raw):
            raise ValueError('EXTRACTED_FILE_HASH_MISMATCH: ' + name)
    report = {
        'status': 'ok', 'data_version': manifest['id'], 'counts_verified': counts,
        'coverage': manifest['coverage'], 'timezone': manifest['timezone'],
        'archive': str(args.archive.resolve()), 'archive_sha256': archive_hash,
        'destination': str(args.dest.resolve()), 'source_sha256': hashes,
        'manifest_sha256': digest(payloads['manifest.json']),
        'script_sha256': digest(Path(__file__).read_bytes()),
        'model_called': False, 'data_generated': False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('report: ' + str(args.report))


if __name__ == '__main__':
    main()
