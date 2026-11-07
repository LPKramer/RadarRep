"""Municípios do Tocantins, como estão no banco do Radar (com as formas do nome usadas para achá-los no texto)."""
import json


def carregar(con) -> list[dict]:
    """Municípios do banco, do maior para o menor."""
    linhas = con.execute("SELECT * FROM municipios ORDER BY populacao DESC").fetchall()
    return [{**dict(l), "variantes": json.loads(l["variantes"])} for l in linhas]
