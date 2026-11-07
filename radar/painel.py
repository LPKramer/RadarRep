"""Painel do radar no navegador, no estilo dos serviços de streaming: destaque, fileiras de capas, Top 10 e a ficha de
cada post. Mostra só o que tem a ver com a Energisa, direta ou indiretamente: as menções (posts e stories que a IA
ligou à empresa ou ao serviço de energia) e as contas que as publicaram.

Lê o banco direto e só para leitura, então as menções aparecem à medida que a vigilância e a IA as encontram. As capas
ficam em data/capas/ (capas.py); sem capa, o cartão vira um cartaz com o texto do post. `python -m radar painel` abre
http://127.0.0.1:8787.
"""
import json
import math
import re
import socket
import sys
import threading
import unicodedata
import webbrowser
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from unidecode import unidecode

from . import app_dados, capas, config, db, localizacao, monitoramento, relatorio
from . import municipios as mun

WEB = Path(__file__).resolve().parent / "web"
PORTA = 8787
POR_LINHA = 20
POR_PAGINA = 48
CIDADES = 5  # fileiras de cidade na tela inicial: as mais populosas
LOCAL_MAX = localizacao.LOCAL_MAX  # conta ligada a até tantos municípios conta como local na fileira da cidade
AO_VIVO = timedelta(minutes=15)  # visita mais recente que isso: a vigilância está rodando
TIPOS_STATIC = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".ttf": "font/ttf", ".svg": "image/svg+xml",
                ".txt": "text/plain; charset=utf-8", ".png": "image/png"}
TIPOS_MIDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".mp4": "video/mp4"}

# Todo post que o painel mostra passa por aqui, e só entra o que a IA ligou à Energisa (sobre_energia): o que cita a
# empresa (cita_energisa) e o que trata do serviço de energia sem citá-la (falta de luz, poste caído, conta, obra).
# Vem do Instagram (posts e stories) e dos sites de notícia (rede 'web', matérias achadas pelo Google Notícias).
# O resto do que a vigilância coleta (sorteio, política, fofoca) fica no banco, fora da tela.
SQL_POST = """
SELECT p.rede, p.post_id, p.username, p.tipo, p.publicado_em, p.legenda, p.curtidas, p.comentarios,
       p.visualizacoes, p.url, p.capa, p.arquivo, p.local, p.medido_em,
       c.nome, c.seguidores, c.engajamento_medio, k.tipo AS tipo_conta,
       x.post_id IS NOT NULL AS mencao, x.sentimento, x.tema, x.setor, x.alcance, x.resumo, x.cita_energisa,
       COALESCE(p.curtidas, 0) + COALESCE(p.comentarios, 0) AS interacoes
FROM posts p
JOIN mencoes x ON x.rede = p.rede AND x.post_id = p.post_id AND x.sobre_energia = 1
LEFT JOIN contas c ON c.rede = p.rede AND c.username = p.username
LEFT JOIN classificacoes k ON k.rede = p.rede AND k.username = p.username
WHERE p.rede IN ('instagram', 'web')
"""
# As contas que publicaram algo sobre a Energisa, com quantas vezes (e quantas negativas).
SQL_CONTAS_ENERGISA = """
SELECT c.username, c.nome, c.seguidores, k.tipo, COUNT(*) AS mencoes,
       SUM(x.sentimento = 'negativo') AS negativas
FROM posts p
JOIN mencoes x ON x.rede = p.rede AND x.post_id = p.post_id AND x.sobre_energia = 1
JOIN contas c ON c.rede = p.rede AND c.username = p.username
LEFT JOIN classificacoes k ON k.rede = c.rede AND k.username = c.username
WHERE p.rede = 'instagram'
"""
ORDENS = {
    "recentes": "p.publicado_em DESC",
    "interacoes": "interacoes DESC, p.publicado_em DESC",
    "views": "p.visualizacoes IS NULL, p.visualizacoes DESC, interacoes DESC",
}
TIPOS_CONTA = ["portal_noticias", "perfil_fofoca", "influenciador_local", "pagina_cidade_comunidade",
               "policial_plantao", "jornalista_radialista", "orgao_publico", "politico"]

# Fileiras fixas: id -> (título, formato do cartão, filtros, quantos na tela inicial). Tudo já é sobre a Energisa.
LINHAS = {
    "top10": ("Top 10 da semana", "top10", {"dias": 7, "ordem": "interacoes", "sem_stories": 1, "rede": "instagram"},
              10),
    "mencoes": ("Menções à Energisa", "mencao", {"ordem": "recentes"}, POR_LINHA),
    "negativas": ("Negativas", "mencao", {"sentimento": "negativo", "ordem": "recentes"}, POR_LINHA),
    "noticias": ("Notícias de sites", "mencao", {"rede": "web", "ordem": "recentes"}, POR_LINHA),
    "diretas": ("Citam a Energisa", "post", {"cita": 1, "ordem": "recentes"}, POR_LINHA),
    "indiretas": ("Sobre energia elétrica, sem citar a Energisa", "post", {"cita": 0, "ordem": "recentes"},
                  POR_LINHA),
    "stories": ("Stories sobre a Energisa", "story", {"formato": "Story", "ordem": "recentes"}, 40),
    "reels": ("Reels sobre a Energisa", "post", {"formato": "Video", "ordem": "views"}, POR_LINHA),
    "portais": ("Em portais", "post", {"tipo_conta": "portal_noticias", "ordem": "recentes"}, POR_LINHA),
    "paginas": ("Em páginas de cidade", "post", {"tipo_conta": "pagina_cidade_comunidade", "ordem": "recentes"},
                POR_LINHA),
    "fofoca": ("Em perfis de fofoca", "post", {"tipo_conta": "perfil_fofoca", "ordem": "recentes"}, POR_LINHA),
    "influenciadores": ("Com influenciadores", "post", {"tipo_conta": "influenciador", "ordem": "recentes"},
                        POR_LINHA),
    "plantao": ("No plantão policial", "post", {"tipo_conta": "policial_plantao", "ordem": "recentes"}, POR_LINHA),
    "jornalistas": ("Com jornalistas", "post", {"tipo_conta": "jornalista_radialista", "ordem": "recentes"},
                    POR_LINHA),
}
VER_TUDO = {"negativas": "ver/mencoes?sentimento=negativo"}  # fileira cujo "ver tudo" é outra página com filtro
SOBREPOR = {"dias", "sentimento", "ordem"}  # filtros que a página "ver tudo" pode trocar
# Setor da Energisa que teria de responder ou agir (a IA escolhe um de mencoes.SETORES para cada menção).
NOMES_SETOR = {
    "operacao": "Operação", "manutencao": "Manutenção", "atendimento": "Atendimento", "comercial": "Comercial",
    "obras_expansao": "Obras e expansão", "seguranca": "Segurança", "rh": "RH", "institucional": "Institucional",
    "regulatorio_juridico": "Regulatório e jurídico", "nenhum": "Fora da Energisa",
}


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _dias(valor, padrao=None) -> float | None:
    """O filtro de período vindo da página: um número de dias, 'todos' (None) ou nada (o padrão)."""
    if valor in (None, ""):
        return padrao
    if valor == "todos":
        return None
    try:
        dias = float(valor)
    except ValueError:
        return padrao
    return dias if math.isfinite(dias) and dias > 0 else padrao


def _iso(data: datetime) -> str:
    return data.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _data(valor) -> datetime | None:
    if not valor:
        return None
    try:
        data = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return data if data.tzinfo else data.replace(tzinfo=timezone.utc)


# --- Texto ----------------------------------------------------------------------------------

RE_URL = re.compile(r"https?://\S+|www\.\S+")
RE_MARCA = re.compile(r"(?<!\w)[#@][\w.]+")
CATEGORIAS_FORA = {"So", "Sk", "Cf", "Cs", "Co", "Cn"}  # emojis, símbolos soltos e caracteres de controle


def titulo(legenda: str | None, limite: int = 150) -> str:
    """A primeira linha com texto de verdade da legenda, sem emojis, hashtags, @ e links."""
    for linha in (legenda or "").splitlines():
        limpa = RE_MARCA.sub(" ", RE_URL.sub(" ", linha))
        limpa = "".join(ch for ch in limpa if unicodedata.category(ch) not in CATEGORIAS_FORA)
        limpa = re.sub(r"\s+", " ", limpa).strip(" -–—|:•·*_~,;.!")
        if sum(ch.isalpha() for ch in limpa) >= 3:
            return limpa if len(limpa) <= limite else limpa[:limite].rsplit(" ", 1)[0] + "…"
    return ""


def normalizar(texto: str | None) -> str:
    return unidecode(texto).lower() if texto else ""


def _like(termo: str) -> str:
    return "%" + termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# --- Consultas ------------------------------------------------------------------------------

def monitoradas(con) -> list[str]:
    return [c["username"] for c in monitoramento.monitoradas(con)]


def _consulta(filtros: dict, lista_monitoradas: list[str] | None, agora: datetime) -> tuple[str, list]:
    sql, args = [SQL_POST], []
    horas = float(filtros.get("horas") or 0) or float(filtros.get("dias") or 0) * 24
    if horas:
        sql.append("AND p.publicado_em >= ?")
        args.append(_iso(agora - timedelta(hours=horas)))
    if filtros.get("rede"):  # instagram ou web (sites de notícia)
        sql.append("AND p.rede = ?")
        args.append(filtros["rede"])
    if filtros.get("formato"):
        sql.append("AND p.tipo = ?")
        args.append(filtros["formato"])
    elif filtros.get("sem_stories"):  # o Top 10 é de posts: story não mostra curtidas nem comentários
        sql.append("AND COALESCE(p.tipo, '') != 'Story'")
    if filtros.get("cita") is not None:  # 1: cita a Energisa; 0: trata do serviço de energia sem citá-la
        sql.append("AND x.cita_energisa = ?")
        args.append(int(filtros["cita"]))
    if filtros.get("sentimento"):
        sql.append("AND x.sentimento = ?")
        args.append(filtros["sentimento"])
    if filtros.get("setor"):
        sql.append("AND x.setor = ?")
        args.append(filtros["setor"])
    if filtros.get("tipo_conta") == "influenciador":
        sql.append("AND (k.tipo = 'influenciador_local' OR EXISTS (SELECT 1 FROM listas l WHERE l.rede = p.rede "
                   "AND l.username = p.username AND l.lista = 'influenciadores_to'))")
    elif filtros.get("tipo_conta"):
        sql.append("AND k.tipo = ?")
        args.append(filtros["tipo_conta"])
    if filtros.get("cidade"):  # posts das contas locais da cidade
        sql.append("AND p.username IN (SELECT cm.username FROM conta_municipio cm WHERE cm.rede = 'instagram' "
                   "AND cm.fonte = 'ia' AND cm.ibge_id = ? AND (SELECT COUNT(*) FROM conta_municipio c2 "
                   "WHERE c2.rede = cm.rede AND c2.username = cm.username AND c2.fonte = 'ia') <= ?)")
        args += [int(filtros["cidade"]), LOCAL_MAX]
    if filtros.get("municipio"):  # menções que citam o município
        sql.append("AND p.post_id IN (SELECT mm.post_id FROM mencao_municipio mm WHERE mm.rede = p.rede "
                   "AND mm.ibge_id = ?)")
        args.append(int(filtros["municipio"]))
    if filtros.get("conta"):
        sql.append("AND p.username = ?")
        args.append(filtros["conta"])
    if filtros.get("monitoradas") and lista_monitoradas is not None:
        sql.append("AND p.username IN (SELECT value FROM json_each(?))")
        args.append(json.dumps(lista_monitoradas))
    sql.append("ORDER BY " + ORDENS.get(filtros.get("ordem"), ORDENS["recentes"]))
    return " ".join(sql), args


def _item(linha, tem: set[str]) -> dict:
    mencao = None
    if linha["mencao"]:
        mencao = {"sentimento": linha["sentimento"], "tema": linha["tema"], "setor": linha["setor"],
                  "alcance": linha["alcance"], "resumo": linha["resumo"], "citaEnergisa": bool(linha["cita_energisa"])}
    story = linha["tipo"] == "Story"
    return {
        "id": linha["post_id"], "rede": linha["rede"], "conta": linha["username"], "nome": linha["nome"],
        "tipoConta": linha["tipo_conta"],
        "formato": linha["tipo"], "data": linha["publicado_em"],
        "titulo": "" if story else titulo(linha["legenda"]),  # o texto do story é OCR: ruim de exibir
        "curtidas": linha["curtidas"], "comentarios": linha["comentarios"], "views": linha["visualizacoes"],
        "interacoes": linha["interacoes"], "seguidores": linha["seguidores"],
        "capa": (linha["post_id"] in tem or capas.valida(linha["capa"])
                 or (story and capas.imagem_do_story(linha["arquivo"]) is not None)),
        "mencao": mencao, "link": linha["url"],
    }


def posts(con, filtros: dict, limite: int = POR_LINHA, pagina: int = 0, lista_monitoradas=None, agora=None,
          tem: set[str] | None = None) -> tuple[list[dict], bool]:
    """Posts que passam nos filtros, já no formato do cartão. Devolve (itens, há mais)."""
    agora = agora or _agora()
    if filtros.get("monitoradas") and lista_monitoradas is None:
        lista_monitoradas = monitoradas(con)
    tem = capas.existentes("posts") if tem is None else tem
    sql, args = _consulta(filtros, lista_monitoradas, agora)
    linhas = con.execute(sql + " LIMIT ? OFFSET ?", (*args, limite + 1, pagina * limite)).fetchall()
    return [_item(l, tem) for l in linhas[:limite]], len(linhas) > limite


def _municipios_das_mencoes(con, ids: list[str]) -> dict[str, list[str]]:
    nomes: dict[str, list[str]] = {}
    if not ids:
        return nomes
    for post_id, nome in con.execute(
            "SELECT mm.post_id, m.nome FROM mencao_municipio mm JOIN municipios m ON m.ibge_id = mm.ibge_id "
            "WHERE mm.post_id IN (SELECT value FROM json_each(?)) ORDER BY m.populacao DESC",
            (json.dumps(ids),)):
        nomes.setdefault(post_id, []).append(nome)
    return nomes


def destaques(con, agora=None, tem=None, n: int = 5) -> list[dict]:
    """Os itens do destaque no topo: as menções dos últimos 14 dias (negativas e de mais interação primeiro); sem
    elas, as últimas menções."""
    agora = agora or _agora()
    itens, _ = posts(con, {"dias": 14, "ordem": "interacoes"}, 50, agora=agora, tem=tem)
    itens.sort(key=lambda p: (p["mencao"]["sentimento"] != "negativo", -p["interacoes"]))
    if not itens:
        itens, _ = posts(con, {"ordem": "recentes"}, n, agora=agora, tem=tem)
    itens = itens[:n]
    municipios = _municipios_das_mencoes(con, [p["id"] for p in itens if p["mencao"]])
    for p in itens:
        p["municipios"] = municipios.get(p["id"], [])
    return itens


def _cidades(con, n: int = CIDADES) -> list[tuple[int, str]]:
    """Os municípios com mais menções à Energisa (o município do fato, apontado pela IA)."""
    return [(l[0], l[1]) for l in con.execute(
        "SELECT m.ibge_id, m.nome FROM mencao_municipio mm JOIN mencoes x ON x.rede = mm.rede "
        "AND x.post_id = mm.post_id AND x.sobre_energia = 1 JOIN municipios m ON m.ibge_id = mm.ibge_id "
        "GROUP BY m.ibge_id ORDER BY COUNT(*) DESC, m.populacao DESC LIMIT ?", (n,))]


def definicao(con, linha_id: str) -> tuple[str, str, dict] | None:
    """(título, formato, filtros) de uma fileira, inclusive as de cidade, município e conta."""
    if linha_id in LINHAS:
        nome, formato, filtros, _ = LINHAS[linha_id]
        return nome, formato, dict(filtros)
    tipo, _, valor = linha_id.partition("-")
    if tipo in ("cidade", "municipio", "storiescidade") and valor.isdigit():
        linha = con.execute("SELECT nome FROM municipios WHERE ibge_id = ?", (int(valor),)).fetchone()
        if not linha:
            return None
        if tipo == "cidade":  # o que as contas da cidade publicaram sobre a Energisa
            return f"Contas de {linha[0]}", "post", {"cidade": int(valor), "ordem": "recentes"}
        if tipo == "storiescidade":
            return f"Stories · {linha[0]}", "story", {"cidade": int(valor), "formato": "Story"}
        return f"Menções · {linha[0]}", "mencao", {"municipio": int(valor), "ordem": "recentes"}
    if tipo == "setor" and valor in NOMES_SETOR:
        return NOMES_SETOR[valor], "mencao", {"setor": valor, "ordem": "recentes"}
    if tipo == "conta" and capas.RE_USERNAME.match(valor):  # os stories da conta têm fileira própria
        return f"@{valor}", "post", {"conta": valor, "ordem": "recentes", "sem_stories": 1}
    return None


def linha(con, linha_id: str, pagina: int = 0, sobrepor: dict | None = None, limite: int = POR_PAGINA,
          lista_monitoradas=None, agora=None, tem=None) -> dict | None:
    """Uma fileira (ou a página "ver tudo" dela), com os filtros que a página pode trocar."""
    achada = definicao(con, linha_id)
    if achada is None:
        return None
    nome, formato, filtros = achada
    for chave, valor in (sobrepor or {}).items():
        if chave not in SOBREPOR:
            continue
        if chave == "dias":
            dias = None if valor in (None, "", "todos") else _dias(valor)
            if dias is None and valor not in (None, "", "todos"):
                continue  # número inválido: fica o período da fileira
            filtros.pop("horas", None)
            filtros.pop("dias", None)
            if dias:
                filtros["dias"] = dias
        elif chave == "sentimento" and valor not in ("negativo", "neutro", "positivo", ""):
            continue
        elif valor:
            filtros[chave] = valor
        else:
            filtros.pop(chave, None)
    itens, mais = posts(con, filtros, limite, pagina, lista_monitoradas, agora, tem)
    horas = float(filtros.get("horas") or 0) or float(filtros.get("dias") or 0) * 24
    ativos = {"dias": round(horas / 24, 2) if horas else None, "sentimento": filtros.get("sentimento"),
              "ordem": filtros.get("ordem") or "recentes"}
    return {"id": linha_id, "titulo": nome, "formato": formato, "itens": itens, "mais": mais, "filtros": ativos}


def inicio(con, agora=None) -> dict:
    agora = agora or _agora()
    tem = capas.existentes("posts")
    linhas = []
    for linha_id, (nome, formato, filtros, limite) in LINHAS.items():
        itens, _ = posts(con, filtros, limite, agora=agora, tem=tem)
        if linha_id == "top10" and len(itens) < 10:  # semana com poucas menções: o mês, e então tudo
            for dias, outro_nome in ((30, "Top 10 do mês"), (None, "Top 10")):
                sem_periodo = {k: v for k, v in filtros.items() if k != "dias"}
                itens, _ = posts(con, sem_periodo | ({"dias": dias} if dias else {}), limite, agora=agora, tem=tem)
                nome = outro_nome
                if len(itens) >= 10:
                    break
        if itens:
            linhas.append({"id": linha_id, "titulo": nome, "formato": formato, "itens": itens,
                           "verTudo": VER_TUDO.get(linha_id, linha_id != "top10")})
    for ibge_id, nome in _cidades(con):
        itens, _ = posts(con, {"municipio": ibge_id, "ordem": "recentes"}, POR_LINHA, agora=agora, tem=tem)
        if itens:
            linhas.append({"id": f"municipio-{ibge_id}", "titulo": nome, "formato": "mencao", "itens": itens,
                           "verTudo": True, "municipio": ibge_id})
    fotos = capas.existentes("perfis")
    quem_fala = [_cartao_conta(l, fotos) for l in _contas_energisa(con, limite=POR_LINHA)]
    if quem_fala:  # o "ver tudo" abre a página Contas (todas as monitoradas) em ordem de menções
        linhas.append({"id": "contas", "titulo": "Quem mais fala da Energisa", "formato": "conta",
                       "itens": quem_fala, "verTudo": "contas?ordem=mencoes"})
    return {"destaques": destaques(con, agora, tem), "linhas": linhas}


# --- Ficha do post --------------------------------------------------------------------------

def _repercussao(con, post_id: str) -> dict:
    try:
        df = relatorio.carregar(con)
    except Exception:
        return {}
    achada = df[df["post_id"] == post_id]
    if achada.empty:
        return {}
    r = achada.iloc[0]
    return {"repercutiram": int(r["contas_que_repercutiram"]), "coberturaEstadual": r["teve_cobertura_estadual"] == "sim"}


def _arquivo_midia(arquivo: str | None) -> Path | None:
    """O arquivo salvo do story (imagem ou vídeo), só se estiver dentro de data/stories."""
    if not arquivo:
        return None
    caminho = Path(arquivo)
    try:
        caminho.resolve().relative_to(capas.STORIES.resolve())
    except ValueError:
        return None
    return caminho if caminho.suffix.lower() in TIPOS_MIDIA and caminho.exists() else None


def _resumo_conta(con, username: str, rede: str = "instagram") -> dict:
    """A conta (ou o site de notícia, na rede 'web') que publicou o post."""
    linha = con.execute(
        "SELECT c.username, c.nome, c.seguidores, k.tipo, k.abrangencia FROM contas c LEFT JOIN classificacoes k "
        "ON k.rede = c.rede AND k.username = c.username WHERE c.rede = ? AND c.username = ?",
        (rede, username)).fetchone()
    if not linha:
        return {"username": username, "rede": rede}
    arquivo = capas.arquivo_foto(username) if rede == "instagram" else None
    return {"username": linha["username"], "rede": rede, "nome": linha["nome"], "seguidores": linha["seguidores"],
            "tipo": linha["tipo"], "abrangencia": linha["abrangencia"],
            "foto": bool(arquivo and arquivo.exists()),
            "municipios": _municipios_da_conta(con, username) if rede == "instagram" else []}


def _municipios_da_conta(con, username: str) -> list[str]:
    nomes = [l[0] for l in con.execute(
        "SELECT m.nome FROM conta_municipio cm JOIN municipios m ON m.ibge_id = cm.ibge_id WHERE cm.rede = 'instagram' "
        "AND cm.username = ? AND cm.fonte = 'ia' ORDER BY m.populacao DESC", (username,))]
    return nomes or [l[0] for l in con.execute(
        "SELECT DISTINCT m.nome FROM conta_municipio cm JOIN municipios m ON m.ibge_id = cm.ibge_id "
        "WHERE cm.rede = 'instagram' AND cm.username = ? ORDER BY m.populacao DESC", (username,))]


def post(con, post_id: str, agora=None) -> dict | None:
    linha_post = con.execute(SQL_POST + " AND p.post_id = ?", (post_id,)).fetchone()  # só se for da Energisa
    if not linha_post:
        return None
    arquivo = capas.arquivo_post(post_id)
    item = _item(linha_post, {post_id} if arquivo and arquivo.exists() else set())
    item["onde"] = onde_do_post(con, linha_post)
    seguidores, media = linha_post["seguidores"], linha_post["engajamento_medio"]
    item.update({
        "legenda": linha_post["legenda"], "local": linha_post["local"], "medidoEm": linha_post["medido_em"],
        "engajamentoPct": round(100 * linha_post["interacoes"] / seguidores, 2) if seguidores else None,
        "indice": round(linha_post["interacoes"] / media, 2) if media else None,
    })
    if item["mencao"]:
        x = con.execute("SELECT reacao, reacao_resumo, n_comentarios_lidos FROM mencoes WHERE rede = ? "
                        "AND post_id = ?", (linha_post["rede"], post_id)).fetchone()
        item["mencao"].update({"reacao": x["reacao"], "reacaoResumo": x["reacao_resumo"],
                               "comentariosLidos": x["n_comentarios_lidos"],
                               "municipios": _municipios_das_mencoes(con, [post_id]).get(post_id, [])})
        item["mencao"].update(_repercussao(con, post_id))
    item["textosComentarios"] = [{"texto": l[0], "curtidas": l[1]} for l in con.execute(
        "SELECT texto, curtidas FROM comentarios WHERE rede = 'instagram' AND post_id = ? AND texto IS NOT NULL "
        "ORDER BY COALESCE(curtidas, 0) DESC LIMIT 6", (post_id,))]
    midia = _arquivo_midia(linha_post["arquivo"])
    item["midia"] = ({"tipo": "video" if midia.suffix.lower() == ".mp4" else "imagem", "url": f"/midia/{post_id}"}
                     if midia else None)
    item["contaInfo"] = _resumo_conta(con, linha_post["username"], linha_post["rede"])
    mais, _ = posts(con, {"conta": linha_post["username"], "ordem": "recentes"}, 13, agora=agora)
    item["maisDaConta"] = [p for p in mais if p["id"] != post_id][:12]
    return item


# --- Contas e municípios --------------------------------------------------------------------

SQL_CONTA = """
SELECT c.username, c.nome, c.bio, c.seguidores, c.seguindo, c.n_posts, c.verificada, c.categoria, c.url_externa,
       c.posts_30d, c.engajamento_medio, k.tipo, k.abrangencia, s.prioridade, ROUND(s.valor) AS score,
       (SELECT v.ultima_em FROM visitas v WHERE v.rede = c.rede AND v.username = c.username) AS visita
FROM contas c
LEFT JOIN classificacoes k ON k.rede = c.rede AND k.username = c.username
LEFT JOIN score s ON s.rede = c.rede AND s.username = c.username
WHERE c.rede = 'instagram'
"""


def _cartao_conta(linha, fotos: set[str]) -> dict:
    cartao = {"username": linha["username"], "nome": linha["nome"], "tipo": linha["tipo"],
              "seguidores": linha["seguidores"], "foto": linha["username"] in fotos}
    if "mencoes" in linha.keys():
        cartao.update({"mencoes": linha["mencoes"], "negativas": linha["negativas"] or 0})
    return cartao


def _contas_energisa(con, filtro: str = "", args: tuple = (), limite: int = POR_PAGINA, pagina: int = 0) -> list:
    """Contas que publicaram sobre a Energisa (com `filtro` SQL extra), das que mais publicaram para as que menos."""
    return con.execute(SQL_CONTAS_ENERGISA + filtro + " GROUP BY c.username "
                       "ORDER BY mencoes DESC, negativas DESC, c.seguidores DESC LIMIT ? OFFSET ?",
                       (*args, limite, pagina * limite)).fetchall()


# A página Contas (e a busca de contas) traz todas as monitoradas, mais as que publicaram sobre a Energisa sem estar no
# monitoramento, cada uma com quantas menções tem.
SQL_CONTAS_TODAS = """
SELECT c.username, c.nome, c.seguidores, k.tipo, COALESCE(m.mencoes, 0) AS mencoes, COALESCE(m.negativas, 0) AS negativas
FROM contas c
LEFT JOIN classificacoes k ON k.rede = c.rede AND k.username = c.username
LEFT JOIN (SELECT p.username, COUNT(*) AS mencoes, SUM(x.sentimento = 'negativo') AS negativas FROM posts p
           JOIN mencoes x ON x.rede = p.rede AND x.post_id = p.post_id AND x.sobre_energia = 1
           WHERE p.rede = 'instagram' GROUP BY p.username) m ON m.username = c.username
WHERE c.rede = 'instagram' AND (m.username IS NOT NULL OR c.username IN (SELECT value FROM json_each(?)))
"""
ORDENS_CONTAS = {"seguidores": "c.seguidores DESC", "mencoes": "mencoes DESC, negativas DESC, c.seguidores DESC"}


def _filtro_tipo(tipo: str | None) -> tuple[str, tuple]:
    if tipo == "influenciador":
        return (" AND (k.tipo = 'influenciador_local' OR EXISTS (SELECT 1 FROM listas l WHERE l.rede = c.rede "
                "AND l.username = c.username AND l.lista = 'influenciadores_to'))", ())
    return (" AND k.tipo = ?", (tipo,)) if tipo else ("", ())


def lista_contas(con, tipo: str | None = None, pagina: int = 0, limite: int = POR_PAGINA,
                 ordem: str = "seguidores") -> dict:
    """Todas as contas monitoradas (e as que publicaram sobre a Energisa fora do monitoramento), com quantas menções
    cada uma tem: das mais seguidas para as menos, ou das que mais falam da Energisa. Filtro por tipo de conta."""
    ordem = ordem if ordem in ORDENS_CONTAS else "seguidores"
    lista = json.dumps(monitoradas(con))
    filtro, args = _filtro_tipo(tipo)
    linhas = con.execute(SQL_CONTAS_TODAS + filtro + f" ORDER BY {ORDENS_CONTAS[ordem]} LIMIT ? OFFSET ?",
                         (lista, *args, limite + 1, pagina * limite)).fetchall()
    fotos = capas.existentes("perfis")
    presentes = {l["tipo"] for l in con.execute(SQL_CONTAS_TODAS, (lista,))}
    return {"itens": [_cartao_conta(l, fotos) for l in linhas[:limite]], "mais": len(linhas) > limite,
            "tipos": [t for t in TIPOS_CONTA if t in presentes], "ordem": ordem}


def conta(con, username: str, agora=None) -> dict | None:
    agora = agora or _agora()
    linha_conta = con.execute(SQL_CONTA + " AND c.username = ?", (username,)).fetchone()
    if not linha_conta:
        return None
    arquivo = capas.arquivo_foto(username)
    dados = {k: linha_conta[k] for k in linha_conta.keys()}
    contagem = _contas_energisa(con, " AND c.username = ?", (username,), 1)
    dados.update({"foto": bool(arquivo and arquivo.exists()), "municipios": _municipios_da_conta(con, username),
                  "monitorada": username in set(monitoradas(con)), "onde": onde_da_conta(con, username),
                  "mencoes": contagem[0]["mencoes"] if contagem else 0,
                  "negativas": (contagem[0]["negativas"] or 0) if contagem else 0})
    tem = capas.existentes("posts")
    stories, _ = posts(con, {"conta": username, "formato": "Story", "ordem": "recentes"}, 40, agora=agora, tem=tem)
    dados["linhas"] = [{"id": "story-conta", "titulo": "Stories sobre a Energisa", "formato": "story",
                        "itens": stories, "verTudo": False}] if stories else []
    dados["posts"] = linha(con, f"conta-{username}", 0, agora=agora, tem=tem)  # as menções da conta, sem stories
    return dados


@lru_cache(maxsize=1)
def _mapa() -> dict:
    return app_dados.mapa()


# --- Mapa -----------------------------------------------------------------------------------
# Cada post e cada conta ficam num município (localizacao.py); no mapa, os itens de um município se espalham em
# espiral em volta do centro dele, os mais relevantes no meio.

# camada -> (distância entre os pontos, pontos por município; o resto entra só na contagem). As menções à Energisa e
# as contas que as publicaram.
CAMADAS = {"mencoes": (3.2, 40), "perfis": (3.6, 30)}


@lru_cache(maxsize=1)
def _centros() -> dict[int, tuple[float, float]]:
    return {ibge_id: localizacao.centro(d) for ibge_id, d in _mapa()["paths"].items()}


def mapa_base(con) -> dict:
    """O contorno de cada município e o ponto onde ficam os itens dele."""
    geo, centros = _mapa(), _centros()
    return {"largura": geo["largura"], "altura": geo["altura"], "municipios": [
        {"id": l[0], "nome": l[1], "d": geo["paths"].get(l[0], ""), "x": centros.get(l[0], (0, 0))[0],
         "y": centros.get(l[0], (0, 0))[1]} for l in con.execute("SELECT ibge_id, nome FROM municipios ORDER BY nome")]}


def _nome_municipio(municipios_, ibge_id: int) -> str:
    return next((m["nome"] for m in municipios_ if m["ibge_id"] == ibge_id), "")


def onde_do_post(con, linha_post) -> dict | None:
    """Município aproximado do post e de onde a pista veio (fato, marcacao, texto ou conta)."""
    municipios_ = mun.carregar(con)
    achado = localizacao.do_post(
        linha_post["post_id"], linha_post["legenda"], linha_post["local"], linha_post["username"],
        localizacao.municipios_do_fato(con, [linha_post["post_id"]]), localizacao.cidades_das_contas(con, municipios_),
        localizacao.localizador(municipios_))
    return {"id": achado[0], "nome": _nome_municipio(municipios_, achado[0]), "fonte": achado[1]} if achado else None


def onde_da_conta(con, username: str) -> dict | None:
    """A cidade da conta e todos os municípios ligados a ela (para destacar no mapa)."""
    municipios_ = mun.carregar(con)
    cidade = localizacao.cidades_das_contas(con, municipios_).get(username)
    ids = [l[0] for l in con.execute(
        "SELECT DISTINCT cm.ibge_id FROM conta_municipio cm WHERE cm.rede = 'instagram' AND cm.username = ? "
        "AND cm.fonte = 'ia'", (username,))]
    if cidade is None and not ids:
        return None
    return {"id": cidade, "nome": _nome_municipio(municipios_, cidade) if cidade else "", "municipios": ids,
            "fonte": "conta"}


def _ponto(item: dict, fonte: str) -> dict:
    m = item["mencao"] or {}
    return {"id": item["id"], "rede": item["rede"], "conta": item["conta"], "nome": item["nome"],
            "formato": item["formato"], "data": item["data"],
            "titulo": m.get("resumo") or item["titulo"], "capa": item["capa"], "interacoes": item["interacoes"],
            "views": item["views"], "sentimento": m.get("sentimento"), "tema": m.get("tema"), "fonte": fonte}


def mapa(con, camada: str = "mencoes", dias=None, sentimento: str | None = None, agora=None) -> dict:
    """Os pontos da camada (menções à Energisa ou as contas que as publicaram), cada um no seu município, e a
    contagem por município."""
    agora = agora or _agora()
    camada = camada if camada in CAMADAS else "mencoes"
    passo, por_municipio = CAMADAS[camada]
    municipios_ = mun.carregar(con)
    cidades = localizacao.cidades_das_contas(con, municipios_)
    grupos: dict[int, list[dict]] = {}
    sem_local = 0
    if camada == "perfis":
        fotos = capas.existentes("perfis")
        for l in _contas_energisa(con, limite=100_000):
            if l["username"] in cidades:
                grupos.setdefault(cidades[l["username"]], []).append({**_cartao_conta(l, fotos), "fonte": "conta"})
            else:
                sem_local += 1
        for grupo in grupos.values():  # as mais seguidas no centro de cada município
            grupo.sort(key=lambda c: -(c["seguidores"] or 0))
    else:
        filtros = {"ordem": "interacoes"}
        if dias:
            filtros["dias"] = dias
        if sentimento in ("negativo", "neutro", "positivo"):
            filtros["sentimento"] = sentimento
        sql, args = _consulta(filtros, None, agora)
        fato = localizacao.municipios_do_fato(con)
        achar = localizacao.localizador(municipios_)
        tem = capas.existentes("posts")
        for l in con.execute(sql, args):
            achado = localizacao.do_post(l["post_id"], l["legenda"], l["local"], l["username"], fato, cidades, achar)
            if achado is None:
                sem_local += 1
                continue
            grupos.setdefault(achado[0], []).append(_ponto(_item(l, tem), achado[1]))
        for grupo in grupos.values():  # menções e o que mais repercutiu no centro de cada município
            grupo.sort(key=lambda p: (p["sentimento"] is None, -(p["interacoes"] or 0)))
    centros = _centros()
    pontos, contagem = [], []
    for ibge_id, grupo in grupos.items():
        if ibge_id not in centros:
            continue
        contagem.append({"id": ibge_id, "nome": _nome_municipio(municipios_, ibge_id), "n": len(grupo)})
        cx, cy = centros[ibge_id]
        for (dx, dy), item in zip(localizacao.espalhar(min(len(grupo), por_municipio), passo), grupo):
            pontos.append({**item, "x": round(cx + dx, 2), "y": round(cy + dy, 2), "municipio": ibge_id})
    contagem.sort(key=lambda c: (-c["n"], c["nome"]))
    return {"camada": camada, "dias": dias, "sentimento": sentimento, "pontos": pontos, "municipios": contagem,
            "total": sum(c["n"] for c in contagem), "semLocal": sem_local}


def municipio(con, ibge_id: int, agora=None) -> dict | None:
    agora = agora or _agora()
    linha_m = con.execute("SELECT ibge_id, nome, populacao, porte FROM municipios WHERE ibge_id = ?",
                          (ibge_id,)).fetchone()
    if not linha_m:
        return None
    tem = capas.existentes("posts")
    linhas = []
    for linha_id in (f"municipio-{ibge_id}", f"cidade-{ibge_id}"):
        dados = linha(con, linha_id, 0, limite=POR_LINHA, agora=agora, tem=tem)
        if dados and dados["itens"]:
            dados["titulo"] = {"municipio": "Menções à Energisa", "cidade": "Publicadas pelas contas da cidade"}[
                linha_id.split("-")[0]]
            dados["verTudo"] = True
            linhas.append(dados)
    fotos = capas.existentes("perfis")
    contas_m = [_cartao_conta(l, fotos) for l in _contas_energisa(
        con, " AND c.username IN (SELECT cm.username FROM conta_municipio cm WHERE cm.rede = 'instagram' "
        "AND cm.fonte = 'ia' AND cm.ibge_id = ?)", (ibge_id,), 40)]
    if contas_m:
        linhas.append({"id": f"contas-{ibge_id}", "titulo": "Contas da cidade que falam da Energisa",
                       "formato": "conta", "itens": contas_m, "verTudo": False})
    geo = _mapa()
    return {"id": linha_m["ibge_id"], "nome": linha_m["nome"], "populacao": linha_m["populacao"],
            "d": geo["paths"].get(linha_m["ibge_id"], ""), "contas": len(contas_m),
            "mencoes": con.execute("SELECT COUNT(*) FROM mencao_municipio mm JOIN mencoes x ON x.rede = mm.rede "
                                   "AND x.post_id = mm.post_id AND x.sobre_energia = 1 WHERE mm.ibge_id = ?",
                                   (ibge_id,)).fetchone()[0],
            "linhas": linhas}


def setores(con, dias=None, sentimento: str | None = None, agora=None) -> dict:
    """As menções à Energisa separadas pelo setor da empresa a que dizem respeito, com a contagem por sentimento.
    Do setor com mais menções para o com menos; "fora da Energisa" por último."""
    agora = agora or _agora()
    filtros = {"ordem": "recentes"}
    if dias:
        filtros["dias"] = dias
    if sentimento in ("negativo", "neutro", "positivo"):
        filtros["sentimento"] = sentimento
    sql, args = _consulta(filtros, None, agora)
    tem = capas.existentes("posts")
    grupos: dict[str, list] = {}
    for l in con.execute(sql, args):
        grupos.setdefault(l["setor"] if l["setor"] in NOMES_SETOR else "", []).append(l)
    lista = []
    for setor, linhas in grupos.items():
        sentimentos = [l["sentimento"] for l in linhas]
        lista.append({"id": setor, "titulo": NOMES_SETOR.get(setor, "Sem setor"), "n": len(linhas),
                      "negativas": sentimentos.count("negativo"), "neutras": sentimentos.count("neutro"),
                      "positivas": sentimentos.count("positivo"), "itens": [_item(l, tem) for l in linhas[:POR_LINHA]]})
    lista.sort(key=lambda s: (s["id"] in ("nenhum", ""), -s["n"], -s["negativas"], s["titulo"]))
    return {"dias": dias, "sentimento": filtros.get("sentimento"), "total": sum(s["n"] for s in lista),
            "setores": lista}


def busca(con, termo: str, agora=None) -> dict:
    """Menções à Energisa com o termo no texto (ou no resumo da IA) e contas (as da página Contas) com o termo no @ ou
    no nome, as que mais falam da Energisa primeiro. Sem acento e sem diferença de maiúsculas."""
    limpo = normalizar(termo).strip()
    if len(limpo) < 2:
        return {"q": termo, "contas": [], "posts": []}
    con.create_function("norm", 1, normalizar, deterministic=True)
    padrao = _like(limpo)
    fotos = capas.existentes("perfis")
    contas_achadas = [_cartao_conta(l, fotos) for l in con.execute(
        SQL_CONTAS_TODAS + " AND (c.username LIKE ? ESCAPE '\\' OR norm(c.nome) LIKE ? ESCAPE '\\') "
        f"ORDER BY {ORDENS_CONTAS['mencoes']} LIMIT 24", (json.dumps(monitoradas(con)), padrao, padrao))]
    tem = capas.existentes("posts")
    linhas = con.execute(SQL_POST + " AND (norm(p.legenda) LIKE ? ESCAPE '\\' OR norm(x.resumo) LIKE ? ESCAPE '\\') "
                         "ORDER BY p.publicado_em DESC LIMIT 96", (padrao, padrao)).fetchall()
    return {"q": termo, "contas": contas_achadas, "posts": [_item(l, tem) for l in linhas]}


def status(con, apos: int | None = None, agora=None) -> dict:
    agora = agora or _agora()
    visita = con.execute("SELECT MAX(ultima_em) FROM visitas").fetchone()[0]
    quando = _data(visita)
    desde = _iso(agora - timedelta(hours=24))
    contagem = con.execute(
        "SELECT SUM(COALESCE(p.tipo, '') != 'Story'), SUM(p.tipo = 'Story') FROM posts p JOIN mencoes x "
        "ON x.rede = p.rede AND x.post_id = p.post_id AND x.sobre_energia = 1 WHERE p.publicado_em >= ?",
        (desde,)).fetchone()
    # Novidade é menção nova: o post entra no banco e só vira menção quando a IA o analisa, minutos depois.
    novos = con.execute("SELECT COUNT(*) FROM mencoes WHERE rowid > ? AND sobre_energia = 1",
                        (apos,)).fetchone()[0] if apos else 0
    return {
        "agora": _iso(agora), "ultimaVisita": visita,
        "coletadoEm": con.execute("SELECT MAX(medido_em) FROM posts").fetchone()[0],
        "aoVivo": bool(quando and agora - quando < AO_VIVO),
        "ultimoId": con.execute("SELECT MAX(rowid) FROM mencoes").fetchone()[0] or 0,
        "novos": novos,
        "posts24h": contagem[0] or 0, "stories24h": contagem[1] or 0,
        "mencoes": con.execute("SELECT COUNT(*) FROM mencoes WHERE sobre_energia = 1").fetchone()[0],
    }


# --- API ------------------------------------------------------------------------------------

def responder(con, rota: str, q: dict, agora=None) -> dict | None:
    """A resposta de /api/<rota>?<q> (None: não encontrado). `q` vem como o parse_qs a deixa: sem os valores vazios,
    e o último valor de cada chave. O servidor e o site estático (estatico.py) respondem por aqui."""
    recurso, _, valor = rota.partition("/")
    pagina = int(q.get("pagina") or 0) if str(q.get("pagina") or "0").isdigit() else 0
    if recurso == "status":
        apos = q.get("apos")
        return status(con, int(apos) if apos and apos.isdigit() else None, agora)
    if recurso == "inicio":
        return inicio(con, agora)
    if recurso == "linha" and valor:
        return linha(con, valor, pagina, {k: q[k] for k in SOBREPOR if k in q}, agora=agora)
    if recurso == "post" and valor:
        return post(con, valor, agora)
    if recurso == "conta" and valor:
        return conta(con, valor.lower(), agora)
    if recurso == "contas":
        return lista_contas(con, q.get("tipo") or None, pagina, ordem=q.get("ordem") or "seguidores")
    if recurso == "setores":
        return setores(con, _dias(q.get("dias")), q.get("sentimento") or None, agora)
    if recurso == "mapa":
        return mapa(con, q.get("camada") or "mencoes", _dias(q.get("dias")), q.get("sentimento") or None, agora)
    if recurso == "mapa-base":
        return mapa_base(con)
    if recurso == "municipio" and valor.isdigit():
        return municipio(con, int(valor), agora)
    if recurso == "busca":
        return busca(con, q.get("q", ""), agora)
    return None


# --- Servidor -------------------------------------------------------------------------------

_travas: dict[Path, threading.Lock] = {}
_trava_geral = threading.Lock()


def _trava(destino: Path) -> threading.Lock:
    with _trava_geral:
        return _travas.setdefault(destino, threading.Lock())


class Painel(BaseHTTPRequestHandler):
    server_version = "Radar"
    caminho_banco: Path | None = None

    def log_message(self, formato, *args):  # o terminal mostra só o endereço do painel
        pass

    def _conexao(self):
        return db.conectar_leitura(self.caminho_banco)

    def _enviar(self, codigo: int, corpo: bytes, tipo: str, cache: str = "no-store", extra: dict | None = None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        for chave, valor in (extra or {}).items():
            self.send_header(chave, valor)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _json(self, dados, codigo: int = 200):
        self._enviar(codigo, json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                     "application/json; charset=utf-8")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        partes = urlsplit(self.path)
        rota = unquote(partes.path)
        consulta = {k: v[-1] for k, v in parse_qs(partes.query).items()}
        try:
            if rota.startswith("/api/"):
                self._api(rota[5:].strip("/"), consulta)
            elif rota.startswith("/capa/"):
                self._capa(rota[6:])
            elif rota.startswith("/foto/"):
                self._foto(rota[6:])
            elif rota.startswith("/midia/"):
                self._midia(rota[7:])
            else:
                self._estatico(rota)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as erro:
            try:
                self._json({"erro": f"{type(erro).__name__}: {erro}"}, 500)
            except OSError:
                pass

    def _api(self, rota: str, q: dict):
        con = self._conexao()
        try:
            dados = responder(con, rota, q)
        finally:
            con.close()
        if dados is None:
            self._json({"erro": "não encontrado"}, 404)
        else:
            self._json(dados)

    def _imagem(self, destino: Path | None, url_atual, largura: int):
        if destino is None:
            return self._json({"erro": "não encontrado"}, 404)
        if not destino.exists():
            url = url_atual()
            if capas.valida(url):
                with _trava(destino):
                    if not destino.exists():
                        capas.guardar(capas.baixar(url, timeout=10) or b"", destino, largura)
        if not destino.exists():
            return self._json({"erro": "sem imagem"}, 404)
        self._enviar(200, destino.read_bytes(), "image/jpeg", "max-age=86400")

    def _url_de(self, sql: str, chave: str) -> str | None:
        con = self._conexao()
        try:
            linha_url = con.execute(sql, (chave,)).fetchone()
        except Exception:
            return None
        finally:
            con.close()
        return linha_url[0] if linha_url else None

    def _capa(self, post_id: str):
        destino = capas.arquivo_post(post_id)
        if destino is not None and not destino.exists():  # story da Energisa: a capa sai da imagem salva para o OCR
            imagem = capas.imagem_do_story(self._url_de(
                "SELECT arquivo FROM posts WHERE rede = 'instagram' AND post_id = ? AND tipo = 'Story'", post_id))
            if imagem:
                with _trava(destino):
                    if not destino.exists():
                        capas.guardar_arquivo(imagem, destino)
        self._imagem(destino,
                     lambda: self._url_de("SELECT capa FROM posts WHERE rede = 'instagram' AND post_id = ?", post_id),
                     capas.LARGURA_POST)

    def _foto(self, username: str):
        self._imagem(capas.arquivo_foto(username.lower()),
                     lambda: self._url_de("SELECT foto FROM contas WHERE rede = 'instagram' AND username = ?",
                                          username.lower()), capas.LARGURA_FOTO)

    def _midia(self, post_id: str):
        arquivo = _arquivo_midia(self._url_de("SELECT arquivo FROM posts WHERE rede = 'instagram' AND post_id = ?",
                                              post_id)) if capas.RE_ID.match(post_id) else None
        if arquivo is None:
            return self._json({"erro": "não encontrado"}, 404)
        dados = arquivo.read_bytes()
        tipo = TIPOS_MIDIA[arquivo.suffix.lower()]
        intervalo = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "") or "")
        if intervalo and (intervalo[1] or intervalo[2]):  # o <video> pede pedaços para poder avançar
            inicio_b = int(intervalo[1]) if intervalo[1] else max(0, len(dados) - int(intervalo[2]))
            fim = min(int(intervalo[2]), len(dados) - 1) if intervalo[1] and intervalo[2] else len(dados) - 1
            if inicio_b >= len(dados):
                return self._enviar(416, b"", tipo, extra={"Content-Range": f"bytes */{len(dados)}"})
            return self._enviar(206, dados[inicio_b:fim + 1], tipo, "max-age=3600",
                                {"Content-Range": f"bytes {inicio_b}-{fim}/{len(dados)}", "Accept-Ranges": "bytes"})
        self._enviar(200, dados, tipo, "max-age=3600", {"Accept-Ranges": "bytes"})

    def _estatico(self, rota: str):
        nome = "index.html" if rota in ("", "/") else rota.lstrip("/")
        arquivo = (WEB / nome).resolve()
        try:
            arquivo.relative_to(WEB)
        except ValueError:
            return self._json({"erro": "não encontrado"}, 404)
        if not arquivo.is_file() or arquivo.suffix not in TIPOS_STATIC:
            return self._json({"erro": "não encontrado"}, 404)
        cache = "max-age=604800" if arquivo.suffix == ".ttf" else "no-cache"
        self._enviar(200, arquivo.read_bytes(), TIPOS_STATIC[arquivo.suffix], cache)


class Servidor(ThreadingHTTPServer):
    """No Windows, o SO_REUSEADDR do http.server deixa dois painéis escutarem a mesma porta: aqui ela é exclusiva."""
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _ip_local() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # não envia nada: só escolhe a interface de saída
            return s.getsockname()[0]
    except OSError:
        return "IP-deste-computador"


def servir(porta: int = PORTA, rede: bool = False, abrir: bool = True, aviso=print) -> None:
    db.conectar().close()  # cria as colunas novas (capa, foto) num banco antigo
    Painel.caminho_banco = config.DB_PATH
    try:
        servidor = Servidor(("0.0.0.0" if rede else "127.0.0.1", porta), Painel)
    except OSError:
        aviso(f"A porta {porta} já está em uso: o painel pode já estar aberto em http://127.0.0.1:{porta}/. "
              f"Para abrir outro, use --porta {porta + 1}.")
        return
    manter = capas.Manter(db.conectar_leitura, aviso=aviso)
    manter.start()
    url = f"http://127.0.0.1:{porta}/"
    aviso(f"Painel em {url}" + (f" (no celular, na mesma rede: http://{_ip_local()}:{porta}/)" if rede else "")
          + ". Ctrl+C fecha.")
    if abrir:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    try:
        servidor.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        manter.parar.set()
        servidor.server_close()
