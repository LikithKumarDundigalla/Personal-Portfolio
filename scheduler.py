"""
Background scheduler:
  - Refreshes stock prices daily at configured hour
  - Sends loan payment reminder on configured day of month
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import db
import assets as asset_mod
import notifier

_scheduler: BackgroundScheduler | None = None


def _job_refresh_prices():
    print("[Scheduler] Refreshing asset prices...")
    results = asset_mod.refresh_all_prices()
    print(f"[Scheduler] Updated {len(results)} assets.")


def _job_loan_reminder():
    print("[Scheduler] Sending loan reminders...")
    loans = db.get_all_loans()
    active = [l for l in loans if l["remaining_balance"] > 0]
    if not active:
        return
    sender   = db.get_setting("email_sender")
    password = db.get_setting("email_password")
    receiver = db.get_setting("email_receiver")
    notifier.send_loan_reminder(active, sender, password, receiver)


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    hour   = int(db.get_setting("price_update_hour",   "18"))
    minute = int(db.get_setting("price_update_minute", "0"))
    day    = int(db.get_setting("reminder_day",        "1"))

    _scheduler = BackgroundScheduler()

    # Daily price refresh
    _scheduler.add_job(
        _job_refresh_prices,
        CronTrigger(hour=hour, minute=minute),
        id="price_refresh",
        replace_existing=True,
    )

    # Monthly loan reminder
    _scheduler.add_job(
        _job_loan_reminder,
        CronTrigger(day=day, hour=9, minute=0),
        id="loan_reminder",
        replace_existing=True,
    )

    _scheduler.start()
    print(f"[Scheduler] Started — prices at {hour:02d}:{minute:02d}, reminders on day {day}.")


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()