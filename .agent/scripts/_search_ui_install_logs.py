import sqlite3
from datetime import datetime

terms = ['dependency', 'dependencies', 'installDependencies', 'workspaceDependency', 'workspace dependencies', 'local environment', 'setup script', 'rpc.method', 'install']

def ts_to_local(ts):
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

db = r"C:\Users\Administrator\.codex\logs_2.sqlite"
con = sqlite3.connect(db)
cur = con.cursor()
for term in terms:
    print(f"\n=== TERM: {term} ===")
    rows = cur.execute('''
        select id, ts, level, target, substr(coalesce(feedback_log_body,''),1,1000)
        from logs
        where lower(coalesce(feedback_log_body,'')) like ?
          and target not like 'codex_api::sse::responses%'
          and target not like 'codex_client::transport%'
          and target not like 'codex_core::stream_events_utils%'
          and target not like 'feedback_tags%'
          and target not like 'codex_core::spawn%'
        order by id desc
        limit 20
    ''', (f'%{term.lower()}%',)).fetchall()
    for row in rows:
        print(f"ID={row[0]} TIME={ts_to_local(row[1])} LEVEL={row[2]} TARGET={row[3]}")
        print(row[4])
        print('---')
