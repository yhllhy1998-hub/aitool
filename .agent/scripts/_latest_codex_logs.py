import sqlite3
from datetime import datetime


def ts_to_local(ts):
    try:
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(ts)

db = r"C:\Users\Administrator\.codex\logs_2.sqlite"
con = sqlite3.connect(db)
cur = con.cursor()
query = '''
select id, ts, level, target, substr(coalesce(feedback_log_body,''),1,700)
from logs
where target not like 'codex_api::sse::responses%'
  and target not like 'codex_client::transport%'
  and target not like 'codex_core::stream_events_utils%'
  and target not like 'feedback_tags%'
order by id desc
limit 200
'''
rows = cur.execute(query).fetchall()
for row in rows[:120]:
    print(f"ID={row[0]} TIME={ts_to_local(row[1])} LEVEL={row[2]} TARGET={row[3]}")
    print(row[4])
    print('---')
