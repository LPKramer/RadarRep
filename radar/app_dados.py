"""Mapa dos municípios do Tocantins em SVG, a partir da malha do IBGE."""
import json
import math
from pathlib import Path

# Malha municipal do IBGE (API de malhas v3, qualidade mínima): ~5 mil pontos.
MALHA = Path(__file__).resolve().parent / "dados" / "malha_to.geojson"
LARGURA_MAPA = 200


def _aneis(geometria: dict) -> list:
    if geometria["type"] == "Polygon":
        return geometria["coordinates"]
    return [anel for poligono in geometria["coordinates"] for anel in poligono]


def mapa(caminho: Path = MALHA, largura: int = LARGURA_MAPA) -> dict:
    """Projeta a malha num plano (equirretangular corrigida pela latitude média, norte para cima) e devolve um
    path SVG por código IBGE."""
    feicoes = json.loads(Path(caminho).read_text(encoding="utf-8"))["features"]
    pontos = [p for f in feicoes for anel in _aneis(f["geometry"]) for p in anel]
    oeste, leste = min(p[0] for p in pontos), max(p[0] for p in pontos)
    sul, norte = min(p[1] for p in pontos), max(p[1] for p in pontos)
    fator = math.cos(math.radians((norte + sul) / 2))
    escala = largura / ((leste - oeste) * fator)

    def path(geometria):
        return "".join("M" + "L".join(f"{(lon - oeste) * fator * escala:.1f},{(norte - lat) * escala:.1f}"
                                      for lon, lat in anel) + "Z" for anel in _aneis(geometria))

    return {"largura": largura, "altura": round((norte - sul) * escala, 1),
            "paths": {int(f["properties"]["codarea"]): path(f["geometry"]) for f in feicoes}}
