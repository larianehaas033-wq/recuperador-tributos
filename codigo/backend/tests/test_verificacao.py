"""Conferência automática do enquadramento (sem revisão manual)."""
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
EMP = {"regime": "LUCRO_REAL", "ind_ativ": "2", "uf": "SC"}
COLS = ITEM_SELECT + ["modelo"]


def item(**kw):
    d = {c: None for c in COLS}
    d.update(dict(origem="C170", periodo="2024-03", data="2024-03-10", qtd=1.0, vl_item=100.0, vl_desc=0.0,
                  vl_bc_icms=0.0, aliq_icms=0.0, vl_icms=0.0, vl_bc_icms_st=0.0, vl_icms_st=0.0, vl_ipi=0.0,
                  cst_pis="01", vl_bc_pis=100.0, aliq_pis=1.65, vl_pis=1.65, cst_cofins="01", vl_bc_cofins=100.0,
                  aliq_cofins=7.6, vl_cofins=7.6, cfop="5102", ind_oper="1"))
    d.update(kw)
    return [d[c] for c in COLS]


def rodar(itens, produtos=None, evid=None):
    df = to_frame(itens, COLS).with_row_index("rid")
    motor = MotorPisCofins(BASE, EMP, df, to_frame([], COLS), {}, date(2026, 11, 17), produtos or {}, evid)
    return motor.executar()[0]


def test_moto_nao_e_monofasica():
    # 8711 não está no art. 1º da Lei 10.485/2002 (versão anterior da base incluía por engano)
    assert BASE.classificar("87112010", "2024-03-10", "MONOFASICO") is None
    assert BASE.classificar("87032310", "2024-03-10", "MONOFASICO").codigo == "MONO_VEICULOS"


def test_leite_confirmado_pela_descricao_creme_nao():
    c = rodar([item(cod_item="L1", ncm="04012010", descricao="LEITE UHT INTEGRAL 1L"),
               item(cod_item="C1", ncm="04015010", descricao="CREME DE LEITE 200G")])
    conf = {x.cod_item: x.confianca for x in c if x.tributo == "PIS"}
    assert conf == {"L1": "ALTA"}  # creme de leite não está na lei: nem entra como oportunidade


def test_autopeca_anexo_ii_comprovada_pelo_fornecedor():
    linha = item(cod_item="V1", ncm="84811000", descricao="VALVULA REDUTORA 1/2")
    sem = rodar([linha])
    com = rodar([linha], evid={"MONOFASICO": {"84811000"}, "ALIQ_ZERO": set()})
    assert sem[0].confianca == "BAIXA" and com[0].confianca == "ALTA"


def test_credito_uso_e_consumo_fica_fora():
    entrada = dict(ind_oper="0", cfop="1102", cst_pis="70", cst_cofins="70", vl_pis=0.0, vl_cofins=0.0,
                   cnpj_part="99888777000155", ncm="48201000")
    c = rodar([item(cod_item="U1", descricao="CADERNO", **entrada)],
              produtos={"U1": {"tipo_item": "07", "descricao": "CADERNO"}})
    assert not [x for x in c if x.tese == "PISCOF_CREDITO_ENTRADA"]
    c = rodar([item(cod_item="R1", descricao="CHOCOLATE", **dict(entrada, ncm="18063210")),
               item(cod_item="R1", ncm="18063210", descricao="CHOCOLATE")],
              produtos={"R1": {"tipo_item": "00", "descricao": "CHOCOLATE"}})
    cred = [x for x in c if x.tese == "PISCOF_CREDITO_ENTRADA"]
    assert cred and all(x.confianca == "ALTA" for x in cred)


def test_cclasstrib_farmacia():
    from app.engine.cadastro import classificar_ibs
    casos = {
        ("96190000", "ABSORVENTE NOTURNO C/ABAS 8UN"): "200013",
        ("96190000", "FRALDA INFANTIL M 30UN"): "200035",
        ("34011190", "SABONETE ERVA DOCE 90G"): "200035",
        ("33061000", "CREME DENTAL 90G"): "200035",
        ("90251190", "TERMOMETRO DIGITAL"): "200004",
        ("40151200", "LUVA PROCEDIMENTO M 100UN"): "200030",
        ("90183111", "SERINGA 3ML C/AGULHA"): "200030",
        ("30059090", "ATADURA DE CREPE 10CM"): "000001",
        ("30049069", "DIPIRONA 500MG 10CP"): "200032",
        ("30022090", "VACINA GRIPE"): "200053",
        ("19059090", "PAO FRANCES KG"): "200003",
        ("19059090", "PAO DOCE 400G"): "000001",
        ("10063021", "ARROZ TIPO 1 5KG"): "200003",
        ("07020000", "TOMATE KG"): "200014",
        ("20091200", "SUCO DE LARANJA INTEGRAL"): "200034",
        ("33049910", "PROTETOR SOLAR FPS50"): "000001",
        ("87131000", "CADEIRA DE RODAS"): "200007",
    }
    erros = {k: (v, classificar_ibs(BASE, *k)["cclasstrib"]) for k, v in casos.items()
             if classificar_ibs(BASE, *k)["cclasstrib"] != v}
    assert not erros, erros


def test_credito_de_compra_exige_ncm_coerente():
    """Compra sem NCM, com NCM incompatível ou de produto de alíquota zero não vira crédito comprovado."""
    prod = {k: {"tipo_item": "00", "descricao": d} for k, d in
            (("S1", "LEITE PREMIARE 1L"), ("O1", "OVOS EMBALADO"), ("A1", "ACUCAR A.ALEGRE 5KG"),
             ("B1", "BISCOITO RECHEADO 140G"))}
    compra = dict(ind_oper="0", cfop="1102", cnpj_part="12345678000199", cst_pis="70", cst_cofins="70",
                  vl_pis=0.0, vl_cofins=0.0)
    c = rodar([item(cod_item="S1", ncm=None, descricao="LEITE PREMIARE 1L", **compra),
               item(cod_item="O1", ncm="04089100", descricao="OVOS EMBALADO", **compra),
               item(cod_item="A1", ncm="17011100", descricao="ACUCAR A.ALEGRE 5KG", **compra),
               item(cod_item="B1", ncm="19053100", descricao="BISCOITO RECHEADO 140G", **compra),
               item(cod_item="B1", ncm="19053100", descricao="BISCOITO RECHEADO 140G")], produtos=prod)
    conf = {x.cod_item: x.confianca for x in c if x.tese == "PISCOF_CREDITO_ENTRADA" and x.tributo == "PIS"}
    assert conf == {"S1": "BAIXA", "O1": "BAIXA", "B1": "ALTA"}  # açúcar (1701.11 → 1701.14) é alíquota zero


def test_nectar_e_ice_nao_viram_restituicao():
    c = rodar([item(cod_item="N1", ncm="22029900", descricao="SUCO DEL VALLE 1L TP PESSEGO"),
               item(cod_item="I1", ncm="22089000", descricao="BEB.ICE 51 275ML LIMAO"),
               item(cod_item="E1", ncm="22029900", descricao="ENERG.MONSTER GREEN 473ML")])
    assert {x.cod_item for x in c if x.tese in ("PISCOF_MONO_SAIDA", "PISCOF_ALIQ_ZERO_SAIDA")} == {"E1"}


def test_descarte_da_desossa_nao_gera_credito():
    compra = dict(ind_oper="0", cfop="1102", cnpj_part="12345678000199", cst_pis="73", cst_cofins="73",
                  vl_pis=0.0, vl_cofins=0.0)
    c = rodar([item(cod_item="D1", ncm="05061000", descricao="OSSOS/OUTRAS PERDAS - DESCARTE", **compra)],
              produtos={"D1": {"tipo_item": "00", "descricao": "OSSOS/OUTRAS PERDAS - DESCARTE"}})
    assert not [x for x in c if x.tese == "PISCOF_CREDITO_ENTRADA"]


def test_sabonete_em_barra_e_aliquota_zero_nao_monofasico():
    """3401.11.90 Ex 01 (sabão): Lei 10.925, art. 1º, XXVI. Crédito na compra é vedado por ser alíquota zero."""
    compra = dict(ind_oper="0", cfop="1102", cnpj_part="12345678000199", cst_pis="50", cst_cofins="50",
                  vl_bc_pis=171.32, vl_pis=2.83, vl_bc_cofins=171.32, vl_cofins=13.02)
    c = rodar([item(cod_item="P1", ncm="34011190", descricao="SABONETE PROTEX 85G CREAM", **compra)],
              produtos={"P1": {"tipo_item": "00", "descricao": "SABONETE PROTEX 85G CREAM"}})
    r = {(x.tese, x.tributo): (x.valor_recuperar, x.confianca) for x in c}
    assert r == {("RISCO_CRED_ALIQ_ZERO", "PIS"): (Decimal("2.83"), "ALTA"),
                 ("RISCO_CRED_ALIQ_ZERO", "COFINS"): (Decimal("13.02"), "ALTA")}
