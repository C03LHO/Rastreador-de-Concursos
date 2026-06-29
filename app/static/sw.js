// Service worker do PWA.
//
// Estrategia:
// - Shell (pagina, icones, manifest): cache primeiro, atualiza em segundo plano.
// - API (/api/concursos e /api/areas): rede primeiro e, se falhar (offline ou
//   fonte fora do ar), cai para a ultima resposta guardada no cache. Isso segue
//   a mesma ideia do app: sempre mostrar o ultimo estado bom.
// - /api/status e /api/coletar nunca usam cache (sao sempre ao vivo).

const VERSAO = "concursos-v12";
const SHELL = [
  "/",
  "/static/app.css",
  "/static/app.js",
  "/static/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/favicon.png",
];

self.addEventListener("install", (evento) => {
  // Pre-carrega o shell e ja assume o controle.
  evento.waitUntil(
    caches.open(VERSAO).then((cache) => cache.addAll(SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (evento) => {
  // Limpa caches de versoes antigas.
  evento.waitUntil(
    caches.keys().then((chaves) =>
      Promise.all(
        chaves.filter((c) => c !== VERSAO).map((c) => caches.delete(c))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (evento) => {
  const req = evento.request;
  const url = new URL(req.url);

  // So tratamos requisicoes GET do mesmo dominio.
  if (req.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }

  // Status e coleta sempre ao vivo, sem cache.
  if (url.pathname.startsWith("/api/status") ||
      url.pathname.startsWith("/api/coletar")) {
    return;
  }

  // Dados (concursos e areas): rede primeiro, cache como rede de seguranca.
  if (url.pathname.startsWith("/api/")) {
    evento.respondWith(redeComFallback(req));
    return;
  }

  // Navegacao (abrir a pagina): rede primeiro, cai para a pagina cacheada.
  if (req.mode === "navigate") {
    evento.respondWith(
      fetch(req).catch(() => caches.match("/"))
    );
    return;
  }

  // Estaticos: cache primeiro.
  evento.respondWith(
    caches.match(req).then((cacheado) => cacheado || fetch(req))
  );
});

async function redeComFallback(req) {
  const cache = await caches.open(VERSAO);
  try {
    const resp = await fetch(req);
    // Guarda a resposta boa para uso offline.
    if (resp && resp.ok) {
      cache.put(req, resp.clone());
    }
    return resp;
  } catch (e) {
    // Sem rede: devolve a ultima resposta guardada, se houver.
    const cacheado = await cache.match(req);
    if (cacheado) return cacheado;
    return new Response(
      JSON.stringify({ total: 0, concursos: [], offline: true }),
      { headers: { "Content-Type": "application/json" } }
    );
  }
}
