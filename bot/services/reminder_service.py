# bot/services/reminder_service.py
import asyncio
import logging
from typing import List, Dict, Any
from datetime import datetime, date, timedelta
from bot.db.database import get_conn
from bot.utils import compute_deadline_for_requirement, business_days_between
import pytz

# timezone for app
TIMEZONE = pytz.timezone("Asia/Bangkok")
CHUNK_SIZE = 15

# thresholds (configurable)
THRESHOLDS = {
    "monthly": 3,
    "quarterly": 3,
    "default": 10
}

logger = logging.getLogger(__name__)


# --- Helper: convert a deadline date to midnight next day (tz-aware) ---
def _deadline_to_midnight_next_day(deadline_date: date) -> datetime:
    """
    Return timezone-aware datetime representing midnight of the day AFTER deadline_date
    (i.e. deadline is valid up to but not including this datetime).
    Using midnight next day simplifies "still valid during deadline day" semantics.
    """
    return datetime(deadline_date.year, deadline_date.month, deadline_date.day, 0, 0, 0, tzinfo=TIMEZONE) + timedelta(days=1)


# --- Helper: run DB read in thread and return structured payloads to send ---
def _gather_reminder_payloads(db_path: str, ref_date: date = None) -> List[Dict[str, Any]]:
    """
    Return a list of payloads per team:
      [
         {
           "team_id": int,
           "chat_id": int,
           "team_name": str,
           "items": [
               {"requirement_id": rid, "company_tax": cid, "company_name": name,
                "form_code": form_code, "period_str": period_str, "deadline": dl_date (date), "days_left": int, "owner_id": owner_telegram_id}
           ]
         }, ...
      ]
    This function performs DB reads synchronously (but will normally be called with asyncio.to_thread).
    """
    if ref_date is None:
        ref_date = datetime.now(TIMEZONE).date()

    conn = get_conn(db_path)
    try:
        cur = conn.cursor()
        # get teams with chat id
        cur.execute("SELECT id, group_chat_id, name FROM teams WHERE group_chat_id IS NOT NULL")
        teams = cur.fetchall()
        payloads = []
        # load holidays if exists
        try:
            cur.execute("SELECT date FROM holidays")
            rows = cur.fetchall()
            holidays = [datetime.strptime(r[0], "%Y-%m-%d").date() for r in rows]
        except Exception:
            holidays = []

        for t in teams:
            team_id, chat_id, team_name = t
            # get companies in team
            cur.execute("SELECT company_tax_id, company_name, owner_telegram_id FROM companies WHERE team_id = ?", (team_id,))
            comps = cur.fetchall()
            if not comps:
                continue
            company_ids = [c[0] for c in comps]
            placeholders = ",".join(["?"] * len(company_ids))
            # fetch requirements for these companies
            cur.execute(f"SELECT id, company_tax_id, form_code, period FROM requirements WHERE company_tax_id IN ({placeholders})", company_ids)
            reqs = cur.fetchall()
            items = []
            for rid, cid, form_code, freq in reqs:
                if not freq:
                    continue
                # domain-level: compute deadline (date) and period_str
                try:
                    deadline, period_str = compute_deadline_for_requirement(freq, ref_date)
                except Exception as e:
                    # skip if compute failed for a requirement
                    logger.exception("compute_deadline_for_requirement failed for requirement %s: %s", rid, e)
                    continue
                if not deadline:
                    continue
                # business days left (exclusive start, inclusive end)
                days_left = business_days_between(ref_date - timedelta(days=1), deadline, holidays)
                # threshold: configurable mapping with default fallback
                thr = THRESHOLDS.get(freq.lower(), THRESHOLDS["default"]) if isinstance(freq, str) else THRESHOLDS["default"]
                if days_left <= thr and days_left >= 0:
                    # check submission exists
                    cur2 = conn.cursor()
                    cur2.execute("SELECT 1 FROM submissions WHERE company_tax_id=? AND form_code=? AND ky_thue=? LIMIT 1", (cid, form_code, period_str))
                    if cur2.fetchone():
                        continue
                    # load company owner info (try to use earlier fetched comps if possible)
                    cur2.execute("SELECT company_name, owner_telegram_id FROM companies WHERE company_tax_id = ?", (cid,))
                    cr = cur2.fetchone()
                    comp_name = cr[0] if cr and cr[0] else cid
                    owner_id = cr[1] if cr and len(cr) > 1 else None
                    items.append({
                        "requirement_id": rid,
                        "company_tax": cid,
                        "company_name": comp_name,
                        "form_code": form_code,
                        "period_str": period_str,
                        "deadline": deadline,
                        "days_left": days_left,
                        "owner_id": owner_id
                    })
            if items:
                payloads.append({"team_id": team_id, "chat_id": chat_id, "team_name": team_name, "items": items})
        return payloads
    finally:
        conn.close()


# --- helper to insert reminders_sent record (run in thread) ---
def _insert_reminder_sent(db_path: str, requirement_id: int, remind_for_date: str, mode: str, note: str = None):
    """
    Insert a reminders_sent record. sent_at uses sqlite's datetime('now') (UTC).
    """
    conn = get_conn(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO reminders_sent(requirement_id, remind_for_date, mode, sent_at, note) VALUES (?, ?, ?, datetime('now'), ?)",
            (requirement_id, remind_for_date, mode, note)
        )
        conn.commit()
    finally:
        conn.close()


async def send_daily_reminders(app, db_path: str):
    """
    Async wrapper to gather payloads in thread, then send messages (awaiting bot API),
    and insert reminders_sent after successful send.
    """
    ref_date = datetime.now(TIMEZONE).date()
    payloads = await asyncio.to_thread(_gather_reminder_payloads, db_path, ref_date)
    bot = app.bot

    for p in payloads:
        chat_id = p.get("chat_id")
        team_name = p.get("team_name")
        items = p.get("items", [])

        # separate owner-specific and group items
        group_items_no_owner = []  # list of tuples (rid, line, deadline_iso)
        owner_map = {}  # owner_id -> list of tuples (rid, line, deadline_iso)

        for it in items:
            line = f"• {it['company_name']} ({it['company_tax']}) — {it['form_code']} — kỳ {it['period_str']} — hạn {it['deadline'].isoformat()} — còn {it['days_left']} ngày làm việc"
            if it.get("owner_id"):
                owner_map.setdefault(it["owner_id"], []).append((it["requirement_id"], line, it["deadline"].isoformat()))
            else:
                group_items_no_owner.append((it["requirement_id"], line, it["deadline"].isoformat()))

        # send owner-specific messages (each owner gets one message)
        for owner_id, owner_items in owner_map.items():
            lines = [f"🔔 Nhắc nộp (tự động) — {ref_date.isoformat()}"]
            for _, text_line, dl in owner_items:
                lines.append(text_line)
            msg_text = "\n".join(lines)
            try:
                if owner_id and chat_id:
                    await bot.send_message(chat_id=chat_id, text=f"<a href=\"tg://user?id={owner_id}\">Người phụ trách</a>\n{msg_text}", parse_mode="HTML")
                else:
                    if chat_id:
                        await bot.send_message(chat_id=chat_id, text=msg_text)
                # on success: insert reminders_sent records for each rid (do insert in thread)
                for rid, _, dl in owner_items:
                    await asyncio.to_thread(_insert_reminder_sent, db_path, rid, dl, "initial", "daily initial")
            except Exception as e:
                logger.exception("[send_daily_reminders] failed to send owner message for owner %s: %s", owner_id, e)
                # continue with other messages
                continue

        # then send group-level messages (chunking)
        if group_items_no_owner:
            header = f"🔔 Danh sách tờ khai sắp đến hạn ({ref_date.isoformat()}) cho nhóm: {team_name}"
            lines = [header] + [t for (_, t, _) in group_items_no_owner]
            # chunk lines into CHUNK_SIZE
            for i in range(0, len(lines), CHUNK_SIZE):
                chunk = lines[i:i+CHUNK_SIZE]
                try:
                    await bot.send_message(chat_id=chat_id, text="\n".join(chunk))
                except Exception as e:
                    logger.exception("[send_daily_reminders] failed group chunk send: %s", e)
                    continue
            # insert reminders_sent for group-level items
            for rid, _, dl in group_items_no_owner:
                await asyncio.to_thread(_insert_reminder_sent, db_path, rid, dl, "initial", "daily initial")


async def send_hourly_reminders(app, db_path: str):
    """
    Hourly check: find items with deadline within the next 24 hours and send urgent reminders.
    NOTE: deadline is treated as valid THROUGH the deadline date; we compute midnight next day for comparisons.
    """
    now = datetime.now(TIMEZONE)
    ref_date = now.date()
    payloads = await asyncio.to_thread(_gather_reminder_payloads, db_path, ref_date)
    bot = app.bot

    for p in payloads:
        chat_id = p.get("chat_id")
        items = p.get("items", [])
        for it in items:
            deadline_date = it["deadline"]  # a date object
            # midnight next day (tz-aware) — represents EXCLUSIVE end of deadline day
            dl_dt_end = _deadline_to_midnight_next_day(deadline_date)
            hours_left = (dl_dt_end - now).total_seconds() / 3600.0

            # send urgent reminders if deadline is within next 24 hours (including any time during the deadline day)
            if 0 <= hours_left <= 24:
                rid = it["requirement_id"]

                # check last hourly sent to avoid spamming (read DB)
                def _last_hourly_sent(db_path_local, requirement_id, remind_date):
                    conn = get_conn(db_path_local)
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT sent_at FROM reminders_sent WHERE requirement_id=? AND remind_for_date=? AND mode='hourly' ORDER BY sent_at DESC LIMIT 1",
                            (requirement_id, remind_date)
                        )
                        r = cur.fetchone()
                        return r[0] if r else None
                    finally:
                        conn.close()

                last_sent = await asyncio.to_thread(_last_hourly_sent, db_path, rid, deadline_date.isoformat())
                send_allowed = False
                if not last_sent:
                    send_allowed = True
                else:
                    try:
                        # SQLite datetime('now') returns UTC string like 'YYYY-MM-DD HH:MM:SS'
                        # parse as UTC then convert to TIMEZONE for correct difference calculation
                        last_dt_utc = datetime.strptime(last_sent, "%Y-%m-%d %H:%M:%S")
                        # attach UTC tzinfo then convert
                        last_dt_utc = last_dt_utc.replace(tzinfo=pytz.UTC)
                        last_dt_local = last_dt_utc.astimezone(TIMEZONE)
                        if (now - last_dt_local).total_seconds() >= 3600:
                            send_allowed = True
                    except Exception:
                        # if parse fails, allow sending to avoid silence
                        logger.exception("[send_hourly_reminders] failed to parse last_sent '%s' for requirement %s", last_sent, rid)
                        send_allowed = True

                if not send_allowed:
                    continue

                approx_hours = max(0, int(hours_left))
                text = f"⏰ [Nhắc gấp] {it['company_name']} ({it['company_tax']}) — {it['form_code']} — kỳ {it['period_str']} — hạn {deadline_date.isoformat()} (~{approx_hours} giờ còn lại). Vui lòng nộp ngay!"
                try:
                    owner_id = it.get("owner_id")
                    if owner_id and chat_id:
                        await bot.send_message(chat_id=chat_id, text=f"<a href=\"tg://user?id={owner_id}\">Người phụ trách</a>\n{text}", parse_mode="HTML")
                    else:
                        if chat_id:
                            await bot.send_message(chat_id=chat_id, text=text)
                    # record sent
                    await asyncio.to_thread(_insert_reminder_sent, db_path, rid, deadline_date.isoformat(), "hourly", "hourly reminder")
                except Exception as e:
                    logger.exception("[send_hourly_reminders] failed send for requirement %s: %s", rid, e)
                    continue
