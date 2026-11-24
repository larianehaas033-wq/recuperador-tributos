"""Planilha de itens de NF-e baixada do DF-e / SAT (SEF/SC) — "Excel Itens das notas NF-es".

Cada linha é um item de nota com os campos do XML (chave, emitente, destinatário, produto, ICMS, ICMS-ST, PIS/COFINS,
IBS/CBS). Serve no lugar dos XMLs quando o cliente não tem os arquivos: vira a mesma estrutura de nota que o leitor de
XML produz, e o resto do programa (cruzamento com a EFD, malha, crédito de ICMS) funciona igual.
"""
from __future__ import annotations

from pathlib import Path

from .sped_common import only_digits

COLUNAS_MINIMAS = {"ChaveAcesso", "IdItem", "ValorICMS", "NcmProduto", "CfopProduto"}


def eh_planilha_dfe(path: Path) -> bool:
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        return False
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        cab = next(wb.worksheets[0].iter_rows(values_only=True), ())
        return COLUNAS_MINIMAS <= {str(c) for c in cab if c}
    except Exception:  # noqa: BLE001
        return False


def eh_planilha_dfe_notas(path: Path) -> bool:
    """A planilha só de notas (sem itens) não serve: o crédito depende do CST de cada item."""
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        return False
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        cab = {str(c) for c in next(wb.worksheets[0].iter_rows(values_only=True), ()) if c}
        return "ChaveAcesso" in cab and "ValorTotalICMS" in cab and "IdItem" not in cab
    except Exception:  # noqa: BLE001
        return False


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return float(str(v).replace(".", "").replace(",", ".") or 0)


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def ler_planilha_dfe(path: Path) -> list[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    linhas = wb.worksheets[0].iter_rows(values_only=True)
    cab = [str(c) if c is not None else "" for c in next(linhas)]
    notas: dict[str, dict] = {}
    for vals in linhas:
        r = dict(zip(cab, vals))
        chave = only_digits(_s(r.get("ChaveAcesso")))
        if len(chave) != 44:
            continue
        data = r.get("DataEmissaoNfe")
        data = data.strftime("%Y-%m-%d") if hasattr(data, "strftime") else (_s(data)[:10] or None)
        # optante do Simples que destaca ICMS em grupo normal (ICMS00/20..., ex.: excesso de sublimite) dá crédito normal;
        # só o grupo ICMSSN (CSOSN) limita o crédito ao vCredICMSSN
        simples = _s(r.get("SnSnaEmitente")) == "1" and _s(r.get("TipoIcmsTag")).upper().startswith("ICMSSN")
        n = notas.get(chave)
        if n is None:
            n = notas[chave] = dict(
                tipo="NFE", arquivo=path.name, chave=chave, modelo=chave[20:22], serie=_s(r.get("SerieDocumento")),
                numero=_s(r.get("NumeroDocumento")), data=data, periodo=data[:7] if data else None,
                tp_nf="0" if _s(r.get("TipoOperacaoDocumento")).upper().startswith("E") else "1",
                fin_nfe=None, chave_ref=only_digits(_s(r.get("ChaveAcessoDfeRef"))) or None,
                cnpj_emit=only_digits(_s(r.get("CnpjEmitente")) or _s(r.get("CpfDoEmitente"))),
                nome_emit="", uf_emit=_s(r.get("UfEmitente")), crt_emit="1" if simples else "3",
                cnpj_dest=only_digits(_s(r.get("CnpjDoDestinatario")) or _s(r.get("CpfDoDestinatario"))),
                dest_cpf=bool(_s(r.get("CpfDoDestinatario"))), nome_dest="", uf_dest=_s(r.get("UfDestinatario")),
                cstat="", autorizada=_s(r.get("SituacaoDocumento")).lower().startswith("autoriz"),
                vl_doc=0.0, vl_icms=0.0, vl_icms_st=0.0, vl_pis=0.0, vl_cofins=0.0, itens=[], fonte="DFE_EXCEL",
            )
        orig = _s(r.get("OrigemMercadoria"))[:1]
        trib = _s(r.get("IcmsTributacao"))
        if simples and len(trib) == 3:
            cst_icms, csosn = orig + trib, trib       # CSOSN com 4 dígitos (origem + CSOSN)
        else:
            cst_icms, csosn = (orig + trib[-2:]) if trib else "", ""
        if n["chave_ref"] is None and only_digits(_s(r.get("ChaveAcessoDfeRef"))):
            n["chave_ref"] = only_digits(_s(r.get("ChaveAcessoDfeRef")))
        it = dict(
            num_item=_s(r.get("IdItem")), cod_item=_s(r.get("Produto")), descricao=_s(r.get("DescricaoProduto")),
            ncm=only_digits(_s(r.get("NcmProduto"))), cest=only_digits(_s(r.get("Cest"))), cfop=_s(r.get("CfopProduto")),
            unidade=_s(r.get("UnidadeComercial")), qtd=_f(r.get("QuantidadeUnidadeComercial")),
            vl_item=_f(r.get("ValorTotalProduto")), vl_desc=_f(r.get("ValorDesconto")), vl_frete=_f(r.get("ValorFrete")),
            vl_outro=_f(r.get("ValorOutrasDespesas")), cst_icms=cst_icms, csosn=csosn,
            vl_bc_icms=_f(r.get("ValorBaseCalculoICMS")), aliq_icms=_f(r.get("PercentualIcmsAliq")),
            vl_icms=_f(r.get("ValorICMS")), vl_cred_sn=_f(r.get("ValorIcmssnCredito")),
            vl_bc_icms_st=_f(r.get("ValorBaseCalculoICMSST")) or _f(r.get("ValorIcmsstRetBc")),
            vl_icms_st=_f(r.get("ValorIcmsst")) or _f(r.get("ValorIcmsstRet")), vl_ipi=_f(r.get("ValorIpi")),
            cst_pis=_s(r.get("PisCst")), vl_bc_pis=_f(r.get("ValorPisBc")), aliq_pis=_f(r.get("PercentualPisAliq")),
            vl_pis=_f(r.get("ValorPis")), cst_cofins=_s(r.get("CofinsCst")), vl_bc_cofins=_f(r.get("ValorCofinsBc")),
            aliq_cofins=_f(r.get("PercentualCofinsAliq")), vl_cofins=_f(r.get("ValorCofins")),
            cst_ibscbs=_s(r.get("CstIbscbs")), cclasstrib=_s(r.get("CClassTribIbscbs")),
        )
        n["itens"].append(it)
        total_item = _f(r.get("ValorTotalItemNfe")) or (it["vl_item"] - it["vl_desc"] + it["vl_frete"] + it["vl_outro"]
                                                       + it["vl_icms_st"] + it["vl_ipi"])
        n["vl_doc"] += total_item
        n["vl_icms"] += it["vl_icms"]
        n["vl_icms_st"] += it["vl_icms_st"]
        n["vl_pis"] += it["vl_pis"]
        n["vl_cofins"] += it["vl_cofins"]
    for n in notas.values():
        n["itens"].sort(key=lambda i: int(i["num_item"]) if i["num_item"].isdigit() else 0)
        n["vl_cred_sn"] = sum(i["vl_cred_sn"] for i in n["itens"])
        for k in ("vl_doc", "vl_icms", "vl_icms_st", "vl_pis", "vl_cofins"):
            n[k] = round(n[k], 2)
    return list(notas.values())
