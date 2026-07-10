import sqlite3
from datetime import datetime

terms = ['install','dependency','dependencies','local environment','setup script','setup','requirements','pip','venv','workspace dependencies']

def ts_to_local(ts):
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

db = r"C:\Users\Administrator\.codex\logs_2.sqlite"
con = sqlite3.connect(db)
cur = con.cursor()
for term in terms:
    print(f"\n=== TERM: {term} ===")
    rows = cur.execute('''
        select id, ts, level, target, substr(coalesce(feedback_log_body,''),1,1200)
        from logs
        where lower(coalesce(feedback_log_body,'')) like ?
          and target not like 'codex_api::sse::responses%'
          and target not like 'codex_client::transport%'
        order by id desc
        limit 25
    ''', (f'%{term.lower()}%',)).fetchall()
    for row in rows:
        print(f"ID={row[0]} TIME={ts_to_local(row[1])} LEVEL={row[2]} TARGET={row[3]}")
        print(row[4])
        print('---')
