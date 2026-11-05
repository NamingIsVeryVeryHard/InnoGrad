"""Restore a verified backup into an EMPTY data directory."""
import argparse, hashlib, json, tarfile
from pathlib import Path, PurePosixPath

def main():
    p=argparse.ArgumentParser(); p.add_argument('--archive',required=True,type=Path); p.add_argument('--data',required=True,type=Path); a=p.parse_args()
    if a.data.exists() and any(a.data.iterdir()): raise SystemExit('Destination must be empty')
    a.data.mkdir(parents=True,exist_ok=True)
    with tarfile.open(a.archive,'r:gz') as tf:
        members=tf.getmembers()
        if len({m.name for m in members}) != len(members):
            raise SystemExit('Duplicate archive member')
        for m in members:
            name=PurePosixPath(m.name)
            if not m.isfile() or name.is_absolute() or '..' in name.parts or '\\' in m.name:
                raise SystemExit('Unsafe archive member')
            if m.name not in ('innograd.db','backup-manifest.json') and not m.name.startswith('files/'):
                raise SystemExit('Unexpected archive member')
        manifest=json.load(tf.extractfile('backup-manifest.json'))
        expected={'innograd.db':manifest['database_sha256'],**manifest['files']}
        if {m.name for m in members} != set(expected)|{'backup-manifest.json'}:
            raise SystemExit('Manifest membership mismatch')
        for name,digest in expected.items():
            if hashlib.sha256(tf.extractfile(name).read()).hexdigest()!=digest:
                raise SystemExit('Hash mismatch: '+name)
        for name in expected:
            dest=a.data/name; dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(tf.extractfile(name).read())
    print('Verified database and files restored. Configure secrets separately.')

if __name__=='__main__': main()
