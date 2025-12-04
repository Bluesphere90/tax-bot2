import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_conn(DATABASE_URL: str | None = None):
    if DATABASE_URL is None:
        DATABASE_URL = os.getenv("DATABASE_URL")

    # Kết nối PostgreSQL
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def ensure_tables(conn):
    cur = conn.cursor()

    # ==========================
    # TẠO BẢNG THEO SCHEMA CỦA BẠN
    # (đã convert từ SQLite -> Postgre kiểu an toàn)
    # ==========================

    # teams
    cur.execute("""
    CREATE TABLE IF NOT EXISTS teams (
        id SERIAL PRIMARY KEY,
        group_chat_id BIGINT UNIQUE,
        name TEXT
    );
    """)

    # companies
    cur.execute("""
    CREATE TABLE IF NOT EXISTS companies (
        id SERIAL PRIMARY KEY,
        company_tax_id TEXT UNIQUE,
        company_name TEXT,
        team_id INTEGER REFERENCES teams(id),
        owner_username TEXT,
        owner_telegram_id TEXT,
        status TEXT DEFAULT 'active'
    );
    """)

    # forms
    cur.execute("""
    CREATE TABLE IF NOT EXISTS forms (
        form_code TEXT PRIMARY KEY,
        display_name TEXT
    );
    """)

    # holidays
    cur.execute("""
    CREATE TABLE IF NOT EXISTS holidays (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        note TEXT
    );
    """)

    # requirements
    cur.execute("""
    CREATE TABLE IF NOT EXISTS requirements (
        id SERIAL PRIMARY KEY,
        company_tax_id TEXT NOT NULL REFERENCES companies(company_tax_id),
        form_code TEXT NOT NULL REFERENCES forms(form_code),
        period TEXT,
        UNIQUE(company_tax_id, form_code, period)
    );
    """)

    # submissions
    cur.execute("""
    CREATE TABLE IF NOT EXISTS submissions (
        id SERIAL PRIMARY KEY,
        company_tax_id TEXT REFERENCES companies(company_tax_id),
        company_name TEXT,
        form_code TEXT,
        form_raw TEXT,
        ky_thue TEXT,
        lan_nop TEXT,
        loai_to_khai TEXT,
        ma_tb TEXT,
        so_thong_bao TEXT,
        ngay_thong_bao TEXT,
        ma_giaodich TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)

    # reminders_sent
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reminders_sent (
        id SERIAL PRIMARY KEY,
        team_id INTEGER REFERENCES teams(id),
        requirement_id INTEGER REFERENCES requirements(id),
        remind_for_date DATE NOT NULL,
        mode TEXT NOT NULL,
        sent_at TIMESTAMP DEFAULT NOW(),
        message_id TEXT,
        chat_id BIGINT,
        note TEXT
    );
    """)

    conn.commit()
    cur.close()
