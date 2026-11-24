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
    exige_descricao: bool = True  # condicional cuja descrição não confere é descartada (False: fica como possibilidade)

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
    coerencia: dict = field(default_factory=dict)
    icms_st_fora: list = field(default_factory=list)
    icms_st_dentro: list = field(default_factory=list)
    icms_st_cobertura: dict = field(default_factory=dict)
    origem: str = "embutida"
    _cache: dict = field(default_factory=dict)

    def fora_da_st(self, uf: str | None, ncm: str | None, data: str | None, descricao: str | None = None):
        """Produto sem ST na UF na data. Com a lista positiva da UF (Anexo 1-A do RICMS/SC), fora dela = fora da ST
        pela lei; além disso, os segmentos retirados por decreto (ex.: Decreto SC 982/2020)."""
        data = data or ""
        for r in self.icms_st_fora:
            if r.get("uf") == (uf or "").upper() and ncm and r["inicio"] <= data <= r.get("fim", "9999") \
                    and any(ncm.startswith(x) for x in r["ncm_prefixos"]):
                return r
        if ncm and self._tem_lista_st(uf, data):
            if not self._candidatos_st(uf, ncm, data):
                return {"segmento": "Produto fora da lista de ST da UF na data",
                        "fundamento": "RICMS/SC-01, Anexo 1-A (bens e mercadorias sujeitos à ST): o NCM não consta da "
                                      "lista vigente na data da operação"}
            if descricao and not self.na_st(uf, ncm, data, descricao):
                return {"segmento": "Produto fora da lista de ST da UF na data",
                        "fundamento": "RICMS/SC-01, Anexo 1-A: o NCM aparece na lista só para outro produto (ex.: 2106.90 "
                                      "só para bebida energética ou hidroeletrolítica), e a descrição não é desse produto"}
        return None

    def _tem_lista_st(self, uf, data=None):
        """A lista positiva da UF está completa a partir da data de cobertura (antes dela, só as exclusões valem)."""
        ini = self.icms_st_cobertura.get((uf or "").upper())
        return bool(ini) and (data is None or (data or "") >= ini)

    def _candidatos_st(self, uf, ncm, data):
        data = data or ""
        return [r for r in self.icms_st_dentro
                if r.get("uf") == (uf or "").upper() and not r.get("somente_porta_a_porta")
                and r.get("inicio", "") <= data <= r.get("fim", "9999")
                and any(ncm.startswith(x) for x in r["ncm_prefixos"])]

    def na_st(self, uf: str | None, ncm: str | None, data: str | None, descricao: str | None = None):
        """Item da lista de ST da UF vigente na data. Item com 'palavras' (NCM que também tem produto sem ST, ex.:
        2106.90 energético x suplemento) só vale se a descrição confere. None se não constar."""
        from ..engine.comum import contem, norm, termo  # noqa: PLC0415
        if not ncm:
            return None
        desc = norm(descricao)
        sem_palavra = None
        for r in self._candidatos_st(uf, ncm, data):
            if r.get("palavras_excluir") and desc and contem(desc, tuple(termo(x) for x in r["palavras_excluir"])):
                continue
            pal = r.get("palavras")
            if not pal:
                sem_palavra = sem_palavra or r
            elif desc and contem(desc, tuple(termo(x) for x in pal)):
                return r
        return sem_palavra

    def icms_beneficios_uf(self, uf: str | None) -> bool:
        """A base já tem os benefícios de ICMS (isenção/redução/crédito presumido) da UF? Ainda não para nenhuma."""
        return False

    def classificar(self, ncm: str | None, data: str | None, tipo: str, descricao: str | None = None) -> Regra | None:
        """Devolve a regra do tipo pedido que melhor se aplica ao produto.

        Regra condicional (depende de 'Ex', destinação ou do tipo de produto) só vale quando a descrição confere com
        o texto legal; sem descrição, fica como possibilidade a conferir. Regra cuja descrição bate num termo de
        exclusão é descartada. Empate: a mais específica (condicional que conferiu > só NCM; prefixo mais longo)."""
        from ..engine.comum import contem, norm
        desc = norm(descricao) if descricao else ""
        key = (ncm, (data or "")[:7], tipo, desc)
        if key in self._cache:
            return self._cache[key]
        melhor, nota = None, (-1, -1)
        for r in self.regras:
            if r.tipo != tipo or not r.cobre(ncm, data):
                continue
            if desc and contem(desc, r.palavras_excluir):
                continue
            if not r.condicional:
                peso = 1
            elif desc and r.palavras:
                if contem(desc, r.palavras):
                    peso = 2
                elif r.exige_descricao:
                    continue  # a descrição mostra que não é o produto da lei
                else:
                    peso = 0  # depende da destinação: fica como possibilidade (fornecedor pode comprovar)
            else:
                peso = 0
            n = (peso, max(len(p) for p in r.prefixos if ncm.startswith(p)))
            if n > nota:
                melhor, nota = r, n
        self._cache[key] = melhor
        return melhor

    def cfops(self, nome: str) -> frozenset[str]:
        return frozenset(self.cfop.get(nome, []))


def _parse(data: dict, origem: str) -> BaseRegras:
    from ..engine.comum import termo
    ibs = data.get("ibs_cbs", {})
    for r in ibs.get("regras", []):
        r["_palavras"] = tuple(termo(x) for x in r.get("palavras", []))
        r["_excluir"] = tuple(termo(x) for x in r.get("palavras_excluir", []))
    regras = [
        Regra(
            codigo=r["codigo"], tipo=r["tipo"], grupo=r.get("grupo", ""),
            prefixos=tuple(r["ncm_prefixos"]), excecoes=tuple(r.get("excecoes", [])),
            vigencia_ini=r.get("vigencia_ini", "1900-01-01"), vigencia_fim=r.get("vigencia_fim", "2999-12-31"),
            fundamento=r["fundamento"], confianca=r.get("confianca", "MEDIA"),
            observacao=r.get("observacao", ""), somente_revenda=bool(r.get("somente_revenda", False)),
            palavras=tuple(termo(x) for x in r.get("palavras", [])),
            palavras_excluir=tuple(termo(x) for x in r.get("palavras_excluir", [])),
            exige_descricao=bool(r.get("exige_descricao", True)),
        )
        for r in data["regras"]
    ]
    return BaseRegras(
        versao=data["versao"], publicado_em=data.get("publicado_em", ""), regras=regras,
        icms_modal={x["uf"]: x for x in data.get("icms_aliquota_modal", [])},
        icms_ncm=data.get("icms_aliquota_ncm", []), cfop=data.get("cfop", {}), teses=data.get("teses", {}),
        ibs=ibs, coerencia=data.get("coerencia_ncm", {}), origem=origem,
        icms_st_fora=data.get("icms_st_excluidos", []),
        icms_st_dentro=data.get("icms_st_incluidos", []),
        icms_st_cobertura=data.get("icms_st_cobertura", {}),
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
            # compara numericamente: "2026.11.17.10" é mais nova que "2026.11.17.9"
            if (compativel and not validar(local)
                    and config.versao_tupla(local["versao"]) >= config.versao_tupla(embutida["versao"])):
                # o que a versão baixada não trouxer (tese, seção nova) vem da base embutida no programa
                for k, v in embutida.items():
                    if k not in local:
                        local[k] = v
                    elif isinstance(v, dict) and isinstance(local[k], dict):
                        local[k] = {**v, **local[k]}
                return _parse(local, "atualizada")
        except (json.JSONDecodeError, KeyError):
            pass
    return _parse(embutida, "embutida")
