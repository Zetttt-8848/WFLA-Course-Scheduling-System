"""SQLite immutable dataset snapshots and version-bound solver jobs."""
import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager


class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS datasets(id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, dataset_id INTEGER NOT NULL REFERENCES datasets(id), state TEXT NOT NULL, result TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=30);db.row_factory=sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db;db.commit()
        finally: db.close()

    def save(self,data):
        with self.connect() as db:
            return db.execute("INSERT INTO datasets(title,body) VALUES (?,?)",(data["config"]["title"],json.dumps(data,ensure_ascii=False))).lastrowid

    def get(self,identifier):
        with self.connect() as db:
            row=db.execute("SELECT * FROM datasets WHERE id=?",(identifier,)).fetchone()
        return json.loads(row["body"]) if row else None

    def list_datasets(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,title,created FROM datasets ORDER BY id DESC LIMIT 100")]

    def new_run(self,dataset_id):
        with self.connect() as db:
            return db.execute("INSERT INTO runs(dataset_id,state) VALUES (?,'RUNNING')",(dataset_id,)).lastrowid

    def finish(self,run_id,result):
        with self.connect() as db:
            db.execute("UPDATE runs SET state=?,result=? WHERE id=?",(result["status"],json.dumps(result,ensure_ascii=False),run_id))

    def run(self,identifier):
        with self.connect() as db: row=db.execute("SELECT * FROM runs WHERE id=?",(identifier,)).fetchone()
        if not row: return None
        value=dict(row);value["result"]=json.loads(value["result"]) if value["result"] else None;return value

    def list_runs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,dataset_id,state,created FROM runs ORDER BY id DESC LIMIT 30")]


def worker(database,run_id,dataset_id,seconds):
    store=Store(database)
    try:
        from .solver import solve
        result=solve(store.get(dataset_id),seconds)
    except Exception:
        import traceback
        Path(database).parent.joinpath(f"run-{run_id}-error.log").write_text(traceback.format_exc(),encoding="utf-8")
        result={"status":"ERROR","message":f"求解进程出错，详情保存在本机run-{run_id}-error.log；未修改原数据或旧结果。"}
    store.finish(run_id,result)
