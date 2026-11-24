"""Gera arquivos SPED e XML de teste com valores conhecidos."""
from __future__ import annotations

from pathlib import Path

CNPJ = "11222333000181"
FORN = "99888777000155"


def _l(*campos) -> str:
    return "|" + "|".join(str(c) for c in campos) + "|"


def _c170(n, cod, qtd, vl, cfop, cst_icms, bc_icms, aliq_icms, vl_icms, bc_st, vl_st,
          cst_pis, bc_pis, aliq_pis, vl_pis, cst_cof, bc_cof, aliq_cof, vl_cof, unid="UN"):
    f = lambda v: f"{v:.2f}".replace(".", ",")  # noqa: E731
    return _l("C170", n, cod, "", f(qtd), unid, f(vl), "0,00", "0", cst_icms, cfop, "", f(bc_icms), f(aliq_icms),
              f(vl_icms), f(bc_st), "0,00", f(vl_st), "0", "", "", "0,00", "0,00", "0,00", cst_pis, f(bc_pis),
              f(aliq_pis), "", "", f(vl_pis), cst_cof, f(bc_cof), f(aliq_cof), "", "", f(vl_cof), "")


def efd_contribuicoes(path: Path) -> Path:
    L = [
        _l("0000", "006", "0", "", "", "01032024", "31032024", "FARMACIA TESTE LTDA", CNPJ, "SC", "4202008", "", "00", "2"),
        _l("0001", "0"),
        _l("0110", "1", "1", "1", ""),
        _l("0140", "", "FARMACIA TESTE LTDA", CNPJ, "SC", "", "4202008", "", ""),
        _l("0150", "F1", "DISTRIB XYZ", "1058", FORN, "", "", "4202008", "", "", "", "", ""),
        _l("0200", "P1", "DIPIRONA 500MG", "", "", "UN", "00", "30049099", "", "", "", ""),
        _l("0200", "P2", "SHAMPOO 300ML", "", "", "UN", "00", "33051000", "", "", "", ""),
        _l("0200", "P3", "CHOCOLATE 90G", "", "", "UN", "00", "18063210", "", "", "", ""),
        _l("0200", "P4", "ARROZ 1KG", "", "", "UN", "00", "10063021", "", "", "", ""),
        _l("C001", "0"),
        _l("C010", CNPJ, "2"),
        # saída NF-e
        _l("C100", "1", "0", "", "55", "00", "1", "100", "4224031122233300018155001000000100100000001",
           "10032024", "10032024", "350,00", "0", "0,00", "0,00", "350,00", "9", "0,00", "0,00", "0,00", "200,00",
           "34,00", "0,00", "0,00", "0,00", "5,78", "26,60", "0,00", "0,00"),
        _c170(1, "P1", 1, 100, "5102", "060", 0, 0, 0, 0, 0, "01", 100, 1.65, 1.65, "01", 100, 7.6, 7.60),
        _c170(2, "P3", 1, 200, "5102", "000", 200, 17, 34, 0, 0, "01", 200, 1.65, 3.30, "01", 200, 7.6, 15.20),
        _c170(3, "P4", 1, 50, "5102", "040", 0, 0, 0, 0, 0, "01", 50, 1.65, 0.83, "01", 50, 7.6, 3.80),
        # entrada NF-e
        _l("C100", "0", "1", "F1", "55", "00", "1", "900", "4224039988877700015555001000000900100000009",
           "05032024", "05032024", "1800,00", "0", "0,00", "0,00", "1800,00", "9", "0,00", "0,00", "0,00",
           "1000,00", "170,00", "0,00", "0,00", "0,00", "8,25", "38,00", "0,00", "0,00"),
        _c170(1, "P3", 100, 1000, "1102", "000", 1000, 17, 170, 0, 0, "70", 0, 0, 0, "70", 0, 0, 0),
        _c170(2, "P1", 50, 500, "1102", "060", 0, 0, 0, 0, 0, "50", 500, 1.65, 8.25, "50", 500, 7.6, 38.00),
        _c170(3, "P2", 30, 300, "1102", "060", 0, 0, 0, 0, 0, "70", 0, 0, 0, "70", 0, 0, 0),
        _l("C990", "12"),
        _l("M001", "0"),
        _l("M200", "3,30", "0,00", "0,00", "3,30", "0,00", "0,00", "3,30", "0,00", "0,00", "0,00", "0,00", "2,00"),
        _l("M600", "100,00", "0,00", "0,00", "100,00", "0,00", "0,00", "100,00", "0,00", "0,00", "0,00", "0,00", "100,00"),
        _l("M990", "3"),
        _l("9999", "30"),
    ]
    path.write_text("\n".join(L) + "\n", encoding="latin-1")
    return path


def efd_icms(path: Path) -> Path:
    L = [
        _l("0000", "018", "0", "01032024", "31032024", "FARMACIA TESTE LTDA", CNPJ, "", "SC", "255000001", "4202008",
           "", "", "A", "1"),
        _l("0150", "F1", "DISTRIB XYZ", "1058", FORN, "", "", "4202008", "", "", "", "", ""),
        _l("0200", "P3", "CHOCOLATE 90G", "", "", "UN", "00", "18063210", "", "", "", "", ""),
        _l("0200", "P5", "SORVETE POTE 2L", "", "", "UN", "00", "21050010", "", "", "", "", ""),
        _l("C100", "0", "1", "F1", "55", "00", "1", "900", "4224039988877700015555001000000900100000009",
           "05032024", "05032024", "1800,00", "0", "0,00", "0,00", "1800,00", "9", "0,00", "0,00", "0,00",
           "1000,00", "170,00", "120,00", "20,40", "0,00", "0,00", "0,00", "0,00", "0,00"),
        _c170(1, "P3", 100, 1000, "1102", "000", 1000, 17, 170, 0, 0, "70", 0, 0, 0, "70", 0, 0, 0),
        _c170(2, "P5", 10, 80, "1403", "060", 0, 0, 0, 120, 20.40, "70", 0, 0, 0, "70", 0, 0, 0),
        _l("C100", "0", "1", "F1", "55", "00", "1", "901", "4224039988877700015555001000000901100000010",
           "06032024", "06032024", "300,00", "0", "0,00", "0,00", "300,00", "9", "0,00", "0,00", "0,00",
           "0,00", "0,00", "0,00", "0,00", "0,00", "0,00", "0,00", "0,00", "0,00"),
        _l("C100", "1", "0", "", "65", "00", "1", "500", "4224031122233300018165001000000500100000005",
           "20032024", "20032024", "207,00", "0", "0,00", "0,00", "207,00", "9", "0,00", "0,00", "0,00",
           "117,00", "42,00", "0,00", "0,00", "0,00", "0,00", "0,00", "0,00", "0,00"),
        _l("E110", "42,00", "0,00", "0,00", "0,00", "170,00", "0,00", "0,00", "0,00", "0,00", "0,00", "0,00",
           "0,00", "128,00", "0,00"),
    ]
    path.write_text("\n".join(L) + "\n", encoding="latin-1")
    return path


def _nfe(chave, mod, tp, emit, dest, data, itens, vicms, cpf_dest=False):
    dets = []
    for i, it in enumerate(itens, 1):
        cst = it["cst"]
        grp = "ICMS00" if cst.endswith("00") else ("ICMS60" if cst.endswith("60") else "ICMS40")
        dets.append(f"""
<det nItem="{i}"><prod><cProd>{it['cod']}</cProd><xProd>{it['desc']}</xProd><NCM>{it['ncm']}</NCM>
<CFOP>{it['cfop']}</CFOP><uCom>UN</uCom><qCom>{it['qtd']}</qCom><vProd>{it['vl']:.2f}</vProd></prod>
<imposto><ICMS><{grp}><orig>{cst[0]}</orig><CST>{cst[1:]}</CST><vBC>{it.get('bc', 0):.2f}</vBC>
<pICMS>{it.get('aliq', 0):.2f}</pICMS><vICMS>{it.get('icms', 0):.2f}</vICMS></{grp}></ICMS>
<PIS><PISAliq><CST>01</CST><vBC>{it['vl']:.2f}</vBC><pPIS>1.65</pPIS><vPIS>{it['vl']*0.0165:.2f}</vPIS></PISAliq></PIS>
<COFINS><COFINSAliq><CST>01</CST><vBC>{it['vl']:.2f}</vBC><pCOFINS>7.60</pCOFINS><vCOFINS>{it['vl']*0.076:.2f}</vCOFINS></COFINSAliq></COFINS>
{f"<IBSCBS><CST>{it['cclass'][:3]}</CST><cClassTrib>{it['cclass']}</cClassTrib></IBSCBS>" if it.get('cclass') else ''}
</imposto></det>""")
    dest_tag = f"<CPF>{dest}</CPF>" if cpf_dest else f"<CNPJ>{dest}</CNPJ>"
    total = sum(i["vl"] for i in itens)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><NFe><infNFe Id="NFe{chave}" versao="4.00">
<ide><mod>{mod}</mod><serie>1</serie><nNF>{chave[25:34].lstrip('0')}</nNF><dhEmi>{data}T10:00:00-03:00</dhEmi><tpNF>{tp}</tpNF></ide>
<emit><CNPJ>{emit}</CNPJ><enderEmit><UF>SC</UF></enderEmit><CRT>3</CRT></emit>
<dest>{dest_tag}<enderDest><UF>SC</UF></enderDest></dest>
{''.join(dets)}
<total><ICMSTot><vICMS>{vicms:.2f}</vICMS><vST>0.00</vST><vPIS>0</vPIS><vCOFINS>0</vCOFINS><vNF>{total:.2f}</vNF></ICMSTot></total>
</infNFe></NFe><protNFe><infProt><chNFe>{chave}</chNFe><cStat>100</cStat></infProt></protNFe></nfeProc>"""


def xmls(pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    k1 = "4224039988877700015555001000000900100000009"
    k2 = "4224039988877700015555001000000901100000010"
    k3 = "4224039988877700015555001000000902100000011"
    k4 = "4224031122233300018165001000000500100000005"
    k5 = "4224031122233300018155001000000600100000006"
    (pasta / "k1.xml").write_text(_nfe(k1, "55", "1", FORN, CNPJ, "2024-03-05", [
        dict(cod="X9", desc="CHOCOLATE", ncm="18063210", cfop="5102", qtd=100, vl=1000, cst="000", bc=1000, aliq=17, icms=170)
    ], 170), encoding="utf-8")
    (pasta / "k2.xml").write_text(_nfe(k2, "55", "1", FORN, CNPJ, "2024-03-06", [
        dict(cod="X8", desc="BALA", ncm="17049020", cfop="5102", qtd=10, vl=300, cst="000", bc=294.12, aliq=17, icms=50)
    ], 50), encoding="utf-8")
    (pasta / "k3.xml").write_text(_nfe(k3, "55", "1", FORN, CNPJ, "2024-03-07", [
        dict(cod="X7", desc="BISCOITO", ncm="19053100", cfop="5102", qtd=10, vl=117.65, cst="000", bc=117.65, aliq=17, icms=20)
    ], 20), encoding="utf-8")
    (pasta / "k4.xml").write_text(_nfe(k4, "65", "1", CNPJ, "12345678909", "2024-03-20", [
        dict(cod="P5", desc="SORVETE POTE 2L", ncm="21050010", cfop="5102", qtd=1, vl=100, cst="000", bc=100, aliq=17, icms=17),
        dict(cod="P5", desc="SORVETE POTE 2L", ncm="21050010", cfop="5405", qtd=10, vl=90, cst="060"),
        dict(cod="P3", desc="CHOCOLATE 90G", ncm="18063210", cfop="5102", qtd=1, vl=100, cst="000", bc=100, aliq=25, icms=25,
             cclass="200034"),
    ], 42, cpf_dest=True), encoding="utf-8")
    (pasta / "k5.xml").write_text(_nfe(k5, "55", "1", CNPJ, FORN, "2024-03-25", [
        dict(cod="P3", desc="CHOCOLATE 90G", ncm="18063210", cfop="5102", qtd=5, vl=50, cst="000", bc=50, aliq=17, icms=8.5)
    ], 8.5), encoding="utf-8")
    return pasta
