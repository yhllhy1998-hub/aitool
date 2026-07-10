import sqlite3
from datetime import datetime

terms = [
    'website_probe',
    'website_probe_workbench',
    '127.0.0.1:8766',
    '127.0.0.1:8765',
    '127.0.0.1:7897',
    '/backend-api/ps/',
    '/backend-api/codex/',
    'tls handshake',
    'unexpected eof',
    '451 Unavailable',
]

def ts_to_local(ts):
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

db = r"C:\Users\Administrator\.codex\logs_2.sqlite"
con = sqlite3.connect(db)
cur = con.cursor()
for term in terms:
    print(f"\n=== TERM: {term} ===")
    rows = cur.execute('''
        select id, ts, level, target, substr(coalesce(feedback_log_body,''),1,1400)
        from logs
        where ts >= strftime('%s','now','-20 minutes')
          and lower(coalesce(feedback_log_body,'')) like ?
        order by id desc
        limit 20
    ''', (f'%{term.lower()}%',)).fetchall()
    for row in rows:
        print(f"ID={row[0]} TIME={ts_to_local(row[1])} LEVEL={row[2]} TARGET={row[3]}")
        print(row[4])
        print('---')
