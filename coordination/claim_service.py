"""Run the Mac claim broker and request a public status refresh after queue changes."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile

from coordination.github_claims import poll


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(config_path, state_path, receipt_path):
    config = json.loads(config_path.read_text())
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    results = poll(config, state, lambda: atomic_json(state_path, state))
    if any(result['status'] != 'pending' for result in results):
        state['sync_pending'] = True
    atomic_json(state_path, state)
    publication = 'not_needed'
    if state.get('sync_pending'):
        command = config['publisher']
        if not isinstance(command, list) or not command or any(not isinstance(part, str) for part in command):
            raise ValueError('Invalid private publisher command')
        try:
            completed = subprocess.run(command, timeout=300, capture_output=True)
            if completed.returncode == 0:
                state['sync_pending'] = False
                publication = 'refreshed'
            else:
                publication = 'retry_pending'
        except (subprocess.SubprocessError, OSError):
            publication = 'retry_pending'
        atomic_json(state_path, state)
    receipt = dict(status='CHECKED', checked_at=datetime.now(timezone.utc).isoformat(),
                   requests=results, publication=publication)
    atomic_json(receipt_path, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    with args.state.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another claim broker owns the lock')
            return
        print(json.dumps(run(args.config, args.state, args.receipt)))


if __name__ == '__main__':
    main()
