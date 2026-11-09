// Mapa das calçadas: ruas coloridas pela avaliação das fotos, num gradiente
// que depende do zoom; avaliação das fotos à mão, exportação para o Roboflow
// e coleta de ruas novas. Os dados vêm do servidor local
// (scripts/interface/servidor.py): ver dados.js.

// As classes de avaliação (banco.CLASSES_AVALIACAO): cor e nome na tela.
const CORES = {
  adequada: "#1a9641",
  parcialmente_adequada: "#a88400",
  inadequada: "#e66101",
  sem_calcada: "#b2182b",
  nao_identificavel: "#7b3294",
};
const NOMES = {
  adequada: "Adequada",
  parcialmente_adequada: "Parcialmente adequada",
  inadequada: "Inadequada",
  sem_calcada: "Sem calçada",
  nao_identificavel: "Não identificável",
};
// Da melhor para a pior (a ordem dos botões e das teclas 1–5), e por fim a que não tem nota.
const CLASSES = ["adequada", "parcialmente_adequada", "inadequada", "sem_calcada", "nao_identificavel"];
// Nota de cada classe, de 0 (pior) a 1 (melhor). `nao_identificavel` não tem
// nota: não diz nada sobre a calçada.
const NOTAS = { adequada: 1, parcialmente_adequada: 0.7, inadequada: 0.4, sem_calcada: 0 };
// O nome de cada classe no projeto do Roboflow (sem acento, como o
// scripts/transformacao/extract_features.py procura).
const NOMES_ROBOFLOW = {
  adequada: "Adequada", parcialmente_adequada: "Parcialmente Adequado", inadequada: "Inadequada",
  sem_calcada: "Sem calcada", nao_identificavel: "Nao identificavel",
};

// Escala de cores da nota (0 = sem calçada, 0.4 = inadequada, 0.7 =
// parcialmente adequada, 1 = adequada).
// Fica toda verde a partir de 0.85: uma rua em sua maioria adequada é verde.
const ESCALA = [[0, "#b2182b"], [0.4, "#e66101"], [0.65, "#e8b81e"], [0.85, "#1a9641"], [1, "#1a9641"]];
const NIVEIS = 40; // tons distintos da escala: trechos vizinhos com o mesmo tom viram uma linha só

// Raio da média (ver notaEm), em pixels de tela: o mesmo em qualquer zoom,
// então de longe ele cobre a rua inteira e de perto só as fotos vizinhas.
const RAIO_PX = 30;
const RAIO_MIN = 15; // m: abaixo disso, o detalhe seria menor que uma zona de coleta

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...filhos) => {
  const e = document.createElement(tag);
  for (const [chave, valor] of Object.entries(props)) {
    if (chave.includes("-")) e.setAttribute(chave, valor); // aria-*, data-*
    else e[chave] = valor;
  }
  e.append(...filhos);
  return e;
};

// A API da coleta, no servidor local (os dados do mapa vêm de FONTE, dados.js).
async function api(rota, corpo) {
  const resp = await fetch(rota, corpo === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo),
  });
  const dados = await resp.json();
  if (!resp.ok) throw Object.assign(new Error(dados.erro || resp.statusText), { dados, status: resp.status });
  return dados;
}

function esc(texto) {
  return String(texto ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function corDaNota(nota) {
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  for (let i = 1; i < ESCALA.length; i++) {
    const [n1, c1] = ESCALA[i];
    if (nota <= n1) {
      const [n0, c0] = ESCALA[i - 1];
      const t = (nota - n0) / (n1 - n0 || 1);
      const [a, b] = [hex(c0), hex(c1)];
      return `rgb(${a.map((v, j) => Math.round(v + t * (b[j] - v))).join(",")})`;
    }
  }
  return ESCALA[ESCALA.length - 1][1];
}

// --------------------------------------------------------------------------
// Mapa
// --------------------------------------------------------------------------

// Canvas com tolerância: as linhas finas (1 px de longe) ainda pegam o mouse e o toque.
const mapa = L.map("mapa", { renderer: L.canvas({ tolerance: 8 }), zoomControl: false }).setView([-25.4284, -49.2733], 13);
const icone = (nome) => `<svg class="icone" aria-hidden="true"><use href="#i-${nome}"/></svg>`;

function lerPreferencia(chave, padrao) {
  try { return localStorage.getItem(chave) || padrao; } catch { return padrao; }
}
function gravarPreferencia(chave, valor) {
  try { localStorage.setItem(chave, valor); } catch {}
}

// Botão de recolher o painel lateral, acima do zoom; a escolha fica no navegador.
const BotaoPainel = L.Control.extend({
  onAdd() {
    const barra = L.DomUtil.create("div", "leaflet-bar");
    const botao = L.DomUtil.create("a", "alternar-painel", barra);
    botao.href = "#";
    botao.setAttribute("role", "button");
    botao.setAttribute("aria-controls", "painel");
    const atualizar = () => {
      const recolhido = document.body.classList.contains("painel-recolhido");
      botao.innerHTML = icone(recolhido ? "panel-open" : "panel-close");
      botao.title = recolhido ? "Mostrar o painel" : "Recolher o painel";
      botao.setAttribute("aria-label", botao.title);
      botao.setAttribute("aria-expanded", String(!recolhido));
    };
    L.DomEvent.disableClickPropagation(barra);
    L.DomEvent.on(botao, "click", (ev) => {
      L.DomEvent.preventDefault(ev);
      const recolhido = document.body.classList.toggle("painel-recolhido");
      gravarPreferencia("painelRecolhido", recolhido ? "1" : "");
      atualizar();
      // Depois da animação da coluna (180 ms), o mapa mede de novo a largura final.
      setTimeout(() => mapa.invalidateSize(), duracao(260) + 20);
    });
    atualizar();
    return barra;
  },
});
if (lerPreferencia("painelRecolhido", "")) document.body.classList.add("painel-recolhido");
new BotaoPainel({ position: "topleft" }).addTo(mapa);
L.control.zoom({ position: "topleft", zoomInTitle: "Aproximar", zoomOutTitle: "Afastar" }).addTo(mapa);
// O mapa muda de largura quando o painel abre ou fecha.
new ResizeObserver(() => mapa.invalidateSize()).observe($("mapa"));
const escuro = matchMedia("(prefers-color-scheme: dark)").matches;
// Com movimento reduzido pedido pelo sistema, as animações ficam mais curtas (não somem: foram pedidas).
const REDUZIR_MOVIMENTO = matchMedia("(prefers-reduced-motion: reduce)").matches;
const duracao = (ms) => (REDUZIR_MOVIMENTO ? Math.min(ms, 150) : ms);
// Roda `fim` quando a animação termina, uma vez só. O estado final não
// depende só do evento: um temporizador garante (aba em segundo plano,
// animação congelada) e um cancel() não dispara nada.
function aoTerminar(animacao, ms, fim) {
  let feito = false;
  const concluir = () => {
    if (feito || animacao.playState === "idle") return; // cancelada
    feito = true;
    fim();
  };
  animacao.onfinish = concluir;
  setTimeout(concluir, ms + 80);
}
// Mapa de fundo: Stadia Alidade Smooth, claro ou escuro conforme o tema, nos
// mesmos cinzas da página e com poucos ícones (nada de hospital em destaque
// de longe). Em 127.0.0.1 funciona sem conta na Stadia.
L.tileLayer(`https://tiles.stadiamaps.com/tiles/${escuro ? "alidade_smooth_dark" : "alidade_smooth"}/{z}/{x}/{y}{r}.png`, {
  maxZoom: 19,
  attribution: '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a> &copy; <a href="https://openmaptiles.org/">OpenMapTiles</a> '
    + '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(mapa);

const camadaRuas = L.layerGroup().addTo(mapa);   // modo "tudo": as ruas coloridas
const camadaFotos = L.layerGroup();
// As fotos só aparecem de perto: na escala da cidade, cobririam as cores das ruas.
const ZOOM_FOTOS = 15;
mapa.on("zoomend viewreset", () => {
  if (dados) {
    desenharTracados(); // o raio da média e a largura da linha mudaram
    estilizarFotos();
  }
  mostrarFotos();
});
let fixos = null;    // ruas e zonas, como vieram da fonte (mudam só com uma coleta)
let registro = null; // avaliações e exportações, como vieram da fonte
let dados = null;    // o que o mapa desenha, montado dos dois (montarDados)
let zona = null;    // a zona aberta no painel
let ruaSelecionada = null; // a rua destacada pelo clique no card da lista
let foco = 0;       // índice do quadrado destacado no painel

// Esmaece as linhas e fotos de um grupo de `de` a `para` (opacidade); `fim`
// roda no final. Uma animação nova no mesmo grupo cancela a anterior.
function esmaecer(grupo, de, para, fim) {
  const ms = duracao(260);
  const id = (grupo._animacao = (grupo._animacao || 0) + 1);
  const inicio = performance.now();
  let feito = false;
  const concluir = () => {
    if (feito || grupo._animacao !== id) return;
    feito = true;
    definirOpacidade(grupo, para);
    if (fim) fim();
  };
  const quadro = (agora) => {
    if (feito || grupo._animacao !== id) return;
    const t = ms ? Math.min(1, (agora - inicio) / ms) : 1;
    definirOpacidade(grupo, de + (para - de) * (1 - (1 - t) ** 3)); // desacelera no fim
    if (t < 1) requestAnimationFrame(quadro);
    else concluir();
  };
  requestAnimationFrame(quadro);
  setTimeout(concluir, ms + 80); // o estado final não depende dos quadros (aba em segundo plano)
}
function definirOpacidade(grupo, o) {
  grupo._opacidade = o;
  grupo.eachLayer((c) => {
    const final = o * (c._opacidadeBase ?? 1); // _opacidadeBase: rua fora da seleção fica esmaecida
    c.setStyle(c instanceof L.CircleMarker ? { opacity: final, fillOpacity: final } : { opacity: final });
  });
}

// --------------------------------------------------------------------------
// Modos de exibição das avaliações
// --------------------------------------------------------------------------

const MODOS = {
  ocultar: "Mapa limpo, sem nenhuma rua ou foto destacada.",
  foco: "Passe o mouse numa rua avaliada para acender a avaliação em volta dele.",
  tudo: "Todas as ruas avaliadas coloridas pela nota.",
};
const ORDEM_MODOS = Object.keys(MODOS);
const NEUTRA = escuro ? "#ababab" : "#6b6b6b"; // barras da lista com a avaliação oculta
let modo = lerPreferencia("modo", "tudo");
if (!(modo in MODOS)) modo = "tudo";

function escolherModo(novo) {
  if (novo === modo) return;
  modo = novo;
  holofote.mouse = null;
  holofote.lista = null;
  gravarPreferencia("modo", modo);
  aplicarModo(true);
}

// Aplica o modo: o indicador desliza até a opção, o texto de ajuda troca
// esmaecendo e, no mapa, as ruas e as fotos aparecem ou somem aos poucos.
function aplicarModo(animar = false) {
  for (const botao of document.querySelectorAll("#modos [role=radio]")) {
    const ativo = botao.dataset.modo === modo;
    botao.setAttribute("aria-checked", String(ativo));
    botao.tabIndex = ativo ? 0 : -1;
  }
  document.querySelector("#modos .indicador").dataset.posicao = ORDEM_MODOS.indexOf(modo);
  // Os três textos ficam empilhados no mesmo lugar, então a seção não muda de
  // altura; só o do modo escolhido aparece (troca esmaecendo, pelo CSS).
  const ajuda = $("modo-ajuda");
  if (!ajuda.children.length) ajuda.append(...ORDEM_MODOS.map((m) => el("span", { textContent: MODOS[m] })));
  [...ajuda.children].forEach((texto, i) => texto.classList.toggle("ativo", ORDEM_MODOS[i] === modo));
  $("legenda").classList.toggle("apagada", modo === "ocultar");

  if (modo === "tudo" && !mapa.hasLayer(camadaRuas)) {
    camadaRuas.addTo(mapa);
    if (animar) { definirOpacidade(camadaRuas, 0); esmaecer(camadaRuas, 0, 1); }
  } else if (modo !== "tudo" && mapa.hasLayer(camadaRuas)) {
    if (animar) esmaecer(camadaRuas, 1, 0, () => camadaRuas.remove());
    else camadaRuas.remove();
  } else if (modo === "tudo") {
    esmaecer(camadaRuas, 1, 1); // cancela um esmaecimento de saída em andamento
  }
  mostrarFotos(animar);
  if (!dados) return;
  estilizarFotos();
  desenharRuas();
  atualizarRuas();
}

// O controle segmentado: clique, ou setas quando ele tem o foco.
for (const botao of document.querySelectorAll("#modos [role=radio]")) {
  botao.onclick = () => escolherModo(botao.dataset.modo);
}
$("modos").addEventListener("keydown", (ev) => {
  const passo = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[ev.key];
  if (!passo) return;
  ev.preventDefault();
  const novo = ORDEM_MODOS[(ORDEM_MODOS.indexOf(modo) + passo + ORDEM_MODOS.length) % ORDEM_MODOS.length];
  escolherModo(novo);
  document.querySelector(`#modos [data-modo="${novo}"]`).focus();
});

// --------------------------------------------------------------------------
// Holofote (modo "ao passar"): acende só o gradiente em volta do mouse, na
// rua avaliada mais próxima dele. Desenhado num canvas próprio, que acompanha
// o mapa; as ruas apagadas não são desenhadas.
// --------------------------------------------------------------------------

const HOLOFOTE_RAIO = 90;      // px: até onde o gradiente acende em volta do mouse
const HOLOFOTE_ALCANCE = 14;   // px: o mouse "está sobre a rua" até essa distância dela

const holofote = {
  mouse: null,   // { rua, ponto }: a rua sob o mouse e onde ele está (layer point)
  lista: null,   // nome da rua sob o mouse na lista: acende inteira
};
let tracados = []; // por rua avaliada: os segmentos em layer points, com a cor de cada um

mapa.createPane("holofote").style.zIndex = 390; // abaixo das fotos
const CamadaHolofote = L.Layer.extend({
  onAdd(m) {
    this._canvas = L.DomUtil.create("canvas", "leaflet-zoom-hide");
    m.getPane("holofote").appendChild(this._canvas);
    m.on("moveend zoomend resize", this._posicionar, this);
    this._posicionar();
  },
  onRemove(m) {
    this._canvas.remove();
    m.off("moveend zoomend resize", this._posicionar, this);
  },
  _posicionar() {
    const tamanho = this._map.getSize(), escala = window.devicePixelRatio || 1;
    this._origem = this._map.containerPointToLayerPoint([0, 0]);
    L.DomUtil.setPosition(this._canvas, this._origem);
    Object.assign(this._canvas, { width: tamanho.x * escala, height: tamanho.y * escala });
    Object.assign(this._canvas.style, { width: `${tamanho.x}px`, height: `${tamanho.y}px` });
    this._ctx = this._canvas.getContext("2d");
    this._ctx.setTransform(escala, 0, 0, escala, 0, 0);
    this.redesenhar();
  },
  redesenhar() {
    const ctx = this._ctx, o = this._origem;
    ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
    const alvo = alvoDoHolofote();
    if (!alvo) return;
    ctx.lineCap = "round";
    ctx.lineWidth = larguraDaLinha();
    for (const t of alvo.tracado.trechos) {
      for (let i = 0; i < t.pontos.length - 1; i++) {
        const a = t.pontos[i], b = t.pontos[i + 1];
        let alfa = 1;
        if (alvo.ponto) {
          const d = alvo.ponto.distanceTo(L.point((a.x + b.x) / 2, (a.y + b.y) / 2));
          if (d >= HOLOFOTE_RAIO) continue;
          alfa = (1 - d / HOLOFOTE_RAIO) ** 1.5; // apaga aos poucos até a borda
        }
        ctx.globalAlpha = alfa;
        ctx.strokeStyle = t.cores[i];
        ctx.beginPath();
        ctx.moveTo(a.x - o.x, a.y - o.y);
        ctx.lineTo(b.x - o.x, b.y - o.y);
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  },
});
const camadaHolofote = new CamadaHolofote().addTo(mapa);

// O que o holofote ilumina agora: a rua da lista (inteira), a rua sob o
// mouse (em volta dele) ou, sem mouse, a rua da zona aberta (em volta da foto)
// ou a rua selecionada (inteira). No modo "Ocultar", só a rua selecionada.
function alvoDoHolofote() {
  const achar = (nome) => tracados.find((t) => t.nome === nome);
  if (modo === "ocultar" && ruaSelecionada && achar(ruaSelecionada)) return { tracado: achar(ruaSelecionada), ponto: null };
  if (modo !== "foco") return null;
  if (holofote.lista) return achar(holofote.lista) && { tracado: achar(holofote.lista), ponto: null };
  if (holofote.mouse) return { tracado: achar(holofote.mouse.rua), ponto: holofote.mouse.ponto };
  if (zona) {
    const tracado = zona.ruas.map(achar).find(Boolean);
    if (tracado) return { tracado, ponto: mapa.latLngToLayerPoint([zona.lat, zona.lon]) };
  }
  if (ruaSelecionada && achar(ruaSelecionada)) return { tracado: achar(ruaSelecionada), ponto: null };
  return null;
}

// A rua avaliada mais perto de um ponto (layer point), se estiver a até HOLOFOTE_ALCANCE px.
function ruaPerto(p) {
  let melhor = null, menor = HOLOFOTE_ALCANCE;
  for (const t of tracados) {
    if (!t.limites.contains(p)) continue;
    for (const tr of t.trechos) {
      for (let i = 0; i < tr.pontos.length - 1; i++) {
        const d = L.LineUtil.pointToSegmentDistance(p, tr.pontos[i], tr.pontos[i + 1]);
        if (d < menor) {
          menor = d;
          melhor = { tracado: t, nota: (tr.notas[i] + tr.notas[i + 1]) / 2 };
        }
      }
    }
  }
  return melhor;
}

const dicaHolofote = L.tooltip({ direction: "top", offset: [0, -14], className: "dica-holofote" });
let quadroPendente = null;
mapa.on("mousemove", (ev) => {
  if (modo !== "foco") return;
  if (quadroPendente) cancelAnimationFrame(quadroPendente);
  quadroPendente = requestAnimationFrame(() => {
    quadroPendente = null;
    const achou = ruaPerto(ev.layerPoint);
    holofote.mouse = achou ? { rua: achou.tracado.nome, ponto: ev.layerPoint } : null;
    mapa.getContainer().style.cursor = achou ? "pointer" : "";
    if (achou && !fotoSobMouse) { // sobre uma foto, só a prévia dela aparece
      dicaHolofote.setLatLng(ev.latlng).setContent(`<b>${esc(achou.tracado.nome)}</b><br>nota ${formatarNota(achou.nota)}`);
      if (!mapa.hasLayer(dicaHolofote)) dicaHolofote.addTo(mapa);
    } else {
      dicaHolofote.remove();
    }
    camadaHolofote.redesenhar();
  });
});
mapa.on("mouseout", () => {
  holofote.mouse = null;
  dicaHolofote.remove();
  mapa.getContainer().style.cursor = "";
  camadaHolofote.redesenhar();
});
// Clique no mapa: no modo "ao passar", perto de uma rua avaliada abre a foto
// mais próxima; em qualquer outro ponto vazio, fecha o painel da zona.
// (Fotos e trechos coloridos tratam o próprio clique e não chegam aqui.)
mapa.on("click", (ev) => {
  const achou = modo === "foco" && ruaPerto(ev.layerPoint);
  if (achou) abrirFotoMaisProxima(achou.tracado.fotos, ev.latlng);
  else if (zona) fecharZona();
  else if (ruaSelecionada) selecionarRua(null);
});

// Passar o mouse (ou o foco do teclado) numa rua da lista acende a rua inteira.
function revelarRua(nome) {
  if (modo !== "foco") return;
  holofote.lista = nome;
  atualizarRuas();
}
function esconderRua(nome) {
  if (holofote.lista !== nome) return;
  holofote.lista = null;
  atualizarRuas();
}

// Depois de mudar o modo, a lista ou a zona aberta: redesenha o holofote.
function atualizarRuas() {
  camadaHolofote.redesenhar();
  for (const item of document.querySelectorAll(".rua")) item.classList.toggle("revelada", item.dataset.rua === holofote.lista);
}

// --------------------------------------------------------------------------
// Ruas e fotos no mapa
// --------------------------------------------------------------------------

// Busca os dados na fonte e redesenha o que mudou. `soAvaliacoes` reaproveita
// as ruas e zonas já carregadas; sem mudança desde a última vez, nada é
// redesenhado (a atualização periódica não mexe na tela à toa).
let assinatura = "";
async function carregar(enquadrar = false, { soAvaliacoes = false } = {}) {
  try {
    [fixos, registro] = await Promise.all([
      soAvaliacoes && fixos ? fixos : FONTE.carregarFixos(),
      FONTE.carregarAvaliacoes(),
    ]);
  } catch (e) {
    if (!dados) $("ruas").replaceChildren(el("li", { className: "vazio erro", textContent: `Não deu para carregar o mapa: ${e.message}` }));
    else if (!soAvaliacoes) mostrarToast("erro", "alerta", "Não deu para atualizar o mapa", e.message);
    return;
  }
  const nova = JSON.stringify([fixos.zonas.map((z) => [z.id, z.posicao]), fixos.ruas.map((r) => [r.nome, r.zonas, r.pendentes]),
    registro.avaliacoes.map((a) => [a.ponto_id, a.posicao, a.quadrado, a.classe, a.quando]), registro.exportados.length, registro.ultima]);
  if (nova === assinatura && !enquadrar) return;
  assinatura = nova;
  redesenhar(enquadrar);
}

function redesenhar(enquadrar = false) {
  dados = montarDados(fixos, registro);
  if (enquadrar && dados.ruas.length) mapa.fitBounds(limitesDe(dados.ruas), { padding: [30, 30] });
  desenharTracados();
  desenharFotos();
  desenharRuas();
  desenharProgresso();
  if (zona) { // outra pessoa pode ter avaliado a zona aberta
    const atual = zonaDetalhada(zona.zona);
    if (atual) { zona = atual; desenharQuadrados(); }
  }
}

const chaveDe = (pid, posicao, k) => `${pid}_${posicao}_${k}`;

// "2026-10-24 21:16:41.732" (UTC, do banco) -> ms
function instante(quando) {
  let t = quando.replace(" ", "T").replace(/(\.\d{3})\d+/, "$1");
  if (!/(Z|[+-]\d\d:?\d\d)$/.test(t)) t += "Z";
  return Date.parse(t);
}

// Das ruas, zonas e avaliações, o que o mapa e a barra lateral mostram:
//   fotos       uma por (rua, zona): o ponto, os quadrados, as classes e a nota da zona
//               (a média das notas dos quadrados avaliados, NOTAS)
//   ruas        o traçado e o resumo de cada rua
//   exportacao  quantas avaliações há e quantas são novas, no total e por rua
//   avaliacoes  a avaliação de cada quadrado da vista escolhida, por chaveDe
function montarDados({ ruas, zonas }, { avaliacoes, exportados, ultima }) {
  const porChave = new Map(avaliacoes.map((a) => [chaveDe(a.ponto_id, a.posicao, a.quadrado), a]));
  const exportado = new Map(exportados.map((e) => [chaveDe(e.ponto_id, e.posicao, e.quadrado), e.quando_avaliacao]));
  const nova = (a) => {
    const e = exportado.get(chaveDe(a.ponto_id, a.posicao, a.quadrado));
    return !e || instante(a.quando) > instante(e);
  };

  const validas = new Map(); // só as avaliações de quadrados que estão na vista escolhida
  const fotos = [];
  const exportacao = { total: 0, novas: 0, ruas: {}, ultima };
  for (const z of zonas) {
    const classes = [];
    let novas = 0;
    for (const q of z.quadrados) {
      const chave = chaveDe(z.id, z.posicao, q.quadrado);
      const a = porChave.get(chave);
      if (!a) continue;
      validas.set(chave, a);
      classes.push(a.classe);
      if (nova(a)) novas++;
    }
    const notas = classes.filter((c) => c in NOTAS).map((c) => NOTAS[c]);
    const contagem = {};
    for (const c of classes) contagem[c] = (contagem[c] || 0) + 1;
    exportacao.total += classes.length;
    exportacao.novas += novas;
    for (const rua of z.ruas) {
      fotos.push({
        rua, zona: z.id, posicao: z.posicao, lat: z.lat, lon: z.lon, endereco: z.endereco, captura: z.captura,
        quadrados: z.quadrados.map((q) => q.quadrado), avaliados: classes.length, classes: contagem,
        nota: notas.length ? notas.reduce((s, n) => s + n, 0) / notas.length : null,
      });
      if (classes.length) {
        const r = (exportacao.ruas[rua] ||= { total: 0, novas: 0 });
        r.total += classes.length;
        r.novas += novas;
      }
    }
  }
  fotos.sort((a, b) => a.rua.localeCompare(b.rua) || a.zona - b.zona);

  const resumoDas = (nome) => {
    const daRua = fotos.filter((f) => f.rua === nome);
    return {
      com_foto: daRua.length, avaliadas: daRua.filter((f) => f.avaliados).length,
      classes: Object.fromEntries(CLASSES.map((c) => [c, daRua.reduce((s, f) => s + (f.classes[c] || 0), 0)])),
    };
  };
  return {
    ruas: ruas.map((r) => ({ ...r, ...resumoDas(r.nome) })),
    fotos, exportacao, avaliacoes: validas, nova,
    zonas: new Map(zonas.map((z) => [z.id, z])),
  };
}

// A zona como o painel mostra: a vista de contexto e os quadrados, cada um
// com a foto e a avaliação.
function zonaDetalhada(id) {
  const z = dados.zonas.get(id);
  if (!z) return null;
  return {
    ...z, zona: z.id,
    contexto: FONTE.imagem("contexto", `${z.id}_${z.posicao}.jpg`),
    quadrados: z.quadrados.map((q) => ({
      ...q,
      url: FONTE.imagem("quadrados", `${z.id}_${z.posicao}_${q.quadrado}.jpg`),
      avaliacao: dados.avaliacoes.get(chaveDe(z.id, z.posicao, q.quadrado)) || null,
    })),
  };
}

function limitesDe(ruas) {
  return L.latLngBounds(ruas.flatMap((r) => r.trechos.flat()));
}

function raioEmMetros() {
  const metrosPorPixel = 156543.03 * Math.cos(mapa.getCenter().lat * Math.PI / 180) / 2 ** mapa.getZoom();
  return Math.max(RAIO_MIN, RAIO_PX * metrosPorPixel);
}

// Nota num ponto: média das notas das fotos da rua, com peso 1 / (d² + r²),
// d a distância até a foto e r o raio do zoom. De perto (r pequeno) é uma
// interpolação pelo inverso da distância: entre duas fotos a cor passa de
// uma para a outra aos poucos, no caminho todo. De longe (r grande) as fotos
// pesam quase igual e sai a média geral da rua.
function notaEm(x, y, fotos, raio2) {
  let soma = 0, pesos = 0;
  for (const [fx, fy, nota] of fotos) {
    const peso = 1 / ((x - fx) ** 2 + (y - fy) ** 2 + raio2);
    soma += peso * nota;
    pesos += peso;
  }
  return soma / pesos;
}

const formatarNota = (nota) => nota.toFixed(2).replace(".", ",");

// Calcula a nota de cada vértice das ruas avaliadas no zoom atual. Serve
// às duas formas de mostrar: as linhas do modo "tudo" (camadaRuas) e o
// holofote do modo "ao passar" (tracados). Ruas sem nenhuma nota não são
// desenhadas: só se vê o que já foi avaliado.
function desenharTracados() {
  camadaRuas.clearLayers();
  tracados = [];
  const raio = raioEmMetros();
  const raio2 = raio * raio;
  const largura = larguraDaLinha();
  const texto = (nota) => `nota ${formatarNota(nota)} · média das fotos num raio de ~${formatarDistancia(raio)}`;
  for (const rua of dados.ruas) {
    const latRef = rua.trechos[0][0][0];
    const kx = 111320 * Math.cos(latRef * Math.PI / 180), ky = 111320;
    const daRua = dados.fotos.filter((f) => f.rua === rua.nome);
    const comNota = daRua.filter((f) => f.nota !== null).map((f) => [f.lon * kx, f.lat * ky, f.nota]);
    if (!comNota.length) continue;

    const tracado = { nome: rua.nome, fotos: daRua, trechos: [], limites: L.bounds([]) };
    for (const trecho of rua.trechos) {
      const notas = trecho.map(([lat, lon]) => notaEm(lon * kx, lat * ky, comNota, raio2));
      const pontos = trecho.map((p) => mapa.latLngToLayerPoint(p));
      pontos.forEach((p) => tracado.limites.extend(p));
      tracado.trechos.push({ pontos, notas, cores: notas.slice(1).map((n, i) => corDaNota((n + notas[i]) / 2)) });

      // Modo "tudo": cada segmento tem a nota média das duas pontas, num dos
      // NIVEIS tons; segmentos vizinhos do mesmo tom viram uma linha só.
      const tom = notas.slice(1).map((n, i) => Math.round((n + notas[i]) / 2 * NIVEIS));
      let inicio = 0;
      for (let j = 1; j <= tom.length; j++) {
        if (j === tom.length || tom[j] !== tom[inicio]) {
          const nota = tom[inicio] / NIVEIS;
          const linha = L.polyline(trecho.slice(inicio, j + 1), { color: corDaNota(nota), weight: largura, opacity: 1, lineCap: "round", lineJoin: "round" });
          linha.rua = rua.nome;
          linha
            .bindTooltip(`<b>${esc(rua.nome)}</b><br>${texto(nota)}`, { sticky: true })
            .on("click", (ev) => {
              L.DomEvent.stopPropagation(ev); // não chega ao mapa (que fecharia a zona)
              abrirFotoMaisProxima(daRua, ev.latlng);
            })
            .addTo(camadaRuas);
          inicio = j;
        }
      }
    }
    // Uma margem para a busca do mouse não perder a rua na borda.
    tracado.limites = L.bounds(tracado.limites.min.subtract([HOLOFOTE_RAIO, HOLOFOTE_RAIO]),
      tracado.limites.max.add([HOLOFOTE_RAIO, HOLOFOTE_RAIO]));
    tracados.push(tracado);
  }
  desenharDestaque();
  camadaHolofote.redesenhar();
}

// --------------------------------------------------------------------------
// Rua selecionada (clique no card da lista): ela fica como está e o resto do
// mapa (as outras ruas e as fotos delas) esmaece. No modo "Ao passar" ela
// acende inteira; no "Ocultar", é a única rua desenhada (holofote).
// --------------------------------------------------------------------------

const ESMAECIDA = 0.25; // opacidade do que não é da rua selecionada

function desenharDestaque() {
  camadaRuas.eachLayer((linha) => {
    linha._opacidadeBase = ruaSelecionada && linha.rua !== ruaSelecionada ? ESMAECIDA : 1;
    linha.setStyle({ opacity: (camadaRuas._opacidade ?? 1) * linha._opacidadeBase });
  });
  estilizarFotos();
}

// Seleciona a rua (null desfaz). Selecionar enquadra a rua no mapa.
function selecionarRua(nome) {
  ruaSelecionada = nome;
  for (const card of document.querySelectorAll(".rua")) {
    const sim = card.dataset.rua === nome;
    card.classList.toggle("selecionada", sim);
    card.querySelector(".rua-principal").setAttribute("aria-pressed", String(sim));
  }
  if (dados) desenharDestaque();
  camadaHolofote.redesenhar();
  const rua = nome && dados.ruas.find((r) => r.nome === nome);
  if (rua) mapa.fitBounds(limitesDe([rua]), { padding: [30, 30] });
}

// Largura da linha (px) por zoom: 80% da largura com que o mapa de fundo
// (Stadia Alidade Smooth) desenha uma rua residencial — mediana medida nos
// tiles: 1 px até o zoom 14, 2 px no 15 e 16, 3 no 17, 5 no 18 e 8 no 19. É a
// via mais estreita entre as coletadas, então a cor fica dentro de qualquer
// rua. Abaixo do zoom 15 a linha fica com 1 px (menos que isso some).
const LARGURAS = { 15: 1.6, 16: 1.6, 17: 2.4, 18: 4, 19: 6.4 };
function larguraDaLinha() {
  return LARGURAS[Math.min(19, mapa.getZoom())] || 1;
}

function formatarDistancia(m) {
  return m >= 1000 ? `${(m / 1000).toFixed(1).replace(".", ",")} km` : `${Math.round(m / 5) * 5} m`;
}

function abrirFotoMaisProxima(fotos, latlng) {
  if (!fotos.length) return;
  const maisProxima = fotos.reduce((a, b) => (mapa.distance(latlng, [a.lat, a.lon]) <= mapa.distance(latlng, [b.lat, b.lon]) ? a : b));
  abrirZona(maisProxima.zona);
}

function fotosUnicas() {
  // Uma zona de esquina aparece em duas ruas; no mapa, um marcador só.
  const vistas = new Map();
  for (const f of dados.fotos) if (!vistas.has(f.zona)) vistas.set(f.zona, f);
  return [...vistas.values()];
}

function corDaFoto(f) {
  if (f.nota !== null) return corDaNota(f.nota);
  return f.avaliados ? CORES.nao_identificavel : "#ffffff";
}

// A dica de uma foto é uma prévia: a vista da zona e, embaixo, a zona, a
// nota (só no modo "tudo") e o endereço. A imagem tem tamanho fixo, para a
// dica não pular de lugar quando ela termina de carregar.
function previaDaFoto(marcador) {
  const f = marcador.foto;
  const nota = modo === "tudo" && f.nota !== null
    ? `<span class="previa-nota"><span class="bolinha" style="background:${corDaNota(f.nota)}"></span>${formatarNota(f.nota)}</span>` : "";
  return `<img src="${FONTE.imagem("contexto", `${f.zona}_${f.posicao}.jpg`)}" width="256" height="144" alt="">`
    + `<div class="previa-linha"><b>Zona ${f.zona}</b>${nota}</div>`
    + `<div class="previa-sub">${esc(enderecoCurto(f.endereco))} · ${f.avaliados}/${f.quadrados.length} avaliados</div>`;
}

// A foto sob o mouse: enquanto houver uma, as dicas das ruas ficam fechadas
// (a da foto tem prioridade e as duas não se sobrepõem).
let fotoSobMouse = null;

// Raio das fotos por zoom: pontos discretos, que crescem um pouco de perto.
const RAIOS_FOTO = { 15: 2.5, 16: 3, 17: 3.5, 18: 4, 19: 5 };
const raioDaFoto = () => RAIOS_FOTO[Math.min(19, mapa.getZoom())] || 2.5;

function desenharFotos() {
  camadaFotos.clearLayers();
  for (const f of fotosUnicas()) {
    const m = L.circleMarker([f.lat, f.lon], { weight: 1, color: escuro ? "#e6e6e6" : "#1f1f1f", fillOpacity: 1 });
    m.foto = f;
    m.zona = f.zona;
    m.bindTooltip(previaDaFoto, { direction: "top", offset: [0, -8], className: "previa-foto" });
    m.on("mouseover", () => {
      fotoSobMouse = m;
      dicaHolofote.remove();
      camadaRuas.eachLayer((linha) => linha.closeTooltip());
    });
    m.on("mouseout", () => { if (fotoSobMouse === m) fotoSobMouse = null; });
    m.on("click", (ev) => {
      L.DomEvent.stopPropagation(ev); // não deixa o clique chegar ao mapa (holofote)
      abrirZona(f.zona);
    });
    m.addTo(camadaFotos);
  }
  estilizarFotos();
}

// As fotos só aparecem de perto e nunca no modo "ocultar".
// O interruptor "Fotos no mapa" (o navegador lembra a escolha).
let fotosVisiveis = lerPreferencia("fotosVisiveis", "1") === "1";
function alternarFotos() {
  fotosVisiveis = !fotosVisiveis;
  gravarPreferencia("fotosVisiveis", fotosVisiveis ? "1" : "0");
  $("alternar-fotos").setAttribute("aria-checked", String(fotosVisiveis));
  mostrarFotos(true);
}
$("alternar-fotos").setAttribute("aria-checked", String(fotosVisiveis));
$("alternar-fotos").onclick = alternarFotos;

function mostrarFotos(animar = false) {
  const mostrar = fotosVisiveis && mapa.getZoom() >= ZOOM_FOTOS && modo !== "ocultar";
  if (mostrar && !mapa.hasLayer(camadaFotos)) {
    camadaFotos.addTo(mapa);
    if (animar) { definirOpacidade(camadaFotos, 0); esmaecer(camadaFotos, 0, 1); }
  } else if (!mostrar && mapa.hasLayer(camadaFotos)) {
    if (animar) esmaecer(camadaFotos, 1, 0, () => camadaFotos.remove());
    else camadaFotos.remove();
  } else if (mostrar) {
    esmaecer(camadaFotos, 1, 1); // cancela um esmaecimento de saída em andamento
  }
}

// Cor e tamanho das fotos: a avaliação só aparece no modo "tudo"; nos
// outros, as fotos ficam brancas (onde há foto, não como ela foi avaliada).
function estilizarFotos() {
  const raio = raioDaFoto();
  // Com uma rua selecionada, as fotos das outras ruas esmaecem.
  const daRua = ruaSelecionada && dados ? new Set(dados.fotos.filter((f) => f.rua === ruaSelecionada).map((f) => f.zona)) : null;
  camadaFotos.eachLayer((m) => {
    const selecionada = zona && m.zona === zona.zona;
    m._opacidadeBase = daRua && !daRua.has(m.zona) && !selecionada ? ESMAECIDA : 1;
    const opacidade = (camadaFotos._opacidade ?? 1) * m._opacidadeBase;
    m.setStyle({
      fillColor: modo === "tudo" ? corDaFoto(m.foto) : "#ffffff",
      radius: selecionada ? raio + 3 : raio,
      weight: selecionada ? 2.5 : 1,
      opacity: opacidade, fillOpacity: opacidade,
    });
    if (selecionada) m.bringToFront();
  });
}

// A zona aberta: destacada no mapa e marcada na lista de zonas.
function destacarMarcador() {
  estilizarFotos();
  marcarZonaAtual();
}

// --------------------------------------------------------------------------
// Barra lateral
// --------------------------------------------------------------------------

// Só ruas com avaliação aparecem no mapa, então a legenda é só a escala.
function desenharLegenda() {
  const gradiente = ESCALA.map(([n, c]) => `${c} ${n * 100}%`).join(", ");
  $("legenda").replaceChildren(
    el("div", { className: "escala" },
      el("span", { className: "gradiente", style: `background:linear-gradient(to right, ${gradiente})` }),
      el("div", { className: "rotulos" }, el("span", { textContent: "Sem calçada" }),
        el("span", { textContent: "Inadequada" }), el("span", { textContent: "Adequada" }))),
    el("p", { className: "ajuda", textContent: "De longe, a cor é a geral da rua; de perto, a de cada altura. Ruas ainda sem avaliação não aparecem." }));
}

// Para buscar nomes: sem acento, minúsculas, espaços simples.
const normalizar = (texto) => texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
const casaComBusca = (nome, busca) => normalizar(nome).includes(normalizar(busca));
// "2023 Av. Sete de Setembro, Curitiba, Paraná" -> "2023 Av. Sete de Setembro"
const enderecoCurto = (endereco) => (endereco || "").split(",")[0] || "sem endereço";

// Abre ou fecha um bloco deslizando a altura e esmaecendo. Uma animação nova
// no mesmo bloco cancela a anterior; `depois` roda quando ela termina.
function animarAltura(bloco, abrir, depois) {
  if (bloco._animacao) bloco._animacao.cancel();
  bloco.hidden = false;
  bloco.style.overflow = "hidden";
  const cheio = { height: `${bloco.scrollHeight}px`, paddingTop: getComputedStyle(bloco).paddingTop, opacity: 1 };
  const vazio = { height: "0px", paddingTop: "0px", opacity: 0 };
  const animacao = bloco.animate(abrir ? [vazio, cheio] : [cheio, vazio],
    { duration: duracao(abrir ? 280 : 220), easing: "cubic-bezier(.2, .8, .2, 1)" });
  bloco._animacao = animacao;
  aoTerminar(animacao, duracao(abrir ? 280 : 220), () => {
    bloco._animacao = null;
    bloco.style.overflow = "";
    bloco.hidden = !abrir;
    if (depois) depois();
  });
}

// O que está aberto na lista de ruas, guardado no navegador: as ruas com as
// zonas à mostra e os grupos ("Faltam avaliar" começa aberto, "Avaliadas"
// fechado) que o usuário trocou do padrão.
function lerConjunto(chave) {
  try { return new Set(JSON.parse(lerPreferencia(chave, "[]"))); } catch { return new Set(); }
}
const ruasAbertas = lerConjunto("ruasAbertas");
const gruposTrocados = lerConjunto("gruposTrocados");
const GRUPO_ABERTO_PADRAO = { faltam: true, feitas: false };

function desenharRuas() {
  if (!dados.ruas.length) {
    $("ruas").replaceChildren(el("li", { className: "vazio", textContent: "Nenhuma rua coletada ainda. Use \"Coletar uma rua\", abaixo." }));
    return;
  }
  const busca = $("busca-ruas").value;
  const ruas = dados.ruas.filter((r) => casaComBusca(r.nome, busca));
  if (!ruas.length) {
    $("ruas").replaceChildren(el("li", { className: "vazio", textContent: `Nenhuma rua coletada com "${busca.trim()}" no nome.` }));
    return;
  }
  $("ruas").replaceChildren(...ruas.map(itemDaRua));
}

// Um botão que abre e fecha `painel` deslizando; `aoTrocar(aberto)` grava o estado.
function ligarExpansao(botao, painel, aoTrocar) {
  botao.onclick = (ev) => {
    ev.stopPropagation();
    const abrir = painel.hidden;
    botao.setAttribute("aria-expanded", String(abrir));
    aoTrocar(abrir);
    animarAltura(painel, abrir);
  };
}

// Uma rua da lista: o card (clique centraliza no mapa) e, pela seta no canto
// dele, as zonas, separadas entre as que faltam avaliar e as já avaliadas.
function itemDaRua(r, i) {
  const mostrar = modo !== "ocultar";
  const fotos = dados.fotos.filter((f) => f.rua === r.nome);
  const quadrados = fotos.reduce((s, f) => s + f.quadrados.length, 0);
  const avaliados = CLASSES.reduce((s, c) => s + r.classes[c], 0);
  const notas = fotos.filter((f) => f.nota !== null).map((f) => f.nota);
  const notaGeral = notas.length ? notas.reduce((a, b) => a + b, 0) / notas.length : null;

  // Barra: quadrados por classe (com o modo "ocultar", só avaliados x não avaliados).
  const barra = el("div", { className: "barra", "aria-hidden": "true" });
  const fatia = (n, cor) => n && barra.append(el("span", { style: `width:${100 * n / quadrados}%;background:${cor}` }));
  if (mostrar) for (const c of CLASSES) fatia(r.classes[c], CORES[c]);
  else fatia(avaliados, NEUTRA);
  fatia(quadrados - avaliados, "transparent");

  const linha1 = el("span", { className: "linha1" }, el("span", { className: "nome", textContent: r.nome }));
  if (mostrar && notaGeral !== null) {
    const descricao = `Nota geral ${formatarNota(notaGeral)}, de 0 (sem calçada) a 1 (adequada)`;
    linha1.append(el("span", { className: "nota", title: descricao, "aria-label": descricao },
      el("span", { className: "bolinha", style: `background:${corDaNota(notaGeral)}` }), formatarNota(notaGeral)));
  }
  const meta = `${r.com_foto}/${r.zonas} zonas com foto · ${r.avaliadas} avaliadas` + (r.pendentes ? ` · ${r.pendentes} pendentes` : "");
  const principal = el("button", { type: "button", className: "rua-principal" },
    linha1, barra, el("span", { className: "meta", textContent: meta }));
  principal.setAttribute("aria-pressed", String(r.nome === ruaSelecionada));
  principal.title = "Destacar a rua no mapa (clique de novo para desfazer)";
  principal.onclick = () => selecionarRua(r.nome === ruaSelecionada ? null : r.nome);

  const aberta = ruasAbertas.has(r.nome);
  const painel = el("div", { className: "zonas", id: `zonas-${i}` }, conteudoDasZonas(r, fotos, i));
  painel.hidden = !aberta;
  const seta = el("button", {
    type: "button", className: "botao-icone pequeno expandir",
    "aria-expanded": String(aberta), "aria-controls": painel.id, "aria-label": `Zonas da ${r.nome}`,
  });
  seta.innerHTML = icone("chevron-down");

  const card = el("div", { className: "rua" + (aberta ? " aberta" : "") + (r.nome === holofote.lista ? " revelada" : "")
    + (r.nome === ruaSelecionada ? " selecionada" : "") }, principal, seta);
  card.dataset.rua = r.nome;
  ligarExpansao(seta, painel, (abrir) => {
    card.classList.toggle("aberta", abrir);
    if (abrir) ruasAbertas.add(r.nome);
    else ruasAbertas.delete(r.nome);
    gravarPreferencia("ruasAbertas", JSON.stringify([...ruasAbertas]));
  });
  // Passar o mouse ou dar foco no card também revela a rua (modo "ao passar").
  card.onmouseenter = () => revelarRua(r.nome);
  card.onmouseleave = () => esconderRua(r.nome);
  card.addEventListener("focusin", () => revelarRua(r.nome));
  card.addEventListener("focusout", (ev) => { if (!card.contains(ev.relatedTarget)) esconderRua(r.nome); });
  return el("li", { className: "rua-item" }, card, painel);
}

// As zonas de uma rua em dois grupos recolhíveis: as que faltam avaliar e as avaliadas.
function conteudoDasZonas(r, fotos, i) {
  if (!fotos.length) return el("div", { className: "zonas-dentro" }, el("p", { className: "nada", textContent: "Nenhuma zona com foto ainda." }));
  const grupo = (tipo, titulo, lista, vazio) => {
    const chave = `${r.nome}|${tipo}`;
    const aberto = GRUPO_ABERTO_PADRAO[tipo] !== gruposTrocados.has(chave);
    const lista_ = el("div", { className: "grupo-lista", id: `zonas-${i}-${tipo}` },
      lista.length ? el("ul", {}, ...lista.map(itemDaZona)) : el("p", { className: "nada", textContent: vazio }));
    lista_.hidden = !aberto;
    const cabeca = el("button", { type: "button", className: "grupo-cabeca", "aria-expanded": String(aberto), "aria-controls": lista_.id },
      el("span", { textContent: titulo }), el("span", { className: "num", textContent: lista.length }));
    cabeca.insertAdjacentHTML("beforeend", icone("chevron-down"));
    ligarExpansao(cabeca, lista_, (abrir) => {
      if (abrir === GRUPO_ABERTO_PADRAO[tipo]) gruposTrocados.delete(chave);
      else gruposTrocados.add(chave);
      gravarPreferencia("gruposTrocados", JSON.stringify([...gruposTrocados]));
    });
    return el("div", { className: "grupo" }, cabeca, lista_);
  };
  return el("div", { className: "zonas-dentro" },
    grupo("faltam", "Faltam avaliar", fotos.filter((f) => f.avaliados < f.quadrados.length), "Nenhuma: a rua toda já foi avaliada."),
    grupo("feitas", "Avaliadas", fotos.filter((f) => f.avaliados === f.quadrados.length), "Nenhuma ainda."));
}

// Uma zona na lista: a cor da nota (se o modo mostra), o endereço e quantos
// quadrados já têm avaliação. Clique abre a zona.
function itemDaZona(f) {
  const cor = modo !== "ocultar" && f.nota !== null ? corDaNota(f.nota) : "transparent";
  const botao = el("button", { type: "button", className: "zona-item", title: f.endereco || "" },
    el("span", { className: "bolinha", style: `background:${cor}` }),
    el("span", { className: "endereco", textContent: enderecoCurto(f.endereco) }),
    el("span", { className: "quadros", textContent: `${f.avaliados}/${f.quadrados.length}`, title: "Quadrados avaliados" }));
  botao.dataset.zona = f.zona;
  if (zona && zona.zona === f.zona) botao.setAttribute("aria-current", "true");
  botao.onclick = () => abrirZona(f.zona);
  return el("li", {}, botao);
}

// Marca na lista a zona aberta no painel.
function marcarZonaAtual() {
  for (const item of document.querySelectorAll(".zona-item")) {
    if (zona && Number(item.dataset.zona) === zona.zona) item.setAttribute("aria-current", "true");
    else item.removeAttribute("aria-current");
  }
}

function desenharProgresso() {
  const unicas = fotosUnicas();
  const quadrados = unicas.reduce((s, f) => s + f.quadrados.length, 0);
  const avaliados = unicas.reduce((s, f) => s + f.avaliados, 0);
  const fracao = quadrados ? avaliados / quadrados : 0;
  $("contagem-ruas").textContent = dados.ruas.length;
  $("progresso-barra").style.width = `${100 * fracao}%`;
  $("progresso").textContent = unicas.length
    ? `${avaliados} de ${quadrados} quadrados avaliados (${Math.round(100 * fracao)}%), em ${unicas.filter((f) => f.avaliados).length} de ${unicas.length} zonas com foto.`
    : "Ainda não há fotos para avaliar.";
  desenharExportacao();
}

$("busca-ruas").addEventListener("input", () => dados && desenharRuas());

// --------------------------------------------------------------------------
// Exportar para conferência: um .zip que o Roboflow importa já anotado, de
// todas as ruas ou de uma (uma zona de esquina conta nas duas), com tudo ou
// só as avaliações novas: as ainda não exportadas, ou refeitas depois de
// exportadas. O zip é montado aqui na página, com as fotos da fonte.
//
// O projeto do Roboflow (apx2-bzsou) é de detecção de objetos e é baixado em
// COCO pelo treino (scripts/ingestao/download_roboflow.py e
// scripts/transformacao/extract_features.py), que lê a classe de cada imagem
// pelas anotações dela. Por isso cada quadrado vai com uma caixa cobrindo a
// imagem inteira, na classe da avaliação (NOMES_ROBOFLOW). As imagens têm o
// mesmo nome que o upload-roboflow.py usa (`<rua>__<zona>_<vista>_<quadrado>.jpg`):
// a mesma foto, mandada pelos dois caminhos, é reconhecida como duplicata.
// --------------------------------------------------------------------------

let exportarSoNovas = lerPreferencia("exportarNovas", "1") === "1";
let exportarRua = lerPreferencia("exportarRua", "");   // "" = todas as ruas
const TODAS_AS_RUAS = "Todas as ruas";

// -> "24/10 18:16" (hora local)
const dataLocal = (quando) => new Date(instante(quando))
  .toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

// Os quadrados avaliados que entram no zip, com o nome do arquivo: a rua
// pedida ou, numa zona de esquina, a primeira em ordem alfabética.
function quadradosParaExportar(modo, rua) {
  const pastas = new Map(dados.ruas.map((r) => [r.nome, r.pasta]));
  const lista = [];
  for (const z of dados.zonas.values()) {
    if (rua && !z.ruas.includes(rua)) continue;
    const pasta = pastas.get(rua || z.ruas[0]);
    for (const q of z.quadrados) {
      const a = dados.avaliacoes.get(chaveDe(z.id, z.posicao, q.quadrado));
      if (!a || !(a.classe in NOMES_ROBOFLOW) || (modo === "novas" && !dados.nova(a))) continue;
      const nome = `${z.id}_${z.posicao}_${q.quadrado}.jpg`;
      lista.push({ ponto_id: z.id, posicao: z.posicao, quadrado: q.quadrado, classe: a.classe, quando: a.quando,
        url: FONTE.imagem("quadrados", nome), arquivo: pasta ? `${pasta}__${nome}` : nome });
    }
  }
  return lista.sort((a, b) => a.ponto_id - b.ponto_id || a.quadrado - b.quadrado);
}

// O .zip: as fotos e um _annotations.coco.json. `progresso(i, n)` a cada foto baixada.
async function montarZip(lista, progresso) {
  const zip = new JSZip();
  const coco = {
    info: { description: "Avaliações das calçadas feitas no mapa (scripts/interface)", date_created: new Date().toISOString() },
    licenses: [], images: [], annotations: [],
    categories: CLASSES.map((c, i) => ({ id: i + 1, name: NOMES_ROBOFLOW[c], supercategory: "calcada" })),
  };
  let feitas = 0;
  const baixar = async (q, i) => {
    const resp = await fetch(q.url);
    if (!resp.ok) throw new Error(`a foto ${q.arquivo} não veio (${resp.status})`);
    const blob = await resp.blob();
    const bitmap = await createImageBitmap(blob);
    const { width, height } = bitmap;
    bitmap.close();
    zip.file(q.arquivo, blob);
    coco.images[i] = { id: i + 1, file_name: q.arquivo, width, height };
    coco.annotations[i] = { id: i + 1, image_id: i + 1, category_id: CLASSES.indexOf(q.classe) + 1,
      bbox: [0, 0, width, height], area: width * height, iscrowd: 0, segmentation: [] };
    progresso(++feitas, lista.length);
  };
  // Seis fotos por vez.
  let proxima = 0;
  await Promise.all(Array.from({ length: 6 }, async () => {
    while (proxima < lista.length) {
      const i = proxima++;
      await baixar(lista[i], i);
    }
  }));
  zip.file("_annotations.coco.json", JSON.stringify(coco, null, 1));
  return zip.generateAsync({ type: "blob", compression: "STORE" }); // JPEG já é comprimido
}

// conferencia_calcadas_2026-10-24[_rua-x][_novas].zip
function nomeDoZip(modo, rua) {
  const partes = ["conferencia_calcadas", new Date().toLocaleDateString("sv-SE")]; // AAAA-MM-DD, data local
  if (rua) partes.push(dados.ruas.find((r) => r.nome === rua)?.pasta || "rua");
  if (modo === "novas") partes.push("novas");
  return `${partes.join("_")}.zip`;
}

function desenharExportacao() {
  const exp = dados.exportacao;
  if (exportarRua && !(exportarRua in exp.ruas)) exportarRua = ""; // a rua não tem mais avaliações
  if (document.activeElement !== $("exportar-rua")) $("exportar-rua").value = exportarRua || TODAS_AS_RUAS;
  if (!$("exportar-rua-lista").hidden) desenharOpcoesRua();

  $("exportar-novas").setAttribute("aria-checked", String(exportarSoNovas));
  const recorte = exportarRua ? exp.ruas[exportarRua] : exp;
  const n = exportarSoNovas ? recorte.novas : recorte.total;
  $("exportar-texto").textContent = n
    ? `Exportar ${n} ${n === 1 ? "quadrado" : "quadrados"}`
    : (exportarSoNovas && recorte.total ? "Nada novo para exportar" : "Nenhum quadrado avaliado");
  $("exportar").disabled = n === 0;
  $("contagem-novas").textContent = exp.novas || "";

  const u = exp.ultima;
  $("exportar-ultima").textContent = u
    ? `Última exportação: ${dataLocal(u.quando)} · ${u.rua || "todas as ruas"} · ${u.modo === "novas" ? "só as novas" : "tudo"} · ${u.quadrados} quadrados.`
    : "Nada exportado ainda.";
}

async function exportar() {
  const botao = $("exportar");
  if (botao.getAttribute("aria-busy") === "true") return;
  const rua = exportarRua;
  const modo = exportarSoNovas ? "novas" : "tudo";
  botao.setAttribute("aria-busy", "true");
  $("exportar-texto").textContent = "Gerando o arquivo…";
  try {
    await carregar(false, { soAvaliacoes: true }); // as avaliações de agora (outra aba pode ter avaliado)
    const lista = quadradosParaExportar(modo, rua);
    if (!lista.length) throw new Error(`Nenhuma avaliação${modo === "novas" ? " nova" : ""}${rua ? ` na ${rua}` : ""}: nada para exportar.`);
    const blob = await montarZip(lista, (i, n) => { $("exportar-texto").textContent = `Juntando as fotos… ${i}/${n}`; });
    const nome = nomeDoZip(modo, rua);
    const url = URL.createObjectURL(blob);
    el("a", { href: url, download: nome }).click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    // Guarda o momento da avaliação que foi no zip (não o da exportação): se o
    // quadrado for reavaliado enquanto o zip é montado, ele segue novo.
    await FONTE.registrarExportacao(modo, rua, lista.map(({ ponto_id, posicao, quadrado, quando }) => ({ ponto_id, posicao, quadrado, quando })));
    mostrarToast("sucesso", "check", "Exportado para conferência", `${lista.length} quadrados em ${nome}. No Roboflow: Upload e arraste o arquivo.`);
  } catch (e) {
    mostrarToast("erro", "alerta", "Não deu para exportar", e.message);
  } finally {
    botao.removeAttribute("aria-busy");
    await carregar(false, { soAvaliacoes: true }); // as contagens de novas mudam
    desenharExportacao();
  }
}
$("exportar").onclick = exportar;
$("exportar-novas").onclick = () => {
  exportarSoNovas = !exportarSoNovas;
  gravarPreferencia("exportarNovas", exportarSoNovas ? "1" : "0");
  if (dados) desenharExportacao();
};
// A rua da exportação: um combobox (padrão ARIA) que filtra as ruas enquanto
// se digita. ↑ ↓ andam pela lista, Enter escolhe, Esc fecha sem mudar.
let opcaoAtiva = -1;      // índice da opção destacada pelo teclado
let filtrarRuas = false;  // só filtra depois que algo foi digitado

function opcoesDeRua() {
  const exp = dados.exportacao;
  const busca = filtrarRuas ? $("exportar-rua").value : "";
  return [["", TODAS_AS_RUAS, exp], ...Object.entries(exp.ruas).map(([nome, c]) => [nome, nome, c])]
    .filter(([, rotulo]) => casaComBusca(rotulo, busca));
}

function desenharOpcoesRua() {
  const lista = $("exportar-rua-lista");
  const opcoes = opcoesDeRua();
  opcaoAtiva = Math.min(opcaoAtiva, opcoes.length - 1);
  lista.replaceChildren(...(opcoes.length ? opcoes.map(([valor, rotulo, c], i) => {
    const item = el("li", { role: "option", id: `exportar-rua-op-${i}`, className: i === opcaoAtiva ? "ativa" : "",
      "aria-selected": String(valor === exportarRua) },
      el("span", { className: "opcao-nome", textContent: rotulo, title: rotulo }),
      el("span", { className: "opcao-num", textContent: `${c.novas} ${c.novas === 1 ? "nova" : "novas"} / ${c.total}`,
        title: `${c.novas} avaliações novas de ${c.total}` }));
    item.addEventListener("pointerdown", (ev) => ev.preventDefault()); // não tira o foco do campo
    item.onclick = () => escolherRuaExportacao(valor);
    return item;
  }) : [el("li", { className: "vazio", textContent: "Nenhuma rua avaliada com esse nome." })]));
  $("exportar-rua").setAttribute("aria-activedescendant", opcaoAtiva >= 0 ? `exportar-rua-op-${opcaoAtiva}` : "");
  lista.querySelector(".ativa")?.scrollIntoView({ block: "nearest" });
}

function abrirListaRuas() {
  if (!dados) return;
  $("exportar-rua-lista").hidden = false;
  $("exportar-rua").setAttribute("aria-expanded", "true");
  desenharOpcoesRua();
}

function fecharListaRuas() {
  $("exportar-rua-lista").hidden = true;
  $("exportar-rua").setAttribute("aria-expanded", "false");
  $("exportar-rua").removeAttribute("aria-activedescendant");
  filtrarRuas = false;
  opcaoAtiva = -1;
  $("exportar-rua").value = exportarRua || TODAS_AS_RUAS; // descarta o que foi digitado e não escolhido
}

function escolherRuaExportacao(valor) {
  exportarRua = valor;
  gravarPreferencia("exportarRua", valor);
  fecharListaRuas();
  desenharExportacao();
}

const campoRua = $("exportar-rua");
campoRua.addEventListener("focus", () => { campoRua.select(); abrirListaRuas(); });
campoRua.addEventListener("click", abrirListaRuas);
campoRua.addEventListener("input", () => { filtrarRuas = true; opcaoAtiva = 0; abrirListaRuas(); });
campoRua.addEventListener("blur", fecharListaRuas);
// A seta abre e fecha a lista; pointerdown sem efeito padrão: o foco fica no campo.
$("exportar-rua-seta").addEventListener("pointerdown", (ev) => ev.preventDefault());
$("exportar-rua-seta").onclick = () => {
  if (!$("exportar-rua-lista").hidden) return fecharListaRuas();
  if (document.activeElement === campoRua) abrirListaRuas();
  else campoRua.focus(); // o focus já abre a lista
};
campoRua.addEventListener("keydown", (ev) => {
  const aberta = !$("exportar-rua-lista").hidden;
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    ev.preventDefault();
    if (!aberta) return abrirListaRuas();
    const n = opcoesDeRua().length;
    if (n) opcaoAtiva = (opcaoAtiva + (ev.key === "ArrowDown" ? 1 : -1) + n) % n;
    desenharOpcoesRua();
  } else if (ev.key === "Enter") {
    ev.preventDefault();
    const opcao = opcoesDeRua()[Math.max(opcaoAtiva, 0)];
    if (aberta && opcao) escolherRuaExportacao(opcao[0]);
  } else if (ev.key === "Escape" && aberta) {
    ev.stopPropagation();
    fecharListaRuas();
    campoRua.select();
  }
});

// --------------------------------------------------------------------------
// Painel da zona: avaliação dos quadrados
// --------------------------------------------------------------------------

function abrirZona(id) {
  const detalhada = dados && zonaDetalhada(id);
  if (!detalhada) {
    mostrarToast("erro", "alerta", "Zona não encontrada", `A zona ${id} não está no mapa.`);
    return;
  }
  zona = detalhada;
  atualizarRuas(); // modo "ao passar": o holofote vai para a foto da zona aberta
  const primeiroSemAvaliacao = zona.quadrados.findIndex((q) => !q.avaliacao);
  foco = primeiroSemAvaliacao >= 0 ? primeiroSemAvaliacao : 0;
  $("zona-titulo").textContent = `Zona ${zona.zona} · ${zona.ruas.join(" / ")}`;
  $("zona-info").textContent = [zona.endereco, zona.captura && `captura ${zona.captura}`,
    zona.distancia && `carro a ${zona.distancia.toFixed(0)} m`].filter(Boolean).join(" · ");
  $("zona-contexto").src = zona.contexto;
  $("zona-streetview").href = zona.streetview;
  desenharQuadrados();
  animarPainelZona(true);
  history.replaceState(null, "", `#zona=${zona.zona}`);
  destacarMarcador();
  centrarAoLadoDoPainel(zona.lat, zona.lon);
}

// Põe a zona no meio da parte do mapa que o painel não cobre.
function centrarAoLadoDoPainel(lat, lon) {
  const z = Math.max(mapa.getZoom(), 17);
  const mapaLargura = mapa.getSize().x;
  const painel = $("zona").getBoundingClientRect().width;
  const desvio = mapaLargura - painel > 200 ? painel / 2 : 0; // tela estreita: o painel cobre tudo mesmo
  const centro = mapa.project([lat, lon], z).add([desvio, 0]);
  mapa.setView(mapa.unproject(centro, z), z);
}

// O painel da zona entra deslizando da direita e sai do mesmo jeito, mais
// rápido. Com ele já aberto (troca de zona), não anima de novo; uma animação
// nova cancela a que estiver em andamento.
function animarPainelZona(abrir) {
  const painel = $("zona");
  const emAndamento = painel._animacao;
  if (abrir && !painel.hidden && !emAndamento) return;
  if (emAndamento) emAndamento.cancel();
  painel.hidden = false;
  const fora = { transform: "translateX(24px)", opacity: 0 };
  const dentro = { transform: "none", opacity: 1 };
  const ms = duracao(abrir ? 280 : 200);
  const animacao = painel.animate(abrir ? [fora, dentro] : [dentro, fora],
    { duration: ms, easing: abrir ? "cubic-bezier(.2, .8, .2, 1)" : "ease-in" });
  painel._animacao = animacao;
  aoTerminar(animacao, ms, () => {
    painel._animacao = null;
    painel.hidden = !abrir;
  });
}

// Clique fora do painel da zona, na barra lateral, também o fecha, menos
// numa zona da lista (que abre outra). O mapa trata os cliques dele acima.
document.addEventListener("click", (ev) => {
  if (zona && !ev.target.closest("#zona, #mapa, .zona-item")) fecharZona();
});

function fecharZona() {
  if (!zona) return;
  animarPainelZona(false);
  history.replaceState(null, "", location.pathname);
  zona = null;
  atualizarRuas();
  destacarMarcador();
}

// O dropdown "Avaliar": aberto ou fechado (o navegador lembra) e, no
// cabeçalho, quantos quadrados já têm avaliação e a cor de cada um.
let avaliarAberto = lerPreferencia("avaliarAberto", "") === "1";
function abrirAvaliar(abrir, animar = true) {
  avaliarAberto = abrir;
  gravarPreferencia("avaliarAberto", abrir ? "1" : "");
  $("avaliar-cabeca").setAttribute("aria-expanded", String(abrir));
  if (animar) animarAltura($("avaliar-corpo"), abrir);
  else $("avaliar-corpo").hidden = !abrir;
}
$("avaliar-cabeca").onclick = () => abrirAvaliar(!avaliarAberto);

function desenharResumoAvaliar() {
  const feitos = zona.quadrados.filter((q) => q.avaliacao).length;
  $("avaliar-resumo").replaceChildren(
    ...zona.quadrados.map((q) => el("span", { className: "ponto", style: `background:${q.avaliacao ? CORES[q.avaliacao.classe] : "transparent"}` })),
    el("span", { textContent: zona.quadrados.length ? `${feitos}/${zona.quadrados.length}` : "sem quadrados" }));
}

function desenharQuadrados() {
  desenharResumoAvaliar();
  if (!zona.quadrados.length) {
    $("zona-quadrados").replaceChildren(el("p", { className: "ajuda", textContent: "Esta zona não tem quadrados limpos na vista escolhida." }));
    return;
  }
  $("zona-quadrados").replaceChildren(...zona.quadrados.map((q, i) => {
    const atual = q.avaliacao?.classe;
    const botoes = CLASSES.map((c, j) => {
      const b = el("button", { type: "button", className: atual === c ? "ativa" : "" },
        el("span", { className: "ponto", style: `background:${CORES[c]}` }), NOMES[c], el("kbd", { textContent: j + 1 }));
      if (atual === c) b.style.cssText = `background:${CORES[c]};border-color:${CORES[c]}`;
      b.onclick = (ev) => { ev.stopPropagation(); foco = i; avaliar(q, atual === c ? null : c); };
      return b;
    });
    const quem = q.avaliacao
      ? `${q.avaliacao.origem === "modelo" ? "modelo" : "à mão"}${q.avaliacao.autor ? ` · ${q.avaliacao.autor}` : ""}`
      : "sem avaliação";
    const medidas = q.piso == null ? "" : `piso ${Math.round(q.piso * 100)}% · obstrução ${Math.round(q.obstrucao * 100)}%`;
    const cartao = el("div", { className: "quadrado" + (i === foco ? " foco" : "") },
      el("img", { src: q.url, alt: `Quadrado ${q.quadrado} da calçada`, loading: "lazy" }),
      el("div", { className: "medidas", textContent: `Quadrado ${q.quadrado}${medidas ? " · " + medidas : ""}` }),
      el("div", { className: "classes" }, ...botoes),
      el("div", { className: "quem", textContent: quem }));
    cartao.onclick = () => { foco = i; desenharQuadrados(); };
    return cartao;
  }));
}

async function avaliar(q, classe) {
  const autor = $("autor").value.trim();
  let gravada;
  try {
    gravada = await FONTE.avaliar(zona.zona, zona.posicao, q.quadrado, classe, autor);
  } catch (e) {
    mostrarToast("erro", "alerta", "Não deu para avaliar", e.message);
    return;
  }
  // A avaliação entra nos dados já carregados: sem buscar tudo de novo.
  const mesma = (a) => a.ponto_id === zona.zona && a.posicao === zona.posicao && a.quadrado === q.quadrado;
  registro.avaliacoes = [...registro.avaliacoes.filter((a) => !mesma(a)), ...(gravada ? [gravada] : [])];
  const proximo = zona.quadrados.findIndex((x, i) => i > foco && !x.avaliacao && x !== q);
  if (classe && proximo >= 0) foco = proximo;
  redesenhar(); // redesenha também os quadrados da zona aberta
}

// A próxima zona com quadrado sem avaliação, a partir da zona aberta: na rua
// pedida (o botão da rua) ou na rua da zona aberta (tecla N); se essa rua já
// estiver toda avaliada, segue pelas outras.
function proximaSemAvaliacao(rua = zona ? zona.ruas[0] : null) {
  if (!dados) return;
  const pendente = (f) => f.avaliados < f.quadrados.length;
  const daRua = rua ? dados.fotos.filter((f) => f.rua === rua) : [];
  const ordem = daRua.some(pendente) ? daRua : fotosUnicas();
  const i = zona ? ordem.findIndex((f) => f.zona === zona.zona) : -1;
  const proxima = [...ordem.slice(i + 1), ...ordem.slice(0, i + 1)].find(pendente);
  if (proxima) abrirZona(proxima.zona);
}

document.addEventListener("keydown", (ev) => {
  if (ev.target.matches("input, textarea") || ev.ctrlKey || ev.metaKey || ev.altKey) return;
  if (ev.key === "n" || ev.key === "N") return proximaSemAvaliacao();
  if (ev.key === "f" || ev.key === "F") return alternarFotos();
  if (ev.key === "v" || ev.key === "V") return escolherModo(ORDEM_MODOS[(ORDEM_MODOS.indexOf(modo) + 1) % ORDEM_MODOS.length]);
  if (ev.key === "Escape" && !zona && ruaSelecionada) return selecionarRua(null);
  if (!zona) return;
  if (ev.key === "Escape") return fecharZona();
  if (!zona.quadrados.length) return;
  // Com o "Avaliar" fechado, as teclas de avaliação só o abrem: nada é
  // avaliado sem os quadrados à vista.
  if (/^[0-5]$|^Arrow(Left|Right)$/.test(ev.key) && !avaliarAberto) return abrirAvaliar(true);
  if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
    foco = (foco + (ev.key === "ArrowRight" ? 1 : zona.quadrados.length - 1)) % zona.quadrados.length;
    ev.preventDefault();
    return desenharQuadrados();
  }
  const n = Number(ev.key);
  if (ev.key === "0") avaliar(zona.quadrados[foco], null);
  else if (n >= 1 && n <= CLASSES.length) avaliar(zona.quadrados[foco], CLASSES[n - 1]);
});

$("zona-fechar").onclick = fecharZona;

try { $("autor").value = localStorage.getItem("autor") || ""; } catch {}
$("autor").addEventListener("change", () => { try { localStorage.setItem("autor", $("autor").value.trim()); } catch {} });

// --------------------------------------------------------------------------
// Coleta de uma rua
// --------------------------------------------------------------------------

let acompanhando = null;   // intervalo que lê o log da coleta
let ultimaAtualizacao = 0; // quando o mapa foi recarregado durante a coleta

let previa = null;         // a rua encontrada, esperando confirmação

function statusColeta(texto, erro = false) {
  $("coleta-status").textContent = texto;
  $("coleta-status").classList.toggle("erro", erro);
}

// Primeiro passo: acha a rua e mostra quantas zonas faltam, como o menu do terminal.
async function procurarRua(nome) {
  $("coleta-candidatas").hidden = true;
  $("form-confirmar").hidden = true;
  statusColeta("Procurando a rua…");
  try {
    previa = await api("/api/coleta/previa", { nome });
  } catch (e) {
    statusColeta(e.message, true);
    const candidatas = e.dados?.candidatas;
    if (candidatas) {
      $("coleta-candidatas").replaceChildren(...candidatas.map((c) => {
        const b = el("button", { type: "button", className: "botao", textContent: c });
        b.onclick = () => { $("coleta-nome").value = c; procurarRua(c); };
        return b;
      }));
      $("coleta-candidatas").hidden = false;
    }
    return;
  }
  statusColeta("");
  $("confirmar-texto").textContent = `"${previa.nome}": ${previa.zonas} zonas, ${previa.processadas} já processadas, ${previa.a_fazer} a processar.`;
  $("coleta-limite").max = previa.a_fazer;
  $("coleta-limite").value = "";
  $("form-confirmar").querySelector("button[type=submit]").disabled = previa.a_fazer === 0;
  $("form-confirmar").hidden = false;
}

// Segundo passo: roda a coleta da rua confirmada.
async function iniciarColeta() {
  try {
    const estado = await api("/api/coleta", { nome: previa.nome, limite: $("coleta-limite").value });
    $("form-confirmar").hidden = true;
    mostrarColeta(estado);
    acompanharColeta();
  } catch (e) {
    statusColeta(e.message, true);
  }
}

// O andamento da coleta, lido do log do subprocesso: a etapa atual ("== 2/3
// ...") e, dentro dela, o último contador "[i/n]".
const ETAPAS = { 1: "Procurando os panoramas", 2: "Baixando as fotos", 3: "Conferindo as calçadas" };
function andamentoDoLog(log) {
  let etapa = null, fracao = null;
  for (const linha of log) {
    const e = linha.match(/^== (\d)\/3 /);
    if (e) { etapa = Number(e[1]); fracao = null; continue; }
    const p = linha.match(/\[(\d+)\/(\d+)\]/);
    if (p && etapa) fracao = Number(p[1]) / Number(p[2]);
  }
  return { etapa, fracao };
}

// Em vez do log, um carregamento: spinner, a etapa e uma barra (que anda
// sozinha enquanto a etapa não informa quanto falta).
function mostrarColeta(estado) {
  $("coleta-procurar").disabled = estado.rodando;
  $("coleta-parar").hidden = !estado.rodando;
  $("coleta-andamento").hidden = !estado.rodando;
  if (estado.rodando) $("secao-coleta").open = true;
  if (!estado.rua) return;
  const minutos = Math.round(((estado.fim || Date.now() / 1000) - estado.inicio) / 60);
  if (estado.rodando) {
    const { etapa, fracao } = andamentoDoLog(estado.log);
    $("coleta-titulo").textContent = `Coletando ${estado.rua}${estado.limite ? ` (${estado.limite} zonas)` : ""}`;
    $("coleta-etapa").textContent = (etapa ? `Etapa ${etapa} de 3 · ${ETAPAS[etapa]}` : "Preparando")
      + ` · ${minutos} min`;
    $("coleta-trilho").classList.toggle("indeterminado", fracao === null);
    $("coleta-barra").style.width = fracao === null ? "" : `${100 * fracao}%`;
    if (fracao === null) $("coleta-trilho").removeAttribute("aria-valuenow");
    else $("coleta-trilho").setAttribute("aria-valuenow", Math.round(100 * fracao));
    statusColeta("As fotos aparecem no mapa ao fim de cada etapa.");
    return;
  }
  const textos = {
    concluida: `Última coleta: ${estado.rua}, ${minutos} min${estado.resumo ? ` · ${estado.resumo}` : ""}.`,
    interrompida: `Coleta de ${estado.rua} interrompida. Rodar de novo continua de onde parou.`,
    erro: `A coleta de ${estado.rua} parou com erro${estado.erro ? `: ${estado.erro}` : "."}`,
  };
  statusColeta(textos[estado.situacao] || "", estado.situacao === "erro");
}

// O aviso de fim de coleta, no canto superior direito.
function avisarFimDaColeta(estado) {
  const avisos = {
    concluida: ["sucesso", "check", "Coleta concluída",
      `${estado.rua}${estado.resumo ? ` · ${estado.resumo}` : ""}`],
    interrompida: ["atencao", "pause", "Coleta interrompida", `${estado.rua}. Rodar de novo continua de onde parou.`],
    erro: ["erro", "alerta", "A coleta parou com erro", estado.erro || estado.rua],
  };
  if (avisos[estado.situacao]) mostrarToast(...avisos[estado.situacao]);
}

// Toast: some sozinho depois de TOAST_MS (o tempo para enquanto o mouse ou o
// foco estiver nele) e tem um × para fechar antes.
const TOAST_MS = 1500;
function mostrarToast(tipo, nomeIcone, titulo, texto) {
  const fechar = el("button", { type: "button", className: "botao-icone pequeno", "aria-label": "Fechar o aviso" });
  fechar.innerHTML = icone("x");
  const toast = el("div", { className: `toast ${tipo}`, role: tipo === "erro" ? "alert" : "status" },
    el("span", { className: "toast-icone" }),
    el("div", { className: "toast-texto" }, el("b", { textContent: titulo }), el("span", { textContent: texto })),
    fechar);
  toast.querySelector(".toast-icone").innerHTML = icone(nomeIcone);
  $("toasts").append(toast);

  let saindo = false;
  const sair = () => {
    if (saindo) return;
    saindo = true;
    clearTimeout(temporizador);
    const animacao = toast.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateX(16px)" }],
      { duration: duracao(180), easing: "ease-in" });
    aoTerminar(animacao, duracao(180), () => toast.remove());
  };
  let temporizador = setTimeout(sair, TOAST_MS);
  const pausar = () => clearTimeout(temporizador);
  const retomar = () => { if (!saindo && !toast.matches(":hover, :focus-within")) temporizador = setTimeout(sair, TOAST_MS); };
  toast.addEventListener("mouseenter", pausar);
  toast.addEventListener("focusin", pausar);
  toast.addEventListener("mouseleave", retomar);
  toast.addEventListener("focusout", retomar);
  fechar.onclick = sair;
  toast.animate([{ opacity: 0, transform: "translateX(16px)" }, { opacity: 1, transform: "none" }],
    { duration: duracao(220), easing: "cubic-bezier(.2, .8, .2, 1)" });
}

function acompanharColeta() {
  if (acompanhando) return;
  acompanhando = setInterval(async () => {
    let estado;
    try { estado = await api("/api/coleta"); } catch { return; }
    mostrarColeta(estado);
    if (estado.rodando && Date.now() - ultimaAtualizacao > 20000) {
      ultimaAtualizacao = Date.now();
      carregar();
    }
    if (!estado.rodando) {
      clearInterval(acompanhando);
      acompanhando = null;
      avisarFimDaColeta(estado);
      carregar(); // as zonas da última etapa
    }
  }, 2000);
}

$("form-coleta").onsubmit = (ev) => {
  ev.preventDefault();
  procurarRua($("coleta-nome").value.trim());
};
$("form-confirmar").onsubmit = (ev) => {
  ev.preventDefault();
  iniciarColeta();
};
$("confirmar-cancelar").onclick = () => { $("form-confirmar").hidden = true; previa = null; };
$("coleta-parar").onclick = async () => mostrarColeta(await api("/api/coleta/parar", {}));

// --------------------------------------------------------------------------

desenharLegenda();
aplicarModo();
abrirAvaliar(avaliarAberto, false);
// As seções recolhíveis abrem e fecham deslizando e lembram se ficaram
// abertas (a da coleta começa fechada). O conteúdo de cada uma vai para um
// bloco próprio, que é o que anima.
for (const secao of document.querySelectorAll("details.recolhivel")) {
  const resumo = secao.querySelector("summary");
  const conteudo = el("div", { className: "conteudo" });
  conteudo.append(...[...secao.children].filter((filho) => filho !== resumo));
  secao.append(conteudo);
  const salvo = lerPreferencia(`aberta:${secao.id}`, "");
  if (salvo) secao.open = salvo === "1";
  resumo.addEventListener("click", (ev) => {
    ev.preventDefault();
    if (secao.open && !secao.classList.contains("fechando")) {
      secao.classList.add("fechando");
      animarAltura(conteudo, false, () => {
        secao.open = false;
        conteudo.hidden = false; // o <details> fechado já esconde
        secao.classList.remove("fechando");
      });
    } else {
      secao.classList.remove("fechando");
      secao.open = true;
      animarAltura(conteudo, true);
    }
  });
  secao.addEventListener("toggle", () => gravarPreferencia(`aberta:${secao.id}`, secao.open ? "1" : "0"));
}
// O endereço guarda a vista (#mapa=zoom/lat/lon) ou a zona aberta (#zona=<id>),
// para mandar o link de um trecho ou de uma zona a alguém.
const zonaNoEndereco = location.hash.match(/^#zona=(\d+)$/);
const vistaNoEndereco = location.hash.match(/^#mapa=(\d+)\/(-?[\d.]+)\/(-?[\d.]+)$/);
if (vistaNoEndereco) mapa.setView([Number(vistaNoEndereco[2]), Number(vistaNoEndereco[3])], Number(vistaNoEndereco[1]));
mapa.on("moveend", () => {
  if (zona) return;
  const c = mapa.getCenter();
  history.replaceState(null, "", `#mapa=${mapa.getZoom()}/${c.lat.toFixed(5)}/${c.lng.toFixed(5)}`);
});
carregar(!zonaNoEndereco && !vistaNoEndereco).then(() => zonaNoEndereco && abrirZona(Number(zonaNoEndereco[1])));
// Uma coleta pode já estar rodando (começada em outra aba): a página a acompanha.
api("/api/coleta").then((estado) => {
  mostrarColeta(estado);
  if (estado.rodando) acompanharColeta();
}).catch(() => {});
// Ao voltar para a aba, o mapa relê o banco (o que a coleta fez enquanto isso).
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && dados) carregar(); });
