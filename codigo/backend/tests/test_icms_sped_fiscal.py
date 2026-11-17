"""Só com o SPED Fiscal (sem EFD-Contribuições nem XML): regime informado à mão e ICMS pelo resumo C190."""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.setdefault("RECUPERADOR_DATA", str(TMP / "dados"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.config import DB_PATH  # noqa: E402
from app.importador import importar  # noqa: E402
from app.main import app  # noqa: E402
from tests import fixtures as fx  # noqa: E402

CNPJ = "16966629000120"


def _sped(path: Path) -> Path:
    k = f"422403{CNPJ}650010000008001000000080"
    L = [
        fx._l("0000", "018", "0", "01032024", "31032024", "MERCADO SC LTDA", CNPJ, "", "SC", "255000002", "4202008",
              "", "", "A", "1"),
        fx._l("C100", "1", "0", "", "65", "00", "1", "800", k, "20032024", "20032024", "300,00", "0", "0,00", "0,00",
              "300,00", "9", "0,00", "0,00", "0,00", "200,00", "32,00", "0,00", "0,00", "0,00", "0,00", "0,00",
              "0,00", "0,00"),
        # CST 060 e CFOP 5405 com ICMS: ST declarado e mesmo assim debitado (comprovado)
        fx._l("C190", "060", "5405", "17,00", "100,00", "100,00", "17,00", "0,00", "0,00", "0,00", "0,00", ""),
        # CFOP 5405 com CST 000: só um indicador (a conferir)
        fx._l("C190", "000", "5405", "7,00", "100,00", "100,00", "7,00", "0,00", "0,00", "0,00", "0,00", ""),
        # tributado normal: nada a recuperar
        fx._l("C190", "000", "5102", "17,00", "100,00", "100,00", "17,00", "0,00", "0,00", "0,00", "0,00", ""),
    ]
    path.write_text("\n".join(L) + "\n", encoding="latin-1")
    return path


def test_sped_fiscal_sozinho_regime_manual_e_st_debitado():
    db.init()
    res = importar([_sped(TMP / "sped_fiscal.txt")])
    assert res[0]["status"] == "IMPORTADO", res
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    emp = con.execute("SELECT id FROM empresas WHERE cnpj=?", (CNPJ,)).fetchone()["id"]
    cli = TestClient(app)
    assert cli.post(f"/api/empresas/{emp}/regime", json={"regime": "LUCRO_REAL"}).status_code == 200
    assert con.execute("SELECT regime FROM empresas WHERE id=?", (emp,)).fetchone()["regime"] == "LUCRO_REAL"
    from app.engine.runner import executar_analise
    aid = executar_analise(emp, hoje=date(2026, 11, 17))
    rows = [dict(r) for r in con.execute("SELECT * FROM creditos_identificados WHERE analise_id=?", (aid,))]
    st = sorted((r["cfop"], r["cst_escriturado"], r["valor_recuperar"], r["confianca"], r["num_doc"])
                for r in rows if r["tese"] == "ICMS_ST_TRIBUTADO_C190")
    assert st == [("5405", "000", 7.0, "BAIXA", "800"), ("5405", "060", 17.0, "ALTA", "800")]
    avisos = json.loads(con.execute("SELECT avisos_json FROM analises WHERE id=?", (aid,)).fetchone()[0])
    assert any("informado manualmente" in a for a in avisos)
    assert not any("REGIME NÃO IDENTIFICADO" in a for a in avisos)
