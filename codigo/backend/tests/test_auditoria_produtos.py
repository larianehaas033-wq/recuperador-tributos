"""Auditoria de enquadramento: produtos reais de supermercado e farmácia, com o código que a lei determina.

Cada linha: (NCM, descrição como vem do cadastro, CST PIS/COFINS esperado na revenda pelo varejista, cClassTrib).
"NC" = o programa não pode afirmar sozinho (depende de 'Ex', destinação ou composição) e não deve sugerir troca.
O programa só é publicado se acertar todas as linhas.
"""
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

os.environ.setdefault("RECUPERADOR_DATA", str(Path(tempfile.mkdtemp()) / "dados"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.engine.cadastro import classificar_ibs  # noqa: E402
from app.engine.comum import to_frame  # noqa: E402
from app.engine.pis_cofins import MotorPisCofins  # noqa: E402
from app.engine.runner import ITEM_SELECT  # noqa: E402
from app.rules.loader import carregar  # noqa: E402

BASE = carregar()
COLS = ITEM_SELECT + ["modelo"]
MOTOR = MotorPisCofins(BASE, {"regime": "LUCRO_REAL", "ind_ativ": "2"}, to_frame([], COLS).with_row_index("rid"),
                       to_frame([], COLS), {}, date(2026, 11, 17), {}, None)


def sugerir_pis(ncm: str, desc: str) -> str:
    mono = BASE.classificar(ncm, "2026-06-01", "MONOFASICO", desc)
    zero = None if mono else BASE.classificar(ncm, "2026-06-01", "ALIQ_ZERO", desc)
    regra = mono or zero
    if not regra:
        return "01"
    conf, _ = MOTOR.verificar(regra, {"ncm": ncm, "descricao": desc, "cod_item": "X"}, "T")
    if conf != "ALTA":
        return "NC"
    return "04" if mono else "06"


CASOS = [
    # ---------------- cesta básica e alimentos
    ("10063021", "ARROZ TIPO 1 5KG", "06", "200003"),
    ("07133319", "FEIJAO CARIOCA 1KG", "06", "200003"),
    ("17011400", "ACUCAR CRISTAL 5KG", "06", "200003"),
    ("09012100", "CAFE TORRADO MOIDO 500G", "06", "200003"),
    ("15079011", "OLEO DE SOJA 900ML", "06", "200034"),
    ("15171000", "MARGARINA C/SAL 500G", "06", "200003"),
    ("04051000", "MANTEIGA C/SAL 200G", "06", "200003"),
    ("11010010", "FARINHA DE TRIGO 1KG", "06", "200003"),
    ("19021900", "MACARRAO ESPAGUETE 500G", "06", "200003"),
    ("11022000", "FUBA MIMOSO 1KG", "06", "200003"),
    ("11062000", "FARINHA DE MANDIOCA 1KG", "06", "200003"),
    ("19059090", "PAO FRANCES KG", "06", "200003"),
    ("19059090", "BOLO DE CENOURA", "01", "000001"),
    ("19059010", "PAO DE FORMA 500G", "01", "200034"),
    ("19053100", "BISCOITO RECHEADO 140G", "01", "000001"),
    ("25010020", "SAL REFINADO IODADO 1KG", "01", "200003"),
    # ---------------- leite e derivados
    ("04012010", "LEITE UHT INTEGRAL 1L", "06", "200003"),
    ("04022110", "LEITE EM PO INTEGRAL 400G", "06", "200003"),
    ("04029900", "LEITE CONDENSADO 395G", "01", "000001"),
    ("04015021", "CREME DE LEITE 200G", "01", "000001"),
    ("04015010", "CREME DE LEITE UHT 200G (NCM ERRADA DO CLIENTE)", "01", "000001"),
    ("04014010", "LEITE UHT ZERO LACTOSE 1L", "06", "200003"),
    ("04061010", "QUEIJO MUSSARELA KG", "06", "200003"),
    ("04069020", "QUEIJO PRATO FATIADO", "06", "200003"),
    ("04061090", "REQUEIJAO CREMOSO 200G", "06", "200003"),
    ("04064000", "QUEIJO GORGONZOLA 150G", "01", "000001"),
    ("04039000", "LEITE FERMENTADO CLUB VIGOR 6X80G", "06", "200034"),
    ("04032000", "IOGURTE NATURAL 170G", "06", "200034"),
    ("22029900", "BEBIDA LACTEA BANDEJA 540G MORANGO", "06", "200034"),
    ("19011010", "FORMULA INFANTIL NAN 1 800G", "06", "200003"),
    # ---------------- bebidas
    ("22021000", "BEBIDA 2LT PET COCA COLA", "06", "000001"),
    ("22011000", "AGUA MINERAL S/GAS 500ML", "06", "000001"),
    ("22030000", "CERVEJA LATA 350ML", "06", "000001"),
    ("22029900", "ENERGETICO LATA 250ML", "06", "000001"),
    ("22029900", "NECTAR DE UVA 1L", "01", "000001"),
    ("20091200", "SUCO DE LARANJA INTEGRAL 900ML", "01", "200034"),
    ("20098990", "SUCO PRONTO ADOCADO 1L", "01", "000001"),
    ("22042100", "VINHO TINTO SECO 750ML", "01", "000001"),
    ("21069010", "REFRESCO 25G POP FRUTA GOIABA", "01", "000001"),
    # ---------------- carnes, hortifrúti e ovos
    ("02013000", "CARNE BOVINA PATINHO KG", "06", "200003"),
    ("02071400", "FILE DE PEITO DE FRANGO KG", "06", "200003"),
    ("16010000", "LINGUICA TOSCANA KG", "01", "000001"),
    ("16024100", "PRESUNTO COZIDO FATIADO", "01", "000001"),
    ("04072100", "OVOS BRANCOS DZ", "06", "200014"),
    ("07020000", "TOMATE KG", "06", "200014"),
    ("08039000", "BANANA PRATA KG", "06", "200014"),
    ("07032010", "ALHO KG", "06", "200014"),
    ("09101100", "GENGIBRE KG", "01", "000001"),
    ("20041000", "BATATA PALITO CONGELADA PRE FRITA", "01", "000001"),
    ("20054000", "ERVILHA EM CONSERVA 200G", "01", "000001"),
    ("12024200", "AMENDOIM CRU 500G", "01", "200034"),
    ("20081100", "AMENDOIM JAPONES 150G", "01", "000001"),
    ("20049000", "SELETA DE LEGUMES COZIDOS NO VAPOR CONGELADA", "01", "200034"),
    ("20055100", "FEIJAO COZIDO PRONTO C/SAL", "01", "000001"),
    ("20021000", "TOMATE PELADO EM CONSERVA", "01", "000001"),
    ("20029000", "EXTRATO DE TOMATE 340G", "01", "200034"),
    ("22029900", "ISOTONICO 500ML", "06", "000001"),
    ("22029900", "CHA GELADO PRONTO 1,5L", "06", "000001"),
    ("22029900", "BEBIDA DE SOJA SABOR UVA 1L", "01", "000001"),
    ("08119000", "POLPA DE MORANGO CONGELADA", "06", "200014"),
    ("08111000", "MORANGO CONGELADO COM ACUCAR", "06", "000001"),
    ("08129000", "CEREJA EM CALDA", "06", "000001"),
    ("04069030", "QUEIJO PARMESAO RALADO 50G", "06", "200003"),
    ("04069090", "QUEIJO CHEDDAR FATIADO", "01", "000001"),
    ("04061010", "QUEIJO MINAS FRESCAL KG", "06", "200003"),
    # ---------------- casos reais do supermercado Eliana Dalsenter (análise de 17/11/2026)
    ("04011010", "LEITE TIROL UHT DESNATADO 1L C/TAMPA", "06", "200003"),
    ("04029900", "LEITE COND.MOCA 395G TP", "01", "000001"),
    ("04022130", "NATA AURORA 280G", "01", "000001"),
    ("22029900", "SUCO DEL VALLE 1L TP PESSEGO", "01", "000001"),
    ("22029900", "SUCO MAGUARY 1L TP LAR", "01", "000001"),
    ("22029900", "ADES ORIGINAL 1L TP", "01", "000001"),
    ("22029900", "ENERG.MONSTER GREEN 473ML", "06", "000001"),
    ("22029900", "GATORADE 500ML LARANJA", "06", "000001"),
    ("22029900", "ACHOC.CHOCOLEITE 460ML", "06", "200034"),
    ("22029900", "BEB.LACTEA FERM AURORA GRF 850G COCO", "06", "200034"),
    ("22021000", "REFR.COCA-COLA ORIG 2L PET", "06", "000001"),
    ("19019090", "MIST.LACTEA CREMOR TIROL 395G", "01", "000001"),
    ("19019090", "SOBR.LACTEA AUREA 385G BEIJINHO", "01", "000001"),
    ("04039000", "LEITE FERM.CHAMYTO 1UN 120G", "06", "200034"),
    ("04039000", "SOBREMESA BATAVO CREAMY 200G", "01", "000001"),
    ("04061010", "QUEIJO AURORA FAT 150G MUS", "06", "200003"),
    ("04062000", "QUEIJO RALADO VIGOR PARM 50G", "06", "200003"),
    ("04061090", "QUEIJO COLONIAL", "01", "000001"),
    ("04062000", "QUEIJO RALADO SELETI MIST.ALIM.50G", "01", "000001"),
    ("19012000", "MISTURA P/BOLO FLEISCHMANN 390G AIPIM", "01", "000001"),
    ("19059090", "SALGADINHO TRIGO 50G-PIZZA", "01", "000001"),
    ("21069010", "REFRESCO TANG 18G LAR", "01", "000001"),
    ("21069090", "ADOCANTE ADOCYL 200ML", "01", "000001"),
    ("22089000", "BEB.ICE 51 275ML LIMAO", "01", "000001"),
    ("22089000", "CONHAQUE DREHER 900ML", "01", "000001"),
    ("22071090", "ALCOOL ARAUCARIA 92,8 INPM 1L", "04", "000001"),
    ("38089419", "VEJA BANHEIRO ANTIBAC 500ML", "01", "000001"),
    ("12099100", "SEMENTES ISLA PAK ALFACE", "06", "200038"),
    ("12119010", "OREGANO INCAS 100G", "01", "000001"),
    ("12130000", "PALHA ESPECIAL BRANCA 10", "01", "000001"),
    ("10083090", "ALPISTE KANTY 500GR", "01", "000001"),
    ("10064000", "ARROZ P/CACHORRO AU-AU 5KG", "01", "000001"),
    ("11029000", "FARINHA ARROZ URBANO 1KG", "01", "200034"),
    ("11029000", "FARINHA AVEIA QUAKER 165G", "01", "200003"),
    ("11041900", "FARINHA MILHO FLOC.SINHA 500G", "06", "200003"),
    ("08062000", "UVAS PASSAS JANDIRA S/SEM 100G", "06", "200034"),
    ("03048990", "FILE TILAPIA C.VALE 800G", "06", "200003"),
    ("03048100", "PEIXE SALMAO", "06", "000001"),
    ("96190000", "ABS.ALWAYS SUP PROT C/ABAS 8UN", "01", "200013"),
    ("34011900", "TOALHAS UMED.NATURAL BABY 50UN", "01", "000001"),
    ("34011900", "SABAO ASSIM 5X200G NEUTRO", "01", "200035"),
    ("39269040", "CHUPETA LILLO DIVERTIDA", "01", "000001"),
    ("40151900", "LUVA LATEX MUCAMBO M", "01", "000001"),
    ("39174090", "SIFAO EXTENSIVO PLASBOHN", "01", "000001"),
    ("30039031", "SHAMPOO PETBRILL ANTI-PULGAS 500ML", "04", "000001"),
    ("20091200", "SUCO LARANJA INT.SUQ 2L", "01", "200034"),
    # ---------------- higiene e limpeza
    ("34011190", "SABONETE PROTEX 85G CREAM", "06", "200035"),
    ("33062000", "FIO DENTAL ORAL-B 50M", "06", "000001"),
    ("33069000", "ENXAGUANTE BUCAL LISTERINE 500ML", "06", "000001"),
    ("34012010", "SABONETE EM FLOCOS", "04", "000001"),
    ("34013000", "SABONETE LIQUIDO PROTEX 250ML", "01", "000001"),
    ("34011190", "SABONETE ERVA DOCE 85G", "06", "200035"),
    ("33061000", "CREME DENTAL 90G", "06", "200035"),
    ("96032100", "ESCOVA DENTAL MACIA", "04", "200035"),
    ("33051000", "SHAMPOO 350ML", "04", "000001"),
    ("33072010", "DESODORANTE AEROSOL 150ML", "04", "000001"),
    ("48181000", "PAPEL HIGIENICO FOLHA DUPLA 12UN", "06", "200035"),
    ("96190000", "FRALDA INFANTIL G 30UN", "01", "200035"),
    ("96190000", "ABSORVENTE NOTURNO C/ABAS 8UN", "01", "200013"),
    ("38089419", "DESINFETANTE 500ML PINHO BRIL SILVESTRE", "01", "000001"),
    ("38089419", "AGUA SANITARIA 1L", "01", "200035"),
    ("38089197", "INSETICIDA AEROSOL 300ML", "01", "000001"),
    ("38089197", "INSETICIDA ELETRICO REFIL", "01", "000001"),
    ("34022000", "DETERGENTE LIQUIDO 500ML", "01", "000001"),
    ("34011900", "SABAO EM BARRA 5UN", "01", "200035"),
    # ---------------- farmácia
    ("30049069", "DIPIRONA 500MG 10CP", "04", "200032"),
    ("30049099", "PARACETAMOL 750MG 20CP", "04", "200032"),
    ("33049910", "PROTETOR SOLAR FPS50 120ML", "04", "000001"),
    ("29362710", "VITAMINA C 1G 10 COMPR EFERV", "01", "000001"),
    ("40141000", "PRESERVATIVO LUBRIFICADO 3UN", "01", "200030"),
    ("90183111", "SERINGA 3ML C/AGULHA", "01", "200030"),
    ("90251190", "TERMOMETRO DIGITAL", "01", "200004"),
    ("87131000", "CADEIRA DE RODAS DOBRAVEL", "06", "200007"),
    ("30059090", "ATADURA DE CREPE 10CM", "01", "000001"),
    # ---------------- autopeças e outros
    ("85071000", "BATERIA AUTOMOTIVA 60AH", "04", "000001"),
    ("40112090", "PNEU 275/80 R22.5", "04", "000001"),
    ("85111000", "VELA DE IGNICAO", "04", "000001"),
    ("40093100", "MANGUEIRA JARDIM 20M", "NC", "000001"),
    ("87112010", "MOTOCICLETA 160CC", "01", "000001"),
    ("23091000", "RACAO CAES ADULTO 15KG", "01", "000001"),
    ("49011000", "LIVRO INFANTIL", "06", "410008"),
]


@pytest.mark.parametrize("ncm,desc,pis,cclass", CASOS, ids=[c[1] for c in CASOS])
def test_enquadramento(ncm, desc, pis, cclass):
    assert sugerir_pis(ncm, desc) == pis, f"PIS/COFINS de {desc}"
    assert classificar_ibs(BASE, ncm, desc)["cclasstrib"] == cclass, f"cClassTrib de {desc}"


COERENCIA = [
    # (NCM informado, descrição, grave?, NCM a usar)
    ("30049099", "MELADO LUISALVENSE 400GR", True, "30049099"),
    ("04069030", "LINGUICA PERNIL CAMPEIRA", True, "04069030"),
    ("04089100", "OVOS EMBALADO", True, "04089100"),
    ("", "LEITE PREMIARE 1L SEMIDESNATADO", True, ""),
    ("27101921", "OLEO P/ASSOALHO DIESOLINE 700ML", True, "27101921"),
    ("19012100", "CAFE PILAO 500GR", True, "19012100"),
    ("17011100", "ACUCAR A.ALEGRE 5KG", False, "17011400"),
    ("04031000", "IOGURTE NATURAL VIGOR 150G", False, "04032000"),
    ("39249000", "SABONETEIRA PLASVALE REF.530", False, "39249000"),
    ("76151000", "ACUCAREIRO 5ESTR LUXO", False, "76151000"),
    ("30049099", "XAROPE GUACO COM MEL 120ML", False, "30049099"),
    ("16010000", "MORTADELA FRANGO AURORA 200G", False, "16010000"),
]


@pytest.mark.parametrize("ncm,desc,grave,usar", COERENCIA, ids=[c[1] for c in COERENCIA])
def test_coerencia_ncm(ncm, desc, grave, usar):
    from app.engine.coerencia import conferir
    c = conferir(ncm, desc)
    assert c.grave == grave and c.ncm == usar, c
