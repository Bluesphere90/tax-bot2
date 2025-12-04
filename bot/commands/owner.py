# bot/commands/owner.py
import os
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, Application
from bot.db.database import get_conn
from typing import List

def get_owner_ids():
    raw = os.getenv("OWNER_IDS", "")
    if not raw:
        return set()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    out = set()
    for p in parts:
        try:
            out.add(int(p))
        except ValueError:
            pass
    return out

def is_owner(user_id: int) -> bool:
    return user_id in get_owner_ids()

def _create_team(conn, chat_id: int, name: str):
    cur = conn.cursor()
    # upsert by group_chat_id
    cur.execute(
        "INSERT INTO teams(group_chat_id, name) VALUES (%s, %s) ON CONFLICT (group_chat_id) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        (chat_id, name),
    )
    row = cur.fetchone()
    if row:
        team_id = row[0]
    else:
        # fallback select
        cur.execute("SELECT id FROM teams WHERE group_chat_id = %s", (chat_id,))
        team_id = cur.fetchone()[0]
    conn.commit()
    return team_id

def _delete_team_by_chatid(conn, chat_id: int):
    cur = conn.cursor()
    cur.execute("DELETE FROM teams WHERE group_chat_id = %s", (chat_id,))
    conn.commit()

def _list_teams(conn):
    cur = conn.cursor()
    cur.execute("SELECT id, group_chat_id, name FROM teams")
    return cur.fetchall()

async def register_team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text(f"Chỉ chủ sở hữu bot mới có thể thực hiện lệnh này!")
        return

    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Vui lòng chạy lệnh này trong group muốn đăng ký.")
        return

    conn = get_conn()
    try:
        _create_team(conn, chat.id, chat.title or "Unnamed group")
        await update.message.reply_text(f"Team đã được đăng ký: {chat.title}. Vui lòng thêm người dùng để bắt đầu sử dụng dịch vụ.")
    finally:
        conn.close()

async def remove_team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("Chỉ Owner mới có thể thực hiện lệnh này.")
        return
    chat = update.effective_chat
    conn = get_conn()
    try:
        _delete_team_by_chatid(conn, chat.id)
        await update.message.reply_text("Team đã được xóa.")
    finally:
        conn.close()

async def list_all_teams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("Chỉ Owner mới xem được.")
        return
    conn = get_conn()
    try:
        rows = _list_teams(conn)
        if not rows:
            await update.message.reply_text("Chưa có team nào.")
            return
        lines = [f"{r[0]} — chat_id={r[1]} — name={r[2]}" for r in rows]
        await update.message.reply_text("\n".join(lines))
    finally:
        conn.close()

async def assign_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("Chỉ Owner mới có quyền gán công ty.")
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Cú pháp: /assign_company <MST> <team_chat_id>")
        return
    tax = args[0].strip()
    team_chat_id = args[1].strip()
    try:
        team_chat_id_int = int(team_chat_id)
    except ValueError:
        await update.message.reply_text("team_chat_id phải là số (chat id của group).")
        return

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM teams WHERE group_chat_id = %s", (team_chat_id_int,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Không tìm thấy team tương ứng với chat id này.")
            return
        team_id = t[0]
        cur.execute("INSERT INTO companies(company_tax_id, company_name, team_id) VALUES (%s, %s, %s) ON CONFLICT (company_tax_id) DO UPDATE SET team_id = EXCLUDED.team_id", (tax, tax, team_id))
        cur.execute("UPDATE companies SET team_id = %s WHERE company_tax_id = %s", (team_id, tax))
        conn.commit()
        await update.message.reply_text(f"Đã gán MST {tax} vào team {team_chat_id_int}.")
    finally:
        conn.close()

from bot.services.reminder_service import send_daily_reminders

async def test_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("Bạn không phải Owner.")
        return

    # run reminder immediately
    await send_daily_reminders(context.application)

    await update.message.reply_text("Đã chạy send_daily_reminders() xong.")

def register_owner_handlers(app: Application):
    app.add_handler(CommandHandler("register_team", register_team))
    app.add_handler(CommandHandler("remove_team", remove_team))
    app.add_handler(CommandHandler("list_all_teams", list_all_teams))
    app.add_handler(CommandHandler("assign_company", assign_company))
    app.add_handler(CommandHandler("test_daily", test_daily))
