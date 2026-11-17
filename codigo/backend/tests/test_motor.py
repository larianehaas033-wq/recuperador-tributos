"""Teste de ponta a ponta: importa arquivos com valores conhecidos e confere cada tese à mão."""
import os
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ["RECUPERADOR_DATA"] = str(TMP / "dados")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import db  # noqa: E402
from app.engine.comum import fator_selic  # noqa: E402
from app.engine.runner import executar_analise  # noqa: E402
from app.importador import importar  # noqa: E402
from tests import fixtures  # noqa: E402

HOJE = date(2026, 11, 17)


@pytest.fixture(scope="module")
def analise():
    db.init()
    with db.tx() as con:
        a, m = 2024, 5
        while (a, m) <= (2026, 10):
            con.execute("INSERT INTO selic (competencia, taxa) VALUES (?, 1.0)", (f"{a:04d}-{m:02d}",))
            a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    res = importar([fixtures.efd_contribuicoes(TMP / "contrib.txt"), fixtures.efd_icms(TMP / "icms.txt"),
                    fixtures.xmls(TMP / "xml")])
    assert all(r["status"] == "IMPORTADO" for r in res), res
    con = sqlite3.connect(os.environ["RECUPERADOR_DATA"] + "/recuperador.db")
    con.row_factory = sqlite3.Row
    emp = con.execute("SELECT id FROM empresas").fetchone()["id"]
    aid = executar_analise(emp, hoje=HOJE)
    rows = [dict(r) for r in con.execute("SELECT * FROM creditos_identificados WHERE analise_id=?", (aid,))]
    return rows


def _find(rows, tese, trib, cod=None):
    return [r for r in rows if r["tese"] == tese and r["tributo"] == trib and (cod is None or r["cod_item"] == cod)]


def test_monofasico(analise):
    pis = _find(analise, "PISCOF_MONO_SAIDA", "PIS", "P1")
    cof = _find(analise, "PISCOF_MONO_SAIDA", "COFINS", "P1")
    assert len(pis) == 1 and pis[0]["valor_recuperar"] == 1.65 and pis[0]["cst_correto"] == "04"
    assert cof[0]["valor_recuperar"] == 7.60


def test_aliquota_zero(analise):
    assert _find(analise, "PISCOF_ALIQ_ZERO_SAIDA", "PIS", "P4")[0]["valor_recuperar"] == 0.83
    assert _find(analise, "PISCOF_ALIQ_ZERO_SAIDA", "COFINS", "P4")[0]["cst_correto"] == "06"


def test_icms_na_base(analise):
    # ICMS 34,00 x 1,65% = 0,561 ; x 7,6% = 2,584
    assert _find(analise, "PISCOF_ICMS_BASE", "PIS", "P3")[0]["valor_recuperar"] == 0.56
    assert _find(analise, "PISCOF_ICMS_BASE", "COFINS", "P3")[0]["valor_recuperar"] == 2.58
    # item monofásico não pode aparecer de novo na tese do ICMS
    assert not _find(analise, "PISCOF_ICMS_BASE", "PIS", "P1")


def test_credito_entrada(analise):
    # compra de 1.000 com ICMS 170 em 03/2024 -> base 830 (Lei 14.592/2023)
    pis = _find(analise, "PISCOF_CREDITO_ENTRADA", "PIS", "P3")
    assert pis[0]["base_correta"] == 830.0 and pis[0]["valor_recuperar"] == 13.70
    assert _find(analise, "PISCOF_CREDITO_ENTRADA", "COFINS", "P3")[0]["valor_recuperar"] == 63.08
    # shampoo é monofásico comprado para revenda: sem crédito (Tema 1.093)
    assert not _find(analise, "PISCOF_CREDITO_ENTRADA", "PIS", "P2")


def test_risco_credito_monofasico(analise):
    r = _find(analise, "RISCO_CRED_MONOFASICO", "PIS", "P1")
    assert r and r[0]["valor_recuperar"] == 8.25 and r[0]["natureza"] == "RISCO"


def test_limite_valor_recolhido_pis(analise):
    # PIS recolhido no mês: 2,00. Débitos indevidos (1,65 + 0,83 + 0,56) e crédito (13,70) só viram
    # restituição até 2,00; o resto vira saldo credor.
    pis = [r for r in analise if r["tributo"] == "PIS" and r["natureza"] != "RISCO"]
    assert round(sum(r["valor_restituivel"] for r in pis), 2) == 2.00
    assert round(sum(r["valor_saldo_credor"] for r in pis), 2) == round(1.65 + 0.83 + 0.56 + 13.70 - 2.00, 2)
    # débito indevido é usado antes do crédito extemporâneo
    assert _find(analise, "PISCOF_CREDITO_ENTRADA", "PIS", "P3")[0]["valor_restituivel"] == 0.0


def test_selic(analise):
    # pagamento 25/04/2024 -> Selic de 05/2024 a 10/2026 (30 meses a 1%) + 1% = 31%
    assert fator_selic(date(2024, 4, 25), HOJE, {f"{a}-{m:02d}": 1.0 for a in (2024, 2025, 2026)
                                                 for m in range(1, 13)}) == 31.0
    cof = _find(analise, "PISCOF_MONO_SAIDA", "COFINS", "P1")[0]
    assert cof["valor_restituivel"] == 7.60 and cof["valor_corrigido"] == round(7.60 * 1.31, 2)


def test_icms_st_tributado(analise):
    r = _find(analise, "ICMS_ST_TRIBUTADO_SAIDA", "ICMS", "P5")
    assert len(r) == 1 and r[0]["valor_recuperar"] == 17.0 and r[0]["confianca"] == "ALTA"


def test_ressarcimento_st(analise):
    # base presumida 120/10 = 12/un; vendeu 10 un por 90 -> diferença 30 x 17% = 5,10
    r = _find(analise, "ICMS_ST_RESSARCIMENTO", "ICMS", "P5")
    assert r and r[0]["valor_recuperar"] == 5.10


def test_aliquota_icms(analise):
    r = _find(analise, "ICMS_ALIQ_ACIMA", "ICMS", "P3")
    assert r and r[0]["valor_recuperar"] == 8.0 and r[0]["confianca"] == "BAIXA"


def test_cruzamento(analise):
    menor = [r for r in analise if r["tese"] == "ICMS_CREDITO_MENOR_DESTAQUE"]
    assert len(menor) == 1 and menor[0]["valor_recuperar"] == 50.0
    nao = [r for r in analise if r["tese"] == "ICMS_NOTA_NAO_ESCRITURADA"]
    assert len(nao) == 1 and nao[0]["valor_recuperar"] == 20.0
    risco = [r for r in analise if r["tese"] == "RISCO_SAIDA_NAO_ESCRITURADA"]
    assert len(risco) == 1 and risco[0]["chave"].endswith("600100000006")


def test_reimportar_nao_duplica():
    res = importar([TMP / "contrib.txt"])
    assert res[0]["status"] == "JA_IMPORTADO"


def test_cadastro_tributario(analise):
    from app.engine.runner import gerar_cadastro
    con = sqlite3.connect(os.environ["RECUPERADOR_DATA"] + "/recuperador.db")
    emp = con.execute("SELECT id FROM empresas").fetchone()[0]
    cad = {x["cod_item"]: x for x in gerar_cadastro(emp, hoje=HOJE)}
    p1, p3, p4, p5 = cad["P1"], cad["P3"], cad["P4"], cad["P5"]
    assert p1["cst_pis_cofins"] == "04" and p1["cclasstrib"] == "200032" and p1["reducao_ibscbs"] == 60
    assert "CST PIS/COFINS 01 → 04" in p1["divergencias"]
    assert p4["cst_pis_cofins"] == "06" and p4["cclasstrib"] == "200003"
    assert p5["cst_icms"] == "060" and p5["csosn"] == "500"
    assert p3["cst_icms"] == "000" and p3["csosn"] == "102" and p3["cclasstrib"] == "000001"
    assert "cClassTrib 200034 → 000001" in p3["divergencias"]
    assert cad["P2"]["cclasstrib"] == "000001"  # shampoo não está no Anexo VIII
