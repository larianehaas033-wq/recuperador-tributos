"""Dois SPED do mesmo período (o gerado pelo sistema da farmácia e o transmitido pelo contador): vale o transmitido,
que é o que tem a assinatura digital do PVA depois do |9999|, qualquer que seja a ordem de importação."""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.setdefault("RECUPERADOR_DATA", str(TMP / "dados"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.importador import arquivo_assinado, importar  # noqa: E402
from tests import fixtures as fx  # noqa: E402

ASSINATURA = b"SBRCAAEPDR0\x82\x06\t*\x86H\x86\xf7\r\x01\x07\x02"


def _efd(p, cnpj, nome, assinado):
    L = [
        fx._l("0000", "018", "0", "01032024", "31032024", nome, cnpj, "", "SC", "255000001", "4202008",
              "", "", "A", "1"),
        fx._l("9999", "2"),
    ]
    dados = ("\r\n".join(L) + "\r\n").encode("latin-1")
    p.write_bytes(dados + (ASSINATURA if assinado else b""))
    return p


def _arquivos(cnpj):
    with db.tx() as con:
        return [dict(r) for r in con.execute(
            "SELECT a.nome, a.assinado FROM arquivos_sped a JOIN empresas e ON e.id=a.empresa_id WHERE e.cnpj=?",
            (cnpj,))]


def test_detecta_assinatura():
    assert arquivo_assinado(_efd(TMP / "a.txt", "74111222000133", "X", True))
    assert not arquivo_assinado(_efd(TMP / "b.txt", "74111222000133", "X", False))


def test_transmitido_primeiro_copia_ignorada():
    db.init()
    cnpj = "74222333000144"
    res = importar([_efd(TMP / "1_entregue.txt", cnpj, "FARMA A", True),
                    _efd(TMP / "2_sistema.txt", cnpj, "FARMA A LTDA ME", False)])
    st = {r["arquivo"]: r["status"] for r in res}
    assert st["1_entregue.txt"] == "IMPORTADO" and st["2_sistema.txt"] == "IGNORADO"
    assert _arquivos(cnpj) == [{"nome": "1_entregue.txt", "assinado": 1}]


def test_copia_primeiro_transmitido_substitui():
    db.init()
    cnpj = "74333444000155"
    res = importar([_efd(TMP / "1_sistema.txt", cnpj, "FARMA B LTDA ME", False),
                    _efd(TMP / "2_entregue.txt", cnpj, "FARMA B", True)])
    r2 = next(r for r in res if r["arquivo"] == "2_entregue.txt")
    assert r2["status"] == "IMPORTADO" and r2["substituiu"] == "1_sistema.txt"
    r1 = next(r for r in res if r["arquivo"] == "1_sistema.txt")
    assert any("sem assinatura" in a for a in r1["avisos"])
    assert _arquivos(cnpj) == [{"nome": "2_entregue.txt", "assinado": 1}]
