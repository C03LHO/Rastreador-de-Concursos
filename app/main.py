"""Aplicacao FastAPI: rotas da API REST, tela web e agendamento da coleta.

O scheduler dispara uma coleta no boot (em background, sem travar o start) e
depois roda de tempos em tempos. O intervalo vem da variavel de ambiente
INTERVALO_HORAS e o fuso usado e America/Belem.
"""

import csv
import io
import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from . import collector, db
from .areas import AREAS

# Pasta dos templates (a tela web) e dos arquivos estaticos do PWA.
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Guardamos o scheduler em modulo para conseguir desliga-lo no shutdown.
scheduler = None


def _agendar():
    # Cria e inicia o agendador da coleta e da leitura diaria de editais.
    global scheduler
    intervalo = int(os.environ.get("INTERVALO_HORAS", "1"))
    hora_leitura = int(os.environ.get("HORA_LEITURA", "4"))
    scheduler = BackgroundScheduler(timezone="America/Belem")

    # Coleta da listagem (rapida): roda de tempos em tempos para pegar os
    # concursos novos e disparar notificacoes.
    scheduler.add_job(
        collector.coletar_tudo,
        "interval",
        hours=intervalo,
        id="coleta_periodica",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # Leitura COMPLETA dos editais (paginas de detalhe + PDF): uma vez por dia,
    # de madrugada, pois e a parte pesada/demorada.
    scheduler.add_job(
        collector.coletar_e_enriquecer,
        "cron",
        hour=hora_leitura,
        minute=0,
        id="leitura_diaria",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    # Lembrete diario de prazo dos concursos favoritados (de manha).
    hora_aviso = int(os.environ.get("HORA_AVISO_PRAZO", "8"))
    scheduler.add_job(
        collector.verificar_prazos_favoritos,
        "cron",
        hour=hora_aviso,
        minute=0,
        id="aviso_prazos",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    print(
        f"[scheduler] coleta a cada {intervalo}h, "
        f"leitura de editais todo dia as {hora_leitura}h"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Roda no start: prepara o banco, agenda a coleta e dispara a primeira
    # coleta em uma thread separada para nao travar a subida do servidor.
    db.iniciar_banco()
    _agendar()
    # No boot, coleta e le todos os editais uma vez (em segundo plano), para o
    # primeiro deploy ja ficar completo sem esperar ate as 4h. Depois disso, a
    # leitura pesada so roda no horario agendado.
    threading.Thread(target=collector.coletar_e_enriquecer, daemon=True).start()
    yield
    # Roda no shutdown: encerra o agendador.
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Rastreador de Concursos", lifespan=lifespan)

# Arquivos estaticos do PWA (icones, manifest). Ficam sob /static.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def home():
    # Serve a tela web (HTML unico).
    caminho = TEMPLATES_DIR / "index.html"
    return HTMLResponse(caminho.read_text(encoding="utf-8"))


@app.get("/sw.js")
def service_worker():
    # O service worker precisa ser servido a partir da raiz para o seu escopo
    # cobrir o app inteiro (e nao apenas a pasta /static).
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/concursos")
def api_concursos(
    uf: str = Query(default=None, description="Sigla do estado, ex: pa"),
    area: str = Query(default=None, description="Area, ex: ti"),
    cidade: str = Query(default=None, description="Texto livre, busca no blob"),
    cargo: str = Query(default=None, description="Texto livre, busca no blob"),
    tipo: str = Query(default=None, description="aberto ou previsto"),
    q: str = Query(default=None, description="Busca livre no blob"),
    limite: int = Query(default=100, description="Quantidade maxima de itens"),
    encerrados: bool = Query(default=False, description="Incluir inscricoes encerradas"),
):
    # Traduz a area para a lista de palavras-chave, se a area existir.
    area_palavras = AREAS.get(area.lower()) if area else None

    concursos = db.buscar_concursos(
        uf=uf,
        area_palavras=area_palavras,
        cidade=cidade,
        cargo=cargo,
        tipo=tipo,
        q=q,
        limite=limite,
        incluir_encerrados=encerrados,
    )
    return {"total": len(concursos), "concursos": concursos}


# Colunas exportadas no CSV, na ordem em que aparecem (chave no banco -> rotulo).
_CSV_COLUNAS = [
    ("orgao", "Orgao"),
    ("titulo", "Titulo"),
    ("uf", "UF"),
    ("tipo", "Tipo"),
    ("vagas", "Vagas"),
    ("data_inicio", "Inscricao inicio"),
    ("data_fim", "Inscricao fim"),
    ("link", "Link"),
    ("link_oficial", "Link oficial"),
    ("pdf_url", "Edital PDF"),
    ("fonte", "Fonte"),
]


@app.get("/api/concursos.csv")
def api_concursos_csv(
    uf: str = Query(default=None),
    area: str = Query(default=None),
    cidade: str = Query(default=None),
    cargo: str = Query(default=None),
    tipo: str = Query(default=None),
    q: str = Query(default=None),
    limite: int = Query(default=1000, description="Quantidade maxima de itens"),
    encerrados: bool = Query(default=False),
):
    # Exporta os concursos filtrados em CSV (mesmos filtros de /api/concursos).
    # Util para abrir no Excel/Sheets ou guardar uma copia.
    area_palavras = AREAS.get(area.lower()) if area else None
    concursos = db.buscar_concursos(
        uf=uf, area_palavras=area_palavras, cidade=cidade, cargo=cargo,
        tipo=tipo, q=q, limite=limite, incluir_encerrados=encerrados,
    )

    buffer = io.StringIO()
    # utf-8-sig (BOM) faz o Excel abrir os acentos corretamente.
    escritor = csv.writer(buffer, delimiter=";")
    escritor.writerow([rotulo for _, rotulo in _CSV_COLUNAS])
    for c in concursos:
        escritor.writerow([c.get(chave, "") or "" for chave, _ in _CSV_COLUNAS])

    conteudo = "﻿" + buffer.getvalue()
    return Response(
        content=conteudo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="concursos.csv"'},
    )


@app.get("/api/areas")
def api_areas():
    # Lista as areas disponiveis para o filtro.
    return {"areas": sorted(AREAS.keys())}


@app.get("/api/health")
def api_health():
    # Verificacao leve para o healthcheck do Docker e monitoramento externo.
    # So confirma que a app responde e que o banco esta acessivel.
    try:
        total = db.contar_total()
        return {"status": "ok", "total": total}
    except Exception as erro:
        return {"status": "erro", "detalhe": str(erro)}


@app.get("/api/status")
def api_status():
    # Informa o estado atual do banco, da ultima coleta e do enriquecimento.
    return {
        "total": db.contar_total(),
        "detalhados": db.contar_detalhados(),
        "ultima_coleta": db.get_meta("ultima_coleta"),
        "ultimo_resultado": db.get_meta("ultimo_resultado"),
    }


@app.post("/api/coletar")
def api_coletar():
    # Forca uma coleta imediata. Roda em background para nao travar a resposta,
    # ja que percorrer os 27 estados leva alguns segundos.
    threading.Thread(target=collector.coletar_tudo, daemon=True).start()
    return {"ok": True, "mensagem": "coleta iniciada em background"}


@app.get("/api/perfil")
def api_perfil_get():
    # Devolve o perfil de interesse salvo (UFs, termos, areas e ntfy).
    return collector.carregar_perfil()


@app.post("/api/perfil")
async def api_perfil_post(request: Request):
    # Salva o perfil de interesse. Aceita um JSON com ufs, termos, areas,
    # notificar, ntfy_server, ntfy_topico e app_url.
    try:
        perfil = await request.json()
    except Exception:
        perfil = {}
    db.set_meta("perfil", json.dumps(perfil, ensure_ascii=False))
    return {"ok": True}


@app.post("/api/notificar-teste")
def api_notificar_teste():
    # Dispara uma notificacao de teste para validar a configuracao do ntfy.
    perfil = collector.carregar_perfil()
    ok = collector.enviar_notificacao_teste(perfil)
    return {"ok": ok}


@app.get("/api/provas")
def api_provas(q: str = Query(default=None, description="Cargo ou termo")):
    # Lista provas anteriores do PCI Concursos para treinar (por cargo/termo).
    return collector.buscar_provas(q or "")


@app.get("/api/favoritos")
def api_favoritos():
    # Devolve os hashes favoritados (para marcar estrelas) e a lista completa
    # de concursos favoritados, ordenada por prazo.
    return {
        "hashes": db.hashes_favoritos(),
        "concursos": db.listar_favoritos(),
    }


@app.post("/api/favoritos/{hash_}")
def api_favoritar(hash_: str):
    # Alterna o favorito de um concurso. Retorna se ficou favoritado.
    return {"favorito": db.alternar_favorito(hash_)}
