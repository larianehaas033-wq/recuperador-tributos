"""API local do Recuperador de Tributos (FastAPI). Só escuta em 127.0.0.1."""
from __future__ import annotations

import os

import json
import subprocess
import sys
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Request, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, updater
from .engine.runner import executar_analise, gerar_cadastro, recalcular
from .importador import importar
from .reports.relatorios import gerar_excel, gerar_excel_cadastro, gerar_pdf
from .rules.loader import carregar

db.init()
app = FastAPI(title="Recuperador de Tributos", version=config.VERSION)
_pool = ThreadPoolExecutor(max_workers=1)  # fila de processamento (substitui Celery/Redis no uso local)
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _job(fn, *args) -> str:
    jid = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[jid] = {"status": "FILA", "etapa": "Aguardando", "progresso": 0.0, "resultado": None, "erro": None}

    def progress(etapa: str, p: float):
        with _jobs_lock:
            _jobs[jid].update(etapa=etapa, progresso=round(p, 2))

    def run():
        with _jobs_lock:
            _jobs[jid]["status"] = "RODANDO"
        try:
            res = fn(*args, progress=progress)
            with _jobs_lock:
                _jobs[jid].update(status="CONCLUIDO", progresso=1.0, etapa="Concluído", resultado=res)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            with _jobs_lock:
                _jobs[jid].update(status="ERRO", erro=str(e))

    _pool.submit(run)
    return jid


@app.get("/api/jobs/{jid}")
def job(jid: str):
    with _jobs_lock:
        if jid not in _jobs:
            raise HTTPException(404, "Tarefa não encontrada")
        return _jobs[jid]


# ------------------------------------------------------------------------- status e base
@app.get("/api/status")
def status():
    base = carregar()
    with db.tx() as con:
        ult = con.execute("SELECT executado_em, status, detalhe FROM atualizacoes WHERE fonte='Atualização geral' "
                          "ORDER BY id DESC LIMIT 1").fetchone()
        selic = con.execute("SELECT max(competencia) m, count(*) n FROM selic").fetchone()
        pend = db.rows(con, "SELECT nome, url, alterado_em FROM fontes_monitoradas WHERE pendente_revisao=1")
        n_emp = con.execute("SELECT count(*) n FROM empresas").fetchone()["n"]
    horas = updater.horas_desde_ultima()
    return {
        "versao_programa": config.VERSION,
        "regras": {"versao": base.versao, "origem": base.origem, "publicado_em": base.publicado_em,
                   "qtd": len(base.regras)},
        "ultima_atualizacao": dict(ult) if ult else None,
        "horas_desde_atualizacao": horas,
        "base_desatualizada": horas is None or horas > 26,
        "selic": {"ate": selic["m"], "meses": selic["n"]},
        "fontes_pendentes": pend,
        "empresas": n_emp,
        "pasta_dados": str(config.DATA_DIR),
    }


@app.post("/api/atualizar")
def atualizar():
    return {"job": _job(lambda progress: updater.atualizar_tudo())}


@app.get("/api/versao")
def versao():
    return updater.estado_versao()


@app.post("/api/versao/verificar")
def verificar_versao_agora():
    try:
        return updater.verificar_versao()
    except Exception as e:
        raise HTTPException(502, f"Não foi possível consultar o servidor de atualizações: {e}")


@app.post("/api/atualizar-programa")
def atualizar_programa():
    return {"job": _job(lambda progress: updater.baixar_versao(progress))}


@app.post("/api/reiniciar")
def reiniciar(request: Request):
    """Reabre o programa para usar a versão baixada, sem o usuário fechar a janela: um novo launcher espera este
    processo terminar, troca as pastas, sobe na mesma porta e a tela recarrega sozinha."""
    import subprocess
    import sys
    import threading

    porta = request.url.port or 0
    subprocess.Popen([sys.executable, str(config.ROOT_DIR / "launcher.py"), "--reiniciar", str(porta)],
                     cwd=str(config.ROOT_DIR.parent))
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return {"ok": True}


@app.get("/api/atualizacoes")
def historico_atualizacoes():
    with db.tx() as con:
        return db.rows(con, "SELECT * FROM atualizacoes ORDER BY id DESC LIMIT 200")


@app.get("/api/fontes")
def fontes():
    with db.tx() as con:
        return db.rows(con, "SELECT * FROM fontes_monitoradas ORDER BY nome")


class Url(BaseModel):
    url: str


@app.post("/api/fontes/revisada")
def fonte_revisada(body: Url):
    updater.marcar_revisada(body.url)
    return {"ok": True}


@app.get("/api/regras")
def regras():
    base = carregar()
    return {
        "versao": base.versao, "origem": base.origem, "publicado_em": base.publicado_em,
        "regras": [{"codigo": r.codigo, "tipo": r.tipo, "grupo": r.grupo, "prefixos": r.prefixos,
                    "excecoes": r.excecoes, "fundamento": r.fundamento, "confianca": r.confianca,
                    "observacao": r.observacao, "vigencia": f"{r.vigencia_ini} a {r.vigencia_fim}"}
                   for r in base.regras],
        "teses": base.teses, "icms_modal": base.icms_modal,
    }


@app.get("/api/configuracoes")
def get_config():
    return updater.configuracoes()


@app.post("/api/configuracoes")
def set_config(body: dict):
    return updater.salvar_configuracoes(body)


@app.post("/api/agendar-atualizacao")
def agendar():
    """Cria a tarefa diária no Agendador do Windows (07:30), que roda a atualização mesmo com o programa fechado."""
    if not sys.platform.startswith("win"):
        raise HTTPException(400, "Disponível só no Windows.")
    raiz = config.ROOT_DIR.parent
    pyw = raiz / "python" / "pythonw.exe"
    script = raiz / "atualizar_base.py"
    cmd = ["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", "07:30", "/TN", "RecuperadorTributos_Atualizacao",
           "/TR", f'"{pyw}" "{script}"']
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=0x08000000)
    if r.returncode != 0:
        raise HTTPException(500, r.stderr or r.stdout)
    return {"ok": True, "mensagem": "Atualização diária agendada para 07:30."}


# ------------------------------------------------------------------------- importação
class Caminhos(BaseModel):
    caminhos: list[str]


@app.post("/api/selecionar")
def selecionar(tipo: str = "arquivos"):
    """Abre a janela do Windows para escolher arquivos ou uma pasta (roda no próprio computador)."""
    resultado: list[str] = []

    def dialogo():
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        if tipo == "pasta":
            p = filedialog.askdirectory(title="Escolha a pasta com os arquivos (SPED e XML)")
            if p:
                resultado.append(p)
        else:
            ps = filedialog.askopenfilenames(
                title="Escolha os arquivos SPED (.txt), XMLs, .zip ou a planilha de itens do DF-e (.xlsx)",
                filetypes=[("Arquivos fiscais", "*.txt *.xml *.zip *.xlsx"), ("Todos", "*.*")])
            resultado.extend(ps)
        root.destroy()

    t = threading.Thread(target=dialogo)
    t.start()
    t.join()
    return {"caminhos": resultado}


@app.post("/api/importar")
def importar_caminhos(body: Caminhos):
    paths = [Path(p) for p in body.caminhos if p]
    faltando = [str(p) for p in paths if not p.exists()]
    if faltando:
        raise HTTPException(400, f"Não encontrado: {', '.join(faltando)}")
    return {"job": _job(lambda progress: importar(paths, progress))}


@app.post("/api/upload")
async def upload(files: list[UploadFile]):
    destino = config.DATA_DIR / "uploads" / uuid.uuid4().hex[:8]
    destino.mkdir(parents=True)
    for f in files:
        nome = Path(f.filename or "arquivo").name
        with (destino / nome).open("wb") as out:
            while chunk := await f.read(1024 * 1024):
                out.write(chunk)
    return {"job": _job(lambda progress: importar([destino], progress))}


# ------------------------------------------------------------------------- malha fiscal
@app.get("/api/empresas/{empresa_id}/malha")
def malha_fiscal(empresa_id: int):
    from .engine import malha
    from .rules.loader import carregar
    with db.tx() as con:
        al = malha.verificar(con, empresa_id, carregar())
    return {**malha.resumo(al), "alertas": al}


# ------------------------------------------------------------------------- empresas e análises
@app.get("/api/empresas")
def empresas():
    with db.tx() as con:
        return db.rows(con, """
            SELECT e.*, (SELECT count(*) FROM arquivos_sped a WHERE a.empresa_id=e.id) arquivos,
                   (SELECT min(periodo_ini) FROM arquivos_sped a WHERE a.empresa_id=e.id AND periodo_ini IS NOT NULL) ini,
                   (SELECT max(periodo_ini) FROM arquivos_sped a WHERE a.empresa_id=e.id AND periodo_ini IS NOT NULL) fim,
                   (SELECT max(id) FROM analises x WHERE x.empresa_id=e.id AND status='CONCLUIDA') ultima_analise,
                   (SELECT desatualizada FROM analises x WHERE x.empresa_id=e.id AND status='CONCLUIDA'
                    ORDER BY id DESC LIMIT 1) analise_desatualizada
            FROM empresas e ORDER BY e.nome""")


@app.get("/api/empresas/{eid}")
def empresa(eid: int):
    with db.tx() as con:
        e = con.execute("SELECT * FROM empresas WHERE id=?", (eid,)).fetchone()
        if not e:
            raise HTTPException(404, "Empresa não encontrada")
        arquivos = db.rows(con, "SELECT id, tipo, nome, periodo_ini, finalidade, qtd_registros, importado_em "
                                "FROM arquivos_sped WHERE empresa_id=? ORDER BY tipo, periodo_ini", (eid,))
        analises = db.rows(con, "SELECT id, criado_em, periodo_ini, periodo_fim, versao_regras, status, resumo_json, "
                                "desatualizada "
                                "FROM analises WHERE empresa_id=? ORDER BY id DESC", (eid,))
        cobertura = db.rows(con, "SELECT substr(periodo_ini,1,7) periodo, tipo FROM arquivos_sped "
                                 "WHERE empresa_id=? AND periodo_ini IS NOT NULL", (eid,))
        xml = db.rows(con, "SELECT periodo, count(*) n FROM notas_fiscais WHERE empresa_id=? AND origem='XML' "
                           "GROUP BY periodo", (eid,))
    for a in analises:
        a["resumo"] = json.loads(a.pop("resumo_json") or "{}")
        a["resumo"].pop("serie", None)
    return {"empresa": dict(e), "arquivos": arquivos, "analises": analises, "cobertura": cobertura, "xml": xml}


class RegimeManual(BaseModel):
    regime: str | None = None  # LUCRO_REAL, LUCRO_PRESUMIDO, SIMPLES_NACIONAL ou vazio (automático)


@app.post("/api/empresas/{eid}/regime")
def definir_regime(eid: int, body: RegimeManual):
    """Regime informado pelo usuário: vale nas competências sem EFD-Contribuições (que tem prioridade)."""
    reg = body.regime or None
    if reg not in (None, "LUCRO_REAL", "LUCRO_PRESUMIDO", "SIMPLES_NACIONAL"):
        raise HTTPException(400, "Regime inválido.")
    with db.tx() as con:
        con.execute("UPDATE empresas SET regime_manual=? WHERE id=?", (reg, eid))
        con.execute("UPDATE analises SET desatualizada=1 WHERE empresa_id=?", (eid,))
        from .importador import atualizar_regime
        atualizar_regime(con, eid)
    return {"ok": True}


@app.delete("/api/empresas/{eid}")
def excluir_empresa(eid: int):
    """Exclui a empresa e tudo dela, das tabelas filhas para a principal (mais rápido que só a cascata)."""
    try:
        with db.tx() as con:
            for sql in (
                "DELETE FROM creditos_identificados WHERE analise_id IN (SELECT id FROM analises WHERE empresa_id=?)",
                "DELETE FROM analises WHERE empresa_id=?", "DELETE FROM analitico_icms WHERE empresa_id=?",
                "DELETE FROM itens_nota WHERE empresa_id=?",
                "DELETE FROM notas_fiscais WHERE empresa_id=?", "DELETE FROM apuracoes WHERE empresa_id=?",
                "DELETE FROM produtos WHERE empresa_id=?", "DELETE FROM revisoes_ncm WHERE empresa_id=?",
                "DELETE FROM arquivos_sped WHERE empresa_id=?", "DELETE FROM empresas WHERE id=?",
            ):
                con.execute(sql, (eid,))
            restou = con.execute("SELECT count(*) n FROM empresas WHERE id=?", (eid,)).fetchone()["n"]
    except Exception as e:
        raise HTTPException(500, f"Não foi possível excluir a empresa: {e}") from e
    if restou:
        raise HTTPException(500, "A empresa não foi excluída. Feche e abra o programa e tente de novo.")
    return {"ok": True}


@app.delete("/api/arquivos/{aid}")
def excluir_arquivo(aid: int):
    try:
        with db.tx() as con:
            emp = con.execute("SELECT empresa_id FROM arquivos_sped WHERE id=?", (aid,)).fetchone()
            for sql in ("DELETE FROM analitico_icms WHERE arquivo_id=?", "DELETE FROM itens_nota WHERE arquivo_id=?",
                        "DELETE FROM notas_fiscais WHERE arquivo_id=?",
                        "DELETE FROM apuracoes WHERE arquivo_id=?", "DELETE FROM arquivos_sped WHERE id=?"):
                con.execute(sql, (aid,))
            if emp:  # a análise anterior deixou de refletir os arquivos
                con.execute("UPDATE analises SET desatualizada=1 WHERE empresa_id=?", (emp["empresa_id"],))
    except Exception as e:
        raise HTTPException(500, f"Não foi possível remover o arquivo: {e}") from e
    return {"ok": True}


@app.post("/api/empresas/{eid}/analisar")
def analisar(eid: int):
    return {"job": _job(lambda progress: executar_analise(eid, progress=progress))}


@app.get("/api/analises/{aid}")
def analise(aid: int):
    with db.tx() as con:
        a = con.execute("SELECT * FROM analises WHERE id=?", (aid,)).fetchone()
        if not a:
            raise HTTPException(404, "Análise não encontrada")
        a = dict(a)
        e = dict(con.execute("SELECT * FROM empresas WHERE id=?", (a["empresa_id"],)).fetchone())
        ncms = db.rows(con, """
            SELECT c.ncm, c.tese, min(c.descricao) descricao, count(*) itens, round(sum(c.valor_recuperar), 2) valor,
                   min(c.regra_codigo) regra,
                   CASE WHEN sum(c.confianca <> 'ALTA') > 0 THEN 'BAIXA' ELSE 'ALTA' END confianca, r.decisao
            FROM creditos_identificados c
            LEFT JOIN revisoes_ncm r ON r.empresa_id=? AND r.ncm=c.ncm AND r.tese=c.tese
            WHERE c.analise_id=? AND c.ncm IS NOT NULL AND c.ncm <> ''
              AND c.tese IN ('PISCOF_MONO_SAIDA','PISCOF_ALIQ_ZERO_SAIDA','PISCOF_CREDITO_ENTRADA',
                             'ICMS_ST_TRIBUTADO_SAIDA','ICMS_ALIQ_ACIMA','RISCO_SAIDA_ZERO_SEM_REGRA')
            GROUP BY c.ncm, c.tese ORDER BY valor DESC LIMIT 400""", (a["empresa_id"], aid))
    a["resumo"] = json.loads(a.pop("resumo_json") or "{}")
    a["avisos"] = json.loads(a.pop("avisos_json") or "[]")
    base = carregar()
    a["teses_info"] = {k: {"nome": v["nome"], "via": v["via"], "roteiro": v["roteiro"], "fundamento": v["fundamento"]}
                       for k, v in base.teses.items()}
    return {"analise": a, "empresa": e, "ncms": ncms}


@app.get("/api/analises/{aid}/creditos")
def creditos(aid: int, tese: str | None = None, tributo: str | None = None, natureza: str | None = None,
             confianca: str | None = None, busca: str | None = None, operacao: str | None = None,
             pagina: int = 1, por_pagina: int = 100):
    from .engine.comum import TESES_SAIDA
    where, params = ["analise_id = ?"], [aid]
    if operacao in ("SAIDA", "ENTRADA"):
        marcas = ",".join("?" * len(TESES_SAIDA))
        cond = (f"(substr(cfop,1,1) IN ('5','6','7') OR ((cfop IS NULL OR cfop = '') AND tese IN ({marcas})))")
        where.append(cond if operacao == "SAIDA" else f"NOT {cond}")
        params += list(TESES_SAIDA)
    for campo, valor in (("tese", tese), ("tributo", tributo), ("natureza", natureza), ("confianca", confianca)):
        if valor:
            where.append(f"{campo} = ?")
            params.append(valor)
    if busca:
        where.append("(chave LIKE ? OR ncm LIKE ? OR descricao LIKE ? OR cod_item LIKE ?)")
        params += [f"%{busca}%"] * 4
    w = " AND ".join(where)
    with db.tx() as con:
        total = con.execute(f"SELECT count(*) n FROM creditos_identificados WHERE {w}", params).fetchone()["n"]
        itens = db.rows(con, f"SELECT * FROM creditos_identificados WHERE {w} ORDER BY valor_recuperar DESC "
                             f"LIMIT ? OFFSET ?", params + [por_pagina, (pagina - 1) * por_pagina])
    return {"total": total, "pagina": pagina, "itens": itens}


@app.get("/api/analises/{aid}/compras")
def compras(aid: int, situacao: str | None = None, busca: str | None = None, pagina: int = 1, por_pagina: int = 100):
    """Todos os produtos de compra do período da análise: destacado pelo fornecedor x creditado na EFD."""
    from .engine import compras as cp
    with db.tx() as con:
        a = con.execute("SELECT empresa_id, periodo_ini, periodo_fim FROM analises WHERE id=?", (aid,)).fetchone()
        if not a:
            raise HTTPException(404, "Análise não encontrada")
        linhas = cp.listar(con, a["empresa_id"], a["periodo_ini"], a["periodo_fim"])
    res = cp.resumo(linhas)
    if situacao:
        linhas = [r for r in linhas if r["situacao"] == situacao]
    if busca:
        b = busca.upper()
        linhas = [r for r in linhas if any(b in str(r[c] or "").upper()
                                           for c in ("descricao", "ncm", "nota", "chave", "cod_item"))]
    ini = (pagina - 1) * por_pagina
    return {"total": len(linhas), "pagina": pagina, "resumo": res, "situacoes": cp.SITUACOES,
            "itens": linhas[ini:ini + por_pagina]}


class Revisao(BaseModel):
    ncm: str
    tese: str
    decisao: str  # CONFIRMADO, DESCARTADO ou LIMPAR


@app.post("/api/analises/{aid}/revisao")
def revisar(aid: int, body: Revisao):
    with db.tx() as con:
        emp = con.execute("SELECT empresa_id FROM analises WHERE id=?", (aid,)).fetchone()["empresa_id"]
        if body.decisao == "LIMPAR":
            con.execute("DELETE FROM revisoes_ncm WHERE empresa_id=? AND ncm=? AND tese=?", (emp, body.ncm, body.tese))
        else:
            con.execute("INSERT INTO revisoes_ncm (empresa_id, ncm, tese, decisao) VALUES (?,?,?,?) "
                        "ON CONFLICT(empresa_id, ncm, tese) DO UPDATE SET decisao=excluded.decisao, "
                        "revisado_em=CURRENT_TIMESTAMP", (emp, body.ncm, body.tese, body.decisao))
    return {"job": _job(lambda progress: recalcular(aid))}


@app.get("/api/empresas/{eid}/cadastro")
def cadastro(eid: int, so_divergentes: bool = False):
    linhas = gerar_cadastro(eid)
    base = carregar()
    resumo = {
        "produtos": len(linhas),
        "com_divergencia": sum(1 for x in linhas if x["divergencias"]),
        "nao_comprovados": sum(1 for x in linhas if x["comprovacao"] != "ALTA"),
        "tabela_cclasstrib": base.ibs.get("versao_tabela_cclasstrib"),
    }
    if so_divergentes:
        linhas = [x for x in linhas if x["divergencias"]]
    return {"resumo": resumo, "linhas": linhas}


@app.get("/api/empresas/{eid}/cadastro/excel")
def cadastro_excel(eid: int):
    p = gerar_excel_cadastro(eid)
    return FileResponse(p, filename=p.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/analises/{aid}/excel")
def excel(aid: int):
    p = gerar_excel(aid)
    return FileResponse(p, filename=p.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/analises/{aid}/pdf")
def pdf(aid: int):
    p = gerar_pdf(aid)
    return FileResponse(p, filename=p.name, media_type="application/pdf")


def _abrir(p: Path) -> dict:
    """Abre o arquivo direto no programa padrão (Excel, leitor de PDF) em vez de depender do download da janela."""
    aberto = False
    if sys.platform.startswith("win"):
        try:
            import os
            os.startfile(str(p))  # noqa: S606
            aberto = True
        except OSError:
            subprocess.Popen(["explorer", "/select,", str(p)])
    return {"caminho": str(p), "nome": p.name, "aberto": aberto}


class Tipo(BaseModel):
    tipo: str  # excel ou pdf


@app.post("/api/analises/{aid}/abrir")
def abrir_relatorio(aid: int, body: Tipo):
    return _abrir(gerar_pdf(aid) if body.tipo == "pdf" else gerar_excel(aid))


@app.post("/api/empresas/{eid}/cadastro/abrir")
def abrir_cadastro(eid: int):
    return _abrir(gerar_excel_cadastro(eid))


@app.post("/api/abrir-pasta")
def abrir_pasta():
    pasta = config.DATA_DIR / "relatorios"
    pasta.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        try:
            os.startfile(str(pasta))  # noqa: S606
        except OSError:
            subprocess.Popen(["explorer", str(pasta)])
    return {"pasta": str(pasta)}


@app.get("/api/relatorios/{nome}")
def baixar_relatorio(nome: str):
    """Entrega o relatório pela própria janela: vai para a pasta Downloads, mesmo quando o Windows não abre o Excel."""
    pasta = (config.DATA_DIR / "relatorios").resolve()
    p = (pasta / nome).resolve()
    if p.parent != pasta or not p.is_file():
        raise HTTPException(404, "Relatório não encontrado.")
    return FileResponse(p, filename=p.name)


@app.exception_handler(Exception)
async def erro(_, exc: Exception):
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.middleware("http")
async def sem_cache_da_tela(request, call_next):
    """A página principal nunca fica em cache: depois de atualizar o programa, a janela mostra a tela nova."""
    resp = await call_next(request)
    caminho = request.url.path
    if not caminho.startswith("/api") and not caminho.startswith("/assets/"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


if config.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
