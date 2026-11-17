"""Travas contra falso positivo: regime, CFOP de venda, devoluções e vigência da lei."""
import os
import sys
import tempfile
from datetime import date
from decimal import Decimal
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
    assert r == {"PIS": Decimal("0.99"), "COFINS": Decimal("4.56")}  # 1,65 − 0,66 e 7,60 − 3,04


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


def test_dinheiro_em_decimal_com_arredondamento_meio_para_cima():
    from app.engine.comum import Credito, r2
    assert r2(2.675) == Decimal("2.68")  # round() do Python daria 2.67 (float binário + arredondamento bancário)
    assert r2(Decimal("0.125")) == Decimal("0.13")
    c = Credito(modulo="X", tese="T", tributo="PIS", periodo="2024-01", data=None, valor_recuperar=0.1 + 0.2)
    assert c.valor_recuperar == Decimal("0.30") and isinstance(c.valor_recuperar, Decimal)
    c.valor_restituivel = 1.005
    assert c.valor_restituivel == Decimal("1.01")


def test_mudanca_de_regime_cada_competencia_pela_sua_regra():
    """Presumido em 2022 e Real em 2023: crédito de entrada só em 2023; Tema 69 fora do período do Simples."""
    sem = dict(BISC, ind_oper="0", cfop="1102", cst_pis="70", cst_cofins="70", vl_pis=0.0, vl_cofins=0.0)
    itens = [item(**sem, periodo="2022-06", data="2022-06-10"), item(**sem, periodo="2023-06", data="2023-06-10"),
             item(**BISC, periodo="2021-06", data="2021-06-10")]
    df = to_frame(itens, COLS).with_row_index("rid")
    emp = {"regime": "LUCRO_REAL", "ind_ativ": "2", "uf": "SC",
           "regimes": {"2021-06": "SIMPLES_NACIONAL", "2022-06": "LUCRO_PRESUMIDO", "2023-06": "LUCRO_REAL"}}
    c = MotorPisCofins(BASE, emp, df, to_frame([], COLS), {}, date(2026, 11, 17), PROD, None).executar()[0]
    assert {x.periodo for x in c if x.tese == "PISCOF_CREDITO_ENTRADA"} == {"2023-06"}
    assert not [x for x in c if x.tese == "PISCOF_ICMS_BASE"]  # 2021 era Simples


def test_regime_identificado_por_competencia_e_conflito():
    import sqlite3
    from app.engine.runner import regimes_por_periodo
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE arquivos_sped (empresa_id, tipo, periodo_ini, regime);
        CREATE TABLE notas_fiscais (empresa_id, origem, ind_emit, periodo, crt_emit);
        CREATE TABLE empresas (id, regime);
        INSERT INTO empresas VALUES (1, NULL);
        INSERT INTO arquivos_sped VALUES (1,'EFD_CONTRIB','2022-01-01','LUCRO_PRESUMIDO'),
                                         (1,'EFD_CONTRIB','2023-01-01','LUCRO_REAL');
        INSERT INTO notas_fiscais VALUES (1,'XML','0','2021-05','1'), (1,'XML','0','2023-01','1');
    """)
    reg, av = regimes_por_periodo(con, 1)
    assert reg == {"2021-05": "SIMPLES_NACIONAL", "2022-01": "LUCRO_PRESUMIDO", "2023-01": "LUCRO_REAL"}
    assert any("por competência" in a for a in av) and any("2023-01" in a and "CRT" in a for a in av)
    vazio = sqlite3.connect(":memory:")
    vazio.row_factory = sqlite3.Row
    vazio.executescript("CREATE TABLE arquivos_sped (empresa_id, tipo, periodo_ini, regime);"
                        "CREATE TABLE notas_fiscais (empresa_id, origem, ind_emit, periodo, crt_emit);"
                        "CREATE TABLE empresas (id, regime);")
    assert regimes_por_periodo(vazio, 1) == ({}, [regimes_por_periodo(vazio, 1)[1][0]])
    assert "NÃO IDENTIFICADO" in regimes_por_periodo(vazio, 1)[1][0]


def test_regras_comparadas_numericamente_e_completadas_pela_base_embutida(tmp_path, monkeypatch):
    import json
    from app import config
    from app.rules import loader
    emb = json.loads(open(config.RULES_BUNDLED, encoding="utf-8").read())
    antiga = dict(emb, versao="2026.11.17.9", teses={k: v for k, v in emb["teses"].items() if k != "RISCO_CRED_ALIQ_ZERO"})
    local = tmp_path / "regras.json"
    local.write_text(json.dumps(antiga), encoding="utf-8")
    monkeypatch.setattr(config, "RULES_LOCAL", local)
    emb_nova = dict(emb, versao="2026.11.17.11")
    arq = tmp_path / "emb.json"
    arq.write_text(json.dumps(emb_nova), encoding="utf-8")
    monkeypatch.setattr(config, "RULES_BUNDLED", arq)
    b = loader.carregar()
    assert b.versao == "2026.11.17.11"  # .11 é mais nova que .9 (antes a comparação era de texto)
    nova_local = dict(emb, versao="2026.11.17.12", teses={k: v for k, v in emb["teses"].items()
                                                        if k != "RISCO_CRED_ALIQ_ZERO"})
    local.write_text(json.dumps(nova_local), encoding="utf-8")
    b = loader.carregar()
    assert b.versao == "2026.11.17.12" and "RISCO_CRED_ALIQ_ZERO" in b.teses
