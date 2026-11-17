"""Parser da EFD-Contribuições e da EFD ICMS/IPI (SPED Fiscal).

Leiautes conforme os Guias Práticos da RFB. Registros lidos:

EFD-Contribuições: 0000, 0110, 0140, 0150, 0200, C010, C100, C170, C180, C181,
C185, C190, C191, C195, M200, M600.
EFD ICMS/IPI:      0000, 0150, 0200, C100, C170, C190, E110, H010.

O resultado é uma estrutura neutra (dicionários) que o importador grava no banco.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .sped_common import campo, data_iso, iter_registros, num, only_digits, periodo


@dataclass
class EfdResultado:
    tipo: str
    cnpj: str = ""
    nome: str = ""
    uf: str = ""
    dt_ini: str | None = None
    dt_fin: str | None = None
    finalidade: str = "original"
    ind_ativ: str = ""
    regime_pis_cofins: str = ""       # 1 não cumulativo, 2 cumulativo, 3 ambos (0110)
    participantes: dict = field(default_factory=dict)   # COD_PART -> CNPJ/CPF
    produtos: dict = field(default_factory=dict)        # COD_ITEM -> {descricao, ncm, unidade, tipo}
    notas: list = field(default_factory=list)
    itens: list = field(default_factory=list)
    apuracoes: list = field(default_factory=list)
    inventario: list = field(default_factory=list)
    registros: int = 0
    avisos: list = field(default_factory=list)


def _item_base(**kw) -> dict:
    base = dict(
        origem=None, periodo=None, data=None, chave=None, num_doc=None, ind_oper=None, cnpj_part=None,
        num_item=None, cod_item=None, descricao=None, ncm=None, cfop=None, unidade=None, qtd=0.0,
        vl_item=0.0, vl_desc=0.0, cst_icms=None, vl_bc_icms=0.0, aliq_icms=0.0, vl_icms=0.0,
        vl_bc_icms_st=0.0, vl_icms_st=0.0, vl_ipi=0.0, cst_pis=None, vl_bc_pis=0.0, aliq_pis=0.0,
        vl_pis=0.0, cst_cofins=None, vl_bc_cofins=0.0, aliq_cofins=0.0, vl_cofins=0.0, _nota=None,
    )
    base.update(kw)
    return base


def _c100(f: list[str], participantes: dict, origem: str) -> dict:
    dt = data_iso(campo(f, 10)) or data_iso(campo(f, 11))
    cod_sit = campo(f, 6)
    return dict(
        origem=origem,
        ind_oper=campo(f, 2),
        ind_emit=campo(f, 3),
        cod_part=campo(f, 4),
        cnpj_part=participantes.get(campo(f, 4), ""),
        modelo=campo(f, 5),
        cod_sit=cod_sit,
        cancelada=1 if cod_sit in ("02", "03", "04", "05") else 0,
        serie=campo(f, 7),
        numero=campo(f, 8),
        chave=only_digits(campo(f, 9)) or None,
        data=dt,
        periodo=periodo(dt),
        vl_doc=num(campo(f, 12)),
        vl_icms=num(campo(f, 22)),
        vl_icms_st=num(campo(f, 24)),
        vl_pis=num(campo(f, 26)),
        vl_cofins=num(campo(f, 27)),
        _idx=None,
    )


def _c170(f: list[str], nota: dict, produtos: dict, origem: str) -> dict:
    cod_item = campo(f, 3)
    prod = produtos.get(cod_item, {})
    return _item_base(
        origem=origem,
        periodo=nota["periodo"],
        data=nota["data"],
        chave=nota["chave"],
        num_doc=nota["numero"],
        ind_oper=nota["ind_oper"],
        cnpj_part=nota["cnpj_part"],
        num_item=campo(f, 2),
        cod_item=cod_item,
        descricao=prod.get("descricao") or campo(f, 4),
        ncm=prod.get("ncm"),
        cfop=campo(f, 11),
        unidade=campo(f, 6),
        qtd=num(campo(f, 5)),
        vl_item=num(campo(f, 7)),
        vl_desc=num(campo(f, 8)),
        cst_icms=campo(f, 10),
        vl_bc_icms=num(campo(f, 13)),
        aliq_icms=num(campo(f, 14)),
        vl_icms=num(campo(f, 15)),
        vl_bc_icms_st=num(campo(f, 16)),
        vl_icms_st=num(campo(f, 18)),
        vl_ipi=num(campo(f, 24)),
        cst_pis=campo(f, 25) or None,
        vl_bc_pis=num(campo(f, 26)),
        aliq_pis=num(campo(f, 27)),
        vl_pis=num(campo(f, 30)),
        cst_cofins=campo(f, 31) or None,
        vl_bc_cofins=num(campo(f, 32)),
        aliq_cofins=num(campo(f, 33)),
        vl_cofins=num(campo(f, 36)),
        _nota=nota.get("_idx"),
    )


def parse_efd(path: Path, tipo: str) -> EfdResultado:
    r = EfdResultado(tipo=tipo)
    origem_doc = "SPED_CONTRIB" if tipo == "EFD_CONTRIB" else "SPED_ICMS"
    nota_atual: dict | None = None
    consolidado: dict | None = None
    cnpj_estab = ""

    for f in iter_registros(path):
        r.registros += 1
        reg = campo(f, 1)

        if reg == "0000":
            if tipo == "EFD_CONTRIB":
                r.finalidade = "retificadora" if campo(f, 3) == "1" else "original"
                r.dt_ini, r.dt_fin = data_iso(campo(f, 6)), data_iso(campo(f, 7))
                r.nome, r.cnpj, r.uf = campo(f, 8), only_digits(campo(f, 9)), campo(f, 10)
                r.ind_ativ = campo(f, 14)
            else:
                r.finalidade = "retificadora" if campo(f, 3) == "1" else "original"
                r.dt_ini, r.dt_fin = data_iso(campo(f, 4)), data_iso(campo(f, 5))
                r.nome, r.cnpj, r.uf = campo(f, 6), only_digits(campo(f, 7)), campo(f, 9)
                r.ind_ativ = "0" if campo(f, 15) == "0" else "2"
            cnpj_estab = r.cnpj
        elif reg == "0110" and tipo == "EFD_CONTRIB":
            r.regime_pis_cofins = campo(f, 2)
        elif reg == "0150":
            r.participantes[campo(f, 2)] = only_digits(campo(f, 5)) or only_digits(campo(f, 6))
        elif reg == "0200":
            r.produtos[campo(f, 2)] = dict(
                descricao=campo(f, 3), unidade=campo(f, 6), tipo=campo(f, 7), ncm=only_digits(campo(f, 8))
            )
        elif reg == "C010":
            cnpj_estab = only_digits(campo(f, 2))
        elif reg == "C100":
            nota_atual = _c100(f, r.participantes, origem_doc)
            nota_atual["cnpj_estab"] = cnpj_estab
            nota_atual["_idx"] = len(r.notas)
            r.notas.append(nota_atual)
            consolidado = None
        elif reg == "C170" and nota_atual is not None:
            r.itens.append(_c170(f, nota_atual, r.produtos, "C170"))
        elif reg == "C190" and tipo == "EFD_ICMS_IPI" and nota_atual is not None:
            # analítico do documento por CST/CFOP/alíquota (único detalhe de NFC-e e de NF-e própria)
            nota_atual.setdefault("analitico", []).append(dict(
                cst_icms=campo(f, 2), cfop=campo(f, 3), aliq_icms=num(campo(f, 4)), vl_opr=num(campo(f, 5)),
                vl_bc_icms=num(campo(f, 6)), vl_icms=num(campo(f, 7)), vl_bc_icms_st=num(campo(f, 8)),
                vl_icms_st=num(campo(f, 9)),
            ))
        elif reg in ("C180", "C190") and tipo == "EFD_CONTRIB":
            dt_ini = data_iso(campo(f, 3))
            cod_item = campo(f, 5)
            prod = r.produtos.get(cod_item, {})
            consolidado = dict(
                ind_oper="1" if reg == "C180" else "0",
                data=dt_ini, periodo=periodo(dt_ini), cod_item=cod_item,
                ncm=only_digits(campo(f, 6)) or prod.get("ncm"), descricao=prod.get("descricao"),
                modelo=campo(f, 2),
            )
            nota_atual = None
        elif reg in ("C181", "C185") and consolidado:
            # C181/C185: CST|CFOP|VL_ITEM|VL_DESC|VL_BC|ALIQ|QUANT_BC|ALIQ_QUANT|VL|COD_CTA
            is_pis = reg == "C181"
            item = _item_base(
                origem=reg, periodo=consolidado["periodo"], data=consolidado["data"], ind_oper="1",
                cod_item=consolidado["cod_item"], descricao=consolidado["descricao"], ncm=consolidado["ncm"],
                cfop=campo(f, 3), vl_item=num(campo(f, 4)), vl_desc=num(campo(f, 5)),
            )
            if is_pis:
                item.update(cst_pis=campo(f, 2), vl_bc_pis=num(campo(f, 6)), aliq_pis=num(campo(f, 7)),
                            vl_pis=num(campo(f, 10)))
            else:
                item.update(cst_cofins=campo(f, 2), vl_bc_cofins=num(campo(f, 6)), aliq_cofins=num(campo(f, 7)),
                            vl_cofins=num(campo(f, 10)))
            r.itens.append(item)
        elif reg in ("C191", "C195") and consolidado:
            # C191/C195: CNPJ_CPF_PART|CST|CFOP|VL_ITEM|VL_DESC|VL_BC|ALIQ|QUANT_BC|ALIQ_QUANT|VL|COD_CTA
            is_pis = reg == "C191"
            item = _item_base(
                origem=reg, periodo=consolidado["periodo"], data=consolidado["data"], ind_oper="0",
                cnpj_part=only_digits(campo(f, 2)), cod_item=consolidado["cod_item"],
                descricao=consolidado["descricao"], ncm=consolidado["ncm"], cfop=campo(f, 4),
                vl_item=num(campo(f, 5)), vl_desc=num(campo(f, 6)),
            )
            if is_pis:
                item.update(cst_pis=campo(f, 3), vl_bc_pis=num(campo(f, 7)), aliq_pis=num(campo(f, 8)),
                            vl_pis=num(campo(f, 11)))
            else:
                item.update(cst_cofins=campo(f, 3), vl_bc_cofins=num(campo(f, 7)), aliq_cofins=num(campo(f, 8)),
                            vl_cofins=num(campo(f, 11)))
            r.itens.append(item)
        elif reg == "M200":
            r.apuracoes.append(dict(
                tributo="PIS", periodo=periodo(r.dt_ini),
                debitos=num(campo(f, 2)) + num(campo(f, 9)), creditos=num(campo(f, 3)) + num(campo(f, 4)),
                valor_recolher=num(campo(f, 13)), saldo_credor=0.0,
            ))
        elif reg == "M600":
            r.apuracoes.append(dict(
                tributo="COFINS", periodo=periodo(r.dt_ini),
                debitos=num(campo(f, 2)) + num(campo(f, 9)), creditos=num(campo(f, 3)) + num(campo(f, 4)),
                valor_recolher=num(campo(f, 13)), saldo_credor=0.0,
            ))
        elif reg == "E110":
            r.apuracoes.append(dict(
                tributo="ICMS", periodo=periodo(r.dt_ini), debitos=num(campo(f, 2)),
                creditos=num(campo(f, 6)), valor_recolher=num(campo(f, 13)), saldo_credor=num(campo(f, 14)),
            ))
        elif reg == "H010":
            r.inventario.append(dict(cod_item=campo(f, 2), unidade=campo(f, 3), qtd=num(campo(f, 4)),
                                     vl_unit=num(campo(f, 5)), vl_item=num(campo(f, 6))))
        elif reg in ("D001", "E001", "F001", "M001", "9001"):
            nota_atual = None
            consolidado = None

    # completa NCM de itens C170 cujo 0200 veio depois (não deveria, mas há arquivos assim)
    for it in r.itens:
        if not it.get("ncm") and it.get("cod_item") in r.produtos:
            it["ncm"] = r.produtos[it["cod_item"]].get("ncm")
    if not r.cnpj:
        r.avisos.append("Registro 0000 sem CNPJ.")
    return r
