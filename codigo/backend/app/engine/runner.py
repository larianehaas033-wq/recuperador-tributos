"""Executa uma análise completa para uma empresa e grava os créditos identificados."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

import polars as pl

from .. import db
from ..rules.loader import carregar
from .comum import (NUM_COLS, ZERO, Credito, D, data_corte, data_pagamento, fator_selic, prescrito_credito,
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
            c.valor_restituivel = c.valor_saldo_credor = c.valor_corrigido = ZERO
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
        disponivel = D(recolhido)
        for c in lista:
            parte = min(c.valor_recuperar, max(disponivel, ZERO))
            c.valor_restituivel = r2(parte)
            c.valor_saldo_credor = r2(c.valor_recuperar - parte)
            disponivel -= parte

    for c in creditos:
        if c.valor_restituivel > 0:
            pag = data_pagamento(c.periodo) if c.tributo in ("PIS", "COFINS") else data_pagamento(c.periodo)
            f = fator_selic(pag, hoje, selic)
            c.valor_corrigido = r2(c.valor_restituivel * (1 + f / 100)) if f is not None else c.valor_restituivel
        elif c.natureza != "RISCO":
            c.valor_corrigido = ZERO
    if sem_apuracao:
        avisos.append("Competências sem apuração (M200/M600) importada: " + ", ".join(sorted(sem_apuracao))
                      + ". O limite do valor recolhido não foi aplicado nelas.")


NOME_REGIME = {"LUCRO_REAL": "Lucro Real (não cumulativo)", "LUCRO_PRESUMIDO": "Lucro Presumido (cumulativo)",
               "MISTO": "Lucro Real com receitas cumulativas e não cumulativas", "SIMPLES_NACIONAL": "Simples Nacional"}


def _preencher_regime_antigo(con, empresa_id: int) -> None:
    """Arquivos importados antes da 1.4.1 não guardaram o regime do mês: relê o registro 0110 do arquivo original,
    se ele ainda estiver no mesmo lugar."""
    from pathlib import Path

    from ..importador import REGIME
    try:
        pend = con.execute("SELECT id, caminho FROM arquivos_sped WHERE empresa_id=? AND tipo='EFD_CONTRIB' "
                           "AND regime IS NULL", (empresa_id,)).fetchall()
    except Exception:
        return
    for r in pend:
        try:
            with open(Path(r["caminho"]), encoding="latin-1", errors="ignore") as f:
                for i, linha in enumerate(f):
                    if linha.startswith("|0110|"):
                        reg = REGIME.get(linha.split("|")[2])
                        if reg:
                            con.execute("UPDATE arquivos_sped SET regime=? WHERE id=?", (reg, r["id"]))
                        break
                    if i > 200:
                        break
        except (OSError, TypeError):
            continue


def regimes_por_periodo(con, empresa_id: int) -> tuple[dict, list[str]]:
    """Regime de cada competência. Fonte principal: registro 0110 da EFD-Contribuições do mês. Sem ela, o CRT das
    notas emitidas pela empresa (1, 2 ou 4 = Simples Nacional). Avisa mudança de regime e informação conflitante."""
    regimes, avisos = {}, []
    _preencher_regime_antigo(con, empresa_id)
    # arquivos importados antes da versão 1.4.1 não guardaram o regime: vale o da empresa (lido do 0110 na época)
    for r in con.execute("SELECT substr(a.periodo_ini,1,7) p, coalesce(a.regime, e.regime) regime FROM arquivos_sped a "
                         "JOIN empresas e ON e.id = a.empresa_id WHERE a.empresa_id=? AND a.tipo='EFD_CONTRIB'",
                         (empresa_id,)):
        if r["regime"]:
            regimes[r["p"]] = r["regime"]
    crt = defaultdict(set)
    for r in con.execute("SELECT periodo, crt_emit FROM notas_fiscais WHERE empresa_id=? AND origem='XML' "
                         "AND ind_emit='0' AND crt_emit IS NOT NULL", (empresa_id,)):
        crt[r["periodo"]].add("SIMPLES_NACIONAL" if r["crt_emit"] in ("1", "2", "4") else "NORMAL")
    conflito = []
    for per, tipos in crt.items():
        if per in regimes:
            if "SIMPLES_NACIONAL" in tipos and regimes[per] != "SIMPLES_NACIONAL":
                conflito.append(per)
        elif tipos == {"SIMPLES_NACIONAL"}:
            regimes[per] = "SIMPLES_NACIONAL"
    if not regimes:
        avisos.append("REGIME NÃO IDENTIFICADO: importe a EFD-Contribuições (registro 0110) ou os XMLs emitidos pela "
                      "empresa. Sem o regime, as teses de PIS/COFINS não são calculadas; só as de ICMS.")
        return regimes, avisos
    faixas, atual = [], None
    for per in sorted(regimes):
        if atual and atual[0] == regimes[per]:
            atual[2] = per
        else:
            atual = [regimes[per], per, per]
            faixas.append(atual)
    texto = "; ".join(f"{NOME_REGIME.get(r, r)} de {a[5:]}/{a[:4]} a {b[5:]}/{b[:4]}" for r, a, b in faixas)
    avisos.append(("Regime identificado por competência: " if len(faixas) > 1 else "Regime identificado: ") + texto
                  + (". Cada competência foi analisada pelas regras do seu regime." if len(faixas) > 1 else "."))
    if any(r == "LUCRO_PRESUMIDO" for r in regimes.values()):
        avisos.append("Nas competências do regime cumulativo não há crédito de entradas (Lei 10.637/2002, art. 8º, e "
                      "Lei 10.833/2003, art. 10).")
    if conflito:
        avisos.append("ATENÇÃO: nas competências " + ", ".join(sorted(conflito)) + " a EFD-Contribuições indica "
                      "regime normal, mas as notas emitidas trazem CRT do Simples Nacional. Confirme o regime antes "
                      "de entregar o relatório.")
    return regimes, avisos


def _json_num(o):
    """Decimal no JSON do resumo: o texto do número é o mesmo (centavos exatos)."""
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError(type(o))


def _resumo(creditos: list[Credito], base) -> dict:
    validos = [c for c in creditos if not c.prescrito and not c.excluido]

    def soma(f, campo="valor_corrigido"):
        return r2(sum(getattr(c, campo) for c in validos if f(c)))

    # Totais principais: só o que foi comprovado automaticamente (ou confirmado). O resto fica "a verificar".
    ok = lambda c: c.natureza != "RISCO" and c.confianca == "ALTA"  # noqa: E731
    ver = lambda c: c.natureza != "RISCO" and c.confianca != "ALTA"  # noqa: E731
    por_tese = defaultdict(lambda: {"qtd": 0, "restituivel": ZERO, "corrigido": ZERO, "saldo_credor": ZERO,
                                    "risco": ZERO, "baixa": ZERO})
    for c in validos:
        t = por_tese[c.tese]
        t["qtd"] += 1
        if c.natureza == "RISCO":
            if c.confianca == "ALTA":
                t["risco"] += c.valor_recuperar
            else:
                t["baixa"] += c.valor_recuperar
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
                      **{kk: (r2(vv) if isinstance(vv, Decimal) else vv) for kk, vv in v.items()}})
    teses.sort(key=lambda t: -(t["corrigido"] + t["saldo_credor"] + t["risco"] + t["baixa"]))

    por_periodo = defaultdict(lambda: {"PIS": ZERO, "COFINS": ZERO, "ICMS": ZERO})
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
        "riscos": r2(sum(c.valor_recuperar for c in validos if c.natureza == "RISCO" and c.confianca == "ALTA")),
        "riscos_a_verificar": r2(sum(c.valor_recuperar for c in validos
                                     if c.natureza == "RISCO" and c.confianca != "ALTA")),
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
        regimes, avisos_regime = regimes_por_periodo(con, empresa_id)
        empresa["regimes"] = regimes
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
    avisos += avisos_regime
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
    if regimes:
        creditos, consolidados = MotorPisCofins(base, empresa, itens_contrib, xml_saidas, revisoes, hoje, produtos,
                                                evidencias).executar()
    else:  # sem regime não há como saber quais regras de PIS/COFINS valem: nada é calculado
        creditos, consolidados = [], set()
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
             data_corte(hoje).isoformat(), json.dumps(resumo, ensure_ascii=False, default=_json_num),
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
        regimes, avisos_regime = regimes_por_periodo(con, empresa_id)
        empresa["regimes"] = regimes
    xml_entradas = xml_itens.filter(pl.col("ind_oper") == "0")
    evidencias = {
        "MONOFASICO": set(xml_entradas.filter(pl.col("cst_pis").is_in(["02", "04"]))["ncm"].drop_nulls().to_list()),
        "ALIQ_ZERO": set(xml_entradas.filter(pl.col("cst_pis") == "06")["ncm"].drop_nulls().to_list()),
    }
    return gerar(base, empresa, produtos, itens_contrib, entradas_icms, xml_itens, revisoes, evidencias, hoje)


__all__ = ["gerar_cadastro", "executar_analise", "recalcular", "NUM_COLS"]
