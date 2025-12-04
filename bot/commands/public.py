import traceback

from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, Application, filters
from bot.db.database import get_conn
from bot.services.xml_parser import parse_submission_from_bytes

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Remind - sẵn sàng.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start /help — upload XML để ghi nhận tờ khai.")

# simple document handler
async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle uploaded XML document with strict team ownership policy (Phương án A):
      - If uploaded in a group that is NOT registered as a team -> reject (do not save).
      - If company exists and company.team_id != current_team_id -> reject (do not save).
      - If company.team_id is NULL -> assign company.team_id = current_team_id and save.
      - If company.team_id == current_team_id -> save normally.
      - Only accept TB with ma_tb == '844' (parser sets accepted flag).
    """
    msg = update.message
    if not msg or not msg.document:
        return

    chat = update.effective_chat
    sender = update.effective_user

    # download file bytes
    try:
        file_obj = await context.bot.get_file(msg.document.file_id)
        b = await file_obj.download_as_bytearray()
        data_bytes = bytes(b)
    except Exception as e:
        await msg.reply_text("Không tải được file. Vui lòng thử lại.")
        print("download error:", e)
        return

    # Ensure this message is in a registered team group
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM teams WHERE group_chat_id = ?", (chat.id if chat else None,))
        trow = cur.fetchone()
        if not trow:
            await msg.reply_text("Group này chưa được đăng ký làm team. Owner cần chạy /register_team trước.")
            return
        team_id = trow[0]
    finally:
        conn.close()

    # load known form codes from DB (optional)
    known_codes = None
    conn = get_conn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT form_code FROM forms")
            rows = cur.fetchall()
            known_codes = [r[0] for r in rows if r and r[0]]
        except Exception:
            known_codes = None
    finally:
        conn.close()

    # parse xml
    try:
        parsed = parse_submission_from_bytes(data_bytes, known_codes=known_codes)
    except Exception as e:
        await msg.reply_text("Lỗi khi parse file XML.")
        print("parse error:", e)
        traceback.print_exc()
        return

    # check accepted flag (ma_tb == '844')
    if not parsed.get("accepted"):
        await msg.reply_text("Tệp thông báo không thuộc mã TB=844 — bỏ qua.")
        return

    # extract fields
    company_tax = parsed.get("company_tax_id")
    company_name = parsed.get("company_name") or parsed.get("address") or company_tax
    form_code = parsed.get("form_code")
    form_raw = parsed.get("form_raw") or parsed.get("tokhai_raw") or ""
    ky_thue = parsed.get("ky_thue")
    lan_nop = parsed.get("lan_nop")
    loai_to_khai = parsed.get("loai_to_khai")
    ma_tb = parsed.get("ma_tb")
    so_thong_bao = parsed.get("so_thong_bao")
    ngay_thong_bao = parsed.get("ngay_thong_bao")
    ma_giaodich = parsed.get("ma_giaodich")

    # sender info
    sender_id = str(sender.id) if sender else None
    sender_username = sender.username if (sender and getattr(sender, "username", None)) else (sender.full_name if sender else None)

    # Enforce team ownership rules (Phương án A)
    conn = get_conn()
    try:
        cur = conn.cursor()
        # check if company exists and its team_id
        cur.execute("SELECT team_id FROM companies WHERE company_tax_id = ?", (company_tax,))
        prow = cur.fetchone()
        if prow:
            existing_team_id = prow[0]
            if existing_team_id is None:
                # company exists but no team assigned -> assign to current team
                cur.execute("UPDATE companies SET team_id = ? WHERE company_tax_id = ?", (team_id, company_tax))
            elif existing_team_id != team_id:
                # company belongs to another team -> reject (do NOT save submission)
                # Optionally inform Owner of that other team? For now, just inform sender.
                await msg.reply_text("Công ty này thuộc quản lý của nhóm khác — bạn không có quyền cập nhật ở đây. Submission không được ghi nhận.")
                return
            # else existing_team_id == team_id: ok to proceed
        else:
            # company does not exist -> insert and assign to this team
            cur.execute("INSERT INTO companies(company_tax_id, company_name, team_id, owner_telegram_id, owner_username) VALUES (?, ?, ?, ?, ?)",
                        (company_tax, company_name, team_id, sender_id, sender_username))

        # If company exists and belongs to this team, optionally update owner to sender (policy: allowed)
        # We allow updating owner only when company belongs to current team
        cur.execute("SELECT team_id FROM companies WHERE company_tax_id = ?", (company_tax,))
        team_check = cur.fetchone()
        if team_check and team_check[0] == team_id:
            # update company_name and owner info (overwrite)
            cur.execute("UPDATE companies SET company_name = ?, owner_telegram_id = ?, owner_username = ? WHERE company_tax_id = ?",
                        (company_name, sender_id, sender_username, company_tax))

        # Save submission
        cur.execute(
            """INSERT INTO submissions(company_tax_id, company_name, form_code, form_raw, ky_thue, lan_nop, loai_to_khai,
                                      ma_tb, so_thong_bao, ngay_thong_bao, ma_giaodich)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_tax, company_name, form_code, form_raw, ky_thue, lan_nop, loai_to_khai, ma_tb, so_thong_bao, ngay_thong_bao, ma_giaodich)
        )
        conn.commit()
        # await msg.reply_text("Đã nhận file và ghi nhận thông tin (team hợp lệ).")

        # Build a friendly, human-like confirmation message with parsed details
        try:
            # parsed variables available in scope:
            # company_tax, company_name, form_code, form_raw, ky_thue, ma_tb, so_thong_bao, ngay_thong_bao, ma_giaodich, team_id, sender_username

            # short safe formatting helper
            def _safe(x):
                return x if (x is not None and str(x).strip() != "") else "—"

            lines = []
            lines.append(f"🙏 Cảm ơn bạn, mình đã nhận được tệp và ghi nhận vào hệ thống.")
            lines.append("")  # blank line

            # summary
            lines.append(f"📌 <b>Tóm tắt thông tin đã đọc</b>:")
            lines.append(f"• MST: {_safe(company_tax)}")
            lines.append(f"• Tên công ty: {_safe(company_name)}")
            lines.append(f"• Mã TB: {_safe(ma_tb)}")
            lines.append(f"• Mã tờ khai (form): {_safe(form_code)}")
            lines.append(f"• Kỳ thuế: {_safe(ky_thue)}")
            lines.append(f"• Lần nộp: {_safe(lan_nop)}")
            lines.append(f"• Loại tờ khai: {_safe(loai_to_khai)}")
            lines.append(f"• Số TB: {_safe(so_thong_bao)} — Ngày TB: {_safe(ngay_thong_bao)}")
            lines.append(f"• Mã giao dịch: {_safe(ma_giaodich)}")
            lines.append("")  # blank line

            # owner / team info
            # team_name may not be in scope; show group id instead if necessary
            try:
                chat_title = msg.chat.title if getattr(msg.chat, "title", None) else f"chat_id={msg.chat.id}"
            except Exception:
                chat_title = f"chat_id={getattr(msg.chat, 'id', 'unknown')}"
            lines.append(f"📂 Đã lưu cho nhóm: <b>{chat_title}</b>")
            lines.append(f"👤 Người gửi (được ghi nhận làm người phụ trách tạm thời): {_safe(sender_username)}")
            lines.append("")  # blank line

            # show snippet of form_raw (safe truncated)
            raw_preview = (form_raw or "")[:800].strip()
            if raw_preview:
                lines.append("📰 <b>Trích đoạn nội dung tờ khai</b> (xem nhanh):")
                lines.append(f"<code>{raw_preview.replace('<', '&lt;').replace('>', '&gt;')}</code>")
                lines.append("")  # blank

            # include link to original file (developer instruction: use local path)
            # file path from conversation history (provided as local path)
            # local_file_path = "/mnt/data/xml_parser.py"
            # file_url = f"file://{local_file_path}"
            # lines.append(f"🔗 Bạn/nhóm có thể kiểm tra file gốc tại: {file_url}")
            # lines.append("")  # blank

            # friendly closing
            lines.append(
                "Nếu có gì sai (ví dụ mã tờ khai không khớp), bạn hãy báo cho Admin hoặc dùng /list_companies để kiểm tra. Chúc bạn một ngày làm việc hiệu quả 😊")

            message_text = "\n".join(lines)

            # send as a nicely formatted HTML message
            await msg.reply_text(message_text, parse_mode="HTML", disable_web_page_preview=True)

            # OPTIONAL: also send the original file as a document back to the chat (commented out)
            # Uncomment if you want the bot to re-upload the XML for easy download/inspection.
            # try:
            #     await context.bot.send_document(chat_id=msg.chat.id, document=open(local_file_path, "rb"),
            #                                     filename="original_upload.xml",
            #                                     caption="File gốc (bản sao lưu) — nếu bạn cần tải về.")
            # except Exception as e:
            #     # ignore file send errors, keep the user-friendly reply
            #     print("Could not send original file:", e)

        except Exception as _m:
            # fallback short message if something in formatting fails
            await msg.reply_text("Đã nhận file và ghi nhận. Cảm ơn bạn! Nếu cần kiểm tra thêm, liên hệ Admin.")
            print("Error composing friendly reply:", _m)

    except Exception as e:
        await msg.reply_text("Có lỗi khi lưu dữ liệu. Kiểm tra logs.")
        print("db save error:", e)
        traceback.print_exc()
    finally:
        conn.close()

def register_public_handlers(app: Application):
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
