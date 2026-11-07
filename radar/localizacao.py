"""Localização aproximada dos posts e das contas, para o mapa do painel.

Um post fica no município que a IA apontou no fato (menções); sem isso, no da marcação de local do post; depois, no
primeiro município citado no texto, só com inicial maiúscula ("salva de palmas" não vira Palmas); por fim, na cidade
da conta. A conta fica na cidade que a IA ligou a ela; com mais de LOCAL_MAX municípios ela é estadual e fica fora do
mapa. Sem a IA, vale a cidade da bio ou a da busca que achou a conta.
"""
import json
import math
import re
from collections import defaultdict

from unidecode import unidecode

LOCAL_MAX = 3
OURO = math.pi * (3 - math.sqrt(5))  # ângulo de ouro: espalha os pontos de um município sem sobrepor
RE_PALAVRA = re.compile(r"[A-Za-z0-9]+")


# --- Geometria do mapa -----------------------------------------------------------------------

def aneis(d: str) -> list[list[tuple[float, float]]]:
    """Os anéis de um path SVG feito só de M, L e Z (o de app_dados.mapa)."""
    saida = []
    for parte in d.split("M")[1:]:
        pontos = []
        for par in parte.replace("Z", "").split("L"):
            if "," in par:
                x, y = par.split(",")
                pontos.append((float(x), float(y)))
        if len(pontos) >= 3:
            saida.append(pontos)
    return saida


def _area_e_centroide(anel) -> tuple[float, tuple[float, float]]:
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(anel, anel[1:] + anel[:1]):
        f = x0 * y1 - x1 * y0
        area += f
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    if abs(area) < 1e-9:
        return 0.0, (sum(p[0] for p in anel) / len(anel), sum(p[1] for p in anel) / len(anel))
    return abs(area) / 2, (cx / (3 * area), cy / (3 * area))


def dentro(x: float, y: float, anel) -> bool:
    lado = False
    for (x0, y0), (x1, y1) in zip(anel, anel[1:] + anel[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            lado = not lado
    return lado


def _distancia_da_borda(x: float, y: float, anel) -> float:
    menor = math.inf
    for (x0, y0), (x1, y1) in zip(anel, anel[1:] + anel[:1]):
        dx, dy = x1 - x0, y1 - y0
        comprimento = dx * dx + dy * dy
        t = 0.0 if comprimento == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / comprimento))
        menor = min(menor, math.hypot(x - x0 - t * dx, y - y0 - t * dy))
    return menor


def centro(d: str) -> tuple[float, float]:
    """Onde pôr os pontos de um município: o centroide do maior anel; se ele cair fora (município em forma de
    meia-lua), o ponto de dentro mais longe da borda."""
    lista = aneis(d)
    if not lista:
        return 0.0, 0.0
    anel = max(lista, key=lambda a: _area_e_centroide(a)[0])
    cx, cy = _area_e_centroide(anel)[1]
    if not dentro(cx, cy, anel):
        xs, ys = [p[0] for p in anel], [p[1] for p in anel]
        grade = [(min(xs) + (max(xs) - min(xs)) * i / 30, min(ys) + (max(ys) - min(ys)) * j / 30)
                 for i in range(1, 30) for j in range(1, 30)]
        dentro_dele = [p for p in grade if dentro(*p, anel)]
        if dentro_dele:
            cx, cy = max(dentro_dele, key=lambda p: _distancia_da_borda(*p, anel))
    return round(cx, 2), round(cy, 2)


def espalhar(n: int, passo: float) -> list[tuple[float, float]]:
    """Deslocamentos de n pontos em espiral de girassol: o primeiro no centro, os seguintes em volta."""
    return [(passo * math.sqrt(i) * math.cos(i * OURO), passo * math.sqrt(i) * math.sin(i * OURO)) for i in range(n)]


# --- Município no texto ---------------------------------------------------------------------

def localizador(municipios):
    """Função (texto, maiuscula=True) -> código IBGE do primeiro município citado. `municipios` vem de
    municipios.carregar (do maior para o menor: numa forma repetida, fica o município maior)."""
    formas: dict[str, int] = {}
    for m in municipios:
        for v in m["variantes"]:
            if len(v) >= 4:
                formas.setdefault(v, m["ibge_id"])
    maior = max((len(f.split()) for f in formas), default=0)

    def achar(texto: str | None, maiuscula: bool = True) -> int | None:
        if not texto or not maior:
            return None
        palavras = RE_PALAVRA.findall(unidecode(texto))
        minusculas = [p.lower() for p in palavras]
        for i, palavra in enumerate(palavras):
            if maiuscula and not palavra[0].isupper():
                continue
            for n in range(min(maior, len(palavras) - i), 0, -1):  # "porto nacional" antes de "porto"
                ibge_id = formas.get(" ".join(minusculas[i:i + n]))
                if ibge_id:
                    return ibge_id
        return None

    return achar


# --- Posts e contas -------------------------------------------------------------------------

def cidades_das_contas(con, municipios) -> dict[str, int]:
    """username -> código IBGE da cidade da conta. Das que a IA ligou a mais de um município, vale a que também está
    na bio ou na busca que achou a conta (página de cidade pequena costuma citar a vizinha grande); no empate, a maior."""
    populacao = {m["ibge_id"]: m["populacao"] or 0 for m in municipios}
    fontes: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for username, ibge_id, fonte in con.execute(
            "SELECT username, ibge_id, fonte FROM conta_municipio WHERE rede = 'instagram'"):
        fontes[username][fonte].add(ibge_id)
    cidades = {}
    for username, f in fontes.items():
        ia = f.get("ia") or set()
        candidatas = ia or f.get("bio") or f.get("busca") or set()
        if not candidatas or len(candidatas) > LOCAL_MAX:
            continue  # estadual, ou sem cidade conhecida
        preferidas = candidatas & (f.get("bio", set()) | f.get("busca", set())) if ia else set()
        cidades[username] = max(preferidas or candidatas, key=lambda i: populacao.get(i, 0))
    return cidades


def municipios_do_fato(con, ids: list[str] | None = None) -> dict[str, int]:
    """post_id -> o maior município que a IA apontou no fato da menção."""
    sql = ("SELECT mm.post_id, mm.ibge_id FROM mencao_municipio mm JOIN municipios m ON m.ibge_id = mm.ibge_id "
           "WHERE 1 = 1")  # Instagram e sites de notícia
    args: tuple = ()
    if ids is not None:
        sql += " AND mm.post_id IN (SELECT value FROM json_each(?))"
        args = (json.dumps(ids),)
    fato = {}
    for post_id, ibge_id in con.execute(sql + " ORDER BY m.populacao DESC", args):
        fato.setdefault(post_id, ibge_id)
    return fato


def do_post(post_id: str, legenda: str | None, marcacao: str | None, username: str, fato: dict[str, int],
            cidades: dict[str, int], achar) -> tuple[int, str] | None:
    """(código IBGE, de onde veio): 'fato', 'marcacao', 'texto' ou 'conta'. None sem pista nenhuma."""
    if post_id in fato:
        return fato[post_id], "fato"
    if marcacao and (ibge_id := achar(marcacao, maiuscula=False)):
        return ibge_id, "marcacao"
    if ibge_id := achar(legenda):
        return ibge_id, "texto"
    if username in cidades:
        return cidades[username], "conta"
    return None
