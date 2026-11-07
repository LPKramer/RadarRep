"""Menções à Energisa com engajamento e repercussão. O painel usa a repercussão: quantas contas trataram do mesmo
assunto no mesmo lugar em até 3 dias, e se algum portal estadual cobriu."""
from datetime import timedelta

import pandas as pd

JANELA_REPERCUSSAO = timedelta(days=3)

SQL = """
SELECT p.post_id, p.publicado_em, p.rede,
       CASE WHEN p.rede = 'web' THEN COALESCE(c.nome, p.username) ELSE p.username END AS conta,
       p.tipo AS formato, p.arquivo,
       COALESCE(k.tipo, CASE WHEN p.rede = 'web' THEN 'site_noticias' END) AS tipo_conta, k.abrangencia AS abrangencia_conta,
       c.seguidores, c.engajamento_medio, x.tema, x.setor, x.sentimento, x.alcance, x.cita_energisa,
       (SELECT GROUP_CONCAT(m.nome, '; ') FROM mencao_municipio mm JOIN municipios m ON m.ibge_id = mm.ibge_id
         WHERE mm.rede = x.rede AND mm.post_id = x.post_id) AS municipios,
       p.curtidas, p.comentarios, p.visualizacoes, p.medido_em, x.reacao, x.reacao_resumo, x.n_comentarios_lidos,
       x.resumo, x.confianca, p.legenda, p.url AS link
FROM mencoes x
JOIN posts p ON p.rede = x.rede AND p.post_id = x.post_id
JOIN contas c ON c.rede = p.rede AND c.username = p.username
LEFT JOIN classificacoes k ON k.rede = p.rede AND k.username = p.username
WHERE x.sobre_energia = 1
"""

COLUNAS = ["data", "conta", "rede", "formato", "tipo_conta", "abrangencia_conta", "seguidores", "tema", "setor", "sentimento",
           "alcance",
           "municipios", "cita_energisa", "curtidas", "comentarios", "visualizacoes", "interacoes", "engajamento_pct",
           "indice_vs_media_da_conta", "contas_que_repercutiram", "teve_cobertura_estadual", "horas_ate_medicao",
           "reacao", "reacao_resumo", "n_comentarios_lidos", "resumo", "confianca", "legenda", "link", "arquivo", "post_id"]


def carregar(con, desde: str | None = None) -> pd.DataFrame:
    sql, args = SQL, []
    if desde:
        sql += " AND p.publicado_em >= ?"
        args.append(desde)
    df = pd.read_sql_query(sql + " ORDER BY p.publicado_em DESC", con, params=args)
    if df.empty:
        return pd.DataFrame(columns=COLUNAS)

    publicado = pd.to_datetime(df["publicado_em"], utc=True, errors="coerce")
    df["data"] = publicado.dt.strftime("%Y-%m-%d")
    df["municipios"] = df["municipios"].fillna("")
    df["setor"] = df["setor"].fillna("(sem setor)")
    df["interacoes"] = df["curtidas"].fillna(0) + df["comentarios"].fillna(0)
    df["engajamento_pct"] = (100 * df["interacoes"] / df["seguidores"].where(df["seguidores"] > 0)).round(2)
    # >1 = o post rendeu mais que a média dos posts recentes da própria conta.
    df["indice_vs_media_da_conta"] = (df["interacoes"] / df["engajamento_medio"].where(df["engajamento_medio"] > 0)
                                      ).round(2)
    medido = pd.to_datetime(df["medido_em"], utc=True, errors="coerce")
    df["horas_ate_medicao"] = ((medido - publicado).dt.total_seconds() / 3600).round(0)
    df["cita_energisa"] = df["cita_energisa"].map({1: "sim", 0: "não"})
    contas, estadual = repercussao(df.assign(_quando=publicado))
    df["contas_que_repercutiram"] = contas
    df["teve_cobertura_estadual"] = estadual.map({True: "sim", False: "não"})
    return df[COLUNAS]


def repercussao(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Para cada menção: quantas contas falaram do mesmo tema, no mesmo município (ou, sem município, com o mesmo
    alcance estadual/nacional), até 3 dias antes ou depois; e se alguma delas tem cobertura estadual."""
    linhas = df.to_dict("records")
    municipios = [set(filter(None, r["municipios"].split("; "))) for r in linhas]
    contas, estadual = [], []
    for i, r in enumerate(linhas):
        grupo = set()
        for j, s in enumerate(linhas):
            if s["tema"] != r["tema"] or pd.isna(r["_quando"]) or pd.isna(s["_quando"]):
                continue
            if abs(s["_quando"] - r["_quando"]) > JANELA_REPERCUSSAO:
                continue
            mesmo_lugar = (municipios[i] & municipios[j] if municipios[i] and municipios[j]
                           else r["alcance"] == s["alcance"] and r["alcance"] in ("estadual", "nacional"))
            if mesmo_lugar or i == j:
                grupo.add(j)
        contas.append(len({linhas[j]["conta"] for j in grupo}))
        estadual.append(any(linhas[j]["abrangencia_conta"] == "estadual" for j in grupo))
    return pd.Series(contas, index=df.index), pd.Series(estadual, index=df.index)
