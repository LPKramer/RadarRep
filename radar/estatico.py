"""O painel sem servidor, para o GitHub Pages: grava em arquivos JSON as respostas que a API do painel (painel.py)
daria, e a página lê esses arquivos no lugar do servidor (web/estatico.js). O comando é `python -m radar site`.

Cada pedido que as telas podem fazer vira um arquivo: a tela inicial, a ficha de cada menção, a página de cada conta e
de cada município, o mapa e os setores em cada filtro, a lista de contas. As fileiras ("ver tudo") guardam, para cada
combinação de período, sentimento e ordem, os ids dos cartões de cada página; os cartões ficam uma vez só, em
api/itens.json. A busca roda na página, sobre o texto já sem acento de api/busca.json. As contas são as que o painel
mostra: as monitoradas e as que publicaram sobre a Energisa.

As imagens já baixadas (capas.py) vão junto: as capas em capa/, as fotos dos perfis em foto/ e a mídia salva dos
stories em midia/. Item sem imagem no site sai sem ela, e o cartão vira o cartaz com o texto.

É uma fotografia do banco, lido numa transação só (a coleta pode gravar enquanto isso): "7 dias" são os 7 dias antes
da geração. Nada é gravado no banco nem na pasta de dados.
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from . import capas, painel

SIMPLES = re.compile(r"[0-9a-z_-][0-9a-z_.-]{0,63}")  # id que já serve de nome de arquivo
DIAS = (7, 30, 90, None)  # os períodos dos filtros da página (DIAS_MENCOES no app.js); None é "Tudo"
SENTIMENTOS = ("negativo", "neutro", "positivo")
PASTAS = ("api", "capa", "foto", "midia")  # o que a geração anterior deixou e a nova refaz


def fnv1a(texto: str) -> int:
    """FNV-1a de 32 bits dos bytes UTF-8 do texto."""
    h = 0x811C9DC5
    for byte in texto.encode("utf-8"):
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return h


def nome_arquivo(chave: str) -> str:
    """O nome do arquivo de um id, o mesmo que web/estatico.js calcula: o próprio id, se for curto e só tiver
    minúsculas, números, ponto, hífen e sublinhado; senão, "~" e o FNV-1a dele. Os ids das notícias do Google passam
    de 200 caracteres, e o Windows não distingue maiúscula de minúscula em nome de arquivo."""
    return chave if SIMPLES.fullmatch(chave) else f"~{fnv1a(chave):08x}"


def _chave_dias(dias) -> str:
    return "todos" if dias is None else f"{dias:g}"


def para_o_site(valor, com_capa: set[str], com_foto: set[str], midias: dict[str, dict]):
    """A resposta do servidor com os arquivos que o site tem: capa nos posts de `com_capa`, foto nas contas de
    `com_foto` e, nos stories de `midias`, a mídia com o endereço dela no site."""
    if isinstance(valor, dict):
        saida = {}
        for chave, v in valor.items():
            if chave == "capa" and isinstance(v, bool):
                saida[chave] = valor.get("id") in com_capa
            elif chave == "foto" and isinstance(v, bool):
                saida[chave] = valor.get("username") in com_foto
            elif chave == "midia":
                saida[chave] = midias.get(valor.get("id"))
            else:
                saida[chave] = para_o_site(v, com_capa, com_foto, midias)
        return saida
    if isinstance(valor, list):
        return [para_o_site(v, com_capa, com_foto, midias) for v in valor]
    return valor


def _copiar(origem: Path, alvo: Path) -> None:
    alvo.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origem, alvo)


def _arquivos(con, destino: Path, itens: dict, contas: list[str]) -> tuple[set[str], set[str], dict[str, dict]]:
    """Copia para o site o que já está baixado: as capas das menções, as fotos das contas e a mídia salva dos stories.
    A capa do story sai da imagem que o coletor salvou, como no servidor. Devolve os ids com capa, as contas com foto e
    a mídia de cada story."""
    com_capa, com_foto, midias = set(), set(), {}
    stories = dict(con.execute("SELECT post_id, arquivo FROM posts WHERE tipo = 'Story' AND arquivo IS NOT NULL"))
    for post_id in itens:
        alvo = destino / "capa" / f"{nome_arquivo(post_id)}.jpg"
        origem = capas.arquivo_post(post_id)
        if origem is not None and origem.exists():
            _copiar(origem, alvo)
            com_capa.add(post_id)
        elif (imagem := capas.imagem_do_story(stories.get(post_id))) and capas.guardar_arquivo(imagem, alvo):
            com_capa.add(post_id)
        if (midia := painel._arquivo_midia(stories.get(post_id))) is not None:
            alvo = destino / "midia" / f"{nome_arquivo(post_id)}{midia.suffix.lower()}"
            _copiar(midia, alvo)
            midias[post_id] = {"tipo": "video" if midia.suffix.lower() == ".mp4" else "imagem",
                               "url": f"midia/{alvo.name}"}
    for username in contas:
        origem = capas.arquivo_foto(username)
        if origem is not None and origem.exists():
            _copiar(origem, destino / "foto" / f"{nome_arquivo(username)}.jpg")
            com_foto.add(username)
    return com_capa, com_foto, midias


class _Site:
    def __init__(self, raiz: Path, com_capa: set[str], com_foto: set[str], midias: dict[str, dict]):
        self.raiz = raiz
        self.com_capa, self.com_foto, self.midias = com_capa, com_foto, midias
        self.nomes: set[str] = set()
        self.arquivos = 0
        self.tamanho = 0

    def ajustar(self, dados):
        return para_o_site(dados, self.com_capa, self.com_foto, self.midias)

    def gravar(self, caminho: str, dados) -> None:
        if caminho.lower() in self.nomes:  # dois ids com o mesmo nome de arquivo
            raise ValueError(f"Dois arquivos com o nome {caminho}.")
        self.nomes.add(caminho.lower())
        corpo = json.dumps(self.ajustar(dados), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        destino = self.raiz / caminho
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(corpo)
        self.arquivos += 1
        self.tamanho += len(corpo)


def _preparar(destino: Path) -> None:
    """Pasta vazia, ou um site gerado antes (tem o .nojekyll): os dados e as imagens antigos saem. Pasta com outros
    arquivos não é tocada."""
    if destino.exists() and any(destino.iterdir()):
        if not (destino / ".nojekyll").exists():
            raise FileExistsError(f"A pasta {destino} já tem outros arquivos: escolha uma pasta vazia para o site.")
        for pasta in PASTAS:
            shutil.rmtree(destino / pasta, ignore_errors=True)
    destino.mkdir(parents=True, exist_ok=True)


def _pagina(destino: Path) -> None:
    """Os arquivos da página, com o estatico.js carregado antes do app.js."""
    for arquivo in painel.WEB.rglob("*"):
        if arquivo.is_file():
            _copiar(arquivo, destino / arquivo.relative_to(painel.WEB))
    html = (painel.WEB / "index.html").read_bytes().decode("utf-8")
    app = '<script type="module" src="app.js"></script>'
    if app not in html:
        raise RuntimeError("O index.html não carrega o app.js como esperado.")
    quebra = "\r\n" if "\r\n" in html else "\n"
    html = html.replace(app, f'<script src="estatico.js"></script>{quebra}  {app}')
    (destino / "index.html").write_bytes(html.encode("utf-8"))
    (destino / ".nojekyll").write_bytes(b"")  # o GitHub Pages entrega os arquivos como estão, sem o Jekyll


def _contas_do_painel(con) -> list[str]:
    """As contas a que a página leva: a página Contas, a busca, as fichas e o mapa só mostram as monitoradas e as que
    publicaram sobre a Energisa."""
    monitoradas = json.dumps(painel.monitoradas(con))
    return sorted(l[0] for l in con.execute(painel.SQL_CONTAS_TODAS, (monitoradas,)))


def _ids_das_fileiras(con, contas: list[str]) -> list[str]:
    """Toda fileira a que a página chega: as fixas, as dos setores, as de cada município (menções e contas da cidade)
    e as de cada conta."""
    ids = [*painel.LINHAS, *(f"setor-{s}" for s in painel.NOMES_SETOR)]
    for (ibge,) in con.execute("SELECT ibge_id FROM municipios ORDER BY ibge_id").fetchall():
        ids += [f"municipio-{ibge}", f"cidade-{ibge}"]
    return ids + [f"conta-{u}" for u in contas]


def _paginas(con, rota: str, q: dict, agora) -> list[dict]:
    """Todas as páginas de uma lista paginada (fileira ou contas)."""
    respostas = []
    while True:
        resposta = painel.responder(con, rota, q | {"pagina": str(len(respostas))}, agora)
        respostas.append(resposta)
        if not resposta["mais"]:
            return respostas


def _fileira(con, linha_id: str, itens: dict, site: _Site, agora) -> dict | None:
    """Uma fileira: título, formato, filtros padrão e, para cada combinação de filtros que a página pode pedir, os ids
    dos cartões de cada página."""
    base = painel.responder(con, f"linha/{linha_id}", {}, agora)
    if base is None:
        return None
    padrao = base["filtros"]
    saida = {"titulo": base["titulo"], "formato": base["formato"], "padrao": padrao, "combos": {}}
    if not painel.linha(con, linha_id, 0, {"dias": "todos", "sentimento": ""}, agora=agora)["itens"]:
        saida["vazia"] = True  # nada em período nenhum: qualquer filtro dá a fileira vazia
        return saida
    # Sentimento vazio não chega ao servidor (o parse_qs o descarta): fileira com sentimento padrão nunca fica sem ele.
    sentimentos = [padrao["sentimento"]] + [s for s in SENTIMENTOS if s != padrao["sentimento"]]
    ordens = [padrao["ordem"]] + [o for o in painel.ORDENS if o != padrao["ordem"]]  # endereço salvo pode trazer outra
    for dias in dict.fromkeys([padrao["dias"], *DIAS]):
        for sentimento in sentimentos:
            for ordem in ordens:
                q = {"dias": _chave_dias(dias), "ordem": ordem} | ({"sentimento": sentimento} if sentimento else {})
                paginas = _paginas(con, f"linha/{linha_id}", q, agora)
                if any(site.ajustar(itens.get(p["id"])) != site.ajustar(p) for r in paginas for p in r["itens"]):
                    raise RuntimeError(f"Cartão da fileira {linha_id} diferente do de api/itens.json.")
                f = paginas[0]["filtros"]
                chave = f"{_chave_dias(f['dias'])}|{f['sentimento'] or ''}|{f['ordem']}"
                saida["combos"][chave] = [[p["id"] for p in r["itens"]] for r in paginas]
    return saida


def _contas(con, agora) -> dict:
    """A página Contas em cada filtro de tipo e ordem, com todas as páginas."""
    combos, tipos = {}, []
    for tipo in ("", *painel.TIPOS_CONTA, "influenciador"):
        for ordem in painel.ORDENS_CONTAS:
            paginas = _paginas(con, "contas", {"ordem": ordem} | ({"tipo": tipo} if tipo else {}), agora)
            combos[f"{tipo}|{ordem}"] = [r["itens"] for r in paginas]
            tipos = paginas[0]["tipos"]
    return {"tipos": tipos, "combos": combos}


def _indice_da_busca(con) -> dict:
    """O texto em que a busca procura, já como o servidor o compara (sem acento e minúsculo), na ordem do resultado:
    contas das que mais falam da Energisa para as que menos; menções das mais novas para as mais antigas."""
    monitoradas = json.dumps(painel.monitoradas(con))
    contas = [painel._cartao_conta(l, set()) | {"busca": [l["username"], painel.normalizar(l["nome"])]}
              for l in con.execute(painel.SQL_CONTAS_TODAS + f" ORDER BY {painel.ORDENS_CONTAS['mencoes']}",
                                   (monitoradas,))]
    posts = [{"id": l["post_id"], "busca": painel.normalizar(l["legenda"]) + "\n" + painel.normalizar(l["resumo"])}
             for l in con.execute(painel.SQL_POST + " ORDER BY p.publicado_em DESC")]
    return {"contas": contas, "posts": posts}


def exportar(con, destino: Path | str, agora: datetime | None = None) -> dict:
    """Grava o site em `destino`, com o banco lido numa transação só. Devolve quantos arquivos de dados ele tem e o
    tamanho deles, quantas menções e contas, os ids com capa, as contas com foto e a mídia dos stories."""
    fotografia = not con.in_transaction
    if fotografia:
        con.execute("BEGIN")  # a coleta pode gravar enquanto o site é gerado: tudo sai do mesmo instante do banco
    try:
        return _exportar(con, Path(destino), agora or painel._agora())
    finally:
        if fotografia:
            con.rollback()


def _exportar(con, destino: Path, agora: datetime) -> dict:
    _preparar(destino)
    _pagina(destino)
    contas = _contas_do_painel(con)
    itens = {p["id"]: p for p in painel.posts(con, {}, 1_000_000, agora=agora)[0]}
    site = _Site(destino, *_arquivos(con, destino, itens, contas))
    site.gravar("api/status.json", painel.responder(con, "status", {}, agora) | {"estatico": True})
    for rota in ("inicio", "mapa-base"):
        site.gravar(f"api/{rota}.json", painel.responder(con, rota, {}, agora))
    site.gravar("api/itens.json", itens)
    for post_id in itens:
        site.gravar(f"api/post/{nome_arquivo(post_id)}.json", painel.responder(con, f"post/{post_id}", {}, agora))
    for linha_id in _ids_das_fileiras(con, contas):
        dados = _fileira(con, linha_id, itens, site, agora)
        if dados is not None:
            site.gravar(f"api/linha/{nome_arquivo(linha_id)}.json", dados)
    for username in contas:
        dados = painel.responder(con, f"conta/{username}", {}, agora)
        if dados is not None:
            site.gravar(f"api/conta/{nome_arquivo(username)}.json", dados)
    for (ibge,) in con.execute("SELECT ibge_id FROM municipios ORDER BY ibge_id").fetchall():
        site.gravar(f"api/municipio/{ibge}.json", painel.responder(con, f"municipio/{ibge}", {}, agora))
    site.gravar("api/contas.json", _contas(con, agora))
    for dias in DIAS:
        for sentimento in (None, *SENTIMENTOS):
            q = ({"dias": _chave_dias(dias)} if dias else {}) | ({"sentimento": sentimento} if sentimento else {})
            sufixo = f"{_chave_dias(dias)}_{sentimento or 'todas'}"
            site.gravar(f"api/setores/{sufixo}.json", painel.responder(con, "setores", q, agora))
            site.gravar(f"api/mapa/mencoes_{sufixo}.json",
                        painel.responder(con, "mapa", q | {"camada": "mencoes"}, agora))
    site.gravar("api/mapa/perfis.json", painel.responder(con, "mapa", {"camada": "perfis"}, agora))
    site.gravar("api/busca.json", _indice_da_busca(con))
    return {"arquivos": site.arquivos, "bytes": site.tamanho, "mencoes": len(itens), "contas": len(contas),
            "com_capa": site.com_capa, "com_foto": site.com_foto, "midias": site.midias}
