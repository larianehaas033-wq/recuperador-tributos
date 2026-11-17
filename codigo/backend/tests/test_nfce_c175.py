"""Supermercado: vendas em NFC-e aparecem na EFD-Contribuições só resumidas (C100 + C175, sem produtos).
Os produtos dessas vendas têm de vir dos XMLs; sem eles, a análise avisa o que ficou de fora."""
import os
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.setdefault("RECUPERADOR_DATA", str(TMP / "dados"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.config import DB_PATH  # noqa: E402
from app.engine.runner import executar_analise  # noqa: E402
from app.importador import importar  # noqa: E402
from tests import fixtures as fx  # noqa: E402

CNPJ = "55666777000199"
K_COM_XML = f"422403{CNPJ}650010000007001000000070"
K_SEM_XML = f"422403{CNPJ}650010000007011000000080"


def _efd(path: Path) -> Path:
    L = [
        fx._l("0000", "006", "0", "", "", "01032024", "31032024", "MERCADO TESTE LTDA", CNPJ, "SC", "4202008", "", "00", "2"),
        fx._l("0001", "0"),
        fx._l("0110", "1", "1", "1", ""),
        fx._l("0140", "", "MERCADO TESTE LTDA", CNPJ, "SC", "", "4202008", "", ""),
        fx._l("C001", "0"),
        fx._l("C010", CNPJ, "2"),
    ]
    for chave, num in ((K_COM_XML, "700"), (K_SEM_XML, "701")):
        L += [
            fx._l("C100", "1", "0", "", "65", "00", "1", num, chave, "20032024", "20032024", "100,00", "0", "0,00",
                  "0,00", "100,00", "9", "0,00", "0,00", "0,00", "100,00", "17,00", "0,00", "0,00", "0,00", "1,65",
                  "7,60", "0,00", "0,00"),
            fx._l("C175", "5102", "100,00", "0,00", "01", "100,00", "1,6500", "", "", "1,65", "01", "100,00",
                  "7,6000", "", "", "7,60", "", ""),
        ]
    L += [fx._l("C990", "8"), fx._l("M001", "0"),
          fx._l("M200", "50,00", "0,00", "0,00", "50,00", "0,00", "0,00", "50,00", "0,00", "0,00", "0,00", "0,00", "50,00"),
          fx._l("M600", "200,00", "0,00", "0,00", "200,00", "0,00", "0,00", "200,00", "0,00", "0,00", "0,00", "0,00", "200,00"),
          fx._l("M990", "3"), fx._l("9999", "15")]
    path.write_text("\n".join(L) + "\n", encoding="latin-1")
    return path


def _xml(pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "nfce.xml").write_text(fx._nfe(K_COM_XML, "65", "1", CNPJ, "12345678909", "2024-03-20", [
        dict(cod="S1", desc="SHAMPOO SEDA 325ML", ncm="33051000", cfop="5102", qtd=1, vl=100, cst="000", bc=100,
             aliq=17, icms=17),
    ], 17, cpf_dest=True), encoding="utf-8")
    return pasta


def test_nfce_resumida_usa_itens_do_xml_e_avisa_o_que_falta():
    db.init()
    res = importar([_efd(TMP / "contrib_nfce.txt"), _xml(TMP / "xml_nfce")])
    assert all(r["status"] == "IMPORTADO" for r in res), res
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    emp = con.execute("SELECT id FROM empresas WHERE cnpj=?", (CNPJ,)).fetchone()["id"]
    aid = executar_analise(emp, hoje=date(2026, 11, 17))
    rows = [dict(r) for r in con.execute("SELECT * FROM creditos_identificados WHERE analise_id=?", (aid,))]
    mono = [r for r in rows if r["tese"] == "PISCOF_MONO_SAIDA"]
    assert {(r["tributo"], r["valor_recuperar"], r["num_doc"], r["num_item"]) for r in mono} == {
        ("PIS", 1.65, "700", "1"), ("COFINS", 7.6, "700", "1")}
    import json
    avisos = json.loads(con.execute("SELECT avisos_json FROM analises WHERE id=?", (aid,)).fetchone()[0])
    assert any("1 notas de venda" in a and "lidos dos XMLs" in a for a in avisos)
    assert any("ATENÇÃO: 1 notas de venda (R$ 100,00)" in a and "C175" in a for a in avisos)
    res = json.loads(con.execute("SELECT resumo_json FROM analises WHERE id=?", (aid,)).fetchone()[0])
    s = res["operacoes"]["SAIDA"]
    assert (s["notas"], s["itens"], s["valor_operacoes"], s["notas_sem_produtos"], s["valor_sem_produtos"]) == \
        (1, 1, 100.0, 1, 100.0)
    assert s["recuperar_corrigido"] > 9.25  # 1,65 + 7,60 corrigidos pela Selic
    from fastapi.testclient import TestClient
    from app.main import app
    cli = TestClient(app)
    sai = cli.get(f"/api/analises/{aid}/creditos?operacao=SAIDA").json()
    ent = cli.get(f"/api/analises/{aid}/creditos?operacao=ENTRADA").json()
    assert sai["total"] == 2 and ent["total"] == 0


def test_excluir_arquivo_marca_analise_e_excluir_empresa_apaga_tudo():
    from fastapi.testclient import TestClient
    from app.main import app
    cli = TestClient(app)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    emp = con.execute("SELECT id FROM empresas WHERE cnpj=?", (CNPJ,)).fetchone()["id"]
    arq = con.execute("SELECT id FROM arquivos_sped WHERE empresa_id=? AND tipo='EFD_CONTRIB'", (emp,)).fetchone()["id"]
    assert cli.delete(f"/api/arquivos/{arq}").status_code == 200
    assert con.execute("SELECT min(desatualizada) d FROM analises WHERE empresa_id=?", (emp,)).fetchone()["d"] == 1
    assert cli.delete(f"/api/empresas/{emp}").status_code == 200
    for t in ("empresas WHERE id", "arquivos_sped WHERE empresa_id", "itens_nota WHERE empresa_id",
              "notas_fiscais WHERE empresa_id", "analises WHERE empresa_id"):
        assert con.execute(f"SELECT count(*) FROM {t}=?", (emp,)).fetchone()[0] == 0
    assert emp not in [e["id"] for e in cli.get("/api/empresas").json()]
