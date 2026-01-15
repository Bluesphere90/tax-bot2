#!/bin/bash
# =============================================================================
# PostgreSQL Backup Script for Tax Bot (with Telegram notification)
# =============================================================================
# This script creates timestamped backups, maintains a retention policy,
# and sends the backup file to Telegram.
# =============================================================================

# Configuration
DB_NAME="taxbot_db"
DB_USER="taxbot"
DB_PASSWORD="taxbot123"
DB_HOST="localhost"
DB_PORT="5432"

# Telegram settings (load from config.env)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_DIR/config/config.env"

# Load config
if [ -f "$CONFIG_FILE" ]; then
    export $(grep -v '^#' "$CONFIG_FILE" | xargs)
fi

BOT_TOKEN="${BOT_TOKEN}"
OWNER_ID="${OWNER_IDS}"

# Backup settings
BACKUP_DIR="$PROJECT_DIR/backups"
RETENTION_DAYS=30  # Keep backups for 30 days (since backup happens every 2 weeks)
DATE_FORMAT=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/taxbot_backup_${DATE_FORMAT}.sql.gz"
LOG_FILE="${BACKUP_DIR}/backup.log"

# =============================================================================
# Functions
# =============================================================================

log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

send_telegram_message() {
    local message="$1"
    if [ -n "$BOT_TOKEN" ] && [ -n "$OWNER_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d "chat_id=${OWNER_ID}" \
            -d "text=${message}" \
            -d "parse_mode=HTML" > /dev/null 2>&1
    fi
}

send_telegram_file() {
    local file="$1"
    local caption="$2"
    if [ -n "$BOT_TOKEN" ] && [ -n "$OWNER_ID" ] && [ -f "$file" ]; then
        curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendDocument" \
            -F "chat_id=${OWNER_ID}" \
            -F "document=@${file}" \
            -F "caption=${caption}" \
            -F "parse_mode=HTML" > /dev/null 2>&1
        return $?
    fi
    return 1
}

# =============================================================================
# Main Script
# =============================================================================

# Create backup directory if not exists
mkdir -p "$BACKUP_DIR"

log_message "Starting PostgreSQL backup..."

# Export password for pg_dump
export PGPASSWORD="$DB_PASSWORD"

# Create backup with compression
if pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" | gzip > "$BACKUP_FILE"; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log_message "✅ Backup successful: $BACKUP_FILE ($BACKUP_SIZE)"
    
    # Send backup file to Telegram
    log_message "Sending backup to Telegram..."
    CAPTION="🗄️ <b>Tax Bot Backup</b>
📅 $(date '+%Y-%m-%d %H:%M:%S')
📦 Size: $BACKUP_SIZE
🗃️ Database: $DB_NAME"
    
    if send_telegram_file "$BACKUP_FILE" "$CAPTION"; then
        log_message "✅ Backup file sent to Telegram"
    else
        log_message "⚠️ Failed to send backup to Telegram"
        send_telegram_message "⚠️ Backup created but failed to send file. Check server!"
    fi
else
    log_message "❌ Backup FAILED!"
    send_telegram_message "❌ <b>Tax Bot Backup FAILED!</b>
📅 $(date '+%Y-%m-%d %H:%M:%S')
Please check the server immediately!"
    exit 1
fi

# Clean up old backups (older than RETENTION_DAYS)
log_message "Cleaning up backups older than $RETENTION_DAYS days..."
DELETED_COUNT=$(find "$BACKUP_DIR" -name "taxbot_backup_*.sql.gz" -type f -mtime +$RETENTION_DAYS -delete -print | wc -l)
log_message "Deleted $DELETED_COUNT old backup(s)"

# Show current backups
TOTAL_BACKUPS=$(find "$BACKUP_DIR" -name "taxbot_backup_*.sql.gz" -type f | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
log_message "Current backups: $TOTAL_BACKUPS files, Total size: $TOTAL_SIZE"

log_message "Backup process completed."
echo ""
