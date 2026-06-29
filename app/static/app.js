const $ = (id) => document.getElementById(id);

// Rotulos amigaveis para as areas.
const ROTULOS = {
  ti: "TI", saude: "Saude", educacao: "Educacao", juridico: "Juridico",
  administrativo: "Administrativo", engenharia: "Engenharia",
  seguranca: "Seguranca", fiscal_financeiro: "Fiscal / Financeiro",
};

// Foco regional: Norte + Nordeste + Goias (mesma lista coletada no servidor).
const UFS = ["pa","ac","ap","am","ro","rr","to",
  "al","ba","ce","ma","pb","pe","pi","rn","se","go"];

// Estado atual dos filtros.
const filtros = { q: "", area: "", uf: "", tipo: "", encerrados: false };

// ---------- Montagem dos filtros ----------
function montarUFs() {
  const sel = $("uf");
  UFS.forEach((uf) => {
    const op = document.createElement("option");
    op.value = uf; op.textContent = uf.toUpperCase();
    sel.appendChild(op);
  });
  sel.addEventListener("change", () => { filtros.uf = sel.value; buscar(); });
}

async function montarChips() {
  const box = $("chips");
  let areas = [];
  try {
    const r = await fetch("/api/areas");
    areas = (await r.json()).areas || [];
  } catch (e) {}
  const todas = ["", ...areas];
  box.innerHTML = "";
  todas.forEach((area) => {
    const b = document.createElement("button");
    b.className = "chip" + (area === "" ? " ativo" : "");
    b.dataset.area = area;
    b.textContent = area === "" ? "Todas" : (ROTULOS[area] || area);
    b.addEventListener("click", () => { selecionarArea(area); buscar(); });
    box.appendChild(b);
  });
}

// Seleciona uma area (chip ou toggle "So TI"), sincroniza os chips ativos e
// lembra a preferencia de TI. Nao dispara a busca (quem chama decide).
function selecionarArea(area) {
  filtros.area = area;
  [...$("chips").children].forEach((c) =>
    c.classList.toggle("ativo", (c.dataset.area || "") === area));
  sincronizarToggleTI();
}

// Mantem o botao "So TI" coerente com o filtro e guarda a preferencia, para o
// app abrir ja focado em TI nas proximas vezes.
function sincronizarToggleTI() {
  const on = filtros.area === "ti";
  const t = $("toggle-ti");
  if (t) {
    t.classList.toggle("on", on);
    t.setAttribute("aria-pressed", on ? "true" : "false");
  }
  try { localStorage.setItem("soti", on ? "1" : "0"); } catch (e) {}
}

function montarToggleTI() {
  $("toggle-ti").addEventListener("click", () => {
    selecionarArea(filtros.area === "ti" ? "" : "ti");
    buscar();
  });
}

function montarTipo() {
  $("seg-tipo").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    filtros.tipo = b.dataset.tipo;
    [...$("seg-tipo").children].forEach((c) => c.classList.remove("ativo"));
    b.classList.add("ativo");
    buscar();
  });
}

// Atalhos da regiao do Para. Cada um seleciona PA e busca a cidade.
const CIDADES_PA = [
  "Belem", "Ananindeua", "Maraba", "Parauapebas", "Canaa dos Carajas",
  "Castanhal", "Santarem", "Curionopolis", "Tucurui", "Altamira",
];
function montarChipsPA() {
  const box = $("chips-pa");
  const rotulo = document.createElement("span");
  rotulo.className = "rotulo-pa";
  rotulo.textContent = "PA:";
  box.appendChild(rotulo);
  CIDADES_PA.forEach((cidade) => {
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = cidade;
    b.addEventListener("click", () => {
      // Foca em PA e usa a cidade como busca livre.
      filtros.uf = "pa";
      $("uf").value = "pa";
      filtros.q = cidade;
      $("q").value = cidade;
      $("busca-wrap").classList.add("tem-texto");
      buscar();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    box.appendChild(b);
  });
}

// Busca com pequeno atraso (debounce) enquanto digita.
let timer = null;
function montarBusca() {
  const inp = $("q");
  const wrap = $("busca-wrap");
  inp.addEventListener("input", () => {
    filtros.q = inp.value.trim();
    wrap.classList.toggle("tem-texto", inp.value.length > 0);
    clearTimeout(timer);
    timer = setTimeout(buscar, 280);
  });
  $("limpar-x").addEventListener("click", () => {
    inp.value = ""; filtros.q = "";
    wrap.classList.remove("tem-texto");
    inp.focus(); buscar();
  });
}

// ---------- Busca e renderizacao ----------
function montarQuery() {
  const p = new URLSearchParams();
  if (filtros.q) p.append("q", filtros.q);
  if (filtros.area) p.append("area", filtros.area);
  if (filtros.uf) p.append("uf", filtros.uf);
  if (filtros.tipo) p.append("tipo", filtros.tipo);
  if (filtros.encerrados) p.append("encerrados", "1");
  p.append("limite", "300");
  return p.toString();
}

// Mesma query da busca, mas para o CSV (limite maior, sem cortar a exportacao).
function montarQueryCSV() {
  const p = new URLSearchParams();
  if (filtros.q) p.append("q", filtros.q);
  if (filtros.area) p.append("area", filtros.area);
  if (filtros.uf) p.append("uf", filtros.uf);
  if (filtros.tipo) p.append("tipo", filtros.tipo);
  if (filtros.encerrados) p.append("encerrados", "1");
  p.append("limite", "5000");
  return p.toString();
}

function esqueleto() {
  $("grade").innerHTML = Array.from({ length: 6 })
    .map(() => '<div class="skel"></div>').join("");
  $("resumo").textContent = "Buscando...";
}

async function buscar(silencioso) {
  if (!silencioso) esqueleto();
  try {
    const r = await fetch("/api/concursos?" + montarQuery());
    const d = await r.json();
    $("offline").classList.toggle("mostra", !!d.offline);
    renderizar(d.concursos || [], d.total || 0);
  } catch (e) {
    $("grade").innerHTML = '<div class="estado"><span class="emoji">!</span>Erro ao buscar. Puxe para baixo e tente de novo.</div>';
    $("resumo").textContent = "";
  }
}

function temFiltro() {
  return !!(filtros.q || filtros.area || filtros.uf || filtros.tipo || filtros.encerrados);
}

function renderizar(lista, total) {
  const grade = $("grade");
  const toggle = `<button class="toggle-enc" id="toggle-enc">${filtros.encerrados ? "ocultar encerrados" : "incluir encerrados"}</button>`;
  const limpar = temFiltro() ? ` &middot; <button class="toggle-enc" id="limpar-tudo">limpar filtros</button>` : "";
  if (!lista.length) {
    $("resumo").innerHTML = toggle + limpar;
    grade.innerHTML = '<div class="estado"><span class="emoji">&#128269;</span>Nenhum concurso encontrado.<br>Tente outra busca ou inclua os encerrados.</div>';
  } else {
    const txt = total + " concurso" + (total > 1 ? "s" : "") + " encontrado" + (total > 1 ? "s" : "");
    const exportar = ` &middot; <a class="toggle-enc" href="/api/concursos.csv?${montarQueryCSV()}" download>exportar CSV</a>`;
    $("resumo").innerHTML = `${txt} &middot; ${toggle}${limpar}${exportar}`;
    grade.innerHTML = "";
    lista.forEach((c) => grade.appendChild(card(c)));
  }
  const tb = $("toggle-enc");
  if (tb) tb.addEventListener("click", () => { filtros.encerrados = !filtros.encerrados; buscar(); });
  const lb = $("limpar-tudo");
  if (lb) lb.addEventListener("click", limparFiltros);
}

// Reseta todos os filtros e a busca para o estado inicial.
function limparFiltros() {
  filtros.q = ""; filtros.area = ""; filtros.uf = ""; filtros.tipo = "";
  filtros.encerrados = false;
  $("q").value = "";
  $("busca-wrap").classList.remove("tem-texto");
  $("uf").value = "";
  [...$("chips").children].forEach((c, i) => c.classList.toggle("ativo", i === 0));
  [...$("seg-tipo").children].forEach((c, i) => c.classList.toggle("ativo", i === 0));
  sincronizarToggleTI();
  buscar();
}

// Calcula o status do prazo de inscricao a partir da data de encerramento.
function prazoInfo(dataFim) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(dataFim || "");
  if (!m) return null;
  const fim = new Date(+m[1], +m[2] - 1, +m[3]);
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
  const dias = Math.round((fim - hoje) / 86400000);
  const dataBR = `${m[3]}/${m[2]}`;
  if (dias < 0) return { texto: "Encerrado", classe: "encerrado" };
  if (dias === 0) return { texto: "Encerra hoje", classe: "urgente" };
  if (dias <= 7) return { texto: `Encerra em ${dias}d`, classe: "urgente" };
  return { texto: `Inscricoes ate ${dataBR}`, classe: "prazo" };
}

// Monta a pilula de prazo do card (ou a data de publicacao, se nao houver).
function pilulaPrazo(c) {
  const p = prazoInfo(c.data_fim);
  if (p) return `<span class="pill ${p.classe}">${p.texto}</span>`;
  if (c.data) return `<span class="pill">${esc(formatarDataBR(c.data))}</span>`;
  return "";
}

// Le os detalhes extras (detalhes_json) de um concurso, com seguranca.
function detalhesDe(c) {
  try { return JSON.parse(c.detalhes_json || "{}") || {}; } catch (e) { return {}; }
}

function card(c) {
  const el = document.createElement("div");
  el.className = "card";
  const aberto = c.tipo === "aberto";
  const orgao = c.orgao || "Orgao nao informado";
  const det = detalhesDe(c);
  // Prefere o numero de vagas lido do edital; senao, o texto da listagem.
  const vagas = det.vagas || c.vagas || "nao informado";
  // Descricao do card: o resumo lido (mais informativo) ou o titulo da fonte.
  const desc = c.resumo || c.titulo || "";
  el.innerHTML = `
    <div class="card-topo">
      <h3>${esc(orgao)}</h3>
      <div class="topo-dir">
        ${estrelaHTML(c.hash)}
        <span class="tag ${aberto ? "tag-aberto" : "tag-previsto"}">${aberto ? "Aberto" : "Previsto"}</span>
      </div>
    </div>
    ${desc ? `<div class="desc">${esc(desc)}</div>` : ""}
    <div class="meta">
      <span class="pill uf">${esc((c.uf || "").toUpperCase())}</span>
      ${det.cargos_ti ? `<span class="pill ti">TI</span>` : ""}
      <span class="pill">Vagas: <b>${esc(vagas)}</b></span>
      ${det.salario ? `<span class="pill">${esc(det.salario)}</span>` : ""}
      ${pilulaPrazo(c)}
    </div>
    <div class="ver-mais">Toque para ver detalhes &rsaquo;</div>
  `;
  el.addEventListener("click", () => abrirDetalhe(c));
  ligarEstrelas(el);
  return el;
}

// ---------- Favoritos ----------
let favoritosSet = new Set();

function estrelaHTML(hash) {
  const on = favoritosSet.has(hash);
  return `<button class="estrela ${on ? "on" : ""}" data-fav="${hash}" aria-label="Favoritar" title="Favoritar">
    <svg viewBox="0 0 24 24" fill="${on ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
  </button>`;
}

function ligarEstrelas(raiz) {
  raiz.querySelectorAll(".estrela").forEach((b) => {
    if (b.dataset.ligado) return;
    b.dataset.ligado = "1";
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      const hash = b.dataset.fav;
      try {
        const r = await (await fetch("/api/favoritos/" + hash, { method: "POST" })).json();
        if (r.favorito) favoritosSet.add(hash); else favoritosSet.delete(hash);
        document.querySelectorAll(`.estrela[data-fav="${hash}"]`).forEach((s) => {
          s.classList.toggle("on", r.favorito);
          const svg = s.querySelector("svg");
          if (svg) svg.setAttribute("fill", r.favorito ? "currentColor" : "none");
        });
        if (!r.favorito) {
          const card = b.closest("#favoritos-lista .card");
          if (card) card.remove();
        }
      } catch (e) {}
    });
  });
}

async function carregarFavoritos() {
  try {
    const d = await (await fetch("/api/favoritos")).json();
    favoritosSet = new Set(d.hashes || []);
  } catch (e) {}
}

async function abrirFavoritos() {
  abrirView("view-favoritos");
  const box = $("favoritos-lista");
  box.innerHTML = '<p class="dica">Carregando...</p>';
  try {
    const d = await (await fetch("/api/favoritos")).json();
    favoritosSet = new Set(d.hashes || []);
    const lista = d.concursos || [];
    if (!lista.length) {
      box.innerHTML = '<div class="estado"><span class="emoji">&#11088;</span>Voce ainda nao favoritou nenhum concurso.<br>Toque na estrela de um concurso para salva-lo aqui.</div>';
      return;
    }
    box.innerHTML = "";
    lista.forEach((c) => box.appendChild(card(c)));
  } catch (e) {
    box.innerHTML = '<p class="dica">Erro ao carregar os favoritos.</p>';
  }
}
$("btn-favoritos").addEventListener("click", abrirFavoritos);

// ---------- Detalhe (bottom sheet) ----------
function linkBusca(c) {
  // A fonte nao traz link de edital. Geramos uma busca que sempre funciona.
  const termo = `concurso ${c.orgao || ""} ${(c.uf || "").toUpperCase()} edital inscricao`;
  return "https://www.google.com/search?q=" + encodeURIComponent(termo.trim());
}

function abrirDetalhe(c) {
  if (!c) return;
  const aberto = c.tipo === "aberto";

  const linkReal = c.link && c.link.startsWith("http") ? c.link : "";
  const prazo = prazoInfo(c.data_fim);
  const periodo = montarPeriodo(c);
  const fonte = c.fonte || "Concursos no Brasil";
  // Icones reutilizados nas acoes.
  const icoLink = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>`;
  const icoPdf = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M12 18v-6"/><path d="m9 15 3 3 3-3"/></svg>`;
  // Acao "materia" (a fonte da noticia). Acao "Google" quando nao ha link.
  const acaoMateria = linkReal
    ? `<a class="acao __CLS__" href="${esc(linkReal)}" target="_blank" rel="noopener">${icoLink} Ver materia (${esc(fonte)})</a>`
    : `<a class="acao __CLS__" href="${linkBusca(c)}" target="_blank" rel="noopener"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg> Buscar no Google</a>`;
  // Hierarquia: site oficial > edital (PDF) > materia/Google.
  const temPrincipal = !!(c.link_oficial || c.pdf_url);

  $("sheet-conteudo").innerHTML = `
    <h2>${esc(c.orgao || "Orgao nao informado")}</h2>
    <div class="sub">
      <span class="tag ${aberto ? "tag-aberto" : "tag-previsto"}">${aberto ? "Inscricoes abertas" : "Previsto"}</span>
      <span class="pill uf">${esc((c.uf || "").toUpperCase())}</span>
      ${prazo ? `<span class="pill ${prazo.classe}">${prazo.texto}</span>` : ""}
      ${estrelaHTML(c.hash)}
    </div>

    ${c.titulo ? `<p class="titulo-det">${esc(c.titulo)}</p>` : ""}
    ${c.resumo ? `<p class="resumo-det">${esc(c.resumo)}</p>` : ""}

    ${periodo ? `<div class="info"><span class="rotulo">Periodo de inscricao</span><span class="valor">${periodo}</span></div>` : ""}
    <div class="info"><span class="rotulo">Vagas / Cargo</span><span class="valor">${esc(detalhesDe(c).vagas || c.vagas || "nao informado")}</span></div>
    ${linhasDetalhe(c)}
    <div class="info"><span class="rotulo">Fonte</span><span class="valor">${esc(c.fonte || "Concursos no Brasil")}</span></div>

    <div class="acoes-sheet">
      ${c.link_oficial ? `<a class="acao acao-primaria" href="${esc(c.link_oficial)}" target="_blank" rel="noopener">${icoLink} Site oficial / inscricao</a>` : ""}
      ${c.pdf_url ? `<a class="acao ${c.link_oficial ? "acao-secundaria" : "acao-primaria"}" href="${esc(c.pdf_url)}" target="_blank" rel="noopener">${icoPdf} Baixar edital (PDF)</a>` : ""}
      ${acaoMateria.replace("__CLS__", temPrincipal ? "acao-secundaria" : "acao-primaria")}
      ${(c.data_fim || detalhesDe(c).data_prova) ? `<a class="acao acao-secundaria" href="/api/calendario.ics?hash=${encodeURIComponent(c.hash)}" download>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
        Adicionar ao calendario
      </a>` : ""}
      <button class="acao acao-secundaria" id="btn-provas">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
        Provas anteriores
      </button>
      <button class="acao acao-secundaria" id="btn-compartilhar">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/></svg>
        Compartilhar
      </button>
    </div>
    <p class="nota-link">${c.detalhe_em
      ? "Datas, edital e informacoes lidos automaticamente da materia e do PDF. O 'site oficial' e o melhor link encontrado &mdash; confirme sempre na pagina do orgao/banca."
      : "Lendo a materia e o edital em segundo plano. As informacoes aparecem em instantes."}</p>
  `;

  $("btn-compartilhar").addEventListener("click", () => compartilhar(c));
  $("btn-provas").addEventListener("click", () => {
    fecharSheet();
    abrirTreinar(adivinharCargo(c));
  });
  ligarEstrelas($("sheet-conteudo"));
  abrirSheet();
}

// Rotulos e ordem das informacoes extras (detalhes_json) no detalhe. Os cargos
// de TI vem primeiro, por serem o foco. A vaga ja e mostrada em "Vagas / Cargo".
const ROTULOS_DETALHE = {
  cargos_ti: "Cargos de TI", escolaridade: "Escolaridade", salario: "Salario",
  taxa: "Taxa de inscricao", jornada: "Jornada", banca: "Banca",
  data_prova: "Data da prova", cadastro_reserva: "Cadastro de reserva",
};
function linhasDetalhe(c) {
  let det = {};
  try { det = JSON.parse(c.detalhes_json || "{}"); } catch (e) {}
  return Object.keys(ROTULOS_DETALHE)
    .filter((k) => det[k])
    .map((k) => `<div class="info"><span class="rotulo">${ROTULOS_DETALHE[k]}</span><span class="valor">${esc(det[k])}</span></div>`)
    .join("");
}

// Tenta adivinhar o cargo a partir do titulo/vagas para a busca de provas.
const CARGOS_COMUNS = ["professor", "analista", "tecnico", "assistente",
  "auxiliar", "agente", "guarda", "fiscal", "auditor", "procurador",
  "medico", "enfermeiro", "engenheiro", "advogado", "escriturario",
  "oficial", "soldado", "sargento", "contador", "economista", "psicologo",
  "fisioterapeuta", "dentista", "motorista", "operador", "merendeira"];
function adivinharCargo(c) {
  const t = removerAcento(((c.titulo || "") + " " + (c.vagas || "")).toLowerCase());
  for (const k of CARGOS_COMUNS) { if (t.includes(k)) return k; }
  return "";
}
function removerAcento(s) {
  return (s || "").normalize("NFD").replace(/\p{Diacritic}/gu, "");
}

function abrirSheet() {
  $("backdrop").classList.add("aberto");
  $("sheet").classList.add("aberto");
  // Empilha um estado para o botao voltar do celular fechar o detalhe.
  history.pushState({ sheet: true }, "");
}
function fecharSheet(viaPop) {
  $("backdrop").classList.remove("aberto");
  $("sheet").classList.remove("aberto");
  if (!viaPop && history.state && history.state.sheet) history.back();
}

async function compartilhar(c) {
  const url = (c.link && c.link.startsWith("http")) ? c.link : linkBusca(c);
  const titulo = c.titulo ? `\n${c.titulo}` : "";
  const texto = `${c.orgao}${titulo}\nVagas: ${c.vagas || "n/d"} | ${(c.uf||"").toUpperCase()}\n${url}`;
  if (navigator.share) {
    try { await navigator.share({ title: "Concurso", text: texto }); } catch (e) {}
  } else {
    try {
      await navigator.clipboard.writeText(texto);
      alert("Informacoes copiadas.");
    } catch (e) {}
  }
}

$("backdrop").addEventListener("click", () => fecharSheet());
window.addEventListener("popstate", () => {
  if ($("sheet").classList.contains("aberto")) fecharSheet(true);
});

// Formata uma data AAAA-MM-DD para DD/MM (curta, para os cards).
function formatarDataBR(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[3]}/${m[2]}` : (iso || "");
}

// Formata uma data AAAA-MM-DD para DD/MM/AAAA (completa).
function dataCompleta(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

// Monta o texto do periodo de inscricao para o detalhe.
function montarPeriodo(c) {
  const ini = dataCompleta(c.data_inicio);
  const fim = dataCompleta(c.data_fim);
  if (ini && fim) return `${ini} a ${fim}`;
  if (fim) return `ate ${fim}`;
  return "";
}

// ---------- Status / atualizar ----------
function tempoRelativo(iso) {
  try {
    const seg = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (seg < 60) return "agora mesmo";
    const min = Math.floor(seg / 60);
    if (min < 60) return `ha ${min} min`;
    const h = Math.floor(min / 60);
    if (h < 24) return `ha ${h}h`;
    const dias = Math.floor(h / 24);
    return `ha ${dias} dia${dias > 1 ? "s" : ""}`;
  } catch (e) { return iso; }
}

async function atualizarStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    const quando = s.ultima_coleta ? tempoRelativo(s.ultima_coleta) : "coletando agora";
    let extra = "";
    // Mostra o progresso do enriquecimento enquanto ainda nao terminou.
    if (s.detalhados != null && s.total && s.detalhados < s.total) {
      extra = ` &middot; lendo editais ${s.detalhados}/${s.total}`;
    }
    $("status").innerHTML =
      `<span class="pulo">${s.total}</span> concursos &middot; atualizado ${quando}${extra}`;
    return s;
  } catch (e) {
    $("status").textContent = "sem conexao com o servidor";
    return null;
  }
}

// Verdadeiro quando nenhum filtro esta ativo (visao padrao).
function semFiltros() {
  return !filtros.q && !filtros.area && !filtros.uf && !filtros.tipo;
}

// Logo apos abrir o app a coleta do boot ainda pode estar rodando. Esta
// funcao acompanha o crescimento do banco por uns segundos e recarrega a
// lista conforme novos concursos chegam, sem o usuario precisar fazer nada.
function acompanharColeta() {
  let tentativas = 0;
  let ultimoTotal = -1;
  let ultimoDet = -1;
  const id = setInterval(async () => {
    const s = await atualizarStatus();
    if (s) {
      // Atualiza o grid quando entram novos concursos OU quando o
      // enriquecimento adiciona datas de encerramento. So mexe no grid se
      // o detalhe estiver fechado, para nao atrapalhar a leitura.
      const mudou = s.total !== ultimoTotal || s.detalhados !== ultimoDet;
      ultimoTotal = s.total;
      ultimoDet = s.detalhados;
      if (mudou && !$("sheet").classList.contains("aberto")) {
        buscar(true);
      }
      // Para quando coleta terminou e tudo ja foi enriquecido.
      if (s.ultima_coleta && s.detalhados != null && s.detalhados >= s.total) {
        clearInterval(id);
      }
    }
    // Limite de seguranca (cerca de 15 minutos) para nao ficar para sempre.
    if (++tentativas >= 150) clearInterval(id);
  }, 6000);
}

function montarAtualizar() {
  const btn = $("btn-atualizar");
  btn.addEventListener("click", async () => {
    btn.querySelector("svg").classList.add("girando");
    try { await fetch("/api/coletar", { method: "POST" }); } catch (e) {}
    // A coleta roda em background; atualizamos a tela depois de um tempo.
    setTimeout(async () => {
      await atualizarStatus();
      await buscar();
      btn.querySelector("svg").classList.remove("girando");
    }, 5000);
  });
}

// ---------- Telas Treinar e Perfil ----------
function abrirView(id) {
  $(id).classList.add("aberto");
  $(id).setAttribute("aria-hidden", "false");
  history.pushState({ view: id }, "");
}
function fecharView(id, viaPop) {
  $(id).classList.remove("aberto");
  $(id).setAttribute("aria-hidden", "true");
  if (!viaPop && history.state && history.state.view === id) history.back();
}
document.querySelectorAll("[data-fechar-view]").forEach((b) => {
  b.addEventListener("click", () => fecharView(b.dataset.fecharView));
});

// Treinar (provas anteriores via /api/provas).
let treinarTimer = null;
function abrirTreinar(termoInicial) {
  abrirView("view-treinar");
  if (termoInicial != null) $("treinar-q").value = termoInicial;
  buscarProvas();
}
async function buscarProvas() {
  const termo = $("treinar-q").value.trim();
  const box = $("treinar-resultado");
  box.innerHTML = '<p class="dica">Buscando provas...</p>';
  try {
    const d = await (await fetch("/api/provas?q=" + encodeURIComponent(termo))).json();
    const provas = d.provas || [];
    if (!provas.length) {
      box.innerHTML = `<div class="estado"><span class="emoji">&#128218;</span>Nenhuma prova encontrada para esse cargo.<br>Tente um cargo mais comum (ex: professor, analista).</div>`;
      return;
    }
    box.innerHTML = provas.map((p) => `
      <div class="prova-card">
        <div class="ph"><span class="po">${esc(p.orgao || "")}</span><span class="pa">${esc(p.ano || "")}</span></div>
        <div class="pi">${esc(p.prova || "")}${p.banca ? " &middot; " + esc(p.banca) : ""}</div>
        <a class="baixar" href="${esc(p.url)}" target="_blank" rel="noopener">Baixar no PCI &rsaquo;</a>
      </div>
    `).join("");
  } catch (e) {
    box.innerHTML = '<p class="dica">Nao foi possivel buscar as provas agora.</p>';
  }
}
$("btn-treinar").addEventListener("click", () => abrirTreinar(""));
$("treinar-q").addEventListener("input", () => {
  clearTimeout(treinarTimer);
  treinarTimer = setTimeout(buscarProvas, 400);
});

// Perfil (interesses e ntfy).
const PERFIL_UFS = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT",
  "MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"];
async function montarPerfil() {
  // Chips de UF.
  const boxU = $("perfil-ufs");
  PERFIL_UFS.forEach((uf) => {
    const b = document.createElement("button");
    b.className = "chip"; b.dataset.uf = uf.toLowerCase(); b.textContent = uf;
    b.addEventListener("click", () => b.classList.toggle("on"));
    boxU.appendChild(b);
  });
  // Chips de area.
  const boxA = $("perfil-areas");
  let areas = [];
  try { areas = (await (await fetch("/api/areas")).json()).areas || []; } catch (e) {}
  areas.forEach((a) => {
    const b = document.createElement("button");
    b.className = "chip"; b.dataset.area = a;
    b.textContent = a.replace(/_/g, " ");
    b.addEventListener("click", () => b.classList.toggle("on"));
    boxA.appendChild(b);
  });
  // Carrega o perfil salvo.
  try {
    const p = await (await fetch("/api/perfil")).json();
    (p.ufs || []).forEach((uf) => {
      const c = boxU.querySelector(`[data-uf="${uf.toLowerCase()}"]`);
      if (c) c.classList.add("on");
    });
    (p.areas || []).forEach((a) => {
      const c = boxA.querySelector(`[data-area="${a}"]`);
      if (c) c.classList.add("on");
    });
    $("perfil-termos").value = (p.termos || []).join(", ");
    $("perfil-notificar").checked = !!p.notificar;
    $("perfil-ntfy-server").value = p.ntfy_server || "https://ntfy.sh";
    $("perfil-ntfy-topico").value = p.ntfy_topico || "";
  } catch (e) {}
}
function lerPerfilDaTela() {
  const ufs = [...$("perfil-ufs").querySelectorAll(".chip.on")].map((c) => c.dataset.uf);
  const areas = [...$("perfil-areas").querySelectorAll(".chip.on")].map((c) => c.dataset.area);
  const termos = $("perfil-termos").value.split(/[,\n]/).map((t) => t.trim()).filter(Boolean);
  return {
    ufs, areas, termos,
    notificar: $("perfil-notificar").checked,
    ntfy_server: $("perfil-ntfy-server").value.trim() || "https://ntfy.sh",
    ntfy_topico: $("perfil-ntfy-topico").value.trim(),
    app_url: location.origin,
  };
}
async function salvarPerfil() {
  const msg = $("perfil-msg");
  try {
    await fetch("/api/perfil", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lerPerfilDaTela()),
    });
    msg.textContent = "Perfil salvo!";
  } catch (e) { msg.textContent = "Erro ao salvar."; }
  setTimeout(() => (msg.textContent = ""), 3000);
}
async function testarNotificacao() {
  const msg = $("perfil-msg");
  msg.textContent = "Salvando e enviando teste...";
  await salvarPerfilSilencioso();
  try {
    const r = await (await fetch("/api/notificar-teste", { method: "POST" })).json();
    msg.textContent = r.ok ? "Notificacao de teste enviada!" : "Nao enviou. Confira o topico do ntfy.";
  } catch (e) { msg.textContent = "Erro ao enviar teste."; }
  setTimeout(() => (msg.textContent = ""), 5000);
}
async function salvarPerfilSilencioso() {
  try {
    await fetch("/api/perfil", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lerPerfilDaTela()),
    });
  } catch (e) {}
}
$("btn-perfil").addEventListener("click", () => abrirView("view-perfil"));
$("perfil-salvar").addEventListener("click", salvarPerfil);
$("perfil-testar").addEventListener("click", testarNotificacao);

// Botao voltar do celular fecha as telas abertas.
window.addEventListener("popstate", () => {
  ["view-treinar", "view-perfil", "view-favoritos"].forEach((id) => {
    if ($(id).classList.contains("aberto")) fecharView(id, true);
  });
});

// ---------- PWA: service worker + banner de instalar ----------
function registrarSW() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

let promptInstalar = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  promptInstalar = e;
  if (!localStorage.getItem("instalar-dispensado")) {
    $("instalar").classList.add("mostra");
  }
});
$("instalar-sim").addEventListener("click", async () => {
  $("instalar").classList.remove("mostra");
  if (promptInstalar) { promptInstalar.prompt(); promptInstalar = null; }
});
$("instalar-nao").addEventListener("click", () => {
  $("instalar").classList.remove("mostra");
  localStorage.setItem("instalar-dispensado", "1");
});

window.addEventListener("online", () => { $("offline").classList.remove("mostra"); buscar(); });
window.addEventListener("offline", () => { $("offline").classList.add("mostra"); });

// Escapa texto para evitar quebra de HTML.
function esc(t) {
  const d = document.createElement("div");
  d.textContent = t == null ? "" : String(t);
  return d.innerHTML;
}

// ---------- Inicio ----------
montarUFs();
montarToggleTI();
montarChipsPA();
montarTipo();
montarBusca();
montarAtualizar();
montarPerfil();
atualizarStatus();
// Monta os chips e, com eles prontos, aplica a preferencia "So TI" (se ligada)
// antes da primeira busca, para o app ja abrir focado em TI.
montarChips().then(() => {
  try { if (localStorage.getItem("soti") === "1") selecionarArea("ti"); } catch (e) {}
  return carregarFavoritos();
}).then(() => buscar());
acompanharColeta();
registrarSW();
setInterval(atualizarStatus, 60000);
