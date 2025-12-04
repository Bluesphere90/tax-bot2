import os
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder
from pathlib import Path
import asyncio

from bot.db.database import get_conn, ensure_tables
from bot.commands.owner import register_owner_handlers
from bot.commands.admin import register_admin_handlers
from bot.commands.public import register_public_handlers
from bot.jobs.scheduler import setup_schedulers
from bot.services.reminder_service import send_daily_reminders

BASE_DIR = Path(__file__).resolve().parent.parent

def start_bot():
    env_path = BASE_DIR / "config" / "config.env"
    load_dotenv(env_path)

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN not set in config/config.env")

    db_path = os.getenv("DB_PATH", str(BASE_DIR / "data" / "bot.db"))
    # ensure data dir exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = get_conn(db_path)
    ensure_tables(conn)
    conn.close()

    app = ApplicationBuilder().token(token).build()

    # register command handlers
    register_owner_handlers(app)
    register_admin_handlers(app)
    register_public_handlers(app)

    # scheduler (daily/hourly)
    setup_schedulers(app, db_path)

    print("Bot started.")
    app.run_polling()

