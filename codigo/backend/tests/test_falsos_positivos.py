"""Travas contra falso positivo: regime, CFOP de venda, devoluções e vigência da lei."""
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

os.environ.setdefault("RECUPERADOR_DATA", str(Path(tempfile.mkdtemp()) / "dados"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.comum import to_frame  # noqa: E402
from app.engine.pis_cofins import MotorPisCofins  # noqa: E402
from app.engine.runner import ITEM_SELECT  # noqa: E402
from app.rules.loader import carregar  # noqa: E402

BASE = carregar()
COLS = ITEM_SELECT + ["modelo"]
PROD = {"S1": {"tipo_item": "00", "descricao": "SHAMPOO SEDA 325ML"},
        "B1": {"tipo_item": "00", "descricao": "BISCOITO RECHEADO 140G"}}


def item(**kw):
    d = {c: None for c in COLS}
    d.update(dict(origem="C170", periodo="2024-03", data="2024-03-10", qtd=1.0, vl_item=100.0, vl_desc=0.0,
                  vl_bc_icms=100.0, aliq_icms=17.0, vl_icms=17.0, vl_bc_icms_st=0.0, vl_icms_st=0.0, vl_ipi=0.0,
                  cst_pis="01", vl_bc_pis=100.0, aliq_pis=1.65, vl_pis=1.65, cst_cofins="01", vl_bc_cofins=100.0,
                  aliq_cofins=7.6, vl_cofins=7.6, cfop="5102", ind_oper="1", cnpj_part="12345678000199"))
    d.update(kw)
    return [d[c] for c in COLS]


def rodar(itens, regime="LUCRO_REAL"):
    df = to_frame(itens, COLS).with_row_index("rid")
    motor = MotorPisCofins(BASE, {"regime": regime, "ind_ativ": "2", "uf": "SC"}, df, to_frame([], COLS), {},
                           date(2026, 11, 17), PROD, None)
    return motor.executar()[0]


SHAMPOO = dict(cod_item="S1", ncm="33051000", descricao="SHAMPOO SEDA 325ML")
BISC = dict(cod_item="B1", ncm="19053100", descricao="BISCOITO RECHEADO 140G")
COMPRA = dict(ind_oper="0", cfop="1102", cst_pis="50", cst_cofins="50")


def test_simples_nacional_nao_tem_tema_69_nem_credito_de_entrada():
    c = rodar([item(**BISC), item(**BISC, **COMPRA)], regime="SIMPLES_NACIONAL")
    assert not [x for x in c if x.tese in ("PISCOF_ICMS_BASE", "PISCOF_CREDITO_ENTRADA")]


def test_presumido_nao_tem_credito_de_entrada_mas_tem_tema_69():
    c = rodar([item(**BISC, aliq_pis=0.65, vl_pis=0.65, aliq_cofins=3.0, vl_cofins=3.0),
               item(**BISC, ind_oper="0", cfop="1102", cst_pis="70", cst_cofins="70", vl_pis=0.0, vl_cofins=0.0)],
              regime="LUCRO_PRESUMIDO")
    teses = {x.tese for x in c}
    assert "PISCOF_CREDITO_ENTRADA" not in teses and "PISCOF_ICMS_BASE" in teses


def test_bonificacao_remessa_e_devolucao_de_compra_nao_viram_restituicao():
    c = rodar([item(**SHAMPOO, cfop="5910"), item(**SHAMPOO, cfop="5949"), item(**SHAMPOO, cfop="5202"),
               item(**SHAMPOO, cfop="5152")])
    assert not [x for x in c if x.natureza == "RESTITUICAO"]


def test_devolucao_de_venda_abate_a_restituicao():
    c = rodar([item(**SHAMPOO, periodo="2024-03", data="2024-03-10"),
               item(**SHAMPOO, periodo="2024-04", data="2024-04-05", ind_oper="0", cfop="1202", cst_pis="50",
                    cst_cofins="50", vl_item=40.0, vl_bc_pis=40.0, vl_pis=0.66, vl_bc_cofins=40.0, vl_cofins=3.04)])
    r = {x.tributo: x.valor_recuperar for x in c if x.tese == "PISCOF_MONO_SAIDA"}
    assert r == {"PIS": 0.99, "COFINS": 4.56}  # 1,65 − 0,66 e 7,60 − 3,04


def test_regra_fora_da_vigencia_nao_se_aplica():
    # sabonete em barra só tem alíquota zero desde a Lei 12.839/2013; xampu continua monofásico
    assert BASE.classificar("34011190", "2012-06-01", "ALIQ_ZERO", "SABONETE PROTEX 85G") is None
    assert BASE.classificar("34011190", "2023-07-10", "ALIQ_ZERO", "SABONETE PROTEX 85G").codigo == "ZERO_SABONETE_BARRA"
    # credito de entrada: ICMS fora da base só a partir de 05/2023 (Lei 14.592/2023)
    sem = dict(BISC, ind_oper="0", cfop="1102", cst_pis="70", cst_cofins="70", vl_pis=0.0, vl_cofins=0.0)
    antes = rodar([item(**sem, periodo="2023-04", data="2023-04-10")])
    depois = rodar([item(**sem, periodo="2023-06", data="2023-06-10")])
    base = lambda c: {x.base_correta for x in c if x.tese == "PISCOF_CREDITO_ENTRADA"}  # noqa: E731
    assert base(antes) == {100.0} and base(depois) == {83.0}
