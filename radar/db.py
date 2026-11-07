"""Conexão com o banco do Radar (SQLite). O painel só lê: pode ficar aberto enquanto a coleta grava."""
import sqlite3
from pathlib import Path

from . import config


def conectar_leitura(caminho: Path | str | None = None) -> sqlite3.Connection:
    caminho = Path(caminho or config.DB_PATH).resolve()
    if not caminho.exists():
        raise FileNotFoundError(f"Banco do Radar não encontrado em {caminho}. Use --banco ou RADAR_DB.")
    con = sqlite3.connect(f"{caminho.as_uri()}?mode=ro", uri=True, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 30000")
    return con


# O painel abre o banco ao subir só para conferir que ele existe; aqui nada é criado nem migrado.
conectar = conectar_leitura
