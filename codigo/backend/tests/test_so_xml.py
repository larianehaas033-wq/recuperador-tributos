"""Importar só XMLs (sem SPED): a empresa é cadastrada pelos próprios XMLs e pode ser analisada."""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.setdefault("RECUPERADOR_DATA", str(TMP / "dados"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.importador import importar  # noqa: E402
from tests import fixtures as fx  # noqa: E402

FARM = "70111222000133"
FORN_A = "70333444000155"
FORN_B = "70555666000177"


def _lote(pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    it = [dict(cod="A1", desc="DIPIRONA 500MG", ncm="30049099", cfop="5102", qtd=1, vl=10, cst="060")]
    n = 0
    for forn in (FORN_A, FORN_B):
        for _ in range(3):
            n += 1
            k = f"422410{forn}55001{n:09d}1{n:08d}"
            (pasta / f"c{n}.xml").write_text(fx._nfe(k, "55", "1", forn, FARM, "2024-10-05", it, 0), encoding="utf-8")
    for _ in range(4):
        n += 1
        k = f"422410{FARM}65001{n:09d}1{n:08d}"
        (pasta / f"v{n}.xml").write_text(fx._nfe(k, "65", "1", FARM, "12345678909", "2024-10-20", it, 0,
                                                  cpf_dest=True), encoding="utf-8")
    return pasta


def test_so_xmls_cadastra_a_empresa_e_nao_os_fornecedores():
    db.init()
    res = importar([_lote(TMP / "so_xml")])
    r = [x for x in res if x.get("tipo") == "XML_NFE"][0]
    assert r["importadas"] == 10 and r["sem_empresa"] == 0
    assert len(r["criadas"]) == 1 and r["empresas"]
    with db.tx() as con:
        raizes = {e["raiz_cnpj"] for e in con.execute("SELECT raiz_cnpj FROM empresas")}
        assert FARM[:8] in raizes and FORN_A[:8] not in raizes and FORN_B[:8] not in raizes
        ent = con.execute("SELECT COUNT(*) c FROM notas_fiscais WHERE ind_oper='0' AND empresa_id=?",
                          (r["empresas"][0],)).fetchone()["c"]
        assert ent == 6


def test_empresa_so_com_xmls_pode_ser_analisada():
    from app.engine.runner import executar_analise
    with db.tx() as con:
        eid = con.execute("SELECT id FROM empresas WHERE raiz_cnpj=?", (FARM[:8],)).fetchone()
    if eid is None:
        test_so_xmls_cadastra_a_empresa_e_nao_os_fornecedores()
        with db.tx() as con:
            eid = con.execute("SELECT id FROM empresas WHERE raiz_cnpj=?", (FARM[:8],)).fetchone()
    assert executar_analise(eid["id"])
