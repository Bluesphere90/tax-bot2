# scripts/migrate_sqlite_to_postgres.py
import os
from sqlalchemy import create_engine, MetaData, Table, select
from sqlalchemy.orm import sessionmaker

# sửa đường dẫn sqlite nếu cần
SQLITE_PATH = os.getenv("SQLITE_PATH", "data/bot.db")  # hoặc ./data/db.sqlite
SQLITE_URL = f"sqlite:///{SQLITE_PATH}"
POSTGRES_URL = "postgresql://postgres:MBWooLQpIlocMRuzfPmzldLERklEzCYQ@switchyard.proxy.rlwy.net:27601/railway"

if not POSTGRES_URL:
    raise SystemExit("Set DATABASE_URL environment variable before running this script")

print("SRC:", SQLITE_URL)
print("DST:", POSTGRES_URL)

src_engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
dst_engine = create_engine(POSTGRES_URL)

src_meta = MetaData()
src_meta.reflect(bind=src_engine)

dst_meta = MetaData()
dst_meta.reflect(bind=dst_engine)

tables_to_copy = [
    "teams", "companies", "forms", "holidays",
    "requirements", "submissions", "reminders_sent"
]

SrcSession = sessionmaker(bind=src_engine)
DstSession = sessionmaker(bind=dst_engine)

src = SrcSession()
dst = DstSession()

try:
    for name in tables_to_copy:
        if name not in src_meta.tables:
            print("Skip (no table):", name)
            continue
        if name not in dst_meta.tables:
            print("Skip (target missing):", name)
            continue

        src_table = src_meta.tables[name]
        dst_table = dst_meta.tables[name]

        rows = src.execute(select(src_table)).mappings().all()
        print(f"Copy {len(rows)} rows → {name}")
        if not rows:
            continue

        # optional: clear destination first (uncomment if you want)
        # dst.execute(dst_table.delete())
        # dst.commit()

        # insert in batches
        batch = []
        for r in rows:
            row = dict(r)
            # convert date-like strings for remind_for_date -> keep as-is; Postgres will coerce if format ok
            batch.append(row)
            if len(batch) >= 200:
                dst.execute(dst_table.insert(), batch)
                dst.commit()
                batch = []
        if batch:
            dst.execute(dst_table.insert(), batch)
            dst.commit()

    print("Migration finished.")
except Exception as e:
    print("Error:", e)
    dst.rollback()
    raise
finally:
    src.close()
    dst.close()
