"""SC: perfumes e cosméticos (3303, 3304, 3305, 3307) pagam 25% (Lei 10.297/96, Anexo I, Seção I, item 04).
Protetor solar e solução para lentes pagam 17%. Casos reais da Farmácia Salto Grande (out/2026)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("RECUPERADOR_DATA", str(Path(tempfile.mkdtemp()) / "dados"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.icms import MotorIcms  # noqa: E402
from app.rules.loader import carregar  # noqa: E402


def _esperada(ncm, desc):
    m = MotorIcms.__new__(MotorIcms)
    m.base, m.uf = carregar(), "SC"
    m.modal = m.base.icms_modal["SC"]
    return float(m._aliq_esperada(ncm, desc)[0])


def test_cosmeticos_25():
    assert _esperada("33059000", "COR E TOM 1,0 PRETO AZULADO") == 25
    assert _esperada("33072010", "DES DOVE AER BEAUTY FINISH") == 25
    assert _esperada("33051000", "SH TRESEMME DETOX CAPILAR") == 25
    assert _esperada("33043000", "ESM RISQUE BRIDGERTON 8ML") == 25
    assert _esperada("33030020", "COLONIA BEBE ERVA DOCE GRANADO") == 25


def test_excecoes_17():
    assert _esperada("33049990", "PROTETOR SOLAR SUNDOWN FPS 50 200ML") == 17
    assert _esperada("33049990", "EPISOL SEC FPS70 TOQUE SECO") == 17
    assert _esperada("33079000", "RENU SOLUCAO P/ LENTES 355ML") == 17
    assert _esperada("33049990", "BRONZEADOR CENOURA E BRONZE FPS 6") == 25
    assert _esperada("33049990", "GEL POS SOL ALOE") == 25
    assert _esperada("33049990", "ANASOL LOCAO BRONZ FPS8 120G") == 25
    assert _esperada("33049990", "ISDIN CR FPS 99 ACTIVE 50G") == 17
    assert _esperada("30049069", "DIPIRONA 500MG") == 17
