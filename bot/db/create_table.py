from database import get_conn, ensure_tables
DATABASE_URL="postgresql://postgres:MBWooLQpIlocMRuzfPmzldLERklEzCYQ@switchyard.proxy.rlwy.net:27601/railway"
conn = get_conn(DATABASE_URL)
ensure_tables(conn)
print("PostgreSQL tables created!")
