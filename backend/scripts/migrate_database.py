"""Validate an offline migration by default; --apply performs the file switch."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app.migrations import migrate, rollback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',default=settings().data_dir)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--offline',action='store_true',help='Confirm all services and writers are stopped')
    parser.add_argument('--embedding-model',help='Verified model that produced ALL legacy vectors')
    parser.add_argument('--dimensions',type=int,default=768)
    parser.add_argument('--rollback',metavar='BACKUP_DIRECTORY')
    args = parser.parse_args()
    try:
        if args.rollback:
            result = rollback(args.data_dir,args.rollback,offline=args.offline)
        else:
            result = migrate(args.data_dir,apply=args.apply,offline=args.offline,embedding_model=args.embedding_model,dimensions=args.dimensions)
    except (ValueError,RuntimeError,sqlite3.Error) as exc:
        parser.exit(1,str(exc)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
