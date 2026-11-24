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
    possivel = None
    for r in base.ibs.get("regras", []):
        if not ncm or not any(ncm.startswith(p) for p in r["ncm_prefixos"]):
            continue
        if any(ncm.startswith(e) for e in r.get("excecoes", [])):
            continue
        if contem(desc, r.get("_excluir")):
            continue
        if r.get("_palavras") and not contem(desc, r["_palavras"]):
            possivel = possivel or r  # o NCM está na lei, mas a descrição não confirma: não é prova de que não está
            continue
        return r
    padrao = dict(base.ibs.get("padrao", {}), codigo="IBS_PADRAO", grupo="Tributação integral", observacao="")
    if possivel:
        padrao["possivel"] = possivel
    return padrao


def _moda(valores) -> str | None:
    c = Counter(v for v in valores if v)
    return c.most_common(1)[0][0] if c else None


def gerar(base: BaseRegras, empresa: dict, produtos: dict, itens_contrib: pl.DataFrame, entradas_icms: pl.DataFrame,
          xml_itens: pl.DataFrame, revisoes: dict, evidencias: dict, hoje) -> list[dict]:
    motor = MotorPisCofins(base, empresa, itens_contrib, xml_itens.filter(pl.col("ind_oper") == "1"), revisoes, hoje,
                           produtos, evidencias)
    simples = (empresa.get("regime") or "").startswith("SIMPLES")

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
        cn = conferir(ncm_inf, desc, base) if not servico else None
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
            atual_p = _moda(u["cst_pis"])
            if atual_p in ("04", "06", "05", "07", "08", "09"):
                # o cliente trata como sem tributação e o NCM não está em lista nenhuma: as fontes discordam
                conf = "BAIXA"
                obs.append(f"PIS/COFINS: o cliente usa CST {atual_p}, mas o NCM {ncm} não está em nenhuma lista legal "
                           "(monofásico, alíquota zero, isenção). Ou o CST está errado (vai para 01), ou o NCM está "
                           "errado (ex.: medicamento cadastrado com NCM de alimento). Confira o NCM antes de mudar.")
        regra_pc = ("NCM a corrigir" if ncm_grave else
                    (regra.grupo if pc_comprovado else "Não comprovado") if regra else "Tributação normal")
        fund_pc = regra.fundamento if (regra and pc_comprovado) else ""

        # ICMS / CSOSN
        orig = _moda(origem_cod.get(cod, [])) or "0"
        uf = (empresa.get("uf") or "").upper()
        dia = f"{hoje:%Y-%m-%d}"
        lei_st = base._tem_lista_st(uf, dia) if ncm else False
        item_st = base.na_st(uf, ncm, dia, desc) if lei_st else None
        if servico:
            cst_icms, csosn = "—", "—"
        elif lei_st and item_st:
            # a lei põe o produto na ST da UF (lista oficial): CST 60 na revenda, com ou sem compra com ST no período
            cst_icms, csosn = f"{orig}60", "500"
            obs.append(f"ICMS: na ST de {uf} (Anexo 1-A, CEST {item_st.get('cest', '')}).")
        elif lei_st and base._candidatos_st(uf, ncm, dia) and (_moda(u["cst_icms"]) or "")[-2:] == "60":
            # o NCM tem item na lista de ST, a descrição não confirmou qual, e o cliente usa ST: não conclui
            cst_icms, csosn = f"{orig}60", "500"
            conf = "BAIXA"
            itens = "; ".join(f"CEST {c['cest']} {c['descricao'][:30]}" for c in base._candidatos_st(uf, ncm, dia)[:2])
            obs.append(f"ICMS: o NCM {ncm} tem produtos na ST de {uf} ({itens}), mas a descrição não permitiu "
                       "confirmar que é um deles. Mantido CST 60 para conferir.")
        elif lei_st and (cod in st_cod or ncm in st_ncm):
            # comprou com ST, mas o produto não está na lista de ST da UF: a venda é tributada normalmente
            cst_icms, csosn = f"{orig}00", "102"
            obs.append(f"ICMS: comprado com ST, mas o produto não está na lista de ST de {uf} na data "
                       "(RICMS/SC, Anexo 1-A): a venda é tributada.")
        elif cod in st_cod:
            cst_icms, csosn = f"{orig}60", "500"
        elif ncm in st_ncm:
            cst_icms, csosn = f"{orig}60", "500"
            conf = "BAIXA"
            obs.append("ICMS: só o NCM coincide com uma compra com ST; confirme se o produto está na ST da UF.")
        else:
            cst_icms, csosn = f"{orig}00", "102"
            atual_i = _moda(u["cst_icms"]) or ""
            if (not simples and len(atual_i) == 3 and atual_i.isdigit()
                    and atual_i[-2:] in ("20", "30", "40", "41", "50", "51", "90")
                    and not base.icms_beneficios_uf(empresa.get("uf"))):
                # o cliente aplica isenção/redução/suspensão e a base ainda não tem os benefícios da UF:
                # sem a lei, não há como dizer que está errado — mantém e manda conferir
                cst_icms = f"{orig}{atual_i[-2:]}"
                conf = "BAIXA"
                obs.append(f"ICMS: o cliente usa CST {atual_i} (isenção, redução de base, suspensão ou outras). Os "
                           f"benefícios do RICMS/{empresa.get('uf') or 'UF'} (Anexo 2) ainda não estão na base do "
                           "programa: mantido para o contador conferir (ex.: preservativos e medicamentos "
                           "oncológicos têm isenção por convênio).")

        # IBS/CBS
        if servico:
            ibs = dict(base.ibs.get("padrao", {}), codigo="IBS_SERVICO",
                       grupo="Serviço: depende do enquadramento do serviço", observacao="")
        elif ncm_grave:
            ibs = {"codigo": "IBS_REVISAR", "cst": "Revisar NCM", "cclasstrib": "Revisar NCM", "reducao": None,
                   "grupo": "NCM a corrigir", "fundamento": "", "observacao": ""}
        else:
            ibs = classificar_ibs(base, ncm, desc)
        if ibs.get("possivel"):
            pos = ibs["possivel"]
            if _moda(u["cclasstrib"]) == pos["cclasstrib"]:
                # o cliente já usa o enquadramento possível e nada o desmente: mantém, para o contador confirmar
                ibs = dict(pos, observacao="")
                conf = "BAIXA"
            obs.append(f"IBS/CBS: pode ser {pos['grupo']} (cClassTrib {pos['cclasstrib']}); a descrição não permitiu "
                       "confirmar o produto — conferir.")
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
