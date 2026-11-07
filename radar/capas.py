"""Capas das menções e fotos dos perfis, guardadas em data/capas/ para o painel.

O painel só mostra o que tem a ver com a Energisa, então só isso ganha imagem: a capa de cada menção (post ou story
que a IA ligou à Energisa) e a foto de cada conta que publicou uma. Capas de outros posts são apagadas.

Os endereços de imagem do Instagram são assinados e expiram uns 4 dias depois da leitura (parâmetro `oe`). O coletor
guarda o endereço (posts.capa, contas.foto) e a imagem é baixada enquanto ele vale, direto da rede de distribuição do
Instagram, sem passar pela conta logada: em segundo plano pelo painel, ou por `python -m radar capas`. Como a IA
analisa o post minutos depois da coleta, o endereço ainda vale quando o post vira menção.

A capa de um story sai da imagem que o coletor salvou em data/stories/ para o OCR, sem leitura extra; sem essa
imagem, do endereço guardado nas cópias brutas.
"""
import io
import json
import os
import re
import ssl
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import config

PASTA = config.DATA_DIR / "capas"
STORIES = config.DATA_DIR / "stories"  # onde stories.py salva a mídia dos stories que passam no filtro de energia
LARGURA_POST = 480
LARGURA_FOTO = 160
FOTO_VELHA = timedelta(days=14)  # a foto do perfil é baixada de novo depois disso
INTERVALO = 120  # segundos entre as rodadas do trabalho em segundo plano
POR_RODADA = 300
RE_ID = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
RE_USERNAME = re.compile(r"^[a-z0-9._]{1,30}$")
AGENTE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
ASSINATURAS = (b"\xff\xd8\xff", b"\x89PNG", b"RIFF", b"GIF8")  # JPEG, PNG, WEBP, GIF


# --- Endereços ------------------------------------------------------------------------------

def _candidatos(no: dict) -> list[dict]:
    return [c for c in ((no.get("image_versions2") or {}).get("candidates") or []) if c.get("url")]


def melhor_imagem(no: dict, largura: int = LARGURA_POST) -> str | None:
    """Endereço da imagem do post (a capa, no vídeo) com a menor largura que não fique abaixo de `largura`.
    No carrossel, a primeira imagem."""
    candidatos = _candidatos(no)
    if not candidatos:
        for filho in no.get("carousel_media") or []:
            candidatos = _candidatos(filho)
            if candidatos:
                break
    if candidatos:
        acima = [c for c in candidatos if (c.get("width") or 0) >= largura]
        if acima:
            return min(acima, key=lambda c: c.get("width") or 0)["url"]
        return max(candidatos, key=lambda c: c.get("width") or 0)["url"]
    for chave in ("display_uri", "display_url", "thumbnail_src", "thumbnail_url"):
        valor = no.get(chave)
        if isinstance(valor, str) and valor.startswith("http"):
            return valor
    return None


def foto_do_usuario(usuario: dict) -> str | None:
    """Endereço da foto do perfil, na maior versão que a página trouxer."""
    return ((usuario.get("hd_profile_pic_url_info") or {}).get("url") or usuario.get("profile_pic_url_hd")
            or usuario.get("profile_pic_url") or None)


def expira_em(url: str) -> datetime | None:
    try:
        oe = parse_qs(urlsplit(url).query).get("oe", [None])[0]
        return datetime.fromtimestamp(int(oe, 16), timezone.utc) if oe else None
    except (ValueError, OverflowError, OSError):
        return None


def valida(url: str | None, agora: datetime | None = None) -> bool:
    """O endereço ainda serve (com 5 minutos de folga)? Sem prazo conhecido, conta como válido."""
    if not url or not url.startswith("http"):
        return False
    prazo = expira_em(url)
    return prazo is None or prazo > (agora or datetime.now(timezone.utc)) + timedelta(minutes=5)


# --- Arquivos -------------------------------------------------------------------------------

def arquivo_post(post_id: str) -> Path | None:
    return PASTA / "posts" / f"{post_id}.jpg" if RE_ID.match(str(post_id)) else None


def arquivo_foto(username: str) -> Path | None:
    return PASTA / "perfis" / f"{username}.jpg" if RE_USERNAME.match(str(username)) else None


def imagem_do_story(arquivo: str | None) -> Path | None:
    """A imagem que o coletor salvou do story (no vídeo, a capa .jpg gravada ao lado), só se estiver em data/stories."""
    if not arquivo:
        return None
    imagem = Path(arquivo).with_suffix(".jpg")
    try:
        imagem.resolve().relative_to(STORIES.resolve())
    except (ValueError, OSError):
        return None
    return imagem if imagem.is_file() else None


def existentes(sub: str) -> set[str]:
    """Nomes (sem .jpg) dos arquivos já baixados em data/capas/<sub>."""
    try:
        return {e.name[:-4] for e in os.scandir(PASTA / sub) if e.name.endswith(".jpg")}
    except FileNotFoundError:
        return set()


def guardar(dados: bytes, destino: Path, largura: int) -> bool:
    """Grava a imagem em JPEG, reduzida para `largura`. A escrita é atômica: o painel e a vigilância podem baixar a
    mesma capa ao mesmo tempo. Devolve False se os dados não forem uma imagem."""
    if not dados or not dados.startswith(ASSINATURAS):
        return False
    try:
        from PIL import Image

        with Image.open(io.BytesIO(dados)) as imagem:
            imagem = imagem.convert("RGB")
            if imagem.width > largura:
                imagem = imagem.resize((largura, max(1, round(imagem.height * largura / imagem.width))),
                                       Image.LANCZOS)
            saida = io.BytesIO()
            imagem.save(saida, "JPEG", quality=82, optimize=True, progressive=True)
            dados = saida.getvalue()
    except ImportError:  # sem o Pillow, só o JPEG entra, do tamanho que veio
        if not dados.startswith(ASSINATURAS[0]):
            return False
    except Exception:
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(f"{destino.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporario.write_bytes(dados)
    os.replace(temporario, destino)
    return True


def guardar_arquivo(origem: Path, destino: Path | None, largura: int = LARGURA_POST) -> bool:
    """Capa a partir de uma imagem já baixada (a do story, que foi para o OCR). Nunca levanta erro."""
    try:
        return destino is not None and guardar(Path(origem).read_bytes(), destino, largura)
    except OSError:
        return False


_SSL = None


def _contexto_ssl():
    global _SSL
    if _SSL is None:
        try:  # o mesmo repositório de certificados do Windows que a DeepSeek usa (antivírus que inspeciona HTTPS)
            import truststore

            _SSL = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except ImportError:
            _SSL = ssl.create_default_context()
    return _SSL


def baixar(url: str, timeout: float = 15) -> bytes | None:
    """A imagem do endereço, ou None. Direto da rede de distribuição, sem cookies nem a conta do Instagram."""
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept": "image/*,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(pedido, timeout=timeout, context=_contexto_ssl()) as resposta:
            return resposta.read(10_000_000) if resposta.status == 200 else None
    except Exception:
        return None


# --- Pendentes ------------------------------------------------------------------------------

SQL_POSTS_PENDENTES = """
SELECT p.post_id, p.capa FROM posts p
JOIN mencoes x ON x.rede = p.rede AND x.post_id = p.post_id AND x.sobre_energia = 1
WHERE p.rede = 'instagram' AND p.capa IS NOT NULL
ORDER BY p.publicado_em DESC
"""
# Fotos das contas que o painel mostra: as monitoradas (página Contas) e as que publicaram sobre a Energisa.
SQL_FOTOS_PENDENTES = """
SELECT c.username, c.foto FROM contas c
WHERE c.rede = 'instagram' AND c.foto IS NOT NULL AND (c.username IN (SELECT value FROM json_each(?)) OR c.username IN (
  SELECT p.username FROM posts p JOIN mencoes x ON x.rede = p.rede AND x.post_id = p.post_id AND x.sobre_energia = 1))
ORDER BY c.seguidores DESC
"""


def monitoradas(con) -> list[str]:
    """Os @ das contas monitoradas. Importado aqui: monitoramento traz a coleta inteira."""
    from . import monitoramento

    return [l[0] for l in con.execute(monitoramento.SQL_MONITORADAS)]
SQL_STORIES_ENERGISA = """
SELECT p.post_id, p.arquivo FROM posts p
JOIN mencoes x ON x.rede = p.rede AND x.post_id = p.post_id AND x.sobre_energia = 1
WHERE p.rede = 'instagram' AND p.tipo = 'Story'
ORDER BY p.publicado_em DESC
"""


def stories_da_energisa(con) -> list[tuple[str, str | None]]:
    """(post_id, arquivo salvo) dos stories que a IA ligou à Energisa, os mais novos primeiro."""
    try:
        return [(l[0], l[1]) for l in con.execute(SQL_STORIES_ENERGISA)]
    except Exception:  # banco sem as tabelas das menções
        return []


def pendentes(con, agora: datetime | None = None) -> list[tuple[Path, str, int]]:
    """(destino, endereço, largura) das capas das menções e das fotos das contas que o painel mostra (monitoradas e
    as que publicaram sobre a Energisa), que faltam e ainda podem ser baixadas: capas primeiro, depois fotos."""
    agora = agora or datetime.now(timezone.utc)
    try:
        posts = con.execute(SQL_POSTS_PENDENTES).fetchall()
        fotos = con.execute(SQL_FOTOS_PENDENTES, (json.dumps(monitoradas(con)),)).fetchall()
    except Exception:  # banco ainda sem as colunas novas (nenhum processo novo o abriu)
        return []
    tem = existentes("posts")
    lista = [(arquivo_post(l[0]), l[1], LARGURA_POST) for l in posts if l[0] not in tem and valida(l[1], agora)]
    limite_foto = time.time() - FOTO_VELHA.total_seconds()
    for username, url in fotos:
        destino = arquivo_foto(username)
        if destino is None or not valida(url, agora):
            continue
        try:
            if destino.stat().st_mtime > limite_foto:
                continue
        except FileNotFoundError:
            pass
        lista.append((destino, url, LARGURA_FOTO))
    return [(d, u, w) for d, u, w in lista if d is not None]


def stories_dos_brutos(raw_dir: Path, vistos: set[str], agora: float | None = None,
                       achados: dict[str, str] | None = None) -> dict[str, str]:
    """Acrescenta a `achados` (post_id -> endereço) as imagens dos stories nas cópias brutas dos últimos 5 dias ainda
    não lidas (`vistos` guarda os nomes dos arquivos) e tira os endereços vencidos. Serve aos stories da Energisa que
    ficaram sem a imagem salva."""
    agora = agora or time.time()
    achados = {} if achados is None else achados
    novos = {}
    # Do mais novo para o mais velho (o nome começa pela data): fica o endereço mais novo de cada story.
    for arquivo in sorted(Path(raw_dir).glob("*_stories*.json"), reverse=True):
        if arquivo.name in vistos:
            continue
        try:
            if agora - arquivo.stat().st_mtime > 5 * 86400:
                vistos.add(arquivo.name)
                continue
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # arquivo sendo escrito agora: fica para a próxima rodada
        vistos.add(arquivo.name)
        itens = dados.get("itens") if isinstance(dados, dict) else None
        for item in itens or []:
            if isinstance(item, dict) and item.get("id") and item.get("imagem"):
                novos.setdefault(str(item["id"]), item["imagem"])
    achados.update(novos)  # os arquivos lidos agora são mais novos que os das rodadas anteriores
    for chave in [k for k, url in achados.items() if not valida(url)]:
        del achados[chave]
    return achados


def limpar(con) -> int:
    """Apaga as capas de posts e stories que não são menções à Energisa: o painel não os mostra. Devolve quantas
    apagou."""
    try:
        mencoes = {l[0] for l in con.execute("SELECT post_id FROM mencoes WHERE sobre_energia = 1")}
    except Exception:
        return 0
    apagadas = 0
    try:
        entradas = list(os.scandir(PASTA / "posts"))
    except FileNotFoundError:
        return 0
    for entrada in entradas:
        if entrada.name.endswith(".jpg") and entrada.name[:-4] not in mencoes:
            Path(entrada.path).unlink(missing_ok=True)
            apagadas += 1
    return apagadas


def rodada(con, raw_dir: Path = config.RAW_DIR, vistos: set[str] | None = None, limite: int = POR_RODADA,
           parar=lambda: False, baixar_url=baixar, dormir=time.sleep, falhas: set[Path] | None = None,
           brutos: dict[str, str] | None = None) -> dict:
    """Uma passada: capas dos stories da Energisa, depois capas e fotos pendentes no banco. `falhas` guarda os
    destinos que já falharam, para não insistir neles a cada rodada; `brutos` guarda os endereços das cópias brutas."""
    vistos = set() if vistos is None else vistos
    falhas = set() if falhas is None else falhas
    brutos = {} if brutos is None else brutos
    feitos = {"baixadas": 0, "falhas": 0}
    tem = existentes("posts")
    sem_imagem = []
    for post_id, arquivo in stories_da_energisa(con):
        destino = arquivo_post(post_id)
        if destino is None or post_id in tem or destino in falhas:
            continue
        imagem = imagem_do_story(arquivo)
        if imagem and guardar_arquivo(imagem, destino):
            feitos["baixadas"] += 1
        else:
            sem_imagem.append((post_id, destino))
    lista = []
    if sem_imagem:
        stories_dos_brutos(raw_dir, vistos, achados=brutos)
        for post_id, destino in sem_imagem:
            if brutos.get(post_id):
                lista.append((destino, brutos[post_id], LARGURA_POST))
            else:
                falhas.add(destino)  # o story some em 24 horas: sem imagem salva nem endereço, fica sem capa
    ja = {x[0] for x in lista}
    lista += [x for x in pendentes(con) if x[0] not in ja]
    lista = [x for x in lista if x[0] is not None and x[0] not in falhas]
    tentadas = 0
    for destino, url, largura in lista[:limite]:
        if parar():
            break
        tentadas += 1
        if guardar(baixar_url(url) or b"", destino, largura):
            feitos["baixadas"] += 1
        else:
            feitos["falhas"] += 1
            falhas.add(destino)
        dormir(0.15)
    feitos["faltam"] = len(lista) - tentadas
    return feitos


class Manter(threading.Thread):
    """Baixa as capas em segundo plano enquanto o painel ou a vigilância rodam. `abrir()` devolve uma conexão."""

    def __init__(self, abrir, intervalo: float = INTERVALO, aviso=None):
        super().__init__(name="capas", daemon=True)
        self.abrir, self.intervalo, self.aviso = abrir, intervalo, aviso
        self.parar = threading.Event()
        self.vistos: set[str] = set()
        self.falhas: set[Path] = set()
        self.brutos: dict[str, str] = {}
        self.ultima_limpeza = 0.0
        self.total = 0

    def run(self) -> None:
        while not self.parar.is_set():
            try:
                con = self.abrir()
                try:
                    feitos = rodada(con, vistos=self.vistos, parar=self.parar.is_set, falhas=self.falhas,
                                    brutos=self.brutos)
                    self.total += feitos["baixadas"]
                    if time.time() - self.ultima_limpeza > 3600:
                        limpar(con)
                        self.ultima_limpeza = time.time()
                finally:
                    con.close()
                if feitos["faltam"] and feitos["baixadas"]:
                    continue  # ainda há fila e a rede responde: segue sem esperar
            except Exception as erro:  # nunca derruba o painel nem a vigilância
                if self.aviso:
                    self.aviso(f"capas: {type(erro).__name__}: {erro}")
            self.parar.wait(self.intervalo)
