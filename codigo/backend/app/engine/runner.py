"""Executa uma análise completa para uma empresa e grava os créditos identificados."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime

import polars as pl

from .. import db
from ..rules.loader import carregar
from .comum import (NUM_COLS, Credito, data_corte, data_pagamento, fator_selic, prescrito_credito,
                    prescrito_restituicao, r2, to_frame)
from .icms import MotorIcms
from .pis_cofins import MotorPisCofins

ITEM_SELECT_EXTRA = ["cst_ibscbs", "cclasstrib"]
ITEM_SELECT = ["origem", "periodo", "data", "chave", "num_doc", "ind_oper", "cnpj_part", "num_item", "cod_item",
               "descricao", "ncm", "cfop", "unidade", "qtd", "vl_item", "vl_desc", "cst_icms", "vl_bc_icms",
               "aliq_icms", "vl_icms", "vl_bc_icms_st", "vl_icms_st", "vl_ipi", "cst_pis", "vl_bc_pis", "aliq_pis",
               "vl_pis", "cst_cofins", "vl_bc_cofins", "aliq_cofins", "vl_cofins"]

CRED_COLS = ["analise_id", "modulo", "tese", "tributo", "periodo", "data", "chave", "num_doc", "cod_item",
             "descricao", "ncm", "cfop", "cst_escriturado", "cst_correto", "base_original", "base_correta",
             "valor_pago", "valor_recuperar", "valor_restituivel", "valor_saldo_credor", "valor_corrigido",
             "natureza", "via", "fundamento", "confianca", "regra_codigo", "prescrito", "excluido", "observacao"]


def _itens(con, empresa_id: int, tipo_arquivo: str, extra: str = "", params=()) -> pl.DataFrame:
    cols = ", ".join(f"i.{c}" for c in ITEM_SELECT + ITEM_SELECT_EXTRA)
    sql = (f"SELECT {cols}, n.modelo AS modelo FROM itens_nota i JOIN arquivos_sped a ON a.id = i.arquivo_id "
           f"LEFT JOIN notas_fiscais n ON n.id = i.nota_id "
           f"WHERE i.empresa_id = ? AND a.tipo = ? AND COALESCE(n.cancelada, 0) = 0 {extra}")
    rows = con.execute(sql, (empresa_id, tipo_arquivo, *params)).fetchall()
    df = to_frame(rows, ITEM_SELECT + ITEM_SELECT_EXTRA + ["modelo"])
    return df.with_row_index("rid")


def _notas(con, empresa_id: int, origem: str) -> pl.DataFrame:
    rows = con.execute(
        "SELECT chave, numero, data, periodo, ind_oper, ind_emit, cnpj_emit, cancelada, vl_doc, vl_icms "
        "FROM notas_fiscais WHERE empresa_id=? AND origem=?", (empresa_id, origem)).fetchall()
    schema = {"chave": pl.Utf8, "numero": pl.Utf8, "data": pl.Utf8, "periodo": pl.Utf8, "ind_oper": pl.Utf8,
              "ind_emit": pl.Utf8, "cnpj_emit": pl.Utf8, "cancelada": pl.Int64, "vl_doc": pl.Float64,
              "vl_icms": pl.Float64}
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame([tuple(r) for r in rows], schema=schema, orient="row").with_columns(
        pl.col("vl_doc").fill_null(0.0), pl.col("vl_icms").fill_null(0.0), pl.col("cancelada").fill_null(0))


def _produtos(con, empresa_id: int) -> dict:
    """Cadastro 0200. Se a empresa foi importada por uma versão anterior (sem a tabela), relê os arquivos."""
    rows = con.execute("SELECT cod_item, descricao, ncm, tipo_item FROM produtos WHERE empresa_id=?",
                       (empresa_id,)).fetchall()
    if not rows:
        from pathlib import Path

        from ..importador import gravar_produtos
        from ..parsers.sped_common import campo, iter_registros, only_digits
        for a in con.execute("SELECT caminho FROM arquivos_sped WHERE empresa_id=? AND tipo LIKE 'EFD%'", (empresa_id,)):
            p = Path(a["caminho"] or "")
            if not p.is_file():
                continue
            prods = {}
            for f in iter_registros(p):
                reg = campo(f, 1)
                if reg == "0200":
                    prods[campo(f, 2)] = dict(descricao=campo(f, 3), unidade=campo(f, 6), tipo=campo(f, 7),
                                              ncm=only_digits(campo(f, 8)))
                elif reg and reg[0] in "ACDEFHKM19" and reg not in ("0000",):
                    break
            gravar_produtos(con, empresa_id, prods)
        rows = con.execute("SELECT cod_item, descricao, ncm, tipo_item FROM produtos WHERE empresa_id=?",
                           (empresa_id,)).fetchall()
    return {r["cod_item"]: dict(r) for r in rows}


def _aplicar_limites(creditos: list[Credito], apuracoes: dict, selic: dict, hoje: date, avisos: list) -> None:
    """Divide cada valor entre restituível (vira dinheiro/compensação, corrigido pela Selic) e saldo credor.

    PIS/COFINS: por competência, o que reduz a contribuição devida só vira restituição até o valor
    efetivamente recolhido (M200/M600 campo 13). Débito indevido é alocado antes dos créditos extemporâneos.
    ICMS: a restituição é tratada pelo valor apurado (cada UF tem rito próprio); créditos de entrada ficam
    como crédito a lançar.
    """
    grupos: dict[tuple, list[Credito]] = defaultdict(list)
    sem_apuracao = set()
    for c in creditos:
        if c.natureza == "RISCO":
            continue
        if c.prescrito or c.excluido:
            c.valor_restituivel = c.valor_saldo_credor = c.valor_corrigido = 0.0
            continue
        if c.tributo in ("PIS", "COFINS"):
            grupos[(c.tributo, c.periodo)].append(c)
        elif c.natureza == "RESTITUICAO":
            c.valor_restituivel = c.valor_recuperar
        else:
            c.valor_saldo_credor = c.valor_recuperar

    for (trib, per), lista in grupos.items():
        recolhido = apuracoes.get((per, trib))
        lista.sort(key=lambda c: 0 if c.natureza == "RESTITUICAO" else 1)
        if recolhido is None:
            sem_apuracao.add(per)
            for c in lista:
                if c.natureza == "RESTITUICAO":
                    c.valor_restituivel = c.valor_recuperar
                else:
                    c.valor_saldo_credor = c.valor_recuperar
                c.observacao = (c.observacao + " Limite do valor recolhido não verificado (sem M200/M600).").strip()
            continue
        disponivel = recolhido
        for c in lista:
            parte = min(c.valor_recuperar, max(disponivel, 0.0))
            c.valor_restituivel = r2(parte)
            c.valor_saldo_credor = r2(c.valor_recuperar - parte)
            disponivel -= parte

    for c in creditos:
        if c.valor_restituivel > 0:
            pag = data_pagamento(c.periodo) if c.tributo in ("PIS", "COFINS") else data_pagamento(c.periodo)
            f = fator_selic(pag, hoje, selic)
            c.valor_corrigido = r2(c.valor_restituivel * (1 + f / 100)) if f is not None else c.valor_restituivel
        elif c.natureza != "RISCO":
            c.valor_corrigido = 0.0
    if sem_apuracao:
        avisos.append("Competências sem apuração (M200/M600) importada: " + ", ".join(sorted(sem_apuracao))
                      + ". O limite do valor recolhido não foi aplicado nelas.")


def _resumo(creditos: list[Credito], base) -> dict:
    validos = [c for c in creditos if not c.prescrito and not c.excluido]

    def soma(f, campo="valor_corrigido"):
        return r2(sum(getattr(c, campo) for c in validos if f(c)))

    # Totais principais: só o que foi comprovado automaticamente (ou confirmado). O resto fica "a verificar".
    ok = lambda c: c.natureza != "RISCO" and c.confianca == "ALTA"  # noqa: E731
    ver = lambda c: c.natureza != "RISCO" and c.confianca != "ALTA"  # noqa: E731
    por_tese = defaultdict(lambda: {"qtd": 0, "restituivel": 0.0, "corrigido": 0.0, "saldo_credor": 0.0,
                                    "risco": 0.0, "baixa": 0.0})
    for c in validos:
        t = por_tese[c.tese]
        t["qtd"] += 1
        if c.natureza == "RISCO":
            t["risco"] += c.valor_recuperar
        elif c.confianca != "ALTA":
            t["baixa"] += c.valor_corrigido + c.valor_saldo_credor
        else:
            t["restituivel"] += c.valor_restituivel
            t["corrigido"] += c.valor_corrigido
            t["saldo_credor"] += c.valor_saldo_credor
    teses = []
    for k, v in por_tese.items():
        info = base.teses.get(k, {})
        teses.append({"tese": k, "nome": info.get("nome", k), "via": info.get("via"), "natureza": info.get("natureza"),
                      **{kk: (r2(vv) if isinstance(vv, float) else vv) for kk, vv in v.items()}})
    teses.sort(key=lambda t: -(t["corrigido"] + t["saldo_credor"] + t["risco"] + t["baixa"]))

    por_periodo = defaultdict(lambda: {"PIS": 0.0, "COFINS": 0.0, "ICMS": 0.0})
    for c in validos:
        if ok(c) and c.periodo:
            por_periodo[c.periodo][c.tributo] += c.valor_corrigido + c.valor_saldo_credor
    serie = [{"periodo": p, **{k: r2(v) for k, v in d.items()}} for p, d in sorted(por_periodo.items())]

    return {
        "total_corrigido": soma(ok),
        "total_restituivel": soma(ok, "valor_restituivel"),
        "total_saldo_credor": soma(ok, "valor_saldo_credor"),
        "por_tributo": {t: r2(sum(c.valor_corrigido + c.valor_saldo_credor for c in validos
                                  if ok(c) and c.tributo == t)) for t in ("PIS", "COFINS", "ICMS")},
        "a_verificar": r2(sum(c.valor_corrigido + c.valor_saldo_credor for c in validos if ver(c))),
        "riscos": r2(sum(c.valor_recuperar for c in validos if c.natureza == "RISCO")),
        "prescrito": r2(sum(c.valor_recuperar for c in creditos if c.prescrito and c.natureza != "RISCO")),
        "qtd_itens": len(validos),
        "teses": teses,
        "serie": serie,
    }


def executar_analise(empresa_id: int, hoje: date | None = None, progress=None, analise_id: int | None = None) -> int:
    hoje = hoje or date.today()
    base = carregar()
    avisos: list[str] = []

    with db.tx() as con:
        empresa = dict(con.execute("SELECT * FROM empresas WHERE id=?", (empresa_id,)).fetchone())
        revisoes = {(r["ncm"], r["tese"]): r["decisao"]
                    for r in con.execute("SELECT ncm, tese, decisao FROM revisoes_ncm WHERE empresa_id=?", (empresa_id,))}
        if progress:
            progress("Carregando dados", 0.1)
        itens_contrib = _itens(con, empresa_id, "EFD_CONTRIB")
        entradas_icms = _itens(con, empresa_id, "EFD_ICMS_IPI", "AND i.ind_oper='0'")
        xml_itens = _itens(con, empresa_id, "XML_NFE")
        sped_notas = _notas(con, empresa_id, "SPED_ICMS")
        xml_notas = _notas(con, empresa_id, "XML")
        periodos_icms = {r["p"] for r in con.execute(
            "SELECT substr(periodo_ini,1,7) p FROM arquivos_sped WHERE empresa_id=? AND tipo='EFD_ICMS_IPI'",
            (empresa_id,))}
        apuracoes = {(r["periodo"], r["tributo"]): r["valor_recolher"] for r in con.execute(
            "SELECT periodo, tributo, valor_recolher FROM apuracoes WHERE empresa_id=?", (empresa_id,))}
        selic = {r["competencia"]: r["taxa"] for r in con.execute("SELECT competencia, taxa FROM selic")}
        produtos = _produtos(con, empresa_id)
        ultima_atual = con.execute(
            "SELECT max(executado_em) m FROM atualizacoes WHERE status IN ('OK','SEM_MUDANCA','ALTERADA')").fetchone()["m"]
        pendentes = [r["nome"] for r in con.execute("SELECT nome FROM fontes_monitoradas WHERE pendente_revisao=1")]
        if analise_id is None:
            cur = con.execute("INSERT INTO analises (empresa_id, status) VALUES (?, 'PROCESSANDO')", (empresa_id,))
            analise_id = cur.lastrowid
        else:
            con.execute("DELETE FROM creditos_identificados WHERE analise_id=?", (analise_id,))

    if not itens_contrib.height and not xml_itens.height and not entradas_icms.height:
        avisos.append("Nenhum dado importado para esta empresa.")
    if not empresa.get("regime"):
        avisos.append("Regime de PIS/COFINS não identificado (falta EFD-Contribuições): créditos de entrada não analisados.")
    elif empresa["regime"] == "LUCRO_PRESUMIDO":
        avisos.append("Empresa no regime cumulativo: crédito de entradas não se aplica.")
    if not selic:
        avisos.append("Tabela Selic não carregada: valores sem correção. Use 'Atualizar base' com internet.")
    if pendentes:
        avisos.append("Fontes oficiais alteradas e ainda não revisadas: " + "; ".join(pendentes)
                      + ". Confira se a mudança afeta as regras antes de entregar o relatório.")

    xml_saidas = xml_itens.filter(pl.col("ind_oper") == "1")
    xml_entradas = xml_itens.filter(pl.col("ind_oper") == "0")
    evidencias = {
        "MONOFASICO": set(xml_entradas.filter(pl.col("cst_pis").is_in(["02", "04"]))["ncm"].drop_nulls().to_list()),
        "ALIQ_ZERO": set(xml_entradas.filter(pl.col("cst_pis") == "06")["ncm"].drop_nulls().to_list()),
    }
    if not produtos:
        avisos.append("Cadastro de produtos (registro 0200) não disponível: a destinação das compras não pôde ser "
                      "comprovada. Reimporte os arquivos SPED.")
    if progress:
        progress("Analisando PIS/COFINS", 0.35)
    creditos, consolidados = MotorPisCofins(base, empresa, itens_contrib, xml_saidas, revisoes, hoje, produtos,
                                            evidencias).executar()
    if consolidados and not xml_saidas.height:
        avisos.append("EFD-Contribuições consolidada (C180/C181) em " + ", ".join(sorted(consolidados))
                      + " sem XMLs de venda: a exclusão do ICMS da base não pôde ser verificada nesses meses.")
    if progress:
        progress("Analisando ICMS e cruzamentos", 0.6)
    cred_icms, av_icms = MotorIcms(base, empresa, entradas_icms, xml_itens, sped_notas, xml_notas, periodos_icms,
                                   revisoes, hoje, produtos).executar()
    creditos += cred_icms
    avisos += av_icms

    for c in creditos:
        if c.natureza == "RESTITUICAO":
            c.prescrito = int(prescrito_restituicao(c.periodo, hoje))
        elif c.natureza == "CREDITO_EXTEMPORANEO":
            c.prescrito = int(prescrito_credito(c.data, hoje))
        if c.periodo and c.periodo >= "2027-01" and c.tributo in ("PIS", "COFINS"):
            c.excluido = 1
            c.observacao += " PIS/COFINS extintos a partir de 2027 (LC 214/2025)."

    _aplicar_limites(creditos, apuracoes, selic, hoje, avisos)
    resumo = _resumo(creditos, base)
    periodos = sorted({c.periodo for c in creditos if c.periodo})

    if progress:
        progress("Gravando resultado", 0.85)
    with db.tx() as con:
        con.executemany(
            f"INSERT INTO creditos_identificados ({','.join(CRED_COLS)}) VALUES ({','.join('?' * len(CRED_COLS))})",
            [[analise_id if k == "analise_id" else c.dict()[k] for k in CRED_COLS] for c in creditos],
        )
        con.execute(
            "UPDATE analises SET status='CONCLUIDA', periodo_ini=?, periodo_fim=?, versao_regras=?, "
            "base_atualizada_em=?, selic_ate=?, data_corte_prescricao=?, resumo_json=?, avisos_json=?, criado_em=? "
            "WHERE id=?",
            (periodos[0] if periodos else None, periodos[-1] if periodos else None,
             f"{base.versao} ({base.origem})", ultima_atual, max(selic) if selic else None,
             data_corte(hoje).isoformat(), json.dumps(resumo, ensure_ascii=False),
             json.dumps(avisos, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), analise_id),
        )
    return analise_id


def recalcular(analise_id: int, hoje: date | None = None) -> int:
    with db.tx() as con:
        emp = con.execute("SELECT empresa_id FROM analises WHERE id=?", (analise_id,)).fetchone()["empresa_id"]
    return executar_analise(emp, hoje=hoje, analise_id=analise_id)


def gerar_cadastro(empresa_id: int, hoje: date | None = None) -> list[dict]:
    from .cadastro import gerar
    hoje = hoje or date.today()
    base = carregar()
    with db.tx() as con:
        empresa = dict(con.execute("SELECT * FROM empresas WHERE id=?", (empresa_id,)).fetchone())
        revisoes = {(r["ncm"], r["tese"]): r["decisao"]
                    for r in con.execute("SELECT ncm, tese, decisao FROM revisoes_ncm WHERE empresa_id=?", (empresa_id,))}
        itens_contrib = _itens(con, empresa_id, "EFD_CONTRIB")
        entradas_icms = _itens(con, empresa_id, "EFD_ICMS_IPI", "AND i.ind_oper='0'")
        xml_itens = _itens(con, empresa_id, "XML_NFE")
        produtos = _produtos(con, empresa_id)
    xml_entradas = xml_itens.filter(pl.col("ind_oper") == "0")
    evidencias = {
        "MONOFASICO": set(xml_entradas.filter(pl.col("cst_pis").is_in(["02", "04"]))["ncm"].drop_nulls().to_list()),
        "ALIQ_ZERO": set(xml_entradas.filter(pl.col("cst_pis") == "06")["ncm"].drop_nulls().to_list()),
    }
    return gerar(base, empresa, produtos, itens_contrib, entradas_icms, xml_itens, revisoes, evidencias, hoje)


__all__ = ["gerar_cadastro", "executar_analise", "recalcular", "NUM_COLS"]
