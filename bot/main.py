# main.py (or run.py entrypoint)
import os
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder
from pathlib import Path

from bot.db.database import get_conn, ensure_tables
from bot.commands.owner import register_owner_handlers
from bot.commands.admin import register_admin_handlers
from bot.commands.public import register_public_handlers
from bot.jobs.scheduler import setup_schedulers

BASE_DIR = Path(__file__).resolve().parent

def start_bot():
    # load .env from config if exists (keep backward compatible)
    env_path = BASE_DIR / "config" / "config.env"
    if env_path.exists():
        load_dotenv(env_path)

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN not set in environment")

    # Ensure DATABASE_URL exists
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set in environment")

    # create tables (connects to Postgres)
    conn = get_conn()
    try:
        ensure_tables(conn)
    finally:
        conn.close()

    app = ApplicationBuilder().token(token).build()

    # register command handlers
    register_owner_handlers(app)
    register_admin_handlers(app)
    register_public_handlers(app)

    # scheduler (daily/hourly)
    setup_schedulers(app)

    print("Bot started.")
    app.run_polling()

if __name__ == "__main__":
    start_bot()
