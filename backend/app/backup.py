"""Local SQLite+immutable file backup. Restore only to a new isolated directory."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from .db import now


def verify_bundle(bundle):
    bundle=Path(bundle)
    with sqlite3.connect(f"file:{(bundle/'database.sqlite').resolve()}?mode=ro",uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Foreign key check failed')
        files=db.execute('SELECT storage_key, sha256 FROM files').fetchall()
        archives=db.execute('SELECT COUNT(*) FROM archives').fetchone()[0]
    for key,digest in files:
        if Path(key).name!=key: raise ValueError('Invalid storage key')
        path=bundle/'files'/key
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('File missing or integrity mismatch')
    return {'files':len(files),'archives':archives}


def backup(database, file_root, destination):
    database=Path(database);destination=Path(destination)
    if not database.is_file():raise ValueError('Source database does not exist')
    destination.mkdir(parents=True,exist_ok=False,mode=0o700)
    try:
        with sqlite3.connect(f'file:{database.resolve()}?mode=ro',uri=True) as source:
            with sqlite3.connect(destination/'database.sqlite') as target:source.backup(target)
        (destination/'files').mkdir()
        with sqlite3.connect(destination/'database.sqlite') as db:
            keys=[row[0] for row in db.execute('SELECT storage_key FROM files')]
        for key in keys:
            if Path(key).name!=key:raise ValueError('Invalid storage key')
            shutil.copy2(Path(file_root)/key,destination/'files'/key)
        report=verify_bundle(destination)
        (destination/'manifest.json').write_text(json.dumps({'created_at':now(),**report}),encoding='utf-8')
        return report
    except Exception:
        # An incomplete bundle remains clearly marked and cannot be restored as valid.
        (destination/'INCOMPLETE').write_text('Backup failed; do not use',encoding='utf-8')
        raise


def restore(bundle,destination):
    bundle=Path(bundle);destination=Path(destination)
    if (bundle/'INCOMPLETE').exists() or not (bundle/'manifest.json').exists():raise ValueError('Incomplete backup')
    report=verify_bundle(bundle)
    if bundle.resolve() in destination.resolve().parents:raise ValueError('Restore destination cannot be inside backup')
    if destination.exists():raise ValueError('Refusing to overwrite an existing directory')
    shutil.copytree(bundle,destination)
    verify_bundle(destination)
    return report


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='action',required=True)
    save=sub.add_parser('create');save.add_argument('--database',default='runtime/development.db');save.add_argument('--files',default='runtime/files');save.add_argument('--destination',required=True)
    load=sub.add_parser('restore');load.add_argument('--bundle',required=True);load.add_argument('--destination',required=True)
    args=parser.parse_args()
    print(backup(args.database,args.files,args.destination) if args.action=='create' else restore(args.bundle,args.destination))


if __name__=='__main__':main()
