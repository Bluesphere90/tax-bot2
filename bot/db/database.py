import os
import psycopg2
from pathlib import Path
from typing import Optional



def get_conn(DATABASE_URL: Optional[str]=None):
    if DATABASE_URL is None:
        DATABASE_URL = os.getenv("DATABASE_URL")

    conn = psycopg2.connect(DATABASE_URL)
    # conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn

def ensure_tables(conn):
    cur = conn.cursor()
    # teams: id, group_chat_id, name
    cur.execute("""
    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_chat_id INTEGER UNIQUE,
        name TEXT
    );
    """)
    # companies: company_tax_id unique, name, team_id
    cur.execute("""
    CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_tax_id TEXT UNIQUE,
        company_name TEXT,
        team_id INTEGER,
        status TEXT DEFAULT 'active',
        FOREIGN KEY(team_id) REFERENCES teams(id)
    );
    """)
    # submissions (simple)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_tax_id TEXT,
        form_code TEXT,
        ky_thue TEXT,
        raw TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    """)
    # requirements (for reminders)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS requirements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_tax_id TEXT,
        form_code TEXT,
        period TEXT
    );
    """)
    # reminders_sent (simple)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reminders_sent (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER,
        requirement_id INTEGER,
        remind_for_date TEXT,
        mode TEXT,
        sent_at TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
