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

# As listas ficam na base de regras (regras_base.json, seção "coerencia_ncm"), atualizada pelo repositório:
# nenhuma lista de NCM fica no código.
def _tabelas(base=None) -> dict:
    if base is None:
        from ..rules.loader import carregar
        base = carregar()
    return base.coerencia or {}


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


def conferir(ncm: str | None, descricao: str | None, base=None) -> Conferencia:
    tab = _tabelas(base)
    extintos = tab.get("extintos", {})
    sem_sucessor = tab.get("extintos_sem_sucessor", {})
    ncm = (ncm or "").strip().replace(".", "")
    desc = norm(descricao)
    if not ncm or set(ncm) == {"0"}:
        return Conferencia("", "Produto sem NCM no cadastro: nada pode ser comprovado pelo código.", True)
    alerta = ""
    if ncm in extintos:
        ncm, alerta = extintos[ncm]
    elif ncm in sem_sucessor:
        alerta, grave = sem_sucessor[ncm]
        if grave:
            return Conferencia(ncm, alerta + " Corrija o NCM antes de aplicar o enquadramento.", True)
    else:
        vig = tabela_vigente()
        if vig and len(ncm) == 8 and ncm not in vig:
            alerta = f"O NCM {ncm[:4]}.{ncm[4:6]}.{ncm[6:]} não consta da tabela NCM vigente (Siscomex); confira."
    for termo, modo, prefixos, oque in tab.get("descricao_x_ncm", []):
        prefixos = tuple(prefixos)
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
    for prefixos, termos, oque in tab.get("ncm_x_descricao", []):
        prefixos = tuple(prefixos)
        if ncm.startswith(prefixos) and any(t in d for t in termos):
            return Conferencia(ncm, f"O NCM {_fmt(ncm)} é de {oque}, mas a descrição não corresponde. Corrija o NCM "
                                    "antes de aplicar o enquadramento.", True)
    return Conferencia(ncm, alerta, False)


def _fmt(ncm: str) -> str:
    return f"{ncm[:4]}.{ncm[4:6]}.{ncm[6:]}" if len(ncm) == 8 else ncm


# Itens de controle interno (perda, descarte, quebra): não são mercadoria comprada para revenda nem insumo.
# Ex.: açougue que compra a carcaça inteira (alíquota zero), desossa e lança "OSSOS/PERDAS - DESCARTE".
def controle_interno(descricao: str | None, base=None) -> bool:
    d = f" {norm(descricao)} "
    return any(t in d for t in _tabelas(base).get("controle_interno", []))
