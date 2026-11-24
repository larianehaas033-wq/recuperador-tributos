"""Crédito de ICMS não aproveitado: compra de medicamento (fora da ST em SC desde 2021) lançada com CST 60 sem crédito,
e ICMS creditado nas notas (C190) que não chegou ao E110."""
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
from tests.test_malha import _c100, _c190, _k  # noqa: E402

EMP, DIST, DIST2 = "73222333000144", "73555444000166", "73666444000177"
K1, K2 = _k(DIST, "55", 41), _k(DIST2, "55", 42)


def _efd(p):
    L = [
        fx._l("0000", "018", "0", "01032024", "31032024", "FARMA PERDIDA LTDA", EMP, "", "SC", "255000001", "4202008",
              "", "", "A", "1"),
        fx._l("0150", "D1", "DISTRIB", "1058", DIST, "", "", "4202008", "", "", "", "", ""),
        fx._l("0150", "D2", "DISTRIB 2", "1058", DIST2, "", "", "4202008", "", "", "", "", ""),
        fx._l("0200", "M1", "DIPIRONA 500MG 10CP", "", "", "UN", "00", "30049099", "", "", "", "", ""),
        # compra de medicamento com ICMS destacado lançada como ST, sem crédito
        _c100("0", "1", "D1", "55", "41", K1, 1000, 0),
        fx._c170(1, "M1", 100, 1000, "1403", "060", 0, 0, 0, 0, 0, "70", 0, 0, 0, "70", 0, 0, 0),
        _c190("060", "1403", 1000, 0),
        # compra creditada na nota, mas o E110 levou só parte do crédito
        _c100("0", "1", "D2", "55", "42", K2, 500, 85), _c190("000", "1102", 500, 85),
        fx._l("E110", "0,00", "0,00", "0,00", "0,00", "35,00", "0,00", "0,00", "0,00", "0,00", "0,00", "0,00",
              "0,00", "0,00", "35,00"),
    ]
    p.write_text("\n".join(L) + "\n", encoding="latin-1")
    return p


def _xml(pasta):
    pasta.mkdir(parents=True, exist_ok=True)
    it = [dict(cod="X", desc="DIPIRONA 500MG 10CP", ncm="30049099", cfop="5102", qtd=100, vl=1000, cst="000",
               bc=1000, aliq=17, icms=170)]
    (pasta / "k1.xml").write_text(fx._nfe(K1, "55", "1", DIST, EMP, "2024-03-10", it, 170), encoding="utf-8")
    return pasta


def test_credito_icms_nao_aproveitado():
    db.init()
    res = importar([_efd(TMP / "efd.txt"), _xml(TMP / "xml")])
    eid = next(r["empresa_id"] for r in res if r.get("empresa_id"))
    aid = executar_analise(eid)
    with db.tx() as con:
        cr = [dict(r) for r in con.execute("SELECT * FROM creditos_identificados WHERE analise_id=?", (aid,))]
    menor = [c for c in cr if c["tese"] == "ICMS_CREDITO_MENOR_DESTAQUE"]
    assert len(menor) == 1 and menor[0]["valor_recuperar"] == 170.0
    assert "fora da ST" in menor[0]["observacao"]
    nao = [c for c in cr if c["tese"] == "ICMS_CREDITO_NAO_APURADO"]
    assert len(nao) == 1 and nao[0]["valor_recuperar"] == 50.0


def test_lista_de_compras_mostra_todos_os_produtos():
    from app.engine import compras as cp
    with db.tx() as con:
        eid = con.execute("SELECT id FROM empresas WHERE cnpj=?", (EMP,)).fetchone()["id"]
        linhas = cp.listar(con, eid, "2024-03", "2024-03")
    dip = [r for r in linhas if r["chave"] == K1]
    assert len(dip) == 1 and dip[0]["situacao"] == "MENOR"
    assert dip[0]["destacado"] == 170.0 and dip[0]["creditado"] == 0.0 and dip[0]["diferenca"] == 170.0
