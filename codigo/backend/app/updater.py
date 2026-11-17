"""Atualização da base: Selic (Banco Central), pacote de regras e monitoramento de fontes oficiais.

Rodada automaticamente ao abrir o programa (se a última foi há mais de 20 horas), pelo botão
"Atualizar agora" e, se a usuária ativar, por uma tarefa diária do Agendador do Windows.
"""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import urllib.request
from datetime import datetime
from html import unescape

from . import config, db
from .rules.loader import validar

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0 Safari/537.36 Edg/130.0", "Accept-Language": "pt-BR,pt;q=0.9"}
BLOQUEIO = ("acesso negado", "bloqueio.de.aplicacoes", "access denied", "request blocked")


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


def _log(con, fonte: str, status: str, detalhe: str) -> None:
    con.execute("INSERT INTO atualizacoes (fonte, status, detalhe) VALUES (?,?,?)", (fonte, status, detalhe[:1000]))


def configuracoes() -> dict:
    if config.SETTINGS_PATH.exists():
        try:
            cfg = json.loads(config.SETTINGS_PATH.read_text(encoding="utf-8"))
            if not cfg.get("url_regras"):
                cfg["url_regras"] = config.URL_REGRAS
            return cfg
        except json.JSONDecodeError:
            pass
    return {"url_regras": config.URL_REGRAS, "atualizacao_automatica": True}


def salvar_configuracoes(dados: dict) -> dict:
    atual = configuracoes()
    atual.update({k: v for k, v in dados.items() if k in ("url_regras", "atualizacao_automatica")})
    config.SETTINGS_PATH.write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")
    return atual


def atualizar_selic(con) -> str:
    fontes = json.loads(config.MONITOR_BUNDLED.read_text(encoding="utf-8"))
    dados = json.loads(_get(fontes["selic"]).decode("utf-8"))
    n = 0
    for d in dados:
        dia, mes, ano = d["data"].split("/")
        con.execute(
            "INSERT INTO selic (competencia, taxa, atualizado_em) VALUES (?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(competencia) DO UPDATE SET taxa=excluded.taxa, atualizado_em=CURRENT_TIMESTAMP",
            (f"{ano}-{mes}", float(d["valor"])),
        )
        n += 1
    ultima = max(f"{d['data'][6:]}-{d['data'][3:5]}" for d in dados) if dados else "-"
    _log(con, "Selic (BCB SGS 4390)", "OK", f"{n} meses; última competência {ultima}")
    return ultima


def atualizar_regras(con, url: str) -> str:
    if not url:
        _log(con, "Pacote de regras", "SEM_MUDANCA", "Endereço de atualização de regras não configurado.")
        return "sem endereço"
    data = json.loads(_get(url).decode("utf-8"))
    if config.versao_tupla(data.get("programa_minimo", "0")) > config.versao_tupla(config.VERSION):
        _log(con, "Pacote de regras", "SEM_MUDANCA",
             f"Regras {data.get('versao')} exigem o programa {data['programa_minimo']}: atualize o programa.")
        return "exige programa novo"
    erros = validar(data)
    if erros:
        _log(con, "Pacote de regras", "ERRO", "; ".join(erros))
        return "inválido"
    atual = None
    if config.RULES_LOCAL.exists():
        atual = json.loads(config.RULES_LOCAL.read_text(encoding="utf-8")).get("versao")
    if atual and config.versao_tupla(data["versao"]) <= config.versao_tupla(atual):
        _log(con, "Pacote de regras", "SEM_MUDANCA", f"Versão {atual} já é a mais recente.")
        return atual
    config.RULES_LOCAL.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    _log(con, "Pacote de regras", "ALTERADA", f"Nova versão {data['versao']} instalada.")
    return data["versao"]


URL_NCM = "https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json?perfil=PUBLICO"


def atualizar_ncm(con) -> str:
    """Baixa a tabela NCM vigente (Portal Único Siscomex) para conferir os códigos do cadastro do cliente."""
    dados = json.loads(_get(URL_NCM, timeout=120).decode("utf-8-sig"))
    lista = dados.get("Nomenclaturas") or dados.get("nomenclaturas") or []
    codigos = set()
    for n in lista:
        c = re.sub(r"\D", "", str(n.get("Codigo") or n.get("codigo") or ""))
        fim = str(n.get("Data_Fim") or n.get("dataFim") or "31/12/9999")
        if len(c) == 8 and not (len(fim) == 10 and fim[6:] + fim[3:5] + fim[:2] < datetime.now().strftime("%Y%m%d")):
            codigos.add(c)
    if len(codigos) < 5000:
        raise ValueError(f"tabela NCM incompleta ({len(codigos)} códigos)")
    destino = config.DATA_DIR / "ncm_vigente.json"
    destino.write_text(json.dumps({"atualizada_em": datetime.now().isoformat(timespec="seconds"),
                                   "fonte": URL_NCM, "codigos": sorted(codigos)}), encoding="utf-8")
    from .engine import coerencia
    coerencia.tabela_vigente.cache_clear()
    _log(con, "Tabela NCM (Siscomex)", "OK", f"{len(codigos)} códigos vigentes")
    return f"{len(codigos)} códigos"


def _texto_normalizado(html: bytes) -> str:
    t = html.decode("utf-8", errors="ignore") if b"charset=utf-8" in html[:2000].lower() else html.decode("latin-1")
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t)).strip()


ESTADO_VERSAO = config.DATA_DIR / "atualizacao_programa.json"


def verificar_versao(con=None) -> dict:
    """Consulta o versao.json publicado no repositório e guarda o resultado."""
    try:
        req = urllib.request.Request(config.URL_VERSAO_API, headers={**UA, "Accept": "application/vnd.github.raw"})
        with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()) as r:
            info = json.loads(r.read().decode("utf-8"))
    except Exception:
        info = json.loads(_get(config.URL_VERSAO).decode("utf-8"))
    nova = config.versao_tupla(info.get("versao")) > config.versao_tupla(config.VERSION)
    estado = {"atual": config.VERSION, "disponivel": info.get("versao"), "nova": nova,
              "notas": info.get("notas", []), "pacote": info.get("pacote"), "sha256": info.get("sha256"),
              "pacote_completo": bool(info.get("exige_pacote_completo")), "publicado_em": info.get("publicado_em")}
    baixada = config.ROOT_DIR.parent / "sistema_nova" / "launcher.py"
    estado["baixada"] = baixada.exists()
    ESTADO_VERSAO.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    if con is not None:
        _log(con, "Versão do programa", "ALTERADA" if nova else "SEM_MUDANCA",
             f"Disponível {info.get('versao')}; instalada {config.VERSION}.")
    return estado


def estado_versao() -> dict:
    if ESTADO_VERSAO.exists():
        try:
            e = json.loads(ESTADO_VERSAO.read_text(encoding="utf-8"))
            e["nova"] = config.versao_tupla(e.get("disponivel")) > config.versao_tupla(config.VERSION)
            e["atual"] = config.VERSION
            e["baixada"] = (config.ROOT_DIR.parent / "sistema_nova" / "launcher.py").exists()
            return e
        except json.JSONDecodeError:
            pass
    return {"atual": config.VERSION, "nova": False}


def baixar_versao(progress=None) -> dict:
    """Baixa o pacote da nova versão, confere o SHA-256 e deixa em 'sistema_nova'.
    A troca acontece ao abrir o programa de novo (launcher.py), com a pasta anterior guardada."""
    import shutil
    import zipfile

    estado = verificar_versao()
    if not estado["nova"]:
        return {"ok": False, "mensagem": "O programa já está na versão mais recente."}
    if estado["pacote_completo"]:
        return {"ok": False, "mensagem": "Esta versão troca também o Python e as bibliotecas: baixe o pacote completo."}
    if progress:
        progress("Baixando a nova versão", 0.2)
    dados = _get(f"{config.REPO_RAW}/{estado['pacote']}", timeout=180)
    if hashlib.sha256(dados).hexdigest() != estado["sha256"]:
        raise RuntimeError("O arquivo baixado não confere com a assinatura publicada (SHA-256). Nada foi alterado.")
    if progress:
        progress("Instalando", 0.7)
    raiz = config.ROOT_DIR.parent
    destino = raiz / "sistema_nova"
    tmp = raiz / "sistema_nova_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    import io
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        for nome in z.namelist():
            alvo = (tmp / nome).resolve()
            if not str(alvo).startswith(str(tmp.resolve())):
                raise RuntimeError("Pacote inválido.")
        z.extractall(tmp)
    if not (tmp / "launcher.py").exists() or not (tmp / "app" / "main.py").exists():
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("Pacote incompleto. Nada foi alterado.")
    shutil.rmtree(destino, ignore_errors=True)
    tmp.rename(destino)
    estado["baixada"] = True
    ESTADO_VERSAO.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "mensagem": f"Versão {estado['disponivel']} pronta.", "reiniciar": True}


def monitorar_fontes(con) -> list[str]:
    fontes = json.loads(config.MONITOR_BUNDLED.read_text(encoding="utf-8"))["monitoradas"]
    alteradas = []
    agora = datetime.now().isoformat(timespec="seconds")
    for f in fontes:
        try:
            texto = _texto_normalizado(_get(f["url"], timeout=40))
        except Exception as e:  # fonte fora do ar não interrompe a atualização
            _log(con, f["nome"], "ERRO", f"Não foi possível acessar: {e}")
            continue
        if len(texto) < 2000 or any(b in texto[:3000].lower() for b in BLOQUEIO):
            # página de bloqueio ou erro: não pode virar referência, senão gera alerta falso depois
            _log(con, f["nome"], "ERRO", "O site devolveu uma página de bloqueio ou vazia; tento de novo amanhã.")
            continue
        h = hashlib.sha256(texto.encode()).hexdigest()
        row = con.execute("SELECT hash FROM fontes_monitoradas WHERE url=?", (f["url"],)).fetchone()
        if row is None:
            con.execute("INSERT INTO fontes_monitoradas (url, nome, hash, verificado_em) VALUES (?,?,?,?)",
                        (f["url"], f["nome"], h, agora))
            _log(con, f["nome"], "OK", "Texto registrado como referência.")
        elif row["hash"] != h:
            con.execute("UPDATE fontes_monitoradas SET hash=?, verificado_em=?, alterado_em=?, pendente_revisao=1 "
                        "WHERE url=?", (h, agora, agora, f["url"]))
            _log(con, f["nome"], "ALTERADA", "O texto oficial mudou desde a última verificação. Revisar as regras.")
            alteradas.append(f["nome"])
        else:
            con.execute("UPDATE fontes_monitoradas SET verificado_em=? WHERE url=?", (agora, f["url"]))
    _log(con, "Fontes oficiais", "OK" if not alteradas else "ALTERADA",
         f"{len(fontes)} fontes verificadas; {len(alteradas)} com alteração.")
    return alteradas


def marcar_revisada(url: str) -> None:
    with db.tx() as con:
        con.execute("UPDATE fontes_monitoradas SET pendente_revisao=0 WHERE url=?", (url,))


def atualizar_tudo() -> dict:
    cfg = configuracoes()
    resultado = {"selic": None, "regras": None, "ncm": None, "fontes_alteradas": [], "erros": []}
    with db.tx() as con:
        for nome, fn in (("selic", lambda: atualizar_selic(con)),
                         ("regras", lambda: atualizar_regras(con, cfg.get("url_regras", "")))):
            try:
                resultado[nome] = fn()
            except Exception as e:
                _log(con, nome, "ERRO", str(e))
                resultado["erros"].append(f"{nome}: {e}")
        try:  # tabela NCM: complemento; falha não marca a atualização como erro
            resultado["ncm"] = atualizar_ncm(con)
        except Exception as e:
            _log(con, "Tabela NCM (Siscomex)", "AVISO", str(e)[:200])
        try:
            resultado["versao"] = verificar_versao(con).get("disponivel")
        except Exception as e:
            _log(con, "Versão do programa", "ERRO", str(e))
        try:
            resultado["fontes_alteradas"] = monitorar_fontes(con)
        except Exception as e:
            resultado["erros"].append(f"fontes: {e}")
        _log(con, "Atualização geral", "OK" if not resultado["erros"] else "ERRO",
             "Concluída" if not resultado["erros"] else "; ".join(resultado["erros"]))
    return resultado


def horas_desde_ultima() -> float | None:
    with db.tx() as con:
        r = con.execute("SELECT max(executado_em) m FROM atualizacoes WHERE fonte='Atualização geral'").fetchone()
    if not r or not r["m"]:
        return None
    ultima = datetime.fromisoformat(r["m"].replace(" ", "T"))
    return (datetime.utcnow() - ultima).total_seconds() / 3600


if __name__ == "__main__":  # usado pela tarefa agendada do Windows
    db.init()
    print(json.dumps(atualizar_tudo(), ensure_ascii=False))
