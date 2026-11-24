"""Casos reais do cadastro da Farmácia Salto Grande (24/11/2026), conferidos na lei."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("RECUPERADOR_DATA", str(Path(tempfile.mkdtemp()) / "dados"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.cadastro import classificar_ibs  # noqa: E402
from app.rules.loader import carregar  # noqa: E402


def test_formula_infantil_1901_10_10_sem_marca_na_descricao():
    b = carregar()
    r = b.classificar("19011010", "2026-10-20", "ALIQ_ZERO", "PREGOMIN PLUS 400GR")
    assert r and r.codigo == "ZERO_FORMULAS_INFANTIS"          # Lei 10.925/2004, art. 1º, XI → CST 06
    assert classificar_ibs(b, "19011010", "PREGOMIN PLUS 400GR")["cclasstrib"] == "200003"  # LC 214, Anexo I, item 4


def test_lenco_toalha_umedecida_3401_11_90_monofasico():
    b = carregar()
    r = b.classificar("34011190", "2026-10-20", "MONOFASICO", "TOALHA UMEDECIDA MILI LOVE 50UN")
    assert r and r.codigo == "MONO_BARRA_NAO_SABAO"            # Lei 10.147, 3401.11.90 exceto Ex 01 → CST 04
    assert b.classificar("34011190", "2026-10-20", "MONOFASICO", "SABONETE DOVE 90G") is None   # Ex 01 (sabão)
    assert b.classificar("34011190", "2026-10-20", "ALIQ_ZERO", "SABONETE DOVE 90G")           # alíquota zero


def test_ibs_sem_palavra_nao_vira_integral_as_cegas():
    b = carregar()
    r = classificar_ibs(b, "19011090", "PRODUTO X 400G")
    assert r["cclasstrib"] == "000001" and r.get("possivel", {}).get("cclasstrib") == "200003"
