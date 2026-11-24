"""NFC-e com PIS/COFINS zerado no XML, mas tributado no resumo C175 da EFD-Contribuições (caso real da Farmácia
Salto Grande, out/2026: a farmácia exclui o ICMS da base no próprio C175)."""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.setdefault("RECUPERADOR_DATA", str(TMP / "dados"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.engine.runner import executar_analise  # noqa: E402
from app.importador import importar  # noqa: E402
from tests import fixtures as fx  # noqa: E402

EMP = "74111222000133"
K = f"422410{EMP}65001000000777100000777"


def _efd(p):
    L = [
        fx._l("0000", "006", "0", "", "", "01102024", "31102024", "FARMA C175 LTDA", EMP, "SC", "4202008", "", "00", "9"),
        fx._l("0110", "2", "", "1", "9"),
        fx._l("C010", EMP, "2"),
        fx._l("C100", "1", "0", "", "65", "00", "1", "777", K, "10102024", "10102024", "200,00", "0", "0,00", "0,00",
              "200,00", "9", "0,00", "0,00", "0,00", "200,00", "34,00", "0,00", "0,00", "0,00", "0,00", "0,00", "0,00",
              "0,00"),
        # produto tributado e medicamento vendidos com CST 01: base sem o ICMS (VL_DESC), PIS 0,65% e COFINS 3%
        fx._l("C175", "5102", "200,00", "34,00", "01", "166,00", "0,6500", "", "", "1,08", "01", "166,00", "3,0000",
              "", "", "4,98", "", ""),
    ]
    p.write_text("\n".join(L) + "\n", encoding="latin-1")
    return p


def _xml(pasta):
    pasta.mkdir(parents=True, exist_ok=True)
    it = [dict(cod="M1", desc="DIPIRONA 500MG 10CP", ncm="30049099", cfop="5102", qtd=1, vl=100, cst="000", bc=100,
               aliq=17, icms=17, cst_pis="01", vl_pis=0, vl_cofins=0),
          dict(cod="T1", desc="CHOCOLATE 90G", ncm="18063210", cfop="5102", qtd=1, vl=100, cst="000", bc=100,
               aliq=17, icms=17, cst_pis="01", vl_pis=0, vl_cofins=0)]
    import re
    x = fx._nfe(K, "65", "1", EMP, "12345678909", "2024-10-10", it, 34, cpf_dest=True)
    x = re.sub(r"<vPIS>[\d.]+</vPIS>", "<vPIS>0.00</vPIS>", x)       # NFC-e com PIS/COFINS zerado no XML
    x = re.sub(r"<vCOFINS>[\d.]+</vCOFINS>", "<vCOFINS>0.00</vCOFINS>", x)
    (pasta / "nfce.xml").write_text(x, encoding="utf-8")
    return pasta


def test_pis_pago_pelo_c175_vira_credito_do_monofasico():
    db.init()
    res = importar([_efd(TMP / "contrib.txt"), _xml(TMP / "xml")])
    eid = next(r["empresa_id"] for r in res if r.get("empresa_id"))
    aid = executar_analise(eid)
    with db.tx() as con:
        cr = [dict(r) for r in con.execute("SELECT * FROM creditos_identificados WHERE analise_id=? AND "
                                           "tese='PISCOF_MONO_SAIDA'", (aid,))]
    assert {c["tributo"] for c in cr} == {"PIS", "COFINS"}
    pis = next(c for c in cr if c["tributo"] == "PIS")
    assert abs(pis["valor_recuperar"] - 0.54) < 0.011          # 100 × (166/200) × 0,65%
    assert "C175" in pis["observacao"]
