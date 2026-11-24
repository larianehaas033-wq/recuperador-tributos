"""Alertas de possível malha fiscal ao importar a EFD: devolução escriturada errada, nota não escriturada, crédito
vedado, duplicidade, apuração menor que os documentos e numeração faltante."""
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

EMP = "71222333000144"
CLI = "71999888000177"
FORN = "71555444000166"


def _k(emit, mod, num):
    return f"422403{emit}{mod}001{num:09d}1{num:08d}"


def _c100(io, ie, part, mod, num, chave, vl, icms, sit="00"):
    v = lambda x: f"{x:.2f}".replace(".", ",")  # noqa: E731
    return fx._l("C100", io, ie, part, mod, sit, "1", num, chave, "10032024", "10032024", v(vl), "0", "0,00", "0,00",
                 v(vl), "9", "0,00", "0,00", "0,00", v(vl if icms else 0), v(icms), "0,00", "0,00", "0,00", "0,00",
                 "0,00", "0,00", "0,00")


def _c190(cst, cfop, vl, icms):
    v = lambda x: f"{x:.2f}".replace(".", ",")  # noqa: E731
    return fx._l("C190", cst, cfop, "17,00" if icms else "0,00", v(vl), v(vl if icms else 0), v(icms), "0,00", "0,00",
                 "0,00", "0,00", "")


K_DEV, K_VENDA = _k(CLI, "55", 77), _k(EMP, "55", 5)
K_UC, K_ST = _k(FORN, "55", 31), _k(FORN, "55", 32)
K_S10, K_S13 = _k(EMP, "55", 10), _k(EMP, "55", 13)


def _efd(p: Path) -> Path:
    L = [
        fx._l("0000", "018", "0", "01032024", "31032024", "LOJA MALHA LTDA", EMP, "", "SC", "255000001", "4202008",
              "", "", "A", "1"),
        fx._l("0150", "C1", "CLIENTE", "1058", CLI, "", "", "4202008", "", "", "", "", ""),
        fx._l("0150", "F1", "FORNECEDOR", "1058", FORN, "", "", "4202008", "", "", "", "", ""),
        _c100("0", "1", "C1", "55", "77", K_DEV, 100, 17), _c190("000", "1102", 100, 17),   # devolução como compra
        _c100("0", "1", "F1", "55", "31", K_UC, 50, 5), _c190("000", "1556", 50, 5),       # uso e consumo
        _c100("0", "1", "F1", "55", "31", K_UC, 50, 5), _c190("000", "1556", 50, 5),       # duplicada
        _c100("0", "1", "F1", "55", "32", K_ST, 30, 3), _c190("060", "1403", 30, 3),       # crédito em ST
        _c100("1", "0", "", "55", "10", K_S10, 100, 17), _c190("000", "5102", 100, 17),
        _c100("1", "0", "", "55", "13", K_S13, 100, 17), _c190("000", "5102", 100, 17),
        fx._l("E110", "17,00", "0,00", "0,00", "0,00", "25,00", "0,00", "0,00", "0,00", "0,00", "0,00", "0,00",
              "0,00", "0,00", "8,00"),
    ]
    p.write_text("\n".join(L) + "\n", encoding="latin-1")
    return p


def _xmls(pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    it = lambda cfop, icms: [dict(cod="A", desc="CREME", ncm="33049990", cfop=cfop, qtd=1, vl=100, cst="000",  # noqa: E731
                                 bc=100, aliq=17, icms=icms)]
    dev = fx._nfe(K_DEV, "55", "1", CLI, EMP, "2024-03-10", it("5202", 17), 17)
    dev = dev.replace("<tpNF>", f"<finNFe>4</finNFe><NFref><refNFe>{K_VENDA}</refNFe></NFref><tpNF>")
    (pasta / "dev.xml").write_text(dev, encoding="utf-8")
    (pasta / "venda.xml").write_text(fx._nfe(K_VENDA, "55", "1", EMP, CLI, "2024-03-02", it("5102", 10), 10),
                                     encoding="utf-8")
    return pasta


def test_alertas_de_malha():
    db.init()
    res = importar([_efd(TMP / "efd_icms.txt"), _xmls(TMP / "xml")])
    m = next(r["malha"] for r in res if r.get("malha"))
    assert m["alta"] > 0 and m["principais"]
    from fastapi.testclient import TestClient
    from app.main import app
    d = TestClient(app).get(f"/api/empresas/{m['empresa_id']}/malha").json()
    cod = {a["codigo"] for a in d["alertas"]}
    for esperado in ("DEV_ESCRITURADA_COMO_COMPRA", "DEV_CREDITO_MAIOR_ORIGINAL", "SAIDA_NAO_ESCRITURADA",
                     "CREDITO_ICMS_USO_CONSUMO", "CREDITO_ICMS_ST", "CHAVE_DUPLICADA", "APURACAO_MENOR_DOCUMENTOS",
                     "NUMERACAO_FALTANTE"):
        assert esperado in cod, (esperado, cod)
    apu = next(a for a in d["alertas"] if a["codigo"] == "APURACAO_MENOR_DOCUMENTOS")
    assert apu["valor"] == 17.0
    faltam = sorted(int(a["numero"]) for a in d["alertas"] if a["codigo"] == "NUMERACAO_FALTANTE")
    assert faltam == [6, 7, 8, 9, 11, 12]
    dev = next(a for a in d["alertas"] if a["codigo"] == "DEV_ESCRITURADA_COMO_COMPRA")
    assert dev["numero"] == "77" and dev["operacao"] == "Entrada"
    sai = next(a for a in d["alertas"] if a["codigo"] == "SAIDA_NAO_ESCRITURADA")
    assert sai["numero"] == "5" and sai["operacao"] == "Saída"
    uc = next(a for a in d["alertas"] if a["codigo"] == "CREDITO_ICMS_USO_CONSUMO")
    assert uc["numero"] == "31" and uc["operacao"] == "Entrada"
    for a in d["alertas"]:
        assert a["fundamento"] and a["corrigir"]


def test_credito_pis_cofins_no_cumulativo():
    db.init()
    p = fx.efd_contribuicoes(TMP / "contrib.txt")
    txt = p.read_text(encoding="latin-1").replace(fx.CNPJ, "72111222000133").replace("|0110|1|", "|0110|2|")
    p.write_text(txt, encoding="latin-1")
    res = importar([p])
    m = next(r["malha"] for r in res if r.get("malha"))
    from fastapi.testclient import TestClient
    from app.main import app
    d = TestClient(app).get(f"/api/empresas/{m['empresa_id']}/malha").json()
    cred = [a for a in d["alertas"] if a["codigo"] == "CREDITO_PISCOF_CUMULATIVO"]
    assert cred and cred[0]["valor"] == 46.25 and cred[0]["gravidade"] == "ALTA"
