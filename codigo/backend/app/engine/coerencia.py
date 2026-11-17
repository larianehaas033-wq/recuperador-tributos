"""Conferência do NCM informado pelo cliente antes de aplicar qualquer regra.

Toda regra da lei é aplicada pelo NCM. Se o NCM está errado, o enquadramento sai errado junto (melado com NCM de
remédio vira "medicamento"; açúcar cristal com código extinto vira "tributado"). Por isso, antes de enquadrar:

1. NCM ausente: nada é comprovado pelo NCM.
2. NCM extinto com sucessor único: usa o código vigente e avisa.
3. NCM inexistente na tabela oficial vigente (baixada do Portal Único Siscomex na atualização diária): avisa.
4. Descrição incompatível com o NCM (ex.: "LINGUICA" num código de queijo): nada é comprovado e o cadastro pede a
   correção do NCM, em vez de sugerir CST ou cClassTrib a partir de um código errado.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from .. import config
from .comum import norm

# Códigos que deixaram de existir e têm um único sucessor para o produto típico de varejo.
EXTINTOS = {
    "04031000": ("04032000", "O NCM 0403.10.00 (iogurte) foi extinto em 01/04/2022; o código vigente é 0403.20.00."),
    "17011100": ("17011400", "O NCM 1701.11.00 foi extinto em 2017; açúcar cristal/refinado de cana é 1701.14.00 "
                             "(ou 1701.99.00, se refinado)."),
    "22029000": ("22029900", "O NCM 2202.90.00 foi extinto em 2017; o código vigente é 2202.99.00 "
                             "(ou 2202.91.00, se cerveja sem álcool)."),
}
# Códigos extintos sem sucessor único: só avisa.
# (aviso, grave): grave quando o código nem indica o produto (erro de digitação).
EXTINTOS_SEM_SUCESSOR = {
    "19012000": ("O NCM 1901.20.00 foi desdobrado em 1901.20.10 e 1901.20.90; atualize o cadastro.", False),
    "04013021": ("O NCM 0401.30.21 não existe mais; creme de leite é 0401.40.2x ou 0401.50.2x.", False),
    "19012100": ("O NCM 1901.21.00 não existe (café torrado é 0901.21.00).", True),
    "19020000": ("O NCM 1902.00.00 não existe; informe o código de 8 dígitos da posição 19.02.", True),
}

# Descrição que começa com (ou contém) o termo → o NCM tem de estar numa destas posições.
# (termo, modo, prefixos aceitos, o que é)
DESCRICAO_X_NCM = [
    ("LINGUICA", "inicio", ("1601", "0210", "0203", "0207", "1602"), "linguiça (16.01)"),
    ("MORTADELA", "inicio", ("1601", "1602"), "mortadela (16.01)"),
    ("SALSICHA", "inicio", ("1601",), "salsicha (16.01)"),
    ("MELADO", "inicio", ("1702", "1703", "2106"), "melado (17.02/17.03)"),
    ("LEITE FERM", "inicio", ("0403", "2202"), "leite fermentado (04.03)"),
    ("IOGURTE", "inicio", ("0403", "2202"), "iogurte (04.03)"),
    ("QUEIJO", "inicio", ("0406", "1901", "2106", "2005"), "queijo (04.06)"),
    ("REQUEIJAO", "inicio", ("0406", "1901"), "requeijão (04.06)"),
    ("OVOS", "inicio", ("0407",), "ovos com casca (04.07)"),
    ("CAFE ", "inicio", ("0901", "2101", "2106", "0902"), "café (09.01/21.01)"),
    ("ACUCAR", "inicio", ("1701", "1702", "1704", "2106"), "açúcar (17.01)"),
    ("PAO FRANCES", "inicio", ("1905", "1901"), "pão francês (1905.90.90)"),
    ("PIZZA", "inicio", ("1905", "2106", "1902"), "pizza (1905.90.90)"),
    ("LEITE COND", "inicio", ("0402", "1901"), "leite condensado (04.02)"),
    ("AGUA MIN", "inicio", ("2201",), "água mineral (22.01)"),
    ("CERVEJA", "inicio", ("2203", "2202"), "cerveja (22.03)"),
    ("SABONETE", "inicio", ("3401",), "sabonete (34.01)"),
    ("CREME DENTAL", "inicio", ("3306",), "creme dental (3306.10.00)"),
    ("GEL DENTAL", "inicio", ("3306",), "gel dental (3306.10.00)"),
    ("PAPEL HIG", "inicio", ("4818",), "papel higiênico (4818.10.00)"),
    ("FRALDA", "inicio", ("9619",), "fralda (9619.00.00)"),
    ("SHAMPOO", "inicio", ("3305", "3307", "3401", "3402", "3808"), "xampu (33.05)"),
    ("ARROZ", "inicio", ("1006", "1904", "1102", "1901", "2106"), "arroz (10.06)"),
    ("FEIJAO", "inicio", ("0713", "2004", "2005", "1602", "2106"), "feijão (07.13)"),
]

# NCM → termos que mostram que o produto não é o do código.
NCM_X_DESCRICAO = [
    (("3003", "3004"), (" MELADO", " RACAO", " BISCOITO", " REFRIGERANTE", " CERVEJA", " ACUCAR "),
     "medicamento (30.03/30.04)"),
    (("27101921",), ("ASSOALHO", "LUSTRA", "PEROBA", "LIMPA", "MOVEIS"), "óleo diesel (2710.19.21)"),
]


@dataclass
class Conferencia:
    ncm: str            # NCM a usar no enquadramento
    alerta: str = ""    # texto para o relatório
    grave: bool = False  # o NCM não serve para comprovar nada


@lru_cache(maxsize=1)
def tabela_vigente() -> frozenset[str]:
    """Códigos NCM de 8 dígitos vigentes, baixados do Portal Único Siscomex na atualização diária."""
    try:
        dados = json.loads((config.DATA_DIR / "ncm_vigente.json").read_text(encoding="utf-8"))
        return frozenset(dados.get("codigos", []))
    except (OSError, ValueError):
        return frozenset()


def conferir(ncm: str | None, descricao: str | None) -> Conferencia:
    ncm = (ncm or "").strip().replace(".", "")
    desc = norm(descricao)
    if not ncm or set(ncm) == {"0"}:
        return Conferencia("", "Produto sem NCM no cadastro: nada pode ser comprovado pelo código.", True)
    alerta = ""
    if ncm in EXTINTOS:
        ncm, alerta = EXTINTOS[ncm]
    elif ncm in EXTINTOS_SEM_SUCESSOR:
        alerta, grave = EXTINTOS_SEM_SUCESSOR[ncm]
        if grave:
            return Conferencia(ncm, alerta + " Corrija o NCM antes de aplicar o enquadramento.", True)
    else:
        vig = tabela_vigente()
        if vig and len(ncm) == 8 and ncm not in vig:
            alerta = f"O NCM {ncm[:4]}.{ncm[4:6]}.{ncm[6:]} não consta da tabela NCM vigente (Siscomex); confira."
    for termo, modo, prefixos, oque in DESCRICAO_X_NCM:
        t = termo.strip()
        if modo != "inicio":
            achou = t in desc
        elif " " in t:
            achou = desc.startswith(t)
        else:  # palavra isolada: a primeira palavra da descrição tem de ser exatamente ela (SABONETEIRA ≠ SABONETE)
            achou = (desc.split() or [""])[0] == t
        if achou and not ncm.startswith(prefixos):
            return Conferencia(ncm, f"A descrição indica {oque}, mas o NCM informado é {_fmt(ncm)}. Corrija o NCM "
                                    "antes de aplicar o enquadramento.", True)
    d = f" {desc} "
    for prefixos, termos, oque in NCM_X_DESCRICAO:
        if ncm.startswith(prefixos) and any(t in d for t in termos):
            return Conferencia(ncm, f"O NCM {_fmt(ncm)} é de {oque}, mas a descrição não corresponde. Corrija o NCM "
                                    "antes de aplicar o enquadramento.", True)
    return Conferencia(ncm, alerta, False)


def _fmt(ncm: str) -> str:
    return f"{ncm[:4]}.{ncm[4:6]}.{ncm[6:]}" if len(ncm) == 8 else ncm
