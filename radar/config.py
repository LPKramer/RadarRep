"""Onde ficam os dados que o painel lê: o banco (radar.db) e as pastas de imagens, gerados pela coleta do Radar.

Padrão: a pasta data/ ao lado do código; sem banco nela, a pasta demo/, com as notícias de demonstração que vêm no
repositório. Outra pasta: RADAR_DADOS (ou --dados); outro banco: RADAR_DB (ou --banco).
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DEMO = RAIZ / "demo"
_PADRAO = RAIZ / "data" if (RAIZ / "data" / "radar.db").exists() else DEMO
DATA_DIR = Path(os.getenv("RADAR_DADOS") or _PADRAO)
DB_PATH = Path(os.getenv("RADAR_DB") or DATA_DIR / "radar.db")
RAW_DIR = DATA_DIR / "raw"  # cópias brutas da coleta: o endereço da imagem de stories antigos
