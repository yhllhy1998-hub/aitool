import sqlite3

db = r"C:\Users\Administrator\.codex\logs_2.sqlite"
con = sqlite3.connect(db)
cur = con.cursor()
terms = ["pip", "requirements.txt", "python -m pip", "venv", "install -r", "dependency"]
for term in terms:
    rows = cur.execute(
        "select id, level, target, substr(coalesce(feedback_log_body,''),1,300) from logs where lower(coalesce(feedback_log_body,'')) like ? order by id desc limit 10",
        (f"%{term.lower()}%",),
    ).fetchall()
    print(f"\n=== {term} ({len(rows)}) ===")
    for row in rows:
        print(row)
