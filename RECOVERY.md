# 🔄 Hướng dẫn Phục hồi Dữ liệu (Recovery Guide)

Tài liệu này hướng dẫn cách phục hồi database PostgreSQL khi có sự cố.

---

## 📋 Tổng quan

- **Database:** `taxbot_db`
- **User:** `taxbot`
- **Backup location:** `/home/tran-ninh/OtherProjects/tax-bot2/backups/`
- **Backup schedule:** Mỗi 2 tuần (ngày 1 và 15 hàng tháng, 2:00 AM)
- **Retention:** 30 ngày

---

## 🚨 Các tình huống cần phục hồi

### 1. Lỗi dữ liệu / Xóa nhầm
### 2. Hỏng server / cài lại hệ điều hành
### 3. Chuyển sang máy chủ mới

---

## 🛠️ Phục hồi từ Backup

### Cách 1: Sử dụng Script có sẵn

```bash
cd /home/tran-ninh/OtherProjects/tax-bot2
./scripts/restore_postgres.sh
```

Script sẽ hiển thị danh sách backup và cho bạn chọn file để restore.

### Cách 2: Phục hồi thủ công

```bash
# 1. Set password
export PGPASSWORD="taxbot123"

# 2. Drop database cũ (nếu có)
sudo -u postgres psql -c "DROP DATABASE IF EXISTS taxbot_db;"

# 3. Tạo lại database
sudo -u postgres psql -c "CREATE DATABASE taxbot_db OWNER taxbot;"

# 4. Restore từ file backup
gunzip -c backups/taxbot_backup_YYYYMMDD_HHMMSS.sql.gz | psql -h localhost -U taxbot -d taxbot_db
```

---

## 🖥️ Cài đặt lại trên máy mới

### Bước 1: Cài đặt PostgreSQL

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib -y
```

### Bước 2: Tạo User và Database

```bash
sudo -u postgres psql
```

```sql
CREATE USER taxbot WITH PASSWORD 'taxbot123';
CREATE DATABASE taxbot_db OWNER taxbot;
GRANT ALL PRIVILEGES ON DATABASE taxbot_db TO taxbot;
\c taxbot_db
GRANT ALL ON SCHEMA public TO taxbot;
\q
```

### Bước 3: Clone project

```bash
cd /home/tran-ninh/OtherProjects
git clone https://github.com/YOUR_USERNAME/tax-bot2.git
cd tax-bot2
```

### Bước 4: Cấu hình environment

```bash
cp config/config.env.example config/config.env
# Sửa file config.env với thông tin thực tế
nano config/config.env
```

### Bước 5: Cài đặt dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Bước 6: Restore database từ backup

```bash
# Copy file backup từ Telegram hoặc nơi lưu trữ khác vào thư mục backups/
./scripts/restore_postgres.sh
```

### Bước 7: Chạy bot

```bash
source venv/bin/activate
python app.py
```

---

## 📁 Lấy Backup từ Telegram

Nếu server hỏng hoàn toàn, bạn có thể:

1. Mở Telegram, tìm chat với bot
2. Tìm file backup gần nhất (được gửi tự động mỗi 2 tuần)
3. Download file `.sql.gz`
4. Đặt vào thư mục `backups/` của project
5. Chạy script restore

---

## ⚙️ Cài đặt lại Cron Job

```bash
# Thêm cron job cho backup tự động
(crontab -l 2>/dev/null; echo "0 2 1,15 * * /path/to/tax-bot2/scripts/backup_postgres.sh >> /path/to/tax-bot2/backups/cron.log 2>&1") | crontab -
```

---

## 📞 Liên hệ hỗ trợ

Nếu gặp khó khăn, kiểm tra:
- File log: `backups/backup.log`
- Cron log: `backups/cron.log`

---

*Cập nhật lần cuối: 2026-01-15*
