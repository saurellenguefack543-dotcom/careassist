"""Planificateur in-process (APScheduler). Désactivable (SCHEDULER_ENABLED=0) au profit du cron :
    * * * * *  cd /app && python -m app.cli send-reminders
    0 3 * * *  cd /app && python -m app.cli backup
    45 3 * * * cd /app && python -m app.cli purge
Plusieurs workers : le job d'envoi est idempotent (réclamation atomique), mais n'activez le planificateur que sur UN
processus pour éviter le travail en double (ou utilisez le cron).
"""
from __future__ import annotations

import logging

from . import config

log = logging.getLogger("careassist.scheduler")
_sched = None


def _dispatch():
    from .notifications import dispatch_due
    stats = dispatch_due()
    if stats["due"]:
        log.info("notifications : %s", stats)


def _backup():
    from .backup import run_backup
    log.info("sauvegarde : %s", run_backup())


def _retention():
    from .retention import purge
    log.info("rétention : %s", purge())


def _plans_and_listings():
    from .plans import process_trials
    from .directory import process_listings
    t = process_trials()
    l = process_listings()
    if t["expired"] or t["reminded"] or l["published"]:
        log.info("essais/annuaire : %s %s", t, l)


def _slots():
    from . import booking, db
    for p in db.list_practices():
        booking.generate_slots(p["id"])


def start():
    global _sched
    if _sched or config.env("SCHEDULER_ENABLED", "1").lower() in ("0", "false", "no"):
        return None
    from apscheduler.schedulers.background import BackgroundScheduler
    _sched = BackgroundScheduler(timezone="UTC")
    _sched.add_job(_dispatch, "interval", seconds=int(config.env("REMINDER_INTERVAL_S", "60")), id="notifications",
                   max_instances=1, coalesce=True)
    hour = int(config.env("BACKUP_HOUR_UTC", "2"))
    _sched.add_job(_backup, "cron", hour=hour, minute=0, id="backup", max_instances=1, coalesce=True)
    _sched.add_job(_slots, "cron", hour=hour, minute=30, id="slots", max_instances=1, coalesce=True)
    _sched.add_job(_retention, "cron", hour=hour, minute=45, id="retention", max_instances=1, coalesce=True)
    _sched.add_job(_plans_and_listings, "interval", hours=1, id="plans", max_instances=1, coalesce=True)
    _sched.start()
    log.info("planificateur démarré (rappels toutes les %ss, sauvegarde %02d:00 UTC)", config.env("REMINDER_INTERVAL_S", "60"), hour)
    return _sched


def stop():
    global _sched
    if _sched:
        _sched.shutdown(wait=False)
        _sched = None
