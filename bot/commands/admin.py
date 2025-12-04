from telegram import Update, MessageEntity
from telegram.ext import ContextTypes, CommandHandler, Application
from bot.db.database import get_conn
from typing import List, Dict

import asyncio
from datetime import datetime

from bot.services.reminder_service import _insert_reminder_sent


async def _is_chat_admin(bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

async def add_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot
    if not await _is_chat_admin(bot, chat.id, user.id):
        await update.message.reply_text("Chỉ admin nhóm mới được thêm công ty.")
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Cú pháp: /add_company <MST> [Tên công ty]")
        return
    tax = args[0]
    name = " ".join(args[1:]) if len(args) > 1 else tax

    conn = get_conn()
    try:
        # find team id
        cur = conn.cursor()
        cur.execute("SELECT id FROM teams WHERE group_chat_id = ?", (chat.id,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Group này chưa được đăng ký làm team. Owner cần /register_team trước.")
            return
        team_id = t[0]
        cur.execute("INSERT OR IGNORE INTO companies(company_tax_id, company_name, team_id) VALUES (?,?,?)", (tax, name, team_id))
        cur.execute("UPDATE companies SET company_name=?, team_id=? WHERE company_tax_id=?", (name, team_id, tax))
        conn.commit()
        await update.message.reply_text(f"Đã thêm/gán công ty {tax} vào team.")
    finally:
        conn.close()

async def remove_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot
    if not _is_chat_admin(bot, chat.id, user.id):
        await update.message.reply_text("Chỉ admin nhóm mới được xoá công ty.")
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Cú pháp: /remove_company <MST>")
        return
    tax = args[0]
    conn = get_conn()
    try:
        cur = conn.cursor()
        # ensure company belongs to this team
        cur.execute("SELECT id FROM teams WHERE group_chat_id = ?", (chat.id,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Group chưa được đăng ký.")
            return
        team_id = t[0]
        cur.execute("DELETE FROM companies WHERE company_tax_id=? AND team_id=?", (tax, team_id))
        conn.commit()
        await update.message.reply_text(f"Đã xoá công ty {tax} khỏi team.")
    finally:
        conn.close()


async def list_companies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot
    if not _is_chat_admin(bot, chat.id, user.id):
        await update.message.reply_text("Chỉ admin nhóm mới được xem danh sách công ty.")
        return

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM teams WHERE group_chat_id = ?", (chat.id,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Group chưa được đăng ký làm team. Owner cần /register_team.")
            return
        team_id = t[0]
        cur.execute("SELECT company_tax_id, company_name, owner_username, owner_telegram_id, status FROM companies WHERE team_id = ? ORDER BY company_tax_id", (team_id,))
        rows = cur.fetchall()
        if not rows:
            await update.message.reply_text("Chưa có công ty nào trong team này.")
            return
        lines = []
        for r in rows:
            mst, name, owner_un, owner_id, status = r
            owner_part = f"{owner_un} (id:{owner_id})" if owner_id else "— chưa gán"
            lines.append(f"{mst} — {name or ''} — owner: {owner_part} — {status}")
        # nếu quá dài, gửi nhiều message
        text = "\n".join(lines)
        if len(text) < 4000:
            await update.message.reply_text(text)
        else:
            # chunk by lines
            chunk = []
            for ln in lines:
                chunk.append(ln)
                if len("\n".join(chunk)) > 3000:
                    await update.message.reply_text("\n".join(chunk))
                    chunk = []
            if chunk:
                await update.message.reply_text("\n".join(chunk))
    finally:
        conn.close()

# ---------- SET OWNER ----------
async def set_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage:
      - Reply to the user's message with: /set_owner <MST>
      - OR send: /set_owner <MST> with a text_mention (choose user from UI)
    """
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot
    if not _is_chat_admin(bot, chat.id, user.id):
        await update.message.reply_text("Chỉ admin nhóm mới được gán người phụ trách.")
        return

    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Cú pháp: /set_owner <MST> (reply to the user's message OR mention user via UI)")
        return
    mst = args[0].strip()

    # Prefer reply_to_message.from_user if present
    target_user = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_user = update.message.reply_to_message.from_user
    else:
        # scan entities for text_mention (contains user obj)
        ents = update.message.entities or []
        for e in ents:
            if e.type == MessageEntity.TEXT_MENTION:
                target_user = e.user
                break
        # NOTE: plain @username (MessageEntity.MENTION) does not contain user object; cannot resolve reliably.

    if not target_user:
        await update.message.reply_text("Không tìm thấy người được chỉ định. Vui lòng REPLY vào tin nhắn của người đó hoặc mention họ bằng cách chọn từ danh sách (text-mention). Plain @username có thể không hoạt động.")
        return

    owner_id = target_user.id
    owner_username = target_user.username or (target_user.full_name if hasattr(target_user, "full_name") else None)

    conn = get_conn()
    try:
        cur = conn.cursor()
        # ensure company exists
        cur.execute("SELECT company_tax_id FROM companies WHERE company_tax_id = ?", (mst,))
        if not cur.fetchone():
            await update.message.reply_text("Không tìm thấy công ty với MST đó trong DB. Hãy thêm công ty trước bằng /add_company hoặc upload XML.")
            return
        # ensure this company belongs to THIS team
        cur.execute("SELECT id FROM teams WHERE group_chat_id = ?", (chat.id,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Group chưa được đăng ký làm team.")
            return
        team_id = t[0]
        cur.execute("SELECT team_id FROM companies WHERE company_tax_id = ?", (mst,))
        row = cur.fetchone()
        if row and row[0] is not None and row[0] != team_id:
            await update.message.reply_text("Công ty này không thuộc team hiện tại. Chỉ admin team chủ quản có thể gán owner.")
            return

        # set owner fields
        cur.execute("UPDATE companies SET owner_telegram_id = ?, owner_username = ? WHERE company_tax_id = ?", (str(owner_id), owner_username, mst))
        conn.commit()
        await update.message.reply_text(f"Đã gán {owner_username} (id:{owner_id}) làm người phụ trách cho {mst}.")
    finally:
        conn.close()

# ---------- CLEAR OWNER ----------
async def clear_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot
    if not _is_chat_admin(bot, chat.id, user.id):
        await update.message.reply_text("Chỉ admin nhóm mới được thực hiện.")
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Cú pháp: /clear_owner <MST>")
        return
    mst = args[0].strip()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM teams WHERE group_chat_id = ?", (chat.id,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Group chưa được đăng ký.")
            return
        team_id = t[0]
        cur.execute("SELECT team_id FROM companies WHERE company_tax_id = ?", (mst,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("Không tìm thấy công ty.")
            return
        if row[0] != team_id:
            await update.message.reply_text("Công ty này không thuộc team hiện tại.")
            return
        cur.execute("UPDATE companies SET owner_telegram_id = NULL, owner_username = NULL WHERE company_tax_id = ?", (mst,))
        conn.commit()
        await update.message.reply_text(f"Đã xoá người phụ trách cho {mst}.")
    finally:
        conn.close()

# (Optional) Edit company name
async def edit_company_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot
    if not _is_chat_admin(bot, chat.id, user.id):
        await update.message.reply_text("Chỉ admin nhóm mới được thực hiện.")
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Cú pháp: /edit_company_name <MST> <tên mới>")
        return
    mst = args[0].strip()
    newname = " ".join(args[1:]).strip()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT team_id FROM companies WHERE company_tax_id = ?", (mst,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("Không tìm thấy công ty.")
            return
        cur.execute("SELECT id FROM teams WHERE group_chat_id = ?", (chat.id,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Group chưa đăng ký.")
            return
        team_id = t[0]
        if row[0] != team_id:
            await update.message.reply_text("Công ty này không thuộc team hiện tại.")
            return
        cur.execute("UPDATE companies SET company_name = ? WHERE company_tax_id = ?", (newname, mst))
        conn.commit()
        await update.message.reply_text(f"Đã cập nhật tên công ty {mst} -> {newname}.")
    finally:
        conn.close()
# --- Utility: ensure form exists in master forms table ---
def _ensure_forms_exist(db_path=None):
    conn = get_conn(db_path)
    try:
        cur = conn.cursor()
        # seed common forms (idempotent)
        common = [
            ("01/GTGT", "Giá trị gia tăng"),
            ("05/KK-TNCN", "Khai khấu trừ TNCN"),
            ("05/QTT-TNCN", "Quyết toán thu nhập cá nhân"),
            ("TT200", "Thông tư 200"),
            ("03/TNDN", "TNDN")
        ]
        for code, name in common:
            cur.execute("INSERT OR IGNORE INTO forms(form_code, display_name) VALUES (?, ?)", (code, name))
        conn.commit()
    finally:
        conn.close()

# --- LIST requirements for team (admin) ---
async def list_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot
    if not await _is_chat_admin(bot, chat.id, user.id):
        await update.message.reply_text("Chỉ admin nhóm mới được xem danh sách yêu cầu.")
        return

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM teams WHERE group_chat_id = ?", (chat.id,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Group chưa được đăng ký làm team.")
            return
        team_id = t[0]
        # join requirements -> companies to filter team
        cur.execute("""
            SELECT r.id, r.company_tax_id, r.form_code, r.period
            FROM requirements r
            JOIN companies c ON c.company_tax_id = r.company_tax_id
            WHERE c.team_id = ?
            ORDER BY r.company_tax_id, r.form_code
        """, (team_id,))
        rows = cur.fetchall()
        if not rows:
            await update.message.reply_text("Chưa có requirement nào trong team này.")
            return
        lines = [f"{r[1]} — {r[2]} — {r[3] or '—'} (req_id={r[0]})" for r in rows]
        text = "\n".join(lines)
        # chunk if long
        if len(text) < 4000:
            await update.message.reply_text(text)
        else:
            chunk = []
            for ln in lines:
                chunk.append(ln)
                if len("\n".join(chunk)) > 3000:
                    await update.message.reply_text("\n".join(chunk))
                    chunk = []
            if chunk:
                await update.message.reply_text("\n".join(chunk))
    finally:
        conn.close()

# --- ADD single requirement (admin) ---
async def add_requirement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage:
      /add_requirement <MST> <FORM_CODE> <period>
    Example:
      /add_requirement 0123456789 01/GTGT monthly
    """
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot
    if not await _is_chat_admin(bot, chat.id, user.id):
        await update.message.reply_text("Chỉ admin nhóm mới được thêm yêu cầu.")
        return

    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Cú pháp: /add_requirement <MST> <FORM_CODE> <period>\nVí dụ: /add_requirement 0123456789 01/GTGT monthly")
        return
    mst = args[0].strip()
    form_code = args[1].strip()
    period = args[2].strip().lower()

    conn = get_conn()
    try:
        cur = conn.cursor()
        # check team
        cur.execute("SELECT id FROM teams WHERE group_chat_id = ?", (chat.id,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Group chưa đăng ký làm team.")
            return
        team_id = t[0]

        # check company belongs to this team
        cur.execute("SELECT team_id FROM companies WHERE company_tax_id = ?", (mst,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("Không tìm thấy công ty trong DB. Thêm công ty trước.")
            return
        if row[0] != team_id:
            await update.message.reply_text("Công ty không thuộc team này. Không được phép thêm.")
            return

        # ensure form exists in forms master
        cur.execute("INSERT OR IGNORE INTO forms(form_code, display_name) VALUES (?, ?)", (form_code, form_code))
        # insert requirement (unique constraint to avoid dup)
        try:
            cur.execute("INSERT INTO requirements(company_tax_id, form_code, period) VALUES (?, ?, ?)", (mst, form_code, period))
            conn.commit()
            await update.message.reply_text(f"Đã thêm requirement: {mst} — {form_code} — {period}")
        except Exception as e:
            await update.message.reply_text("Không thể thêm requirement (có thể đã tồn tại).")
    finally:
        conn.close()

# --- REMOVE requirement (admin) ---
async def remove_requirement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /remove_requirement <MST> <FORM_CODE> [period]
    """
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot
    if not await _is_chat_admin(bot, chat.id, user.id):
        await update.message.reply_text("Chỉ admin nhóm mới được xoá requirement.")
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Cú pháp: /remove_requirement <MST> <FORM_CODE> [period]")
        return
    mst = args[0].strip()
    form_code = args[1].strip()
    period = args[2].strip().lower() if len(args) >= 3 else None

    conn = get_conn()
    try:
        cur = conn.cursor()
        # check team ownership
        cur.execute("SELECT id FROM teams WHERE group_chat_id = ?", (chat.id,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Group chưa đăng ký.")
            return
        team_id = t[0]
        cur.execute("SELECT team_id FROM companies WHERE company_tax_id = ?", (mst,))
        row = cur.fetchone()
        if not row or row[0] != team_id:
            await update.message.reply_text("Công ty không thuộc team này hoặc không tồn tại.")
            return
        if period:
            cur.execute("DELETE FROM requirements WHERE company_tax_id = ? AND form_code = ? AND period = ?", (mst, form_code, period))
        else:
            cur.execute("DELETE FROM requirements WHERE company_tax_id = ? AND form_code = ?", (mst, form_code))
        conn.commit()
        await update.message.reply_text("Đã xoá requirement (nếu tồn tại).")
    finally:
        conn.close()

# --- QUICK ADD: add a set of common forms based on requested period ---
async def quick_add_reqs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Quick add command:
      /quick_add <MST> <monthly|quarterly|yearly>
    Behavior:
      - monthly: add 01/GTGT (monthly), 05/KK-TNCN (monthly), and also add yearly forms 05/QTT-TNCN, TT200, 03/TNDN with period='yearly'
      - quarterly: add 01/GTGT (quarterly), 05/KK-TNCN (quarterly), plus yearly forms
      - yearly: add only yearly forms
    """
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot
    if not await _is_chat_admin(bot, chat.id, user.id):
        await update.message.reply_text("Chỉ admin nhóm mới dùng lệnh này.")
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Cú pháp: /quick_add <MST> <monthly|quarterly|yearly>")
        return
    mst = args[0].strip()
    period = args[1].strip().lower()
    if period not in ("monthly", "quarterly", "yearly"):
        await update.message.reply_text("Period phải là monthly, quarterly hoặc yearly.")
        return

    # ensure master forms exist
    _ensure_forms_exist()

    # build list of (form_code, period_to_set)
    to_add = []
    if period == "monthly":
        to_add += [("01/GTGT", "monthly"), ("05/KK-TNCN", "monthly")]
        # yearly always
        to_add += [("05/QTT-TNCN", "yearly"), ("TT200", "yearly"), ("03/TNDN", "yearly")]
    elif period == "quarterly":
        to_add += [("01/GTGT", "quarterly"), ("05/KK-TNCN", "quarterly")]
        to_add += [("05/QTT-TNCN", "yearly"), ("TT200", "yearly"), ("03/TNDN", "yearly")]
    else:  # yearly
        to_add += [("05/QTT-TNCN", "yearly"), ("TT200", "yearly"), ("03/TNDN", "yearly")]

    conn = get_conn()
    try:
        cur = conn.cursor()
        # check team ownership
        cur.execute("SELECT id FROM teams WHERE group_chat_id = ?", (chat.id,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Group chưa đăng ký.")
            return
        team_id = t[0]
        # check company exists and belongs to this team
        cur.execute("SELECT team_id FROM companies WHERE company_tax_id = ?", (mst,))
        row = cur.fetchone()
        if not row:
            await update.message.reply_text("Không tìm thấy công ty. Thêm công ty trước.")
            return
        if row[0] != team_id:
            await update.message.reply_text("Công ty không thuộc team này.")
            return

        added = []
        skipped = []
        for form_code, p in to_add:
            # ensure in forms master
            cur.execute("INSERT OR IGNORE INTO forms(form_code, display_name) VALUES (?, ?)", (form_code, form_code))
            # check exist
            cur.execute("SELECT 1 FROM requirements WHERE company_tax_id = ? AND form_code = ? AND period = ?", (mst, form_code, p))
            if cur.fetchone():
                skipped.append((form_code, p))
            else:
                cur.execute("INSERT INTO requirements(company_tax_id, form_code, period) VALUES (?, ?, ?)", (mst, form_code, p))
                added.append((form_code, p))
        conn.commit()
        resp_lines = []
        if added:
            resp_lines.append("Đã thêm:")
            resp_lines += [f"• {f} — {p}" for f, p in added]
        if skipped:
            resp_lines.append("Đã bỏ qua (đã tồn tại):")
            resp_lines += [f"• {f} — {p}" for f, p in skipped]
        await update.message.reply_text("\n".join(resp_lines))
    finally:
        conn.close()


# ========================
# Force Remind
# ========================

async def force_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /force_remind
    Admin-only. Force-send reminders for ALL requirements of companies in this team,
    ignoring deadline thresholds. Records entries into reminders_sent with mode='forced'.
    Useful for testing.
    """
    chat = update.effective_chat
    user = update.effective_user
    bot = context.bot

    # check admin
    if not await _is_chat_admin(bot, chat.id, user.id):
        await update.message.reply_text("Chỉ admin nhóm mới được dùng lệnh này.")
        return

    db_path = None  # rely on get_conn default
    conn = get_conn()
    try:
        cur = conn.cursor()
        # find team id
        cur.execute("SELECT id, name FROM teams WHERE group_chat_id = ?", (chat.id,))
        t = cur.fetchone()
        if not t:
            await update.message.reply_text("Group này chưa được đăng ký làm team.")
            return
        team_id, team_name = t

        # fetch companies in team
        cur.execute("SELECT company_tax_id, company_name, owner_telegram_id FROM companies WHERE team_id = ?", (team_id,))
        comps = cur.fetchall()
        if not comps:
            await update.message.reply_text("Team hiện chưa có công ty nào.")
            return
        company_ids = [c[0] for c in comps]
        placeholders = ",".join(["?"]*len(company_ids))

        # fetch requirements for these companies
        cur.execute(f"SELECT id, company_tax_id, form_code, period FROM requirements WHERE company_tax_id IN ({placeholders})", company_ids)
        reqs = cur.fetchall()
        if not reqs:
            await update.message.reply_text("Chưa có requirement nào để gửi reminder (team này).")
            return

        # prepare items grouped by owner
        owner_map: Dict[str, List[tuple]] = {}  # owner_id -> list of (reqid, text, remind_for_date)
        group_items: List[tuple] = []  # list of (reqid, text, remind_for_date)

        for rid, cid, form_code, period in reqs:
            # find company name and owner
            cur.execute("SELECT company_name, owner_telegram_id FROM companies WHERE company_tax_id = ?", (cid,))
            cr = cur.fetchone()
            comp_name = cr[0] if cr and cr[0] else cid
            owner_id = cr[1] if cr and len(cr) > 1 else None
            # build a simple period/deadline text for testing
            # we don't compute deadline here; use period as-is for display
            text = f"• {comp_name} ({cid}) — {form_code} — kỳ {period}"
            remind_for_date = datetime.now().date().isoformat()
            if owner_id:
                owner_map.setdefault(str(owner_id), []).append((rid, text, remind_for_date))
            else:
                group_items.append((rid, text, remind_for_date))

        sent_count = 0

        # send owner-specific messages
        for owner_id, items in owner_map.items():
            lines = [f"🔔 (Thử) Nhắc nộp — {datetime.now().date().isoformat()}"]
            for rid, text, dl in items:
                lines.append(text)
            msg_text = "\n".join(lines)
            try:
                await bot.send_message(chat_id=chat.id, text=f"<a href=\"tg://user?id={owner_id}\">Người phụ trách</a>\n{msg_text}", parse_mode="HTML")
            except Exception:
                # fallback non-tag
                try:
                    await bot.send_message(chat_id=chat.id, text=msg_text)
                except Exception:
                    pass
            # record reminders_sent for each
            for rid, text, dl in items:
                # use asyncio.to_thread to run DB insert in thread
                await asyncio.to_thread(_insert_reminder_sent, None, rid, dl, "forced", "force_remind test")
                sent_count += 1

        # send group items (chunking)
        if group_items:
            # build lines
            lines = [f"🔔 (Thử) Danh sách tờ khai (không owner) — {datetime.now().date().isoformat()}"]
            lines += [t for (_, t, _) in group_items]
            # chunk by CHUNK_SIZE lines (uses CHUNK_SIZE from reminder_service or define here)
            CHUNK = 12
            chunk = []
            for ln in lines:
                chunk.append(ln)
                if len(chunk) >= CHUNK:
                    try:
                        await bot.send_message(chat_id=chat.id, text="\n".join(chunk))
                    except Exception:
                        pass
                    chunk = []
            if chunk:
                try:
                    await bot.send_message(chat_id=chat.id, text="\n".join(chunk))
                except Exception:
                    pass
            for rid, text, dl in group_items:
                await asyncio.to_thread(_insert_reminder_sent, None, rid, dl, "forced", "force_remind test")
                sent_count += 1

        await update.message.reply_text(f"Đã gửi thử {sent_count} thông báo (mode=forced).")
    finally:
        conn.close()

# ========================
# End Force Remind
# ========================

def register_admin_handlers(app: Application):
    app.add_handler(CommandHandler("add_company", add_company))
    app.add_handler(CommandHandler("remove_company", remove_company))
    app.add_handler(CommandHandler("list_companies", list_companies))
    app.add_handler(CommandHandler("set_owner", set_owner))
    app.add_handler(CommandHandler("clear_owner", clear_owner))
    app.add_handler(CommandHandler("edit_company_name", edit_company_name))
    app.add_handler(CommandHandler("list_requirements", list_requirements))
    app.add_handler(CommandHandler("add_requirement", add_requirement))
    app.add_handler(CommandHandler("remove_requirement", remove_requirement))
    app.add_handler(CommandHandler("quick_add", quick_add_reqs))
    app.add_handler(CommandHandler("force_remind", force_remind))
