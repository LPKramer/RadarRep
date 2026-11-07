# Radar de Reputação: painel

Painel web, no estilo dos serviços de streaming, para acompanhar o que se publica sobre a Energisa no Tocantins: posts
e stories do Instagram e matérias de sites de notícia. Ele mostra só o que tem a ver com a empresa, direta ou
indiretamente: o que cita a Energisa e o que trata do serviço de energia sem citá-la (falta de luz, poste caído,
conta, obra na rede). A página Contas é a exceção: lista todas as contas monitoradas.

Este repositório tem **só a visualização** e um banco de demonstração com as notícias. A coleta (a vigilância das
contas, a leitura dos stories, a busca de matérias e a análise das menções pela IA) não está aqui. O painel lê o banco
`radar.db` que a coleta do Radar gera, sem gravar nada nele, e pode ficar aberto enquanto ela roda.

## Como rodar

Precisa do Python 3.11 ou mais novo.

```powershell
pip install -r requirements.txt
python -m radar painel
```

O painel abre em http://127.0.0.1:8787 com as notícias de demonstração (`demo/radar.db`). Para usar o banco da coleta:

```powershell
python -m radar painel --banco C:\caminho\radar.db
python -m radar painel --dados C:\caminho\data   # pasta com radar.db, capas/ e stories/ da coleta
python -m radar painel --rede                    # também no celular, na mesma rede Wi-Fi
python -m radar capas                            # baixa agora as capas e fotos que faltam
```

Se existir `data/radar.db` ao lado do código, ele é usado no lugar da demonstração. A pasta `data/` está no
`.gitignore`.

## Notícias de demonstração

`demo/radar.db` traz as 104 menções à Energisa da base, de outubro de 2025 a novembro de 2026:

- 59 posts e stories do Instagram;
- 45 matérias de 22 sites de notícia;
- a análise da IA de cada uma (tema, setor, sentimento, alcance, municípios, resumo);
- as 64 contas e sites que as publicaram;
- os 139 municípios do Tocantins.

Ficam de fora o resto da coleta, os comentários (texto de terceiros), as bios das contas e as imagens. Sem imagem,
cada cartão vira um cartaz com a manchete.

## O que tem em cada tela

- **Início:** destaque com as menções dos últimos 14 dias (negativas primeiro), Top 10 da semana no Instagram, e
  fileiras de menções: todas, negativas, notícias de sites, as que citam a Energisa, as que falam de energia sem
  citá-la, stories, reels, por tipo de conta, por município e as contas que mais falam da Energisa.
- **Ficha da menção:** a análise da IA (tema, setor, sentimento, alcance, resumo), os números, a repercussão, os
  comentários lidos e a localização aproximada num mapa. Matéria de site abre o link da notícia.
- **Menções, Notícias, Reels e Stories:** grade com filtros de período, sentimento e ordem.
- **Setores:** as menções separadas pelo setor da empresa que teria de responder ou agir (operação, manutenção,
  atendimento, comercial, obras e expansão, segurança, RH, institucional, regulatório e jurídico). Para cada setor há
  uma barra com as negativas, neutras e positivas e uma fileira de cartões.
- **Contas:** todas as contas monitoradas, das mais seguidas para as menos ou das que mais falam da Energisa.
- **Mapa:** cada menção no seu município, com zoom. A cor do município diz quantas menções ele tem, e a lista ao lado
  traz a mesma contagem em texto.
- **Busca:** procura no texto das menções, no resumo da IA e no nome das contas, sem diferença de acento.

## Localização aproximada

Uma menção fica no município que a IA apontou no fato. Sem isso, vale o município da marcação de local do post;
depois, o primeiro citado no texto, só com inicial maiúscula ("salva de palmas" não vira Palmas); por fim, a cidade
da conta. A ficha diz de onde veio a pista (`radar/localizacao.py`).

## Imagens

O banco da coleta guarda o endereço da capa de cada post e da foto de cada perfil. O Instagram invalida esses
endereços em uns 4 dias, então o painel baixa as imagens em segundo plano para a pasta `capas/` dos dados, direto da
rede de distribuição do Instagram, sem login (`radar/capas.py`).

## Estrutura

```
radar/
  painel.py        servidor e consultas (API em /api/...)
  web/             a página: index.html, app.js, estilo.css, fontes e marca
  capas.py         imagens das menções e fotos dos perfis
  localizacao.py   município aproximado de cada menção e conta
  app_dados.py     mapa do Tocantins em SVG (malha do IBGE em dados/)
  relatorio.py     repercussão das menções
  monitoramento.py quais contas o Radar monitora
  config.py, db.py, municipios.py, __main__.py
demo/radar.db      notícias de demonstração
```

O banco precisa das tabelas que a coleta cria: `posts`, `mencoes`, `mencao_municipio`, `contas`, `classificacoes`,
`score`, `revisao`, `listas`, `conta_municipio`, `municipios`, `comentarios` e `visitas`.

## Visual e créditos

O visual foi feito com a skill [ui-ux-pro-max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), no padrão
"Video Streaming/OTT": tema escuro e destaque dominante no topo. A tipografia é Barlow Condensed nos títulos e Barlow
no texto, sob a licença SIL Open Font License (`radar/web/fontes/OFL.txt`). O logo e as cores são da identidade
visual da Energisa e pertencem a ela. A malha dos municípios é do IBGE. As notícias pertencem aos veículos e contas
que as publicaram; o painel traz o link de cada uma.
