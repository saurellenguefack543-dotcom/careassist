"""Commandes d'exploitation (cron-ables).

  python -m app.cli send-reminders          envoie les notifications échues (idempotent)
  python -m app.cli backup [--keep 7]       sauvegarde SQLite + rotation
  python -m app.cli list-backups
  python -m app.cli restore <fichier.db>    restaure (arrêter le serveur avant)
  python -m app.cli seed                    données de démo
  python -m app.cli create-user <practice_id> <email> <nom> <role>   (mot de passe demandé)
  python -m app.cli purge --days 1095       supprime les journaux d'appels/messages plus anciens (rétention RGPD)
"""
from __future__ import annotations

import argparse
import getpass
import json


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("send-reminders")
    b = sub.add_parser("backup")
    b.add_argument("--keep", type=int)
    sub.add_parser("list-backups")
    r = sub.add_parser("restore")
    r.add_argument("file")
    sub.add_parser("seed")
    u = sub.add_parser("create-user")
    u.add_argument("practice_id", type=int)
    u.add_argument("email")
    u.add_argument("name")
    u.add_argument("role", choices=["owner", "practitioner", "secretary"])
    pg = sub.add_parser("purge")
    pg.add_argument("--days", type=int, default=1095)
    sub.add_parser("process-trials")
    sub.add_parser("process-listings")
    a = ap.parse_args(argv)

    from . import db
    db.init_db()
    if a.cmd == "send-reminders":
        from .notifications import dispatch_due
        print(json.dumps(dispatch_due()))
    elif a.cmd == "backup":
        from .backup import run_backup
        print(json.dumps(run_backup(a.keep)))
    elif a.cmd == "list-backups":
        from .backup import list_backups
        for f in list_backups():
            print(f)
    elif a.cmd == "restore":
        from .backup import restore
        print(json.dumps(restore(a.file)))
    elif a.cmd == "seed":
        from .seed import seed
        print(f"{seed()} créneaux ajoutés")
    elif a.cmd == "create-user":
        from .auth import create_user
        pw = getpass.getpass("Mot de passe (10 caractères min.) : ")
        if len(pw) < 10:
            raise SystemExit("mot de passe trop court")
        print(create_user(a.practice_id, a.email, pw, a.name, a.role))
    elif a.cmd == "purge":
        from .retention import purge
        print(json.dumps(purge(a.days)))
    elif a.cmd == "process-trials":
        from .plans import process_trials
        print(json.dumps(process_trials()))
    elif a.cmd == "process-listings":
        from .directory import process_listings
        print(json.dumps(process_listings()))


if __name__ == "__main__":
    main()
