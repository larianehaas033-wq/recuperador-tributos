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
    assert _esperada("33049990", "BRONZEADOR CENOURA E BRONZE FPS 6") == 17
    assert _esperada("33049990", "GEL POS SOL ALOE") == 25
    assert _esperada("33049990", "ANASOL LOCAO BRONZ FPS8 120G") == 17      # FPS >= 6 é protetor solar (Anvisa)
    assert _esperada("33049990", "CENOURAEAMP;BRONZE FPS30 AERO") == 17
    assert _esperada("33049990", "BRONZEADOR CENOURA FPS 4") == 25
    assert _esperada("33079000", "TREALENS LEBON 120ML+360ML") == 17
    assert _esperada("33079000", "RENU PLUS S/FRIC 355+120ML") == 17
    assert _esperada("33049990", "BEPANTOL DERMA PROTETOR LABIAL") == 25
    assert _esperada("33049990", "ISDIN CR FPS 99 ACTIVE 50G") == 17
    assert _esperada("30049069", "DIPIRONA 500MG") == 17


def test_medicamento_higiene_fora_da_st_em_sc():
    b = carregar()
    assert b.fora_da_st("SC", "30049099", "2026-10-17")      # DESONIDA
    assert b.fora_da_st("SC", "96190000", "2026-10-17")      # absorvente
    assert b.fora_da_st("SC", "33061000", "2026-10-17")      # creme dental
    assert not b.fora_da_st("SC", "30049099", "2020-12-31")  # antes do Decreto 982/2020 ainda tinha ST
    assert b.fora_da_st("SC", "21050010", "2026-10-17")      # sorvete saiu da ST em 01/04/2023 (Decreto 74/2023)
    assert not b.fora_da_st("SC", "21050010", "2022-10-17")  # ...mas tinha ST antes
    assert not b.fora_da_st("SC", "22030000", "2026-10-17")  # cerveja continua na ST (Seção IV)
    assert b.fora_da_st("SC", "19011010", "2026-10-17")      # fórmula infantil: alimentos saíram em 2018
    assert b.fora_da_st("SC", "85061010", "2026-10-17")      # pilhas: eletrônicos saíram em 2019
    assert not b.fora_da_st("PR", "30049099", "2026-10-17")
    # energético na ST; suplemento com o mesmo NCM não
    assert b.na_st("SC", "21069090", "2026-10-17", "ENERGETICO RED BULL 250ML")
    assert not b.na_st("SC", "21069090", "2026-10-17", "WHEY PROTEIN 900G")
    # cosméticos da Seção XXVI só na venda porta a porta
    assert not b.na_st("SC", "33051000", "2026-10-17", "SHAMPOO SEDA")


def test_soro_fisiologico_com_ncm_de_cosmetico_vai_para_conferencia():
    m = MotorIcms.__new__(MotorIcms)
    m.base, m.uf = carregar(), "SC"
    m.modal = m.base.icms_modal["SC"]
    aliq, fund, conf, _ = m._aliq_esperada("33079000", "SORO FISIOLOGICO 500 ML")
    assert conf == "BAIXA" and "NCM do cadastro provavelmente está errado" in fund


def test_cst_500_na_efd_e_origem_5_tributado_nao_st():
    from app.engine.icms import _eh_st
    assert not _eh_st("500")     # EFD: origem 5 + CST 00
    assert not _eh_st("520")     # origem 5 + CST 20
    assert _eh_st("560") and _eh_st("060") and _eh_st("010")
    assert _eh_st("0500")        # XML do Simples: origem 0 + CSOSN 500
    assert not _eh_st("0102")
    assert _eh_st("201")         # XML antigo: CSOSN 201 sem origem (não existe CST 01)
