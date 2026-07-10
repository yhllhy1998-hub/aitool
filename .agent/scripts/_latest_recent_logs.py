import sqlite3
from datetime import datetime

def ts_to_local(ts):
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

db = r"C:\Users\Administrator\.codex\logs_2.sqlite"
con = sqlite3.connect(db)
cur = con.cursor()
rows = cur.execute('''
select id, ts, level, target, substr(coalesce(feedback_log_body,''),1,1200)
from logs
where ts >= strftime('%s','now','-15 minutes')
order by id desc
limit 180
''').fetchall()
for row in rows:
    print(f"ID={row[0]} TIME={ts_to_local(row[1])} LEVEL={row[2]} TARGET={row[3]}")
    print(row[4])
    print('---')
