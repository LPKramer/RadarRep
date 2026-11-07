"""O painel sem servidor, para o GitHub Pages: grava em arquivos JSON as respostas que a API do painel (painel.py)
daria, e a página lê esses arquivos no lugar do servidor (web/estatico.js). No repositório RadarRep, o comando é
`python -m radar site`.

Cada pedido que as telas podem fazer vira um arquivo: a tela inicial, a ficha de cada menção, a página de cada conta e
de cada município, o mapa e os setores em cada filtro, a lista de contas. As fileiras ("ver tudo") guardam, para cada
combinação de período, sentimento e ordem que a página oferece, os ids dos cartões de cada página; os cartões ficam uma
vez só, em api/itens.json. A busca roda na página, sobre o texto já sem acento de api/busca.json.

É uma fotografia: "7 dias" são os 7 dias antes da geração. As imagens não vão (capa e foto saem como ausentes, e o
cartão vira o cartaz com o texto). Nada é gravado no banco.
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from . import painel

SIMPLES = re.compile(r"[0-9a-z_-][0-9a-z_.-]{0,63}")  # id que já serve de nome de arquivo
DIAS = (7, 30, 90, None)  # os períodos dos filtros da página (DIAS_MENCOES no app.js); None é "Tudo"
SENTIMENTOS = ("negativo", "neutro", "positivo")
SQL_CONTAS = "SELECT username FROM contas WHERE rede = 'instagram' ORDER BY username"


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


def sem_imagens(valor):
    """As imagens não vão para o site: capa e foto saem como ausentes, e a mídia do story também."""
    if isinstance(valor, dict):
        return {k: False if k in ("capa", "foto") and isinstance(v, bool) else None if k == "midia" else sem_imagens(v)
                for k, v in valor.items()}
    if isinstance(valor, list):
        return [sem_imagens(v) for v in valor]
    return valor


class _Site:
    def __init__(self, raiz: Path):
        self.raiz = raiz
        self.nomes: set[str] = set()
        self.arquivos = 0
        self.tamanho = 0

    def gravar(self, caminho: str, dados) -> None:
        if caminho.lower() in self.nomes:  # dois ids com o mesmo nome de arquivo
            raise ValueError(f"Dois arquivos com o nome {caminho}.")
        self.nomes.add(caminho.lower())
        corpo = json.dumps(sem_imagens(dados), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        destino = self.raiz / caminho
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(corpo)
        self.arquivos += 1
        self.tamanho += len(corpo)


def _preparar(destino: Path) -> None:
    """Pasta vazia, ou um site gerado antes (tem o .nojekyll): a api/ antiga sai inteira. Pasta com outros arquivos
    não é tocada."""
    if destino.exists() and any(destino.iterdir()):
        if not (destino / ".nojekyll").exists():
            raise FileExistsError(f"A pasta {destino} já tem outros arquivos: escolha uma pasta vazia para o site.")
        shutil.rmtree(destino / "api", ignore_errors=True)
    destino.mkdir(parents=True, exist_ok=True)


def _pagina(destino: Path) -> None:
    """Os arquivos da página, com o estatico.js carregado antes do app.js."""
    for arquivo in painel.WEB.rglob("*"):
        if arquivo.is_file():
            alvo = destino / arquivo.relative_to(painel.WEB)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(arquivo, alvo)
    html = (painel.WEB / "index.html").read_bytes().decode("utf-8")
    app = '<script type="module" src="app.js"></script>'
    if app not in html:
        raise RuntimeError("O index.html não carrega o app.js como esperado.")
    quebra = "\r\n" if "\r\n" in html else "\n"
    html = html.replace(app, f'<script src="estatico.js"></script>{quebra}  {app}')
    (destino / "index.html").write_bytes(html.encode("utf-8"))
    (destino / ".nojekyll").write_bytes(b"")  # o GitHub Pages entrega os arquivos como estão, sem o Jekyll


def _ids_das_fileiras(con) -> list[str]:
    """Toda fileira a que a página chega: as fixas, as dos setores, as de cada município (menções e contas da cidade)
    e as de cada conta."""
    ids = [*painel.LINHAS, *(f"setor-{s}" for s in painel.NOMES_SETOR)]
    for (ibge,) in con.execute("SELECT ibge_id FROM municipios ORDER BY ibge_id").fetchall():
        ids += [f"municipio-{ibge}", f"cidade-{ibge}"]
    return ids + [f"conta-{u}" for (u,) in con.execute(SQL_CONTAS).fetchall()]


def _paginas(con, rota: str, q: dict, agora) -> list[dict]:
    """Todas as páginas de uma lista paginada (fileira ou contas)."""
    respostas = []
    while True:
        resposta = painel.responder(con, rota, q | {"pagina": str(len(respostas))}, agora)
        respostas.append(resposta)
        if not resposta["mais"]:
            return respostas


def _fileira(con, linha_id: str, itens: dict, agora) -> dict | None:
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
                if any(itens.get(p["id"]) != p for r in paginas for p in r["itens"]):
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
    """Grava o site em `destino`. Devolve quantos arquivos de dados ele tem, o tamanho deles e quantas menções."""
    agora = agora or painel._agora()
    destino = Path(destino)
    _preparar(destino)
    _pagina(destino)
    site = _Site(destino)
    site.gravar("api/status.json", painel.responder(con, "status", {}, agora) | {"estatico": True})
    for rota in ("inicio", "mapa-base"):
        site.gravar(f"api/{rota}.json", painel.responder(con, rota, {}, agora))
    itens = {p["id"]: p for p in painel.posts(con, {}, 1_000_000, agora=agora)[0]}
    site.gravar("api/itens.json", itens)
    for post_id in itens:
        site.gravar(f"api/post/{nome_arquivo(post_id)}.json", painel.responder(con, f"post/{post_id}", {}, agora))
    for linha_id in _ids_das_fileiras(con):
        dados = _fileira(con, linha_id, itens, agora)
        if dados is not None:
            site.gravar(f"api/linha/{nome_arquivo(linha_id)}.json", dados)
    for (username,) in con.execute(SQL_CONTAS).fetchall():
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
    return {"arquivos": site.arquivos, "bytes": site.tamanho, "mencoes": len(itens)}
