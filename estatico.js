// O painel sem servidor (GitHub Pages). radar/estatico.py gravou em api/ as respostas que o servidor (radar/painel.py)
// daria; aqui cada pedido do app.js vira a leitura de um desses arquivos, com os filtros tratados como o servidor os
// trata: valor vazio não conta, e período, sentimento ou página inválidos ficam no padrão. As imagens ficam em capa/ e
// foto/.
'use strict'

window.radarEstatico = (() => {
  const SENTIMENTOS = ['negativo', 'neutro', 'positivo']
  const ORDENS = ['recentes', 'interacoes', 'views']
  const ORDENS_CONTAS = ['seguidores', 'mencoes']
  const arquivos = new Map()

  const falha = (status) => Object.assign(new Error(`HTTP ${status}`), { status })

  function ler(caminho) {
    if (!arquivos.has(caminho)) {
      const pedido = fetch(caminho).then((resposta) => {
        if (!resposta.ok) throw falha(resposta.status)
        return resposta.json()
      })
      pedido.catch(() => arquivos.delete(caminho))
      arquivos.set(caminho, pedido)
    }
    return arquivos.get(caminho)
  }

  // O mesmo nome que radar/estatico.py dá ao arquivo de um id: ele mesmo, se curto e simples; senão, "~" e o FNV-1a.
  function nomeArquivo(chave) {
    if (/^[0-9a-z_-][0-9a-z_.-]{0,63}$/.test(chave)) return chave
    let h = 0x811c9dc5
    for (const byte of new TextEncoder().encode(chave)) h = Math.imul(h ^ byte, 0x01000193) >>> 0
    return '~' + h.toString(16).padStart(8, '0')
  }

  // Como o parse_qs do servidor: valor vazio não conta, e vale o último.
  const valor = (q, chave) => q.getAll(chave).filter(Boolean).pop() || ''
  // Como o _dias do servidor: número de dias maior que zero; o resto (inclusive "todos") é null.
  function numeroDeDias(texto) {
    const n = Number(texto)
    return texto && Number.isFinite(n) && n > 0 ? n : null
  }
  const chaveDias = (dias) => (dias == null ? 'todos' : String(dias))
  const sentimentoValido = (s) => (SENTIMENTOS.includes(s) ? s : null)
  // Como o normalizar do servidor (unidecode e minúsculas), para o texto digitado na busca.
  const normalizar = (texto) => String(texto || '').normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase()

  async function fileira(id, q, pagina) {
    const [itens, dados] = await Promise.all([ler('api/itens.json'), ler(`api/linha/${nomeArquivo(id)}.json`)])
    let { dias, sentimento, ordem } = dados.padrao
    const d = valor(q, 'dias')
    if (dados.periodos) { // aba Recentes: só os períodos dela, e sem filtro de sentimento
      if (dados.periodos.includes(numeroDeDias(d))) dias = numeroDeDias(d)
    } else {
      if (d === 'todos') dias = null
      else if (numeroDeDias(d) != null) dias = numeroDeDias(d)
      sentimento = sentimentoValido(valor(q, 'sentimento')) || sentimento
    }
    ordem = valor(q, 'ordem') || ordem
    const chave = `${chaveDias(dias)}|${sentimento || ''}|${ORDENS.includes(ordem) ? ordem : 'recentes'}`
    const paginas = dados.vazia ? [[]] : dados.combos[chave]
    if (!paginas) throw falha(404)
    return {
      id, titulo: dados.titulo, formato: dados.formato, itens: (paginas[pagina] || []).map((i) => itens[i]),
      mais: pagina + 1 < paginas.length, filtros: { dias, sentimento: sentimento || null, ordem },
      ...(dados.periodos ? { periodos: dados.periodos } : {}),
    }
  }

  async function contas(q, pagina) {
    const dados = await ler('api/contas.json')
    const ordem = ORDENS_CONTAS.includes(valor(q, 'ordem')) ? valor(q, 'ordem') : 'seguidores'
    const paginas = dados.combos[`${valor(q, 'tipo')}|${ordem}`] || [[]]
    return { itens: paginas[pagina] || [], mais: pagina + 1 < paginas.length, tipos: dados.tipos, ordem }
  }

  function setores(q) {
    const nome = `${chaveDias(numeroDeDias(valor(q, 'dias')))}_${sentimentoValido(valor(q, 'sentimento')) || 'todas'}`
    return ler(`api/setores/${nome}.json`)
  }

  async function mapa(q) {
    const dias = numeroDeDias(valor(q, 'dias'))
    const sentimento = valor(q, 'sentimento') || null
    const camada = valor(q, 'camada')
    const nome = camada === 'perfis' || camada === 'base' ? camada
      : `mencoes_${chaveDias(dias)}_${sentimentoValido(sentimento) || 'todas'}`
    return { ...(await ler(`api/mapa/${nome}.json`)), dias, sentimento } // o servidor devolve os filtros como vieram
  }

  async function busca(termo) {
    const t = normalizar(termo).trim()
    if (t.length < 2) return { q: termo, contas: [], posts: [] }
    const [itens, indice] = await Promise.all([ler('api/itens.json'), ler('api/busca.json')])
    return {
      q: termo,
      contas: indice.contas.filter((c) => c.busca.some((texto) => texto.includes(t))).slice(0, 24)
        .map(({ busca: _, ...cartao }) => cartao),
      posts: indice.posts.filter((p) => p.busca.includes(t)).slice(0, 96).map((p) => itens[p.id]),
    }
  }

  async function api(caminho) {
    const [rota, consulta = ''] = caminho.split('?')
    const q = new URLSearchParams(consulta)
    const [recurso, ...resto] = rota.split('/')
    const alvo = decodeURIComponent(resto.join('/'))
    const pagina = /^\d+$/.test(valor(q, 'pagina')) ? Number(valor(q, 'pagina')) : 0
    if (['status', 'inicio', 'mapa-base'].includes(recurso)) return ler(`api/${recurso}.json`)
    if (recurso === 'linha' && alvo) return fileira(alvo, q, pagina)
    if (recurso === 'post' && alvo) return ler(`api/post/${nomeArquivo(alvo)}.json`)
    if (recurso === 'conta' && alvo) return ler(`api/conta/${nomeArquivo(alvo.toLowerCase())}.json`)
    if (recurso === 'municipio' && /^\d+$/.test(alvo)) return ler(`api/municipio/${Number(alvo)}.json`)
    if (recurso === 'contas') return contas(q, pagina)
    if (recurso === 'setores') return setores(q)
    if (recurso === 'mapa') return mapa(q)
    if (recurso === 'busca') return busca(valor(q, 'q'))
    throw falha(404)
  }

  // A capa do post (tipo "capa") ou a foto da conta ("foto"), com o mesmo nome de arquivo dos dados.
  const imagem = (tipo, chave) => `${tipo}/${nomeArquivo(chave)}.jpg`

  return { api, nomeArquivo, imagem }
})()
