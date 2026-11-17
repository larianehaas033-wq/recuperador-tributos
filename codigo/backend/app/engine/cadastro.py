"""Cadastro tributário sugerido por produto: CST de PIS/COFINS, CST de ICMS, CSOSN, CST de IBS/CBS, cClassTrib e NBS.

As sugestões saem das mesmas regras legais usadas na recuperação e das provas dos arquivos do cliente
(compras com ST, CST usado pelos fornecedores, cadastro 0200). Cada linha mostra o que o cliente usa hoje e aponta
divergências.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import polars as pl

from ..rules.loader import BaseRegras
from .coerencia import conferir
from .comum import contem, norm
from .icms import _eh_st
from .pis_cofins import MotorPisCofins

TIPO_DESC = {"00": "Revenda", "01": "Matéria-prima", "02": "Embalagem", "03": "Em processo", "04": "Produto acabado",
             "05": "Subproduto", "06": "Intermediário", "07": "Uso e consumo", "08": "Ativo imobilizado",
             "09": "Serviço", "10": "Outros insumos", "99": "Outros"}


def classificar_ibs(base: BaseRegras, ncm: str, descricao: str) -> dict:
    desc = norm(descricao)
    for r in base.ibs.get("regras", []):
        if not ncm or not any(ncm.startswith(p) for p in r["ncm_prefixos"]):
            continue
        if any(ncm.startswith(e) for e in r.get("excecoes", [])):
            continue
        if r.get("_palavras") and not contem(desc, r["_palavras"]):
            continue
        if contem(desc, r.get("_excluir")):
            continue
        return r
    return dict(base.ibs.get("padrao", {}), codigo="IBS_PADRAO", grupo="Tributação integral", observacao="")


def _moda(valores) -> str | None:
    c = Counter(v for v in valores if v)
    return c.most_common(1)[0][0] if c else None


def gerar(base: BaseRegras, empresa: dict, produtos: dict, itens_contrib: pl.DataFrame, entradas_icms: pl.DataFrame,
          xml_itens: pl.DataFrame, revisoes: dict, evidencias: dict, hoje) -> list[dict]:
    motor = MotorPisCofins(base, empresa, itens_contrib, xml_itens.filter(pl.col("ind_oper") == "1"), revisoes, hoje,
                           produtos, evidencias)
    simples = (empresa.get("regime") or "") == "SIMPLES"

    # o que o cliente usa hoje nas vendas, por produto
    uso = defaultdict(lambda: {"cst_pis": [], "cst_icms": [], "cclasstrib": [], "cst_ibscbs": [], "valor": 0.0,
                               "ncm": [], "descricao": []})
    for df in (itens_contrib.filter(pl.col("ind_oper") == "1"), xml_itens.filter(pl.col("ind_oper") == "1")):
        for row in df.iter_rows(named=True):
            u = uso[row["cod_item"]]
            u["cst_pis"].append(row.get("cst_pis") or row.get("cst_cofins"))
            if row.get("origem") == "XML":
                u["cst_icms"].append(row.get("cst_icms"))
                u["cclasstrib"].append(row.get("cclasstrib"))
                u["cst_ibscbs"].append(row.get("cst_ibscbs"))
                u["valor"] += row["vl_item"] - row["vl_desc"]
            elif row.get("origem") in ("C170", "C181"):
                u["valor"] += row["vl_item"] - row["vl_desc"]
            u["ncm"].append(row.get("ncm"))
            u["descricao"].append(row.get("descricao"))

    # prova de ST na compra e origem da mercadoria
    st_cod, origem_cod = set(), defaultdict(list)
    for row in entradas_icms.iter_rows(named=True):
        if _eh_st(row["cst_icms"]):
            st_cod.add(row["cod_item"])
        if row["cst_icms"] and len(row["cst_icms"]) == 3 and row["cst_icms"][0].isdigit():
            origem_cod[row["cod_item"]].append(row["cst_icms"][0])
    st_ncm = {r["ncm"] for r in xml_itens.filter(pl.col("ind_oper") == "0").iter_rows(named=True)
              if _eh_st(r["cst_icms"]) and r["ncm"]}

    codigos = set(produtos) | {k for k in uso if k}
    linhas = []
    for cod in sorted(codigos):
        p = produtos.get(cod, {})
        u = uso.get(cod, {"cst_pis": [], "cst_icms": [], "cclasstrib": [], "cst_ibscbs": [], "valor": 0.0,
                          "ncm": [], "descricao": []})
        ncm_inf = p.get("ncm") or _moda(u["ncm"]) or ""
        desc = p.get("descricao") or _moda(u["descricao"]) or ""
        tipo = (p.get("tipo_item") or "").zfill(2) if p.get("tipo_item") else ""
        ncm_mercadoria = len(ncm_inf) == 8 and ncm_inf.isdigit() and set(ncm_inf) != {"0"}
        servico = (tipo == "09" and not ncm_mercadoria) or (not ncm_inf and tipo in ("", "99"))
        obs, conf, div = [], "ALTA", []
        if tipo == "09" and not servico:
            div.append("Tipo do item 09 (serviço) no 0200, mas o produto tem NCM de mercadoria: corrija para 00")
        cn = conferir(ncm_inf, desc) if not servico else None
        ncm = cn.ncm if cn else ncm_inf
        ncm_grave = bool(cn and cn.grave)
        if cn and cn.alerta:
            obs.append(f"NCM: {cn.alerta}")
            if ncm_grave:
                div.append("NCM incompatível com a descrição: corrigir antes de aplicar o enquadramento")
            elif ncm != ncm_inf:
                div.append(f"NCM {ncm_inf} → {ncm}")
        row = {"ncm": ncm, "descricao": desc, "cod_item": cod, "data": f"{hoje:%Y-%m-%d}", "cfop": "5102"}

        # PIS/COFINS
        mono = base.classificar(ncm, row["data"], "MONOFASICO", desc)
        zero = None if mono else base.classificar(ncm, row["data"], "ALIQ_ZERO", desc)
        regra = mono or zero
        pc_comprovado = True
        if servico:
            cst_pc = "01"
        elif ncm_grave:
            pc_comprovado, conf, regra = False, "BAIXA", None
            cst_pc = "Revisar NCM"
        elif regra:
            c, motivo = motor.verificar(regra, row, "PISCOF_MONO_SAIDA" if mono else "PISCOF_ALIQ_ZERO_SAIDA")
            cst_regra = ("04" if not motor.industrial else "02") if mono else "06"
            if c == "ALTA":
                cst_pc = cst_regra
            elif not regra.exige_descricao and not contem(norm(desc), regra.palavras):
                regra, cst_pc = None, "01"  # depende da destinação e nada indica o uso previsto na lei
            else:
                # não sugere o que não comprovou: mantém o atual e explica a possibilidade
                pc_comprovado = False
                atual = _moda(u["cst_pis"])
                # mantém o atual só se ele for o próprio CST possível ou o tributado; outro CST não tem respaldo
                cst_pc = atual if atual in (cst_regra, "01") else "01"
                conf = "BAIXA"
                if atual and atual != cst_pc:
                    div.append(f"CST PIS/COFINS {atual} → {cst_pc} (confirmar)")
                obs.append(f"PIS/COFINS: pode ser CST {cst_regra} ({regra.grupo}), mas {motivo[0].lower() + motivo[1:]}")
        else:
            cst_pc = "01"
        regra_pc = ("NCM a corrigir" if ncm_grave else
                    (regra.grupo if pc_comprovado else "Não comprovado") if regra else "Tributação normal")
        fund_pc = regra.fundamento if (regra and pc_comprovado) else ""

        # ICMS / CSOSN
        orig = _moda(origem_cod.get(cod, [])) or "0"
        if servico:
            cst_icms, csosn = "—", "—"
        elif cod in st_cod:
            cst_icms, csosn = f"{orig}60", "500"
        elif ncm in st_ncm:
            cst_icms, csosn = f"{orig}60", "500"
            conf = "BAIXA"
            obs.append("ICMS: só o NCM coincide com uma compra com ST; confirme se o produto está na ST da UF.")
        else:
            cst_icms, csosn = f"{orig}00", "102"

        # IBS/CBS
        if servico:
            ibs = dict(base.ibs.get("padrao", {}), codigo="IBS_SERVICO",
                       grupo="Serviço: depende do enquadramento do serviço", observacao="")
        elif ncm_grave:
            ibs = {"codigo": "IBS_REVISAR", "cst": "Revisar NCM", "cclasstrib": "Revisar NCM", "reducao": None,
                   "grupo": "NCM a corrigir", "fundamento": "", "observacao": ""}
        else:
            ibs = classificar_ibs(base, ncm, desc)
        if ibs.get("observacao"):
            obs.append(f"IBS/CBS: {ibs['observacao']}")

        # divergências com o uso atual
        atual_pc = _moda(u["cst_pis"])
        atual_icms = _moda(u["cst_icms"])
        atual_cc = _moda(u["cclasstrib"])
        if atual_pc and atual_pc != cst_pc and not servico and pc_comprovado:
            div.append(f"CST PIS/COFINS {atual_pc} → {cst_pc}")
        if atual_icms and cst_icms != "—":
            if len(atual_icms) == 3 and atual_icms.isdigit() and atual_icms[-2:] != cst_icms[-2:] and not simples:
                div.append(f"CST ICMS {atual_icms} → {cst_icms}")
            elif simples and atual_icms != csosn:
                div.append(f"CSOSN {atual_icms} → {csosn}")
        if atual_cc and atual_cc != ibs["cclasstrib"] and not ncm_grave:
            div.append(f"cClassTrib {atual_cc} → {ibs['cclasstrib']}")

        linhas.append({
            "cod_item": cod, "descricao": desc, "ncm": ncm_inf, "tipo_item": TIPO_DESC.get(tipo, tipo or "—"),
            "valor_vendido": round(u["valor"], 2),
            "atual_cst_pis_cofins": atual_pc, "atual_cst_icms": atual_icms, "atual_cclasstrib": atual_cc,
            "cst_pis_cofins": cst_pc, "grupo_pis_cofins": regra_pc, "fundamento_pis_cofins": fund_pc,
            "cst_icms": cst_icms, "csosn": csosn,
            "cst_ibscbs": ibs["cst"], "cclasstrib": ibs["cclasstrib"], "reducao_ibscbs": ibs["reducao"],
            "grupo_ibscbs": ibs.get("grupo"), "fundamento_ibscbs": ibs["fundamento"],
            "nbs": "Informar pelo serviço (LC 116 → NBS)" if servico else "Não se aplica (mercadoria)",
            "comprovacao": "Revisar NCM" if ncm_grave else conf, "observacao": " ".join(obs), "divergencias": div,
        })
    linhas.sort(key=lambda r: (-len(r["divergencias"]), -r["valor_vendido"]))
    return linhas
