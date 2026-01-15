#!/bin/bash
# =============================================================================
# PostgreSQL Restore Script for Tax Bot
# =============================================================================
# Usage: ./restore_postgres.sh [backup_file.sql.gz]
# If no file specified, shows available backups and prompts for selection.
# =============================================================================

# Configuration
DB_NAME="taxbot_db"
DB_USER="taxbot"
DB_PASSWORD="taxbot123"
DB_HOST="localhost"
DB_PORT="5432"
BACKUP_DIR="/home/tran-ninh/OtherProjects/tax-bot2/backups"

# =============================================================================
# Functions
# =============================================================================

log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

list_backups() {
    echo ""
    echo "Available backups:"
    echo "=================="
    ls -lh "$BACKUP_DIR"/taxbot_backup_*.sql.gz 2>/dev/null | awk '{print NR". "$NF" ("$5")"}'
    echo ""
}

# =============================================================================
# Main Script
# =============================================================================

BACKUP_FILE="$1"

# If no file specified, list available backups
if [ -z "$BACKUP_FILE" ]; then
    list_backups
    
    # Get list of backup files
    BACKUP_FILES=($(ls -t "$BACKUP_DIR"/taxbot_backup_*.sql.gz 2>/dev/null))
    
    if [ ${#BACKUP_FILES[@]} -eq 0 ]; then
        echo "No backup files found in $BACKUP_DIR"
        exit 1
    fi
    
    echo "Enter the number of backup to restore (or 'q' to quit):"
    read -r SELECTION
    
    if [ "$SELECTION" = "q" ]; then
        echo "Cancelled."
        exit 0
    fi
    
    # Validate selection
    if ! [[ "$SELECTION" =~ ^[0-9]+$ ]] || [ "$SELECTION" -lt 1 ] || [ "$SELECTION" -gt ${#BACKUP_FILES[@]} ]; then
        echo "Invalid selection."
        exit 1
    fi
    
    BACKUP_FILE="${BACKUP_FILES[$((SELECTION-1))]}"
fi

# Check if file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo "Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo ""
echo "⚠️  WARNING: This will REPLACE ALL DATA in database '$DB_NAME'!"
echo "Backup file: $BACKUP_FILE"
echo ""
echo "Are you sure you want to continue? (yes/no)"
read -r CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Cancelled."
    exit 0
fi

log_message "Starting database restore..."

# Export password
export PGPASSWORD="$DB_PASSWORD"

# Drop and recreate database
log_message "Dropping existing database..."
psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -c "DROP DATABASE IF EXISTS $DB_NAME;"
psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

# Restore from backup
log_message "Restoring from backup..."
if gunzip -c "$BACKUP_FILE" | psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" > /dev/null 2>&1; then
    log_message "✅ Restore successful!"
else
    log_message "❌ Restore FAILED!"
    exit 1
fi

log_message "Restore process completed."
