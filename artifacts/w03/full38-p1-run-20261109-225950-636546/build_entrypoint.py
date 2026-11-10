"""Call the existing builder with explicit request policy; no framework edits."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path('/home/yang/FDE/w03-work/fde-agent-w03')
sys.path.insert(0, str(ROOT / 'platform'))
from fde_product.models import CompatibleModel, ModelError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--request-timeout', type=float, required=True)
    parser.add_argument('--retry-timeout', type=float, required=True)
    args = parser.parse_args()
    if not 0 < args.request_timeout <= args.retry_timeout <= 3600:
        raise ValueError('TIMEOUT_POLICY_INVALID')
    # Only this child process is changed, not the user's shell or .env files.
    os.environ['FDE_MODEL_TIMEOUT'] = str(args.request_timeout)
    model = CompatibleModel(max_tokens=32768, retry_max_tokens=65536,
                            timeout=args.request_timeout, retry_timeout=args.retry_timeout)
    print(json.dumps({'build_request_policy': model.policy_config()}, ensure_ascii=False), flush=True)
    from fde_product.metrics.builder import generate
    result = generate(args.config, args.output, selected=None, model=model)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    return 2 if result.get('status') == 'error' else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ModelError as exc:
        print(json.dumps({'status': 'error', 'code': exc.code}), flush=True)
        raise SystemExit(2)
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'error', 'code': str(exc)}, ensure_ascii=False), flush=True)
        raise SystemExit(2)
