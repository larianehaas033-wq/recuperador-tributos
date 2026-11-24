"""Planilha de itens do DF-e (SAT/SEF) no lugar dos XMLs de compra: crédito de ICMS e ST do substituto."""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.setdefault("RECUPERADOR_DATA", str(TMP / "dados"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.parsers.dfe_excel import eh_planilha_dfe, ler_planilha_dfe  # noqa: E402

CAB = ["ChaveAcesso", "SerieDocumento", "NumeroDocumento", "TipoOperacaoDocumento", "SituacaoDocumento", "IdItem",
       "DataEmissaoNfe", "UfEmitente", "SnSnaEmitente", "CnpjEmitente", "CnpjDoDestinatario", "Produto",
       "NcmProduto", "DescricaoProduto", "CfopProduto", "ValorTotalProduto", "ValorDesconto", "TipoIcmsTag",
       "IcmsTributacao", "OrigemMercadoria", "ValorBaseCalculoICMS", "PercentualIcmsAliq", "ValorICMS", "ValorIcmsst",
       "ValorIcmssnCredito", "PisCst", "CofinsCst"]


def _planilha(p):
    import datetime
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(CAB)
    ch = "42261082762824000163550020033969981630781620"
    d = datetime.datetime(2026, 10, 1)
    ws.append([ch, 2, 3396998, "S", "Autorizado", 1, d, "SC", "0", "82762824000163", "16966629000120", "A1",
               "30049099", "DIPIRONA", "5102", 100, 0, "ICMS00", "00", "0", 100, 12, 12, 0, None, "04", "04"])
    ws.append([ch, 2, 3396998, "S", "Autorizado", 2, d, "SC", "0", "82762824000163", "16966629000120", "A2",
               "22029900", "ENERGETICO", "5405", 50, 0, "ICMS10", "10", "0", 50, 17, 8.5, 6, None, "01", "01"])
    sn = "42261013485130000456550070006070431733544475"
    ws.append([sn, 7, 607043, "S", "Autorizado", 1, d, "SC", "1", "13485130000456", "16966629000120", "B1",
               "33059000", "CONDICIONADOR", "5102", 50, 0, "ICMSSN101", "101", "0", 0, 0, 0, 0, 1.5, "04", "04"])
    wb.save(p)
    return p


def test_planilha_vira_notas_como_xml():
    p = _planilha(TMP / "itens.xlsx")
    assert eh_planilha_dfe(p)
    notas = {n["numero"]: n for n in ler_planilha_dfe(p)}
    n = notas["3396998"]
    assert n["vl_icms"] == 20.5 and len(n["itens"]) == 2 and n["crt_emit"] == "3"
    assert n["itens"][1]["cst_icms"] == "010"
    sn = notas["607043"]
    assert sn["crt_emit"] == "1" and sn["itens"][0]["cst_icms"] == "0101" and sn["vl_cred_sn"] == 1.5
