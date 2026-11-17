"""Carrega a base de regras (versão local atualizada ou a que vem com o programa)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .. import config


@dataclass
class Regra:
    codigo: str
    tipo: str
    grupo: str
    prefixos: tuple[str, ...]
    excecoes: tuple[str, ...]
    vigencia_ini: str
    vigencia_fim: str
    fundamento: str
    confianca: str
    observacao: str
    somente_revenda: bool
    palavras: tuple[str, ...] = ()
    palavras_excluir: tuple[str, ...] = ()

    @property
    def condicional(self) -> bool:
        return self.confianca == "CONDICIONAL"

    def cobre(self, ncm: str | None, data: str | None) -> bool:
        if not ncm:
            return False
        if data and not (self.vigencia_ini <= data <= self.vigencia_fim):
            return False
        if any(ncm.startswith(e) for e in self.excecoes):
            return False
        return any(ncm.startswith(p) for p in self.prefixos)


@dataclass
class BaseRegras:
    versao: str
    publicado_em: str
    regras: list[Regra]
    icms_modal: dict
    icms_ncm: list
    cfop: dict
    teses: dict
    ibs: dict = field(default_factory=dict)
    origem: str = "embutida"
    _cache: dict = field(default_factory=dict)

    def classificar(self, ncm: str | None, data: str | None, tipo: str) -> Regra | None:
        """Devolve a regra mais específica (prefixo mais longo) do tipo pedido."""
        key = (ncm, (data or "")[:7], tipo)
        if key in self._cache:
            return self._cache[key]
        melhor, tam = None, -1
        for r in self.regras:
            if r.tipo != tipo or not r.cobre(ncm, data):
                continue
            t = max(len(p) for p in r.prefixos if ncm.startswith(p))
            if t > tam:
                melhor, tam = r, t
        self._cache[key] = melhor
        return melhor

    def cfops(self, nome: str) -> frozenset[str]:
        return frozenset(self.cfop.get(nome, []))


def _parse(data: dict, origem: str) -> BaseRegras:
    regras = [
        Regra(
            codigo=r["codigo"], tipo=r["tipo"], grupo=r.get("grupo", ""),
            prefixos=tuple(r["ncm_prefixos"]), excecoes=tuple(r.get("excecoes", [])),
            vigencia_ini=r.get("vigencia_ini", "1900-01-01"), vigencia_fim=r.get("vigencia_fim", "2999-12-31"),
            fundamento=r["fundamento"], confianca=r.get("confianca", "MEDIA"),
            observacao=r.get("observacao", ""), somente_revenda=bool(r.get("somente_revenda", False)),
            palavras=tuple(r.get("palavras", [])), palavras_excluir=tuple(r.get("palavras_excluir", [])),
        )
        for r in data["regras"]
    ]
    return BaseRegras(
        versao=data["versao"], publicado_em=data.get("publicado_em", ""), regras=regras,
        icms_modal={x["uf"]: x for x in data.get("icms_aliquota_modal", [])},
        icms_ncm=data.get("icms_aliquota_ncm", []), cfop=data.get("cfop", {}), teses=data.get("teses", {}),
        ibs=data.get("ibs_cbs", {}), origem=origem,
    )


def validar(data: dict) -> list[str]:
    erros = []
    for k in ("versao", "regras", "cfop", "teses"):
        if k not in data:
            erros.append(f"campo obrigatório ausente: {k}")
    for r in data.get("regras", []):
        for k in ("codigo", "tipo", "ncm_prefixos", "fundamento"):
            if k not in r:
                erros.append(f"regra {r.get('codigo', '?')} sem {k}")
        if any(not str(p).isdigit() for p in r.get("ncm_prefixos", [])):
            erros.append(f"regra {r.get('codigo')} com prefixo de NCM inválido")
    return erros


def carregar() -> BaseRegras:
    embutida = json.loads(Path(config.RULES_BUNDLED).read_text(encoding="utf-8"))
    if config.RULES_LOCAL.exists():
        try:
            local = json.loads(config.RULES_LOCAL.read_text(encoding="utf-8"))
            compativel = config.versao_tupla(local.get("programa_minimo", "0")) <= config.versao_tupla(config.VERSION)
            if compativel and not validar(local) and local["versao"] >= embutida["versao"]:
                return _parse(local, "atualizada")
        except (json.JSONDecodeError, KeyError):
            pass
    return _parse(embutida, "embutida")
