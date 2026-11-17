"""Acesso ao banco SQLite."""
from __future__ import annotations

import sqlite3
from decimal import Decimal
import threading
from contextlib import contextmanager
from pathlib import Path

from . import config

# valores monetários são gravados pelo texto do Decimal (centavos exatos)
sqlite3.register_adapter(Decimal, str)

_lock = threading.RLock()
_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def connect(path: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or config.DB_PATH), check_same_thread=False, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    return con


MIGRACOES = {"itens_nota": [("cst_ibscbs", "TEXT"), ("cclasstrib", "TEXT")],
             "arquivos_sped": [("regime", "TEXT")], "notas_fiscais": [("crt_emit", "TEXT")],
             "creditos_identificados": [("num_item", "TEXT")],
             "analises": [("desatualizada", "INTEGER DEFAULT 0")]}


def init(path: Path | None = None) -> None:
    with connect(path) as con:
        for tabela, colunas in MIGRACOES.items():  # bancos criados por versões anteriores
            existentes = {r[1] for r in con.execute(f"PRAGMA table_info({tabela})")}
            if existentes:
                for nome, tipo in colunas:
                    if nome not in existentes:
                        con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")
        con.executescript(_SCHEMA)


@contextmanager
def tx(path: Path | None = None):
    """Transação serializada: o programa é de um usuário só, então um lock simples basta."""
    with _lock:
        con = connect(path)
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def rows(con: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, params).fetchall()]
