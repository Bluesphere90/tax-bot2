# bot/jobs/scheduler.py
from telegram.ext import Application
from datetime import time as dtime
import pytz
import asyncio

from bot.services.reminder_service import send_daily_reminders, send_hourly_reminders

TIMEZONE = pytz.timezone("Asia/Bangkok")

def setup_schedulers(app: Application):
    jq = app.job_queue
    if jq is None:
        print("WARNING: JobQueue is not available. Install python-telegram-bot[job-queue] to enable scheduling.")
        return

    async def daily_job(context):
        try:
            await send_daily_reminders(context.application)
        except Exception as e:
            print("Exception in daily_job:", e)

    async def hourly_job(context):
        try:
            await send_hourly_reminders(context.application)
        except Exception as e:
            print("Exception in hourly_job:", e)

    # schedule daily at 08:30 (Asia/Bangkok)
    jq.run_daily(daily_job, time=dtime(hour=8, minute=30, tzinfo=TIMEZONE))

    # schedule hourly repeating every hour
    jq.run_repeating(hourly_job, interval=3600, first=0)

    print("Schedulers set: daily 08:30 (Asia/Bangkok) and hourly repeating every 60 minutes.")
