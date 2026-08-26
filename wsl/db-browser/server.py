"""db-browser MCP — SQLite / PostgreSQL 的自然语言查询通道(自研门面)。

工具: sqlite_query / sqlite_schema / pg_query / pg_schema。
安全模式(只读优先):
  - SQLite 默认 write=False → 连接以 URI mode=ro 打开, 引擎级只读,
    任何写语句直接报错(不靠语句解析猜); 要写入必须显式 write=True。
  - PostgreSQL 默认 write=False → 会话级 default_transaction_read_only=on。
PG 连接串: dsn 参数或环境变量 PG_DSN(postgresql://user:pass@host:5432/db)。
"""
import pathlib
import sys

for _p in pathlib.Path(__file__).resolve().parents:
    if (_p / "huamcp.py").exists():
        sys.path.insert(0, str(_p))
        break
import huamcp  # noqa: E402

import json
import os
import sqlite3
from urllib.parse import quote

mcp = huamcp.server(__file__)

MAX_CELL = 500  # 单元格超长截断, 防一次查询撑爆上下文


def _trim(v):
    s = v if isinstance(v, str) else repr(v) if v is not None else None
    if isinstance(s, str) and len(s) > MAX_CELL:
        return s[:MAX_CELL] + f"…(截断,全长{len(s)})"
    return s


def _rows_to_text(cols, rows, max_rows):
    more = len(rows) - max_rows
    if more > 0:
        rows = rows[:max_rows]
    out = json.dumps(
        {"columns": cols, "rows": [{c: _trim(r[i]) for i, c in enumerate(cols)} for r in rows]},
        ensure_ascii=False,
        indent=1,
    )
    if more > 0:
        out += f"\n(已截断: 省略后 {more} 行, 收窄查询或调大 max_rows)"
    return out


def _sqlite_connect(db_path: str, write: bool):
    p = pathlib.Path(db_path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"数据库文件不存在: {p}")
    mode = "rw" if write else "ro"
    con = sqlite3.connect(f"file:{quote(str(p))}?mode={mode}", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


@mcp.tool()
def sqlite_query(db_path: str, sql: str, write: bool = False, max_rows: int = 50) -> str:
    """对本地 SQLite 数据库文件执行 SQL — 查库/修数的通用通道。

    【何时用】检查任意 .db/.sqlite 文件(应用数据、浏览器历史、自己项目的库);
    SELECT/PRAGMA/写入(建表/INSERT/UPDATE)都走这里。

    【参数】db_path 库文件路径(支持 ~); sql 单条语句; write 默认 False =
    引擎级只读连接(mode=ro), 写语句会报 "attempt to write a readonly database",
    这是保护不是故障 — 确认要改库再传 write=True(建议先备份); max_rows 默认 50,
    超出截断, 单元格超 500 字符截断。
    """
    try:
        con = _sqlite_connect(db_path, write)
    except FileNotFoundError as e:
        return str(e)
    try:
        cur = con.execute(sql)
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            return _rows_to_text(cols, [tuple(r) for r in rows], max_rows)
        if write:
            con.commit()
            return f"OK, {cur.rowcount} 行受影响 (write 模式已提交)"
        return f"OK, {cur.rowcount} 行受影响 (未提交: 当前是只读连接, 写入请传 write=True)"
    except sqlite3.Error as e:
        return f"SQLite 错误: {e}"
    finally:
        con.close()


@mcp.tool()
def sqlite_schema(db_path: str, counts: bool = False) -> str:
    """列出 SQLite 库的表结构: 表名 + 建表 SQL(索引另列)。

    【何时用】拿到陌生 .db 先看这个再写查询。counts=True 时逐表 COUNT(*)
    (大库会慢, 默认 False 只列结构)。
    """
    try:
        con = _sqlite_connect(db_path, write=False)
    except FileNotFoundError as e:
        return str(e)
    try:
        objs = con.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table','view','index') ORDER BY type, name"
        ).fetchall()
        out = []
        for typ, name, sql in objs:
            line = f"[{typ}] {name}"
            if typ in ("table", "view"):
                cols = [r[1] for r in con.execute(f"PRAGMA table_info({name})").fetchall()]
                line += f"  列: {', '.join(cols)}"
                if counts and typ == "table":
                    n = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                    line += f"  行数: {n}"
            out.append(line + (f"\n  {sql}" if sql else ""))
        return "\n".join(out) or "(空库)"
    except sqlite3.Error as e:
        return f"SQLite 错误: {e}"
    finally:
        con.close()


def _pg_connect(dsn: str, write: bool):
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("psycopg 未安装 — 在 wsl/db-browser 重装依赖(uv pip install -r requirements.lock)或检查 venv")
    kwargs = {"connect_timeout": 8}
    if not write:
        kwargs["options"] = "-c default_transaction_read_only=on"
    return psycopg.connect(dsn, **kwargs)


@mcp.tool()
def pg_query(sql: str, dsn: str = "", write: bool = False, max_rows: int = 50) -> str:
    """对 PostgreSQL 执行 SQL(只读优先)。

    【何时用】查/改 Postgres 库。dsn 留空时用环境变量 PG_DSN
    (postgresql://user:pass@host:5432/db; 服务端未配 PG_DSN 且不传 dsn 会给指引)。
    write 默认 False = 会话级只读(服务端强制, 写语句报 25P02/25006 类错误),
    要写入显式传 write=True。
    """
    dsn = dsn.strip() or os.environ.get("PG_DSN", "").strip()
    if not dsn:
        return "缺少 DSN: 传 dsn 参数, 或给 pm2 进程设 PG_DSN 环境变量后 restart mcp-db-browser-8111"
    try:
        with _pg_connect(dsn, write) as con:
            cur = con.execute(sql)
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = cur.fetchmany(max_rows + 1)
                text = _rows_to_text(cols, [tuple(r) for r in rows], max_rows)
                return text
            if write:
                con.commit()
            return f"OK, {cur.rowcount} 行受影响 ({'已提交' if write else '只读会话未提交, 写入请传 write=True'})"
    except RuntimeError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001 — psycopg 错误类型多, 统一给 agent 可读信息
        return f"PG 错误: {type(e).__name__}: {e}"


@mcp.tool()
def pg_schema(dsn: str = "") -> str:
    """列出 PostgreSQL 库的表与列(information_schema)。

    【何时用】接陌生 PG 先看这个。dsn 规则同 pg_query(空则用 PG_DSN 环境变量)。
    """
    dsn = dsn.strip() or os.environ.get("PG_DSN", "").strip()
    if not dsn:
        return "缺少 DSN: 传 dsn 参数, 或设 PG_DSN 环境变量"
    try:
        with _pg_connect(dsn, write=False) as con:
            rows = con.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema NOT IN ('pg_catalog','information_schema') "
                "ORDER BY table_name, ordinal_position"
            ).fetchall()
        tables: dict[str, list[str]] = {}
        for t, c, dt in rows:
            tables.setdefault(t, []).append(f"{c}:{dt}")
        return "\n".join(f"{t}  列: {', '.join(cs)}" for t, cs in tables.items()) or "(库里没有用户表)"
    except RuntimeError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        return f"PG 错误: {type(e).__name__}: {e}"


if __name__ == "__main__":
    huamcp.run(mcp)
