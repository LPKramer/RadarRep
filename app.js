// Painel do radar. Sem framework: o servidor (radar/painel.py) entrega JSON e as capas; aqui só montamos a tela.

const ROT = {
  tema: {
    falta_energia: 'Falta de energia', desligamento_programado: 'Desligamento programado', conta_tarifa: 'Conta e tarifa',
    atendimento: 'Atendimento', obras_investimento: 'Obras e investimento', acidente_seguranca: 'Acidente e segurança',
    iluminacao_publica: 'Iluminação pública', institucional: 'Institucional', outro: 'Outro assunto de energia',
  },
  setor: {
    operacao: 'Operação', manutencao: 'Manutenção', atendimento: 'Atendimento', comercial: 'Comercial',
    obras_expansao: 'Obras e expansão', seguranca: 'Segurança', rh: 'RH', institucional: 'Institucional',
    regulatorio_juridico: 'Regulatório e jurídico', nenhum: 'Fora da Energisa',
  },
  alcance: { local: 'Local', regional: 'Regional', estadual: 'Estadual', nacional: 'Nacional' },
  tipo: {
    portal_noticias: 'Portal', pagina_cidade_comunidade: 'Página de cidade', jornalista_radialista: 'Jornalista',
    perfil_fofoca: 'Fofoca', policial_plantao: 'Plantão policial', influenciador_local: 'Influenciador',
    orgao_publico: 'Órgão público', politico: 'Político', irrelevante: 'Outro perfil',
  },
  reacao: {
    negativa: 'Comentários negativos', positiva: 'Comentários positivos', mista: 'Comentários divididos',
    neutra: 'Comentários neutros',
  },
  sentimento: { negativo: 'Negativa', neutro: 'Neutra', positivo: 'Positiva' },
  formato: { Image: 'Foto', Video: 'Reel', Sidecar: 'Carrossel', Story: 'Story', Materia: 'Matéria' },
}
const COR = { negativo: 'var(--negativo)', neutro: 'var(--neutro)', positivo: 'var(--positivo)' }
const COR_REACAO = { negativa: 'var(--negativo)', positiva: 'var(--positivo)', mista: 'var(--texto)', neutra: 'var(--neutro)' }

const SVG = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`
const SETA_DIR = SVG('m9 5 7 7-7 7')
const SETA_ESQ = SVG('m15 5-7 7 7 7')
const FECHAR = SVG('M6 6l12 12M18 6 6 18')

const conteudo = document.getElementById('conteudo')
const modal = document.getElementById('modal')
const previa = document.getElementById('previa')
const topo = document.getElementById('topo')
const campoBusca = document.getElementById('busca')
const aoVivo = document.getElementById('ao-vivo')
const botaoNovidades = document.getElementById('novidades')
const anuncio = document.getElementById('anuncio')
const reduzir = matchMedia('(prefers-reduced-motion: reduce)')
const podeHover = matchMedia('(hover: hover) and (pointer: fine)')
const ITENS = new Map() // post por id, para a prévia

// ---------- Formatos ----------
const fmtCompacto = new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 })
const fmtInteiro = new Intl.NumberFormat('pt-BR')
const fmtDecimal = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 })
const fmtData = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const fmtDia = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'short' })

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
const enc = encodeURIComponent
const linkSeguro = (url) => (/^https:\/\//.test(url || '') ? url : '') // só https: nada de javascript: vindo do banco
// Post do Instagram: @conta; matéria de site de notícia (rede "web"): o nome do site.
const ehSite = (p) => p.rede === 'web'
const autor = (p) => (ehSite(p) ? p.nome || p.conta : '@' + p.conta)
const textoLink = (p) => (ehSite(p) ? 'Abrir a matéria' : 'Abrir no Instagram')
const compacto = (n) => (n == null ? '–' : fmtCompacto.format(n))
const inteiro = (n) => (n == null ? '–' : fmtInteiro.format(n))
const porcento = (n) => `${fmtDecimal.format(n)}%`
const vezes = (n) => `${fmtDecimal.format(n)}×`
const plural = (n, um, varios) => (n === 1 ? um : varios)
const suave = () => (reduzir.matches ? 'auto' : 'smooth')

function quando(iso) {
  if (!iso) return ''
  const data = new Date(iso)
  const s = (Date.now() - data) / 1000
  if (s < 90) return 'agora'
  if (s < 3600) return `há ${Math.round(s / 60)} min`
  if (s < 86400) return `há ${Math.round(s / 3600)} h`
  const dias = Math.floor(s / 86400)
  if (dias === 1) return 'ontem'
  if (dias < 7) return `há ${dias} dias`
  return fmtDia.format(data).replace('.', '')
}
const dataCompleta = (iso) => (iso ? fmtData.format(new Date(iso)) : '')

// No GitHub Pages não há servidor: o estatico.js responde com os arquivos que `python -m radar site` gravou.
const estatico = window.radarEstatico
const SEM_RESPOSTA = estatico
  ? 'Os dados do painel não carregaram. Recarregue a página.'
  : 'O painel não respondeu. Confira se o comando python -m radar painel continua aberto.'
// Capa do post e foto da conta: o servidor as entrega em capa/<id> e foto/<conta>; o site, em arquivos .jpg.
const urlCapa = (id) => (estatico ? estatico.imagem('capa', id) : `capa/${enc(id)}`)
const urlFoto = (username) => (estatico ? estatico.imagem('foto', username) : `foto/${enc(username)}`)

async function api(caminho) {
  if (estatico) return estatico.api(caminho)
  const resposta = await fetch('api/' + caminho, { cache: 'no-store' })
  if (!resposta.ok) {
    const erro = new Error(`HTTP ${resposta.status}`)
    erro.status = resposta.status
    throw erro
  }
  return resposta.json()
}

// ---------- Cartões ----------
function cartaz(texto, brilho) {
  const estilo = brilho ? ` style="--brilho:${brilho}"` : ''
  return `<span class="cartaz" aria-hidden="true"${estilo}>${texto ? `<span class="cartaz-texto">${esc(texto)}</span>` : ''}</span>`
}

function textoCartaz(p, formato) {
  // O texto do story é OCR: o resumo da IA (todo story no painel é sobre a Energisa) ou o nome da conta dizem mais.
  if (p.formato === 'Story') return p.mencao?.resumo || p.nome || '@' + p.conta
  if (formato === 'mencao' && p.mencao?.resumo) return p.mencao.resumo
  return p.titulo || p.mencao?.resumo || '@' + p.conta
}

function metaCartao(p, formato) {
  if (formato === 'mencao') return [ROT.tema[p.mencao?.tema], quando(p.data)].filter(Boolean).join(' · ')
  if (formato === 'story') return quando(p.data)
  if (ehSite(p)) return ['Matéria', quando(p.data)].join(' · ') // site não tem curtidas
  if (p.formato === 'Video' && p.views) return `${compacto(p.views)} visualizações`
  return `${compacto(p.interacoes)} interações`
}

function cardPost(p, formato = 'post', prefixo = '') {
  ITENS.set(p.id, p)
  const sentimento = p.mencao?.sentimento
  const cor = sentimento ? COR[sentimento] : ''
  const meta = metaCartao(p, formato)
  const rotulo = [prefixo, autor(p), ROT.formato[p.formato],
    sentimento ? `menção ${ROT.sentimento[sentimento].toLowerCase()}` : '', meta].filter(Boolean).join(', ')
  return `<button class="card" type="button" data-formato="${formato}" data-post="${esc(p.id)}"${cor ? ` style="--cor:${cor}"` : ''} aria-label="${esc(rotulo)}">`
    + cartaz(textoCartaz(p, formato), cor)
    + (p.capa ? `<img class="card-midia" src="${urlCapa(p.id)}" alt="" loading="lazy" decoding="async" data-cai>` : '')
    + (sentimento ? `<span class="card-faixa"></span><span class="card-selo">${ROT.sentimento[sentimento]}</span>` : '')
    + `<span class="card-rodape"><span class="card-conta">${esc(autor(p))}</span><span class="card-meta">${esc(meta)}</span></span>`
    + '</button>'
}

function iniciais(c) {
  const base = (c.nome || c.username).normalize('NFKD').replace(/[^\p{L}\p{N}\s]/gu, ' ').trim()
  const partes = base.split(/\s+/).filter(Boolean)
  return (partes.length > 1 ? partes[0][0] + partes[1][0] : (partes[0] || c.username).slice(0, 2)).toUpperCase()
}

function cardConta(c) {
  // Quem já falou da Energisa mostra quantas menções tem; quem não falou, os seguidores.
  const mencoes = c.mencoes ? `${inteiro(c.mencoes)} ${plural(c.mencoes, 'menção', 'menções')}` : ''
  const seguidores = c.seguidores != null ? `${compacto(c.seguidores)} seguidores` : ''
  const negativas = c.negativas ? `${c.negativas} ${plural(c.negativas, 'negativa', 'negativas')}` : ''
  const rotulo = [`${c.nome || c.username}, @${c.username}`, mencoes, negativas, seguidores].filter(Boolean).join(', ')
  return `<a class="card" data-formato="conta" href="#/conta/${enc(c.username)}" aria-label="${esc(rotulo)}">`
    + `<span class="cartaz cartaz-iniciais" aria-hidden="true"><span>${esc(iniciais(c))}</span></span>`
    + (c.foto ? `<img class="card-midia" src="${urlFoto(c.username)}" alt="" loading="lazy" decoding="async" data-cai>` : '')
    + `<span class="card-rodape"><span class="card-conta">${esc(c.nome || '@' + c.username)}</span>`
    + `<span class="card-meta">${esc([mencoes, negativas].filter(Boolean).join(' · ') || seguidores || '@' + c.username)}</span></span></a>`
}

// Numeral vazado do tamanho do cartão (a coluna do número tem 40% da largura e a mesma altura do cartão 4:5).
function top10(p, posicao) {
  const dois = posicao >= 10
  return `<div class="top10-item"><svg class="top10-numero" viewBox="0 0 100 187.5" aria-hidden="true">`
    + `<text x="${dois ? 118 : 114}" y="181" text-anchor="end" font-size="${dois ? 152 : 232}"${dois ? ' letter-spacing="-16"' : ''}>${posicao}</text></svg>`
    + `${cardPost(p, 'post', `${posicao}º lugar`)}</div>`
}

function cartoes(lista, formato) {
  if (formato === 'conta') return lista.map(cardConta).join('')
  if (formato === 'top10') return lista.map((p, i) => top10(p, i + 1)).join('')
  return lista.map((p) => cardPost(p, formato)).join('')
}

// ---------- Fileiras ----------
function linhaHTML(linha) {
  const id = `t-${String(linha.id).replace(/[^\w-]/g, '')}`
  // verTudo pode trazer o destino pronto: "Negativas" abre as menções já filtradas; "Quem mais fala da Energisa", a
  // página Contas em ordem de menções.
  const ver = !linha.verTudo ? '' : typeof linha.verTudo === 'string' ? `#/${linha.verTudo}`
    : linha.formato === 'conta' ? '#/contas' : `#/ver/${enc(linha.id)}`
  return `<section class="linha" aria-labelledby="${id}">
    <div class="linha-cabeca"><h2 class="linha-titulo" id="${id}">${esc(linha.titulo)}</h2>${ver ? `<a class="ver-tudo" href="${ver}">Ver tudo</a>` : ''}</div>
    <div class="trilho-caixa">
      <button class="seta seta-esq" type="button" aria-label="Voltar na fileira ${esc(linha.titulo)}" hidden>${SETA_ESQ}</button>
      <div class="trilho" data-formato="${linha.formato}">${cartoes(linha.itens, linha.formato)}</div>
      <button class="seta seta-dir" type="button" aria-label="Avançar na fileira ${esc(linha.titulo)}" hidden>${SETA_DIR}</button>
    </div>
  </section>`
}

function ativarTrilhos(raiz) {
  raiz.querySelectorAll('.trilho-caixa').forEach((caixa) => {
    const trilho = caixa.querySelector('.trilho')
    const esquerda = caixa.querySelector('.seta-esq')
    const direita = caixa.querySelector('.seta-dir')
    const atualizar = () => {
      esquerda.hidden = trilho.scrollLeft <= 4
      direita.hidden = trilho.scrollLeft >= trilho.scrollWidth - trilho.clientWidth - 4
    }
    trilho.addEventListener('scroll', () => requestAnimationFrame(atualizar), { passive: true })
    esquerda.addEventListener('click', () => trilho.scrollBy({ left: -trilho.clientWidth * 0.86, behavior: suave() }))
    direita.addEventListener('click', () => trilho.scrollBy({ left: trilho.clientWidth * 0.86, behavior: suave() }))
    atualizar()
  })
}

let timerRedimensionar = 0
addEventListener('resize', () => {
  clearTimeout(timerRedimensionar)
  timerRedimensionar = setTimeout(() => document.querySelectorAll('.trilho').forEach((t) => t.dispatchEvent(new Event('scroll'))), 150)
})

// ---------- Destaque ----------
function tituloDestaque(d) {
  if (d.mencao) return ROT.tema[d.mencao.tema] || d.mencao.tema
  return d.titulo || `@${d.conta}`
}

function chamada(itens) {
  return itens.filter(Boolean).join('<span aria-hidden="true">·</span>')
}

function slideHTML(d) {
  const m = d.mencao
  const sentimento = m?.sentimento
  const linhaChamada = m
    ? chamada([`<span class="forte">Menção ${ROT.sentimento[sentimento].toLowerCase()}</span>`,
      esc((d.municipios || []).slice(0, 2).join(', ')), `Impacto ${esc((ROT.alcance[m.alcance] || '').toLowerCase())}`, esc(quando(d.data))])
    : chamada([`<span class="forte">${esc(ROT.formato[d.formato] || 'Post')}</span>`, esc(quando(d.data))])
  const fatos = [
    `<span><b>${esc(autor(d))}</b>${esc(ehSite(d) ? 'site de notícias' : ROT.tipo[d.tipoConta] || '')}</span>`,
    ehSite(d) ? '' : `<span><b>${compacto(d.interacoes)}</b>${plural(d.interacoes, 'interação', 'interações')}</span>`,
    d.views ? `<span><b>${compacto(d.views)}</b>visualizações</span>` : '',
    d.seguidores ? `<span><b>${compacto(d.seguidores)}</b>seguidores</span>` : '',
  ]
  return `<div class="hero-slide">
    <div class="hero-texto">
      <p class="hero-chamada">${linhaChamada}</p>
      <h1 class="hero-titulo">${esc(tituloDestaque(d))}</h1>
      ${m?.resumo ? `<p class="hero-resumo">${esc(m.resumo)}</p>` : ''}
      <p class="hero-fatos">${fatos.join('')}</p>
      <div class="hero-acoes">
        <button class="botao botao-primario" type="button" data-abrir="${esc(d.id)}">Detalhes</button>
        ${linkSeguro(d.link) ? `<a class="botao botao-secundario" href="${esc(d.link)}" target="_blank" rel="noopener">${textoLink(d)}</a>` : ''}
      </div>
    </div>
    ${d.capa ? `<div class="hero-capa" data-cai-caixa><img src="${urlCapa(d.id)}" alt="" data-cai></div>` : ''}
  </div>`
}

function heroHTML(lista) {
  if (!lista.length) return ''
  const paginas = lista.length > 1
    ? `<div class="hero-paginas" role="group" aria-label="Destaques">${lista.map((_, i) => `<button type="button" data-destaque="${i}" aria-label="Destaque ${i + 1} de ${lista.length}" aria-current="${i === 0}"></button>`).join('')}</div>`
    : ''
  return `<section class="hero" aria-label="Destaque"><div class="hero-fundo" aria-hidden="true"></div><div class="hero-marca" aria-hidden="true"></div><div class="hero-palco"></div>${paginas}</section>`
}

function iniciarHero(lista) {
  const hero = conteudo.querySelector('.hero')
  if (!hero) return
  lista.forEach((d) => ITENS.set(d.id, d))
  const mostrar = (i) => {
    const d = lista[i]
    const sentimento = d.mencao?.sentimento
    hero.style.setProperty('--cor', sentimento ? COR[sentimento] : 'var(--destaque-texto)')
    hero.toggleAttribute('data-capa', Boolean(d.capa))
    hero.querySelector('.hero-fundo').innerHTML = d.capa
      ? `<span class="hero-brilho"></span><img src="${urlCapa(d.id)}" alt="" data-cai>`
      : '<span class="hero-brilho"></span>'
    hero.querySelector('.hero-palco').innerHTML = slideHTML(d)
    hero.querySelectorAll('[data-destaque]').forEach((b, j) => b.setAttribute('aria-current', String(j === i)))
  }
  hero.addEventListener('click', (e) => {
    const botao = e.target.closest('[data-destaque]')
    if (botao) mostrar(Number(botao.dataset.destaque))
  })
  mostrar(0)
}

// ---------- Prévia (mouse) ----------
let timerPrevia = 0
let timerSair = 0
let cardDaPrevia = null

function previaHTML(p) {
  const sentimento = p.mencao?.sentimento
  const meta = [
    sentimento ? `<span class="forte">${ROT.sentimento[sentimento]}</span>` : '',
    esc(ROT.formato[p.formato] || ''), esc(quando(p.data)),
    ehSite(p) ? '' : p.views ? `${compacto(p.views)} visualizações` : `${compacto(p.interacoes)} ${plural(p.interacoes, 'interação', 'interações')}`,
  ].filter(Boolean).map((t) => `<span>${t}</span>`).join('')
  const texto = p.mencao?.resumo || p.titulo
  const conta = `${autor(p)}${ehSite(p) ? ' · site de notícias' : p.tipoConta && ROT.tipo[p.tipoConta] ? ' · ' + ROT.tipo[p.tipoConta] : ''}`
  return `<div class="previa-midia" data-abrir="${esc(p.id)}">${cartaz(textoCartaz(p, 'mencao'), sentimento ? COR[sentimento] : '')}`
    + (p.capa ? `<img src="${urlCapa(p.id)}" alt="" data-cai>` : '') + '</div>'
    + `<div class="previa-corpo"><div class="previa-acoes"><button class="botao botao-primario botao-p" type="button" data-abrir="${esc(p.id)}" tabindex="-1">Detalhes</button>`
    + (linkSeguro(p.link) ? `<a class="botao botao-secundario botao-p" href="${esc(p.link)}" target="_blank" rel="noopener" tabindex="-1">${ehSite(p) ? 'Matéria' : 'Instagram'}</a>` : '')
    + `</div><p class="previa-meta">${meta}</p>${texto ? `<p class="previa-texto">${esc(texto)}</p>` : ''}<p class="previa-conta">${esc(conta)}</p></div>`
}

function mostrarPrevia(card) {
  const p = ITENS.get(card.dataset.post)
  const r = card.getBoundingClientRect()
  if (!p || !card.isConnected || r.width === 0 || modal.open) return
  const largura = Math.min(Math.max(r.width * 1.5, 300), 400, document.documentElement.clientWidth - 32)
  const alturaMidia = (largura * 9) / 16
  const esquerda = Math.max(16, Math.min(r.left + r.width / 2 - largura / 2, document.documentElement.clientWidth - 16 - largura))
  previa.style.width = `${largura}px`
  previa.style.setProperty('--cor', p.mencao ? COR[p.mencao.sentimento] : '')
  previa.innerHTML = previaHTML(p)
  let alto = Math.max(76, r.top + r.height / 2 - alturaMidia / 2 - 24)
  alto = Math.max(76, Math.min(alto, innerHeight - 12 - previa.offsetHeight))
  previa.style.left = `${esquerda + scrollX}px`
  previa.style.top = `${alto + scrollY}px`
  previa.style.transformOrigin = `${r.left + r.width / 2 - esquerda}px ${r.top + r.height / 2 - alto}px`
  cardDaPrevia = card
  previa.classList.remove('aberta')
  void previa.offsetWidth
  previa.classList.add('aberta')
}

function esconderPrevia() {
  clearTimeout(timerPrevia)
  clearTimeout(timerSair)
  previa.classList.remove('aberta')
  cardDaPrevia = null
}

document.addEventListener('mouseover', (e) => {
  if (!podeHover.matches) return
  const card = e.target.closest?.('.card[data-post]')
  if (!card || card.closest('.modal')) return
  if (card === cardDaPrevia) return clearTimeout(timerSair)
  clearTimeout(timerPrevia)
  timerPrevia = setTimeout(() => mostrarPrevia(card), 450)
})
document.addEventListener('mouseout', (e) => {
  const card = e.target.closest?.('.card[data-post]')
  if (card && !card.contains(e.relatedTarget)) clearTimeout(timerPrevia)
})
previa.addEventListener('mouseenter', () => clearTimeout(timerSair))
previa.addEventListener('mouseleave', () => { timerSair = setTimeout(esconderPrevia, 90) })
addEventListener('scroll', () => {
  topo.classList.toggle('solido', scrollY > 30)
  if (cardDaPrevia) esconderPrevia()
}, { passive: true })
document.addEventListener('scroll', (e) => { if (e.target.classList?.contains('trilho') && cardDaPrevia) esconderPrevia() }, { capture: true, passive: true })

// Capa que não carrega (endereço vencido): sai a imagem e fica o cartaz que está por baixo.
document.addEventListener('error', (e) => {
  const img = e.target
  if (!(img instanceof HTMLImageElement) || !img.hasAttribute('data-cai')) return
  const caixa = img.closest('[data-cai-caixa]')
  ;(caixa || img).remove()
}, true)

// ---------- Mapinha (ficha e perfil) ----------
const FONTE_LOCAL = {
  fato: 'pelo fato que a IA apontou',
  marcacao: 'pela marcação de local do post',
  texto: 'pela cidade citada no texto',
  conta: 'pela cidade da conta',
}
let promessaBase = null
const mapaBase = () => (promessaBase ||= api('mapa-base').catch((erro) => { promessaBase = null; throw erro }))

function miniMapaHTML(onde, texto) {
  const dados = esc(JSON.stringify({ id: onde.id ?? null, municipios: onde.municipios || [] }))
  const nome = onde.id ? `<a href="#/municipio/${onde.id}"><b>${esc(onde.nome)}</b></a>` : ''
  return `<div class="mini-mapa" data-mini="${dados}"><div>${nome}<span>${esc(texto)}</span></div></div>`
}

async function desenharMiniMapas(raiz) {
  const caixas = [...raiz.querySelectorAll('[data-mini]')]
  if (!caixas.length) return
  let base
  try {
    base = await mapaBase()
  } catch {
    return
  }
  for (const caixa of caixas) {
    if (!caixa.isConnected || caixa.querySelector('svg')) continue
    const { id, municipios } = JSON.parse(caixa.dataset.mini)
    const ligados = new Set(municipios)
    const alvo = base.municipios.find((m) => m.id === id)
    const caminhos = base.municipios.map((m) => `<path d="${esc(m.d)}"${m.id === id ? ' class="alvo"' : ligados.has(m.id) ? ' class="ligado"' : ''}/>`).join('')
    const pino = alvo ? `<circle class="pino" cx="${alvo.x}" cy="${alvo.y}" r="8"/>` : ''
    caixa.insertAdjacentHTML('afterbegin', `<svg viewBox="0 0 ${base.largura} ${base.altura}" aria-hidden="true">${caminhos}${pino}</svg>`)
  }
}

// ---------- Ficha do post ----------
function numerosHTML(lista) {
  return `<div class="numeros">${lista.filter(Boolean).map(([valor, rotulo]) => `<div class="numero"><b>${esc(valor)}</b><span>${esc(rotulo)}</span></div>`).join('')}</div>`
}

function fichaHTML(p) {
  const m = p.mencao
  const sentimento = m?.sentimento
  const cor = sentimento ? COR[sentimento] : ''
  const capa = urlCapa(p.id)
  const c = p.contaInfo || { username: p.conta }
  const titulo = m ? ROT.tema[m.tema] || m.tema : p.formato === 'Story' ? `Story de @${p.conta}` : p.titulo || `Post de ${autor(p)}`
  const site = ehSite(p)

  let frente = ''
  if (p.midia?.tipo === 'video') frente = `<video class="frente" src="${p.midia.url}" controls preload="none" playsinline${p.capa ? ` poster="${capa}"` : ''}></video>`
  else if (p.midia?.tipo === 'imagem') frente = `<img class="frente" src="${p.midia.url}" alt="">`
  else if (p.capa) frente = `<img class="frente" src="${capa}" alt="" data-cai>`
  const fundo = p.capa ? `<img class="fundo" src="${capa}" alt="" data-cai>` : cartaz('', cor)

  const linhaChamada = m
    ? chamada([`<span class="forte">Menção ${ROT.sentimento[sentimento].toLowerCase()}</span>`, esc((m.municipios || []).slice(0, 3).join(', ')), esc(quando(p.data))])
    : chamada([`<span class="forte">${esc(ROT.formato[p.formato] || 'Post')}</span>`, esc(quando(p.data))])

  const selos = m ? [
    `<span class="selo selo-forte" style="--cor:${cor}">${ROT.sentimento[sentimento]}</span>`,
    m.setor ? `<span class="selo">Setor: ${esc(ROT.setor[m.setor] || m.setor)}</span>` : '',
    `<span class="selo">Impacto ${esc((ROT.alcance[m.alcance] || m.alcance || '').toLowerCase())}</span>`,
    m.citaEnergisa ? '<span class="selo">Cita a Energisa</span>' : '',
  ].join('') : ''

  const longa = (p.legenda || '').length > 420
  const legenda = p.legenda
    ? `<div class="legenda"${longa ? ' data-curta' : ''}>${esc(p.legenda)}</div>${longa ? '<button class="ler-mais" type="button">Ler tudo</button>' : ''}`
    : ''

  const fatos = [
    p.onde ? ['Localização aproximada', miniMapaHTML(p.onde, FONTE_LOCAL[p.onde.fonte] || '')] : null,
    site ? ['Site', esc(c.nome || c.username)]
      : ['Conta', `<a href="#/conta/${enc(c.username)}">${esc(c.nome || '@' + c.username)}</a>${c.tipo && ROT.tipo[c.tipo] ? ` · ${esc(ROT.tipo[c.tipo])}` : ''}`],
    c.seguidores != null ? ['Seguidores', inteiro(c.seguidores)] : null,
    ['Publicado', esc(dataCompleta(p.data))],
    m?.municipios?.length ? ['Municípios do fato', esc(m.municipios.join(', '))]
      : c.municipios?.length ? ['Municípios da conta', esc(c.municipios.slice(0, 6).join(', '))] : null,
    p.local ? ['Local marcado', esc(p.local)] : null,
    p.medidoEm ? ['Números de', esc(quando(p.medidoEm))] : null,
  ].filter(Boolean).map(([dt, dd]) => `<div><dt>${dt}</dt><dd>${dd}</dd></div>`).join('')

  const numeros = site ? '' : numerosHTML([ // matéria de site não tem curtidas nem comentários
    p.views != null ? [compacto(p.views), 'visualizações'] : null,
    [p.curtidas == null ? 'ocultas' : compacto(p.curtidas), 'curtidas'],
    [compacto(p.comentarios ?? 0), 'comentários'],
    p.engajamentoPct != null ? [porcento(p.engajamentoPct), 'interações ÷ seguidores'] : null,
    p.indice != null ? [vezes(p.indice), 'em relação à média da conta'] : null,
  ])

  const reacao = m?.reacao
    ? `<section class="secao" style="--cor:${COR_REACAO[m.reacao] || 'var(--texto)'}"><h3 class="secao-titulo"><span class="forte">${esc(ROT.reacao[m.reacao] || m.reacao)}</span></h3>`
      + `${m.reacaoResumo ? `<p>${esc(m.reacaoResumo)}</p>` : ''}${m.comentariosLidos ? `<p class="contagem">Leitura de ${m.comentariosLidos} ${plural(m.comentariosLidos, 'comentário', 'comentários')}</p>` : ''}</section>`
    : ''
  const repercussao = m && m.repercutiram != null
    ? `<section class="secao"><h3 class="secao-titulo">Repercussão</h3>${numerosHTML([
      [inteiro(m.repercutiram), plural(m.repercutiram, 'conta tratou do assunto em até 3 dias', 'contas trataram do assunto em até 3 dias')],
      [m.coberturaEstadual ? 'Sim' : 'Não', 'cobertura de portal estadual'],
    ])}</section>`
    : ''
  const comentarios = p.textosComentarios?.length
    ? `<section class="secao"><h3 class="secao-titulo">Comentários</h3><ul class="comentarios">${p.textosComentarios.map((t) => `<li>${esc(t.texto)}${t.curtidas ? `<small>${inteiro(t.curtidas)} ${plural(t.curtidas, 'curtida', 'curtidas')}</small>` : ''}</li>`).join('')}</ul></section>`
    : ''
  const mais = p.maisDaConta?.length
    ? `<section class="secao"><h3 class="secao-titulo">Mais de ${esc(autor(p))}</h3><div class="mini-grade">${p.maisDaConta.map((x) => cardPost(x, 'post')).join('')}</div></section>`
    : ''

  return `<button class="modal-fechar" type="button" aria-label="Fechar">${FECHAR}</button>
    <div class="modal-midia"${frente ? '' : ' data-vazia'}${cor ? ` style="--brilho:${cor}"` : ''}>
      ${fundo}${frente}
      <div class="modal-cabeca"${cor ? ` style="--cor:${cor}"` : ''}>
        <p class="modal-chamada">${linhaChamada}</p>
        <h2 class="modal-titulo" id="modal-titulo">${esc(titulo)}</h2>
        <div class="modal-acoes">
          ${linkSeguro(p.link) ? `<a class="botao botao-primario" href="${esc(p.link)}" target="_blank" rel="noopener">${textoLink(p)}</a>` : ''}
          ${site ? '' : `<a class="botao botao-secundario" href="#/conta/${enc(p.conta)}">@${esc(p.conta)}</a>`}
        </div>
      </div>
    </div>
    <div class="modal-corpo">
      <div class="colunas">
        <div>
          ${m?.resumo ? `<p class="modal-resumo">${esc(m.resumo)}</p>` : ''}
          ${selos ? `<div class="selos">${selos}</div>` : ''}
          ${legenda}
        </div>
        <dl class="fatos">${fatos}</dl>
      </div>
      ${numeros}${reacao}${repercussao}${comentarios}${mais}
    </div>`
}

async function abrirModal(id) {
  if (modal.dataset.id === id && modal.open) return
  esconderPrevia()
  modal.dataset.id = id
  modal.innerHTML = `<button class="modal-fechar" type="button" aria-label="Fechar">${FECHAR}</button><div class="modal-estado">Carregando…</div>`
  if (!modal.open) modal.showModal()
  try {
    const p = await api('post/' + enc(id))
    if (modal.dataset.id !== id) return
    modal.innerHTML = fichaHTML(p)
    modal.scrollTop = 0
    modal.querySelector('.modal-fechar').focus({ preventScroll: true })
    desenharMiniMapas(modal)
  } catch (erro) {
    if (modal.dataset.id !== id) return
    modal.querySelector('.modal-estado').textContent = erro.status === 404
      ? 'Este post não está mais no banco.'
      : SEM_RESPOSTA
  }
}

modal.addEventListener('close', () => {
  modal.dataset.id = ''
  modal.innerHTML = ''
})
modal.addEventListener('cancel', (e) => {
  e.preventDefault()
  fecharPost()
})
modal.addEventListener('click', (e) => {
  if (e.target !== modal) return
  const r = modal.getBoundingClientRect()
  const fora = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom
  if (fora) fecharPost()
})

// ---------- Rotas ----------
let chaveAtual = null
let geracao = 0

function lerRota() {
  const hash = location.hash.replace(/^#/, '') || '/'
  const [caminho, consulta = ''] = hash.split('?')
  return { caminho: caminho || '/', partes: caminho.split('/').filter(Boolean).map(decodeURIComponent), params: new URLSearchParams(consulta) }
}

function montarHash(caminho, params) {
  const q = params.toString()
  return `#${caminho}${q ? '?' + q : ''}`
}

function abrirPost(id) {
  const { caminho, params } = lerRota()
  if (params.get('p') === id && modal.open) return
  params.set('p', id)
  history.pushState({ modal: true }, '', montarHash(caminho, params))
  sincronizar()
}

function fecharPost() {
  if (history.state?.modal) {
    history.back()
    return
  }
  const { caminho, params } = lerRota()
  params.delete('p')
  history.replaceState(null, '', montarHash(caminho, params))
  sincronizar()
}

function navegar(hash, substituir = false) {
  if (substituir) history.replaceState(null, '', hash)
  else history.pushState(null, '', hash)
  sincronizar()
}

function marcarMenu(partes) {
  let secao = partes[0] || 'inicio'
  if (secao === 'ver') secao = { mencoes: 'mencoes', noticias: 'noticias', reels: 'reels', stories: 'stories' }[partes[1]] || (partes[1]?.startsWith('setor-') ? 'setores' : '')
  if (secao === 'conta') secao = 'contas'
  if (secao === 'municipio' || secao === 'municipios') secao = 'mapa'
  document.querySelectorAll('.menu a').forEach((a) => {
    if (a.dataset.secao === secao) a.setAttribute('aria-current', 'page')
    else a.removeAttribute('aria-current')
  })
}

async function sincronizar() {
  const { caminho, partes, params } = lerRota()
  const semModal = new URLSearchParams(params)
  semModal.delete('p')
  const chave = `${caminho}?${semModal}`
  marcarMenu(partes)
  if (partes[0] !== 'busca' && document.activeElement !== campoBusca) campoBusca.value = ''
  if (chave !== chaveAtual) {
    chaveAtual = chave
    esconderPrevia()
    const minha = ++geracao
    try {
      await renderizar(partes, semModal, minha)
    } catch (erro) {
      if (minha === geracao) conteudo.innerHTML = erroHTML(erro)
    }
  }
  const p = params.get('p')
  if (p) abrirModal(p)
  else if (modal.open) modal.close()
}

addEventListener('hashchange', sincronizar)
addEventListener('popstate', sincronizar)

function erroHTML(erro) {
  return erro?.status === 404
    ? '<div class="erro"><b>Não encontrado</b>Esse item não está no banco do radar.</div>'
    : `<div class="erro"><b>Sem resposta</b>${SEM_RESPOSTA}</div>`
}

async function renderizar(partes, params, minha) {
  const [rota, valor] = partes
  scrollTo({ top: 0, behavior: 'instant' })
  const pronto = () => minha === geracao
  if (!rota) await paginaInicio(pronto)
  else if (rota === 'ver' && valor) await paginaVer(valor, params, pronto)
  else if (rota === 'contas') await paginaContas(params, pronto)
  else if (rota === 'conta' && valor) await paginaConta(valor, pronto)
  else if (rota === 'setores') await paginaSetores(params, pronto)
  else if (rota === 'mapa' || rota === 'municipios') await paginaMapa(params, pronto)
  else if (rota === 'municipio' && valor) await paginaMunicipio(valor, pronto)
  else if (rota === 'busca') await paginaBusca(params, pronto)
  else conteudo.innerHTML = erroHTML({ status: 404 })
  if (pronto() && document.activeElement === document.body) conteudo.focus({ preventScroll: true })
}

// ---------- Páginas ----------
function esqueletoInicio() {
  const linha = `<div><div class="esq-linha">${'<div class="esqueleto"></div>'.repeat(6)}</div></div>`
  return `<div class="esqueleto esq-hero"></div><div class="linhas" style="margin-top:-80px">${linha.repeat(3)}</div>`
}

function esqueletoPagina() {
  return `<div class="pagina"><div class="esqueleto" style="height:56px;width:min(420px,70%);margin-bottom:28px"></div><div class="esq-linha" style="padding:0">${'<div class="esqueleto"></div>'.repeat(6)}</div></div>`
}

async function paginaInicio(pronto) {
  document.title = 'Radar Energisa'
  conteudo.innerHTML = esqueletoInicio()
  const dados = await api('inicio')
  if (!pronto()) return
  if (!dados.linhas.length && !dados.destaques.length) {
    conteudo.innerHTML = '<div class="erro"><b>Nenhuma menção à Energisa ainda</b></div>'
    return
  }
  conteudo.innerHTML = heroHTML(dados.destaques) + `<div class="linhas">${dados.linhas.map(linhaHTML).join('')}</div>`
  iniciarHero(dados.destaques)
  ativarTrilhos(conteudo)
}

function chips(nome, opcoes, atual, cores = {}) {
  return `<div class="filtros" role="group" aria-label="${esc(nome)}">${opcoes.map(([valor, rotulo]) => {
    const cor = cores[valor] ? ` data-cor style="--cor:${cores[valor]}"` : ''
    return `<button class="chip" type="button" data-filtro="${esc(nome)}" data-valor="${esc(valor)}" aria-pressed="${String(valor) === String(atual ?? '')}"${cor}>${esc(rotulo)}</button>`
  }).join('')}</div>`
}

const DIAS_MENCOES = [['7', '7 dias'], ['30', '30 dias'], ['90', '90 dias'], ['todos', 'Tudo']]
const SENTIMENTOS = [['', 'Todas'], ['negativo', 'Negativas'], ['neutro', 'Neutras'], ['positivo', 'Positivas']]

function filtrosDaLinha(dados) {
  // Toda fileira é de menções à Energisa: período e sentimento valem para todas; a ordem, para as de cartão de post.
  const f = dados.filtros || {}
  const dias = f.dias == null ? 'todos' : String(f.dias)
  const grupos = [chips('dias', DIAS_MENCOES, dias), chips('sentimento', SENTIMENTOS, f.sentimento || '', COR)]
  if (dados.formato === 'post' || dados.formato === 'top10') {
    const ordens = f.ordem === 'views' || dados.id === 'reels'
      ? [['views', 'Mais vistos'], ['interacoes', 'Mais interações'], ['recentes', 'Mais recentes']]
      : [['interacoes', 'Mais interações'], ['recentes', 'Mais recentes']]
    grupos.push(chips('ordem', ordens, f.ordem || 'recentes'))
  }
  return grupos.join('')
}

function trocarFiltro(botao) {
  const { caminho, params } = lerRota()
  params.delete('p')
  if (botao.dataset.filtro === 'camada') [...params.keys()].forEach((k) => params.delete(k)) // cada camada tem seus filtros
  params.set(botao.dataset.filtro, botao.dataset.valor)
  navegar(montarHash(caminho, params), true)
}

function ativarMais(raiz, carregar, desenhar) {
  const caixa = raiz.querySelector('.mais')
  const grade = raiz.querySelector('.grade')
  if (!caixa || !grade) return
  let pagina = 0
  let ocupado = false
  const observador = new IntersectionObserver((entradas) => { if (entradas.some((e) => e.isIntersecting)) mais() }, { rootMargin: '700px' })
  async function mais() {
    const botao = caixa.querySelector('button')
    if (ocupado || !botao || !caixa.isConnected) return
    ocupado = true
    botao.textContent = 'Carregando…'
    try {
      const dados = await carregar(pagina + 1)
      pagina += 1
      grade.insertAdjacentHTML('beforeend', desenhar(dados))
      if (dados.mais) botao.textContent = 'Carregar mais'
      else {
        caixa.innerHTML = ''
        observador.disconnect()
      }
    } catch {
      botao.textContent = 'Tentar de novo'
    }
    ocupado = false
  }
  caixa.addEventListener('click', (e) => { if (e.target.closest('button')) mais() })
  observador.observe(caixa)
}

const botaoMais = (mais) => `<div class="mais">${mais ? '<button class="botao botao-secundario" type="button">Carregar mais</button>' : ''}</div>`

async function paginaVer(id, params, pronto) {
  conteudo.innerHTML = esqueletoPagina()
  const consulta = new URLSearchParams(params)
  const dados = await api(`linha/${enc(id)}?${consulta}`)
  if (!pronto()) return
  document.title = `${dados.titulo} · Radar`
  const formato = dados.formato === 'top10' ? 'post' : dados.formato
  const total = dados.itens.length
  const semFiltro = dados.filtros?.dias == null && !dados.filtros?.sentimento
  const vazio = formato === 'story'
    ? `Nenhum story sobre a Energisa ${semFiltro ? 'até agora' : 'com esses filtros'}.`
    : 'Nada com esses filtros.'
  conteudo.innerHTML = `<div class="pagina">
    <div class="pagina-cabeca"><h1 class="pagina-titulo">${esc(dados.titulo)}</h1></div>
    <div class="filtros-linha">${filtrosDaLinha(dados)}</div>
    ${total ? `<div class="grade" data-formato="${formato}">${cartoes(dados.itens, formato)}</div>${botaoMais(dados.mais)}`
      : `<p class="vazio">${vazio}</p>`}
  </div>`
  ativarMais(conteudo, (pagina) => {
    const q = new URLSearchParams(params)
    q.set('pagina', pagina)
    return api(`linha/${enc(id)}?${q}`)
  }, (d) => cartoes(d.itens, formato))
}

const ORDENS_CONTAS = [['seguidores', 'Mais seguidas'], ['mencoes', 'Mais menções à Energisa']]

async function paginaContas(params, pronto) {
  // Todas as contas monitoradas; quem já falou da Energisa mostra quantas menções tem.
  conteudo.innerHTML = esqueletoPagina()
  const tipo = params.get('tipo') || ''
  const ordem = params.get('ordem') || 'seguidores'
  const consulta = (pagina) => `contas?tipo=${enc(tipo)}&ordem=${enc(ordem)}&pagina=${pagina}`
  const dados = await api(consulta(0))
  if (!pronto()) return
  document.title = 'Contas · Radar'
  const opcoes = [['', 'Todas'], ...dados.tipos.map((t) => [t === 'influenciador_local' ? 'influenciador' : t, ROT.tipo[t] || t])]
  conteudo.innerHTML = `<div class="pagina">
    <div class="pagina-cabeca"><h1 class="pagina-titulo">Contas</h1></div>
    <div class="filtros-linha">${chips('tipo', opcoes, tipo)}${chips('ordem', ORDENS_CONTAS, dados.ordem)}</div>
    ${dados.itens.length ? `<div class="grade" data-formato="conta">${dados.itens.map(cardConta).join('')}</div>${botaoMais(dados.mais)}`
      : '<p class="vazio">Nenhuma conta monitorada desse tipo.</p>'}
  </div>`
  ativarMais(conteudo, (pagina) => api(consulta(pagina)), (d) => d.itens.map(cardConta).join(''))
}

async function paginaConta(username, pronto) {
  conteudo.innerHTML = esqueletoPagina()
  const c = await api('conta/' + enc(username))
  if (!pronto()) return
  document.title = `@${c.username} · Radar`
  const foto = c.foto ? `<img src="${urlFoto(c.username)}" alt="" data-cai>` : ''
  const fatos = [
    `<span><b>${inteiro(c.mencoes || 0)}</b>${plural(c.mencoes || 0, 'menção', 'menções')} à Energisa</span>`,
    c.negativas ? `<span><b>${inteiro(c.negativas)}</b>${plural(c.negativas, 'negativa', 'negativas')}</span>` : '',
    c.seguidores != null ? `<span><b>${compacto(c.seguidores)}</b>seguidores</span>` : '',
    c.visita ? `<span>visitada <b class="depois">${esc(quando(c.visita))}</b></span>` : '',
  ].join('')
  const tipo = [c.tipo ? ROT.tipo[c.tipo] || c.tipo : '', c.abrangencia ? `cobertura ${c.abrangencia}` : '',
    c.municipios?.length ? c.municipios.slice(0, 4).join(', ') : ''].filter(Boolean).join(' · ')
  const posts = c.posts?.itens || []
  conteudo.innerHTML = `<section class="perfil">
      <div class="perfil-fundo" aria-hidden="true">${foto}</div>
      <div class="perfil-foto"><span class="cartaz cartaz-iniciais" aria-hidden="true"><span>${esc(iniciais(c))}</span></span>${foto}</div>
      <div>
        <h1 class="perfil-nome">${esc(c.nome || c.username)}</h1>
        <p class="perfil-arroba">@${esc(c.username)}${tipo ? ` · ${esc(tipo)}` : ''}${c.monitorada ? '' : ' · fora do monitoramento'}</p>
        ${c.bio ? `<p class="perfil-bio">${esc(c.bio)}</p>` : ''}
        <p class="perfil-fatos">${fatos}</p>
        <div class="perfil-acoes"><a class="botao botao-primario" href="https://www.instagram.com/${enc(c.username)}/" target="_blank" rel="noopener">Abrir no Instagram</a></div>
      </div>
      ${c.onde ? `<div class="perfil-mapa">${miniMapaHTML(c.onde, c.onde.id ? 'cidade da conta' : 'municípios da conta')}</div>` : ''}
    </section>
    ${c.linhas.length ? `<div class="linhas">${c.linhas.map(linhaHTML).join('')}</div>` : ''}
    <section class="bloco" style="padding-bottom:96px">
      <h2 class="linha-titulo">Menções à Energisa</h2>
      ${posts.length ? `<div class="grade" data-formato="post">${cartoes(posts, 'post')}</div>${botaoMais(c.posts.mais)}`
        : c.linhas.length ? '' : '<p class="vazio">Esta conta ainda não publicou nada sobre a Energisa.</p>'}
    </section>`
  ativarTrilhos(conteudo)
  ativarMais(conteudo.querySelector('.bloco'), (pagina) => api(`linha/conta-${enc(c.username)}?pagina=${pagina}`), (d) => cartoes(d.itens, 'post'))
  desenharMiniMapas(conteudo)
}

// ---------- Setores ----------
// As menções separadas pelo setor da Energisa que teria de responder ou agir. No alto, uma barra por setor, do
// tamanho do número de menções e dividida por sentimento (negativa, neutra, positiva, nessa ordem); embaixo, uma
// fileira de cartões por setor. O texto da linha e o rótulo acessível trazem os números: a cor não fala sozinha.
const PARTES_SENTIMENTO = [['negativo', 'negativa', 'negativas'], ['neutro', 'neutra', 'neutras'], ['positivo', 'positiva', 'positivas']]

function resumoSetor(s) {
  return PARTES_SENTIMENTO.filter(([, , campo]) => s[campo]).map(([, uma, varias]) => `${s[varias]} ${plural(s[varias], uma, varias)}`).join(', ')
}

function graficoSetores(lista) {
  const maximo = Math.max(1, ...lista.map((s) => s.n))
  const linhas = lista.map((s) => {
    const partes = PARTES_SENTIMENTO.filter(([, , campo]) => s[campo]).map(([chave, uma, varias]) => {
      const dica = `${s.titulo}: ${s[varias]} ${plural(s[varias], uma, varias)} (${Math.round((100 * s[varias]) / s.n)}%)`
      return `<i style="flex-grow:${s[varias]};--c:${COR[chave]}" data-dica="${esc(dica)}"></i>`
    }).join('')
    const rotulo = `${s.titulo}: ${s.n} ${plural(s.n, 'menção', 'menções')}${resumoSetor(s) ? `, ${resumoSetor(s)}` : ''}`
    return `<li><button class="setor" type="button" data-rolar="t-setor-${esc(s.id)}" aria-label="${esc(rotulo)}">`
      + `<span class="setor-nome">${esc(s.titulo)}</span>`
      + `<span class="setor-trilha"><span class="setor-barra" style="width:${((100 * s.n) / maximo).toFixed(1)}%">${partes}</span></span>`
      + `<span class="setor-total">${inteiro(s.n)}</span>`
      + `<span class="setor-neg">${s.negativas ? `${s.negativas} ${plural(s.negativas, 'negativa', 'negativas')}` : ''}</span>`
      + '</button></li>'
  }).join('')
  const legenda = PARTES_SENTIMENTO.map(([chave, uma]) => `<span><i style="--c:${COR[chave]}"></i>${uma}</span>`).join('')
  return `<section class="setores-grafico" aria-label="Menções por setor"><ol>${linhas}</ol>`
    + `<p class="legenda-mapa">${legenda}</p><div class="dica-setor" hidden></div></section>`
}

function ativarGraficoSetores(raiz) {
  const grafico = raiz.querySelector('.setores-grafico')
  if (!grafico) return
  const dica = grafico.querySelector('.dica-setor')
  grafico.addEventListener('pointerover', (e) => {
    const parte = e.target.closest('[data-dica]')
    if (!parte) {
      dica.hidden = true
      return
    }
    dica.textContent = parte.dataset.dica
    dica.hidden = false
    const r = parte.getBoundingClientRect()
    const g = grafico.getBoundingClientRect()
    dica.style.left = `${Math.max(dica.offsetWidth / 2 + 8, Math.min(r.left - g.left + r.width / 2, g.width - dica.offsetWidth / 2 - 8))}px`
    dica.style.top = `${r.top - g.top - 6}px`
  })
  grafico.addEventListener('pointerleave', () => { dica.hidden = true })
}

async function paginaSetores(params, pronto) {
  conteudo.innerHTML = esqueletoPagina()
  const consulta = new URLSearchParams()
  for (const chave of ['dias', 'sentimento']) if (params.get(chave)) consulta.set(chave, params.get(chave))
  const dados = await api('setores?' + consulta)
  if (!pronto()) return
  document.title = 'Setores · Radar'
  const dias = dados.dias == null ? 'todos' : String(dados.dias)
  const filtros = chips('dias', DIAS_MENCOES, dias) + chips('sentimento', SENTIMENTOS, dados.sentimento || '', COR)
  const fileiras = dados.setores.map((s) => linhaHTML({ id: `setor-${s.id}`, titulo: s.titulo, formato: 'mencao', itens: s.itens, verTudo: Boolean(s.id) })).join('')
  conteudo.innerHTML = `<div class="pagina pagina-setores">
    <div class="pagina-cabeca"><h1 class="pagina-titulo">Setores</h1>
      <p class="contagem"><b>${inteiro(dados.total)}</b>${plural(dados.total, 'menção', 'menções')} em <b>${inteiro(dados.setores.length)}</b>${plural(dados.setores.length, 'setor', 'setores')}</p></div>
    <div class="filtros-linha">${filtros}</div>
    ${dados.setores.length ? `${graficoSetores(dados.setores)}<div class="linhas">${fileiras}</div>` : '<p class="vazio">Nenhuma menção nesse período.</p>'}
  </div>`
  ativarTrilhos(conteudo)
  ativarGraficoSetores(conteudo)
}

// ---------- Mapa ----------
// Cada menção à Energisa (ou conta que publicou uma) é um ponto no município onde fica (localização aproximada, feita
// no servidor). A cor do município diz quantos itens ele tem; a lista ao lado é a mesma informação em texto, para
// teclado e leitor de tela.
const CAMADAS_MAPA = {
  mencoes: { rotulo: 'Menções', unidade: ['menção', 'menções'], dias: DIAS_MENCOES },
  perfis: { rotulo: 'Contas que falam da Energisa', unidade: ['conta', 'contas'], dias: null },
}
const RAMPA = ['#1a3b54', '#1d4f6d', '#1e6688', '#2484aa'] // do Azul BI ao Azul [Logo]
const SEM_VALOR = '#152738'
const FOTOS_NO_MAPA = 150 // perfis com foto no mapa: os mais seguidos (cada foto é um pedido)

function faixasDoMapa(maximo) {
  const cortes = [1, Math.ceil(maximo * 0.1), Math.ceil(maximo * 0.3), Math.ceil(maximo * 0.6)]
  return cortes.filter((c, i) => i === 0 || c > cortes[i - 1])
}

function corDaFaixa(n, faixas) {
  if (!n) return SEM_VALOR
  let i = 0
  while (i < faixas.length - 1 && n >= faixas[i + 1]) i += 1
  return RAMPA[RAMPA.length - faixas.length + i]
}

function legendaDaCamada(camada, faixas) {
  const itens = []
  if (camada !== 'perfis') {
    itens.push('<span><i style="--c:var(--texto-2)"></i>local no post</span><span><i class="vazado" style="--c:var(--texto-2)"></i>cidade da conta</span>')
    itens.push(...['negativo', 'neutro', 'positivo'].map((s) => `<span><i style="--c:${COR[s]}"></i>${ROT.sentimento[s].toLowerCase()}</span>`))
  } else {
    itens.push('<span>círculo maior: mais seguidores</span>')
  }
  const cores = RAMPA.slice(RAMPA.length - faixas.length)
  itens.push(...faixas.map((de, i) => {
    const ate = faixas[i + 1] ? faixas[i + 1] - 1 : null
    return `<span><i class="quadro" style="--c:${cores[i]}"></i>${ate == null ? `${de} ou mais` : ate === de ? de : `${de} a ${ate}`}</span>`
  }))
  return itens.join('')
}

function raioPerfil(seguidores) {
  return 1.2 + 1.1 * Math.min(1, Math.max(0, (Math.log10(seguidores || 1) - 3) / 3)) // de 1 mil a 1 milhão
}

function pontosHTML(dados) {
  if (dados.camada === 'perfis') {
    const comFoto = new Set(dados.pontos.filter((p) => p.foto).sort((a, b) => (b.seguidores || 0) - (a.seguidores || 0))
      .slice(0, FOTOS_NO_MAPA).map((p) => p.username))
    return dados.pontos.map((p, i) => {
      const r = raioPerfil(p.seguidores)
      const foto = comFoto.has(p.username)
        ? `<image href="${urlFoto(p.username)}" x="${-r}" y="${-r}" width="${2 * r}" height="${2 * r}" clip-path="url(#recorte-redondo)" preserveAspectRatio="xMidYMid slice"/>`
        : ''
      return `<g class="ponto" data-i="${i}"${foto ? ' data-foto' : ''} transform="translate(${p.x} ${p.y})"><circle r="${r}"/>${foto}</g>`
    }).join('')
  }
  return dados.pontos.map((p, i) => {
    const r = dados.camada === 'mencoes' ? 1.9 : p.sentimento ? 1.5 : 1.05
    const cor = p.sentimento ? ` style="--cor:${COR[p.sentimento]}"` : ''
    return `<circle class="ponto" data-i="${i}" data-fonte="${esc(p.fonte)}" cx="${p.x}" cy="${p.y}" r="${r}"${cor}/>`
  }).join('')
}

function dicaHTML(p, camada, nomes) {
  if (camada === 'perfis') {
    return `${p.foto ? `<img src="${urlFoto(p.username)}" alt="">` : ''}<div><b>${esc(p.nome || '@' + p.username)}</b>`
      + `<span>@${esc(p.username)}${p.seguidores != null ? ` · ${compacto(p.seguidores)} seguidores` : ''}</span>`
      + `<span>${inteiro(p.mencoes || 0)} ${plural(p.mencoes || 0, 'menção', 'menções')} à Energisa${p.negativas ? `, ${p.negativas} ${plural(p.negativas, 'negativa', 'negativas')}` : ''}</span>`
      + `<span>${esc(nomes.get(p.municipio) || '')}</span></div>`
  }
  const sentimento = p.sentimento ? `<span class="forte">Menção ${ROT.sentimento[p.sentimento].toLowerCase()}</span>` : ''
  const numeros = p.views ? `${compacto(p.views)} visualizações` : `${compacto(p.interacoes)} ${plural(p.interacoes, 'interação', 'interações')}`
  return `${p.capa ? `<img src="${urlCapa(p.id)}" alt="">` : ''}<div>${sentimento}<b>${esc(p.titulo || '@' + p.conta)}</b>`
    + `<span>${esc(autor(p))} · ${esc(quando(p.data))}${ehSite(p) ? '' : ` · ${numeros}`}</span>`
    + `<span>${esc(nomes.get(p.municipio) || '')} ${esc(FONTE_LOCAL[p.fonte] || '')}</span></div>`
}

function ativarMapa(quadro, dados, nomes, base) {
  if (!quadro) return
  const svg = quadro.querySelector('svg')
  const dica = quadro.querySelector('.dica')
  const L = base.largura
  const A = base.altura
  let vb = { x: 0, y: 0, w: L, h: A }
  const aplicar = () => svg.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`)
  const limitar = () => {
    vb.w = Math.min(L, Math.max(L / 14, vb.w))
    vb.h = (vb.w * A) / L
    vb.x = Math.min(L - vb.w, Math.max(0, vb.x))
    vb.y = Math.min(A - vb.h, Math.max(0, vb.y))
  }
  const noMapa = (e) => {
    const r = svg.getBoundingClientRect()
    return { x: vb.x + ((e.clientX - r.left) / r.width) * vb.w, y: vb.y + ((e.clientY - r.top) / r.height) * vb.h }
  }

  let atual = null
  const esconder = () => {
    dica.hidden = true
    atual?.classList.remove('ativo')
    atual = null
  }
  const mostrar = (ponto) => {
    const p = dados.pontos[ponto.dataset.i]
    if (!p) return
    atual?.classList.remove('ativo')
    atual = ponto
    ponto.classList.add('ativo')
    dica.dataset.camada = dados.camada
    dica.style.setProperty('--cor', p.sentimento ? COR[p.sentimento] : '')
    dica.innerHTML = dicaHTML(p, dados.camada, nomes)
    dica.hidden = false
    const r = ponto.getBoundingClientRect()
    const q = quadro.getBoundingClientRect()
    let x = r.right - q.left + 12
    let y = r.top - q.top - 8
    if (x + dica.offsetWidth > q.width - 8) x = r.left - q.left - dica.offsetWidth - 12
    if (y + dica.offsetHeight > q.height - 8) y = q.height - dica.offsetHeight - 8
    dica.style.left = `${Math.max(8, x)}px`
    dica.style.top = `${Math.max(8, y)}px`
  }
  const zoom = (fator, cx = vb.x + vb.w / 2, cy = vb.y + vb.h / 2) => {
    if (!fator) vb = { x: 0, y: 0, w: L, h: A }
    else {
      const w = Math.min(L, Math.max(L / 14, vb.w / fator))
      vb = { x: cx - ((cx - vb.x) * w) / vb.w, y: cy - ((cy - vb.y) * w) / vb.w, w, h: (w * A) / L }
      limitar()
    }
    aplicar()
    esconder()
  }

  let arrasto = null
  let moveu = false
  let engolirClique = false
  quadro.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || e.target.closest('.mapa-zoom')) return
    arrasto = { x: e.clientX, y: e.clientY, vb: { ...vb } }
    moveu = false
  })
  quadro.addEventListener('pointermove', (e) => {
    if (!arrasto) return
    const dx = e.clientX - arrasto.x
    const dy = e.clientY - arrasto.y
    if (!moveu && Math.hypot(dx, dy) > 5) {
      moveu = true
      quadro.setPointerCapture(e.pointerId)
      quadro.classList.add('arrastando')
      esconder()
    }
    if (!moveu) return
    const r = svg.getBoundingClientRect()
    vb.x = arrasto.vb.x - (dx / r.width) * vb.w
    vb.y = arrasto.vb.y - (dy / r.height) * vb.h
    limitar()
    aplicar()
  })
  const soltar = () => {
    if (moveu) { // o clique que o navegador dispara logo após soltar não abre nada; o próximo, sim
      engolirClique = true
      setTimeout(() => { engolirClique = false }, 0)
    }
    arrasto = null
    moveu = false
    quadro.classList.remove('arrastando')
  }
  quadro.addEventListener('pointerup', soltar)
  quadro.addEventListener('pointercancel', soltar)
  quadro.addEventListener('click', (e) => {
    if (engolirClique) {
      engolirClique = false
      e.preventDefault()
      e.stopPropagation()
      return
    }
    const ponto = e.target.closest('.ponto')
    if (!ponto) return
    e.preventDefault()
    e.stopPropagation()
    const p = dados.pontos[ponto.dataset.i]
    if (dados.camada === 'perfis') navegar('#/conta/' + enc(p.username))
    else abrirPost(p.id)
  }, true)
  quadro.addEventListener('pointerover', (e) => {
    const ponto = e.target.closest?.('.ponto')
    if (ponto && ponto !== atual && !arrasto && e.pointerType === 'mouse') mostrar(ponto)
  })
  quadro.addEventListener('pointerout', (e) => {
    if (e.target.closest?.('.ponto') && !e.relatedTarget?.closest?.('.ponto')) esconder()
  })
  quadro.addEventListener('wheel', (e) => {
    e.preventDefault()
    const p = noMapa(e)
    zoom(e.deltaY < 0 ? 1.25 : 0.8, p.x, p.y)
  }, { passive: false })
  quadro.querySelector('.mapa-zoom').addEventListener('click', (e) => {
    const botao = e.target.closest('[data-zoom]')
    if (botao) zoom(Number(botao.dataset.zoom))
  })
}

async function paginaMapa(params, pronto) {
  conteudo.innerHTML = esqueletoPagina()
  const camada = CAMADAS_MAPA[params.get('camada')] ? params.get('camada') : 'mencoes'
  const cfg = CAMADAS_MAPA[camada]
  const consulta = new URLSearchParams({ camada })
  for (const chave of ['dias', 'sentimento']) if (params.get(chave)) consulta.set(chave, params.get(chave))
  const [base, dados] = await Promise.all([mapaBase(), api('mapa?' + consulta)])
  if (!pronto()) return
  document.title = 'Mapa · Radar'
  const nomes = new Map(base.municipios.map((m) => [m.id, m.nome]))
  const porId = new Map(dados.municipios.map((m) => [m.id, m.n]))
  const maximo = Math.max(1, ...dados.municipios.map((m) => m.n))
  const faixas = faixasDoMapa(maximo)
  const unidade = (n) => plural(n, ...cfg.unidade)
  const caminhos = base.municipios.map((m) => {
    const n = porId.get(m.id) || 0
    return `<a href="#/municipio/${m.id}" aria-label="${esc(m.nome)}: ${n} ${esc(unidade(n))}"><path d="${esc(m.d)}" style="--c:${corDaFaixa(n, faixas)}"/></a>`
  }).join('')
  const filtros = [chips('camada', Object.entries(CAMADAS_MAPA).map(([k, v]) => [k, v.rotulo]), camada)]
  if (cfg.dias) filtros.push(chips('dias', cfg.dias, dados.dias == null ? 'todos' : String(dados.dias)))
  if (camada === 'mencoes') filtros.push(chips('sentimento', SENTIMENTOS, dados.sentimento || '', COR))
  const ranking = dados.municipios.slice(0, 30).map((m, i) => `<li><a href="#/municipio/${m.id}"><span class="pos">${i + 1}</span><span class="nome">${esc(m.nome)}</span><span class="valor">${inteiro(m.n)}</span><span class="barra" style="--p:${Math.round((100 * m.n) / maximo)}%"></span></a></li>`).join('')
  const vazio = { mencoes: 'Nenhuma menção com local nesse período.', perfis: 'Nenhuma conta com cidade conhecida.' }[camada]
  const proporcao = (base.largura / base.altura).toFixed(4)
  conteudo.innerHTML = `<div class="pagina pagina-mapa">
    <div class="pagina-cabeca"><h1 class="pagina-titulo">Mapa</h1>
      <p class="contagem"><b>${inteiro(dados.total)}</b>${esc(unidade(dados.total))} em <b>${inteiro(dados.municipios.length)}</b>${plural(dados.municipios.length, 'município', 'municípios')}${dados.semLocal ? ` · <b>${inteiro(dados.semLocal)}</b>sem local` : ''}</p></div>
    <div class="filtros-linha">${filtros.join('')}</div>
    <div class="mapa-pagina">
      <figure class="mapa" style="margin:0">
        <div class="mapa-quadro">
          <svg viewBox="0 0 ${base.largura} ${base.altura}" style="--proporcao:${proporcao}" role="img" aria-label="Mapa do Tocantins: ${esc(cfg.unidade[1])} por município">
            <defs><clipPath id="recorte-redondo" clipPathUnits="objectBoundingBox"><circle cx=".5" cy=".5" r=".5"/></clipPath></defs>
            <g class="mun">${caminhos}</g><g class="pontos" aria-hidden="true">${pontosHTML(dados)}</g>
          </svg>
          <div class="mapa-zoom"><button type="button" data-zoom="1.6" aria-label="Aproximar">+</button><button type="button" data-zoom="0.625" aria-label="Afastar">−</button><button class="zoom-tudo" type="button" data-zoom="0" aria-label="Mostrar o Tocantins inteiro">TO</button></div>
          <div class="dica" hidden></div>
        </div>
        <figcaption class="legenda-mapa">${legendaDaCamada(camada, faixas)}</figcaption>
      </figure>
      ${ranking ? `<ol class="ranking">${ranking}</ol>` : `<p class="vazio">${vazio}</p>`}
    </div>
  </div>`
  ativarMapa(conteudo.querySelector('.mapa-quadro'), dados, nomes, base)
}

async function paginaMunicipio(id, pronto) {
  conteudo.innerHTML = esqueletoPagina()
  const d = await api('municipio/' + enc(id))
  if (!pronto()) return
  document.title = `${d.nome} · Radar`
  const fatos = [
    d.populacao ? `<span><b>${compacto(d.populacao)}</b>habitantes</span>` : '',
    `<span><b>${inteiro(d.mencoes)}</b>${plural(d.mencoes, 'menção', 'menções')} à Energisa</span>`,
    d.contas ? `<span><b>${inteiro(d.contas)}</b>${plural(d.contas, 'conta da cidade falou', 'contas da cidade falaram')} da Energisa</span>` : '',
  ].join('')
  conteudo.innerHTML = `<section class="cidade">
      <div><h1 class="pagina-titulo">${esc(d.nome)}</h1><p class="perfil-fatos">${fatos}</p></div>
      <div class="cidade-silhueta" aria-hidden="true"><svg><path d="${esc(d.d)}"/></svg></div>
    </section>
    ${d.linhas.length ? `<div class="linhas">${d.linhas.map(linhaHTML).join('')}</div>` : '<p class="vazio bloco">Nenhuma menção à Energisa neste município ainda.</p>'}`
  const svg = conteudo.querySelector('.cidade-silhueta svg')
  const caixa = svg.querySelector('path').getBBox()
  const folga = Math.max(caixa.width, caixa.height) * 0.06
  svg.setAttribute('viewBox', `${caixa.x - folga} ${caixa.y - folga} ${caixa.width + 2 * folga} ${caixa.height + 2 * folga}`)
  ativarTrilhos(conteudo)
}

async function paginaBusca(params, pronto) {
  const q = params.get('q') || ''
  document.title = q ? `${q} · Radar` : 'Busca · Radar'
  // A página fica de pé enquanto se digita: só os resultados mudam, e o campo não perde o foco.
  let pagina = conteudo.querySelector('.pagina-busca')
  if (!pagina) {
    conteudo.innerHTML = `<div class="pagina pagina-busca">
      <div class="pagina-cabeca"><h1 class="pagina-titulo" data-titulo></h1><p class="contagem" data-contagem></p></div>
      <input class="campo-busca campo-pagina" type="search" placeholder="Buscar nas menções e contas" aria-label="Buscar nas menções à Energisa e nas contas que as publicaram" autocomplete="off" spellcheck="false">
      <div data-resultados></div>
    </div>`
    pagina = conteudo.querySelector('.pagina-busca')
    ligarBusca(pagina.querySelector('.campo-pagina'))
  }
  const campo = pagina.querySelector('.campo-pagina')
  if (document.activeElement !== campo) campo.value = q
  pagina.querySelector('[data-titulo]').textContent = q ? `“${q}”` : 'Busca'
  const resultados = pagina.querySelector('[data-resultados]')
  const contagem = pagina.querySelector('[data-contagem]')
  if (q.trim().length < 2) {
    resultados.innerHTML = ''
    contagem.textContent = ''
    if (document.activeElement !== campoBusca) campo.focus()
    return
  }
  const dados = await api('busca?q=' + enc(q))
  if (!pronto()) return
  contagem.innerHTML = `<b>${inteiro(dados.posts.length)}</b>${plural(dados.posts.length, 'menção', 'menções')} · <b>${inteiro(dados.contas.length)}</b>${plural(dados.contas.length, 'conta', 'contas')}`
  const contas = dados.contas.length ? linhaHTML({ id: 'busca-contas', titulo: 'Contas', formato: 'conta', itens: dados.contas, verTudo: false }) : ''
  resultados.innerHTML = `${contas ? `<div class="linhas" style="margin-bottom:28px">${contas}</div>` : ''}
    ${dados.posts.length ? `<div class="grade" data-formato="post">${cartoes(dados.posts, 'post')}</div>` : '<p class="vazio">Nenhuma menção à Energisa com esse termo.</p>'}`
  ativarTrilhos(resultados)
}

// ---------- Busca ----------
let timerBusca = 0
function irParaBusca(valor) {
  const q = valor.trim()
  if (q.length < 2) return
  const destino = '#/busca?q=' + enc(q)
  navegar(destino, lerRota().partes[0] === 'busca')
}
function ligarBusca(campo) {
  if (!campo) return
  campo.addEventListener('input', () => {
    clearTimeout(timerBusca)
    timerBusca = setTimeout(() => irParaBusca(campo.value), 300)
  })
  campo.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      clearTimeout(timerBusca)
      irParaBusca(campo.value)
    } else if (e.key === 'Escape') {
      campo.value = ''
      campo.blur()
    }
  })
}
ligarBusca(campoBusca)

// ---------- Cliques ----------
document.addEventListener('click', (e) => {
  const alvo = e.target
  const abrir = alvo.closest('[data-abrir]')
  if (abrir) {
    e.preventDefault()
    abrirPost(abrir.dataset.abrir)
    return
  }
  const card = alvo.closest('.card[data-post]')
  if (card) {
    abrirPost(card.dataset.post)
    return
  }
  if (alvo.closest('.modal-fechar')) {
    fecharPost()
    return
  }
  const rolar = alvo.closest('[data-rolar]')
  if (rolar) {
    document.getElementById(rolar.dataset.rolar)?.closest('.linha')?.scrollIntoView({ behavior: suave(), block: 'start' })
    return
  }
  const lerMais = alvo.closest('.ler-mais')
  if (lerMais) {
    lerMais.previousElementSibling?.removeAttribute('data-curta')
    lerMais.remove()
    return
  }
  const filtro = alvo.closest('[data-filtro]')
  if (filtro) trocarFiltro(filtro)
})

// ---------- Ao vivo ----------
let ultimoId = null
async function atualizarStatus() {
  if (document.hidden) return
  try {
    const s = await api('status' + (ultimoId ? `?apos=${ultimoId}` : ''))
    if (s.estatico) { // site sem servidor: os dados são do momento em que ele foi gerado
      aoVivo.dataset.estado = 'parado'
      aoVivo.textContent = `Dados até ${fmtDia.format(new Date(s.agora + 'Z')).replace('.', '')}`
      return
    }
    if (ultimoId == null) ultimoId = s.ultimoId
    const parado = quando(s.ultimaVisita)
    aoVivo.dataset.estado = s.aoVivo ? 'vivo' : 'parado'
    aoVivo.textContent = s.aoVivo ? 'Ao vivo' : s.ultimaVisita ? `Parado ${/^(há|agora|ontem)/.test(parado) ? parado : 'desde ' + parado}` : 'Parado'
    aoVivo.title = s.ultimaVisita ? `Última visita a uma página: ${dataCompleta(s.ultimaVisita)}` : ''
    if (s.novos > 0) {
      const texto = `${inteiro(s.novos)} ${plural(s.novos, 'novidade', 'novidades')}`
      if (botaoNovidades.hidden || botaoNovidades.textContent !== texto) {
        botaoNovidades.textContent = texto
        botaoNovidades.hidden = false
        anuncio.textContent = `${texto} no radar`
      }
    }
  } catch {
    aoVivo.dataset.estado = 'parado'
    aoVivo.textContent = 'Painel desconectado'
  }
}
botaoNovidades.addEventListener('click', () => {
  ultimoId = null
  botaoNovidades.hidden = true
  chaveAtual = null
  sincronizar()
  atualizarStatus()
})
if (!estatico) setInterval(atualizarStatus, 30000)
document.addEventListener('visibilitychange', () => { if (!document.hidden) atualizarStatus() })

sincronizar()
atualizarStatus()
