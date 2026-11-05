"""Offline SQLite + files archive. Stop API and Worker before use."""
import argparse, hashlib, json, sqlite3, tarfile, tempfile
from contextlib import closing
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists(): raise SystemExit('Refusing to overwrite a backup')
    if not (args.data/'innograd.db').is_file(): raise SystemExit('Database not found')
    with tempfile.TemporaryDirectory() as tmp:
        db=Path(tmp)/'innograd.db'
        with closing(sqlite3.connect(f'file:{(args.data/"innograd.db").as_posix()}?mode=ro',uri=True)) as source:
            with closing(sqlite3.connect(db)) as target: source.backup(target)
        files=list((args.data/'files').rglob('*')) if (args.data/'files').exists() else []
        manifest={'database_sha256':hashlib.sha256(db.read_bytes()).hexdigest(),'files':{}}
        with tarfile.open(args.output,'w:gz') as archive:
            archive.add(db,arcname='innograd.db')
            for f in files:
                if f.is_file():
                    name=f.relative_to(args.data).as_posix()
                    archive.add(f,arcname=name)
                    manifest['files'][name]=hashlib.sha256(f.read_bytes()).hexdigest()
            p=Path(tmp)/'backup-manifest.json'; p.write_text(json.dumps(manifest,indent=2),encoding='utf8')
            archive.add(p,arcname=p.name)
    print('Backup written:',args.output)

if __name__=='__main__': main()
