"""Parser de XML de NF-e (modelo 55) e NFC-e (modelo 65), inclusive eventos de cancelamento.

Lê arquivos soltos, pastas inteiras (com subpastas) e arquivos .zip com XMLs.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Iterator

from .sped_common import only_digits


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _t(el: ET.Element | None, path: str, default: str = "") -> str:
    if el is None:
        return default
    x = el.find(path)
    return (x.text or "").strip() if x is not None and x.text else default


def _f(el: ET.Element | None, path: str) -> float:
    v = _t(el, path)
    try:
        return float(v) if v else 0.0
    except ValueError:
        return 0.0


def _grupo(imposto: ET.Element | None, nome: str) -> ET.Element | None:
    """Devolve o subgrupo efetivo, ex.: ICMS/ICMS00, PIS/PISAliq."""
    if imposto is None:
        return None
    g = imposto.find(nome)
    if g is None:
        return None
    for child in list(g):
        return child
    return None


def parse_nfe_bytes(data: bytes, nome: str = "") -> dict | None:
    try:
        root = _strip_ns(ET.fromstring(data))
    except ET.ParseError:
        return None

    # Evento de cancelamento (procEventoNFe / evento)
    if root.tag in ("procEventoNFe", "evento", "envEvento"):
        inf = root.find(".//infEvento")
        if inf is not None and _t(inf, "tpEvento") == "110111":
            ret = root.find(".//retEvento/infEvento")
            status = _t(ret, "cStat") if ret is not None else "135"
            if status in ("135", "136", "155", ""):
                return {"tipo": "CANCELAMENTO", "chave": only_digits(_t(inf, "chNFe"))}
        return None

    inf = root.find(".//infNFe")
    if inf is None:
        return None
    chave = only_digits(inf.get("Id", ""))
    prot = root.find(".//protNFe/infProt")
    cstat = _t(prot, "cStat") if prot is not None else ""
    if prot is not None and _t(prot, "chNFe"):
        chave = only_digits(_t(prot, "chNFe"))

    ide = inf.find("ide")
    emit = inf.find("emit")
    dest = inf.find("dest")
    dh = _t(ide, "dhEmi") or _t(ide, "dEmi")
    data = dh[:10] if dh else None
    tot = inf.find("total/ICMSTot")

    nota = dict(
        tipo="NFE",
        arquivo=nome,
        chave=chave,
        modelo=_t(ide, "mod"),
        serie=_t(ide, "serie"),
        numero=_t(ide, "nNF"),
        data=data,
        periodo=data[:7] if data else None,
        tp_nf=_t(ide, "tpNF"),               # 0 entrada, 1 saída (do ponto de vista do emitente)
        fin_nfe=_t(ide, "finNFe"),          # 1 normal, 2 complementar, 3 ajuste, 4 devolução
        chave_ref=next((only_digits(r.text or "") for r in ide.findall("NFref/refNFe")) if ide is not None else iter(()), None),
        cnpj_emit=only_digits(_t(emit, "CNPJ") or _t(emit, "CPF")),
        nome_emit=_t(emit, "xNome"),
        uf_emit=_t(emit, "enderEmit/UF"),
        crt_emit=_t(emit, "CRT"),           # 1 ou 4: Simples Nacional
        cnpj_dest=only_digits(_t(dest, "CNPJ") or _t(dest, "CPF")),
        dest_cpf=bool(_t(dest, "CPF")),
        nome_dest=_t(dest, "xNome"),
        uf_dest=_t(dest, "enderDest/UF"),
        cstat=cstat,
        autorizada=cstat in ("100", "150", ""),
        vl_doc=_f(tot, "vNF"),
        vl_icms=_f(tot, "vICMS"),
        vl_icms_st=_f(tot, "vST"),
        vl_pis=_f(tot, "vPIS"),
        vl_cofins=_f(tot, "vCOFINS"),
        itens=[],
    )
    for det in inf.findall("det"):
        prod = det.find("prod")
        imp = det.find("imposto")
        icms = _grupo(imp, "ICMS")
        pis = _grupo(imp, "PIS")
        cof = _grupo(imp, "COFINS")
        ipi = imp.find("IPI/IPITrib") if imp is not None else None
        ibscbs = imp.find("IBSCBS") if imp is not None else None
        orig = _t(icms, "orig")
        cst = _t(icms, "CST")
        csosn = _t(icms, "CSOSN")
        nota["itens"].append(dict(
            num_item=det.get("nItem"),
            cod_item=_t(prod, "cProd"),
            descricao=_t(prod, "xProd"),
            ncm=only_digits(_t(prod, "NCM")),
            cest=only_digits(_t(prod, "CEST")),
            cfop=_t(prod, "CFOP"),
            unidade=_t(prod, "uCom"),
            qtd=_f(prod, "qCom"),
            vl_item=_f(prod, "vProd"),
            vl_desc=_f(prod, "vDesc"),
            vl_frete=_f(prod, "vFrete"),
            vl_outro=_f(prod, "vOutro"),
            cst_icms=(orig + cst) if cst else (csosn or ""),
            csosn=csosn,
            vl_bc_icms=_f(icms, "vBC"),
            aliq_icms=_f(icms, "pICMS"),
            vl_icms=_f(icms, "vICMS"),
            vl_cred_sn=_f(icms, "vCredICMSSN"),
            vl_bc_icms_st=_f(icms, "vBCST") or _f(icms, "vBCSTRet"),
            vl_icms_st=_f(icms, "vICMSST") or _f(icms, "vICMSSTRet"),
            vl_ipi=_f(ipi, "vIPI"),
            cst_pis=_t(pis, "CST"),
            vl_bc_pis=_f(pis, "vBC"),
            aliq_pis=_f(pis, "pPIS"),
            vl_pis=_f(pis, "vPIS"),
            cst_cofins=_t(cof, "CST"),
            vl_bc_cofins=_f(cof, "vBC"),
            aliq_cofins=_f(cof, "pCOFINS"),
            vl_cofins=_f(cof, "vCOFINS"),
            cst_ibscbs=_t(ibscbs, "CST"),
            cclasstrib=_t(ibscbs, "cClassTrib"),
        ))
    nota["vl_cred_sn"] = sum((it.get("vl_cred_sn") or 0) for it in nota["itens"])
    return nota


def iter_xml_sources(paths: list[Path]) -> Iterator[tuple[str, bytes]]:
    """Percorre arquivos .xml, pastas e .zip, devolvendo (nome, bytes)."""
    for p in paths:
        if p.is_dir():
            for sub in sorted(p.rglob("*")):
                if sub.is_file() and sub.suffix.lower() in (".xml", ".zip"):
                    yield from iter_xml_sources([sub])
        elif p.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(p) as z:
                    for info in z.infolist():
                        if info.filename.lower().endswith(".xml"):
                            yield f"{p.name}:{info.filename}", z.read(info)
            except zipfile.BadZipFile:
                continue
        elif p.suffix.lower() == ".xml":
            yield p.name, p.read_bytes()
