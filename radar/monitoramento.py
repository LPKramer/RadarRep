"""Quais contas o Radar monitora (a página Contas lista todas elas). Só a consulta: a coleta fica fora deste repositório."""

# A IA ligou a conta ao TO: abrangência estadual ou algum município do TO.
SQL_DO_TO_PELA_IA = ("(k.abrangencia = 'estadual' OR EXISTS (SELECT 1 FROM conta_municipio cm WHERE cm.rede = c.rede "
                     "AND cm.username = c.username AND cm.fonte = 'ia'))")
LISTAS_MONITORADAS = ("mais_seguidas_to", "influenciadores_to")

# Monitoradas: prioridade A/B, aprovadas na revisão, as das listas (mais seguidas e influenciadores do TO) e todas
# as páginas de fofoca do TO, mesmo as de score baixo, menos as rejeitadas.
SQL_MONITORADAS = f"""
SELECT c.username, c.profundidade FROM contas c
LEFT JOIN score s ON s.rede = c.rede AND s.username = c.username
LEFT JOIN revisao r ON r.rede = c.rede AND r.username = c.username
LEFT JOIN classificacoes k ON k.rede = c.rede AND k.username = c.username
WHERE c.rede = 'instagram' AND COALESCE(r.status, 'pendente') != 'rejeitada'
  AND (s.prioridade IN ('A', 'B') OR r.status = 'aprovada'
       OR EXISTS (SELECT 1 FROM listas l WHERE l.rede = c.rede AND l.username = c.username
                  AND l.lista IN ({', '.join(f"'{l}'" for l in LISTAS_MONITORADAS)}))
       OR (k.tipo = 'perfil_fofoca' AND c.descartada IS NULL AND COALESCE(c.privada, 0) = 0
           AND {SQL_DO_TO_PELA_IA}))
ORDER BY s.valor DESC, c.seguidores DESC
"""


def monitoradas(con, limite: int | None = None) -> list[dict]:
    contas = [dict(l) for l in con.execute(SQL_MONITORADAS)]
    return contas[:limite] if limite else contas
