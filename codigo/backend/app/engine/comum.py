"""Tipos e regras comuns aos motores: crédito identificado, prazo de 5 anos e correção pela Selic."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import polars as pl

from .. import config

TEXT_COLS = ["cst_ibscbs", "cclasstrib", "origem", "periodo", "data", "chave", "num_doc", "ind_oper", "cnpj_part", "num_item", "cod_item",
             "descricao", "ncm", "cfop", "unidade", "cst_icms", "cst_pis", "cst_cofins", "modelo", "tipo_arquivo"]
NUM_COLS = ["qtd", "vl_item", "vl_desc", "vl_bc_icms", "aliq_icms", "vl_icms", "vl_bc_icms_st", "vl_icms_st",
            "vl_ipi", "vl_bc_pis", "aliq_pis", "vl_pis", "vl_bc_cofins", "aliq_cofins", "vl_cofins"]


@dataclass
class Credito:
    modulo: str
    tese: str
    tributo: str
    periodo: str | None
    data: str | None
    chave: str | None = None
    num_doc: str | None = None
    cod_item: str | None = None
    descricao: str | None = None
    ncm: str | None = None
    cfop: str | None = None
    cst_escriturado: str | None = None
    cst_correto: str | None = None
    base_original: float = 0.0
    base_correta: float = 0.0
    valor_pago: float = 0.0
    valor_recuperar: float = 0.0
    valor_restituivel: float = 0.0
    valor_saldo_credor: float = 0.0
    valor_corrigido: float = 0.0
    natureza: str = "RESTITUICAO"
    via: str = "ADMINISTRATIVO_FEDERAL"
    fundamento: str = ""
    confianca: str = "MEDIA"
    regra_codigo: str | None = None
    prescrito: int = 0
    excluido: int = 0
    observacao: str = ""

    def dict(self) -> dict:
        return asdict(self)


def norm(texto: str | None) -> str:
    """Maiúsculas, sem acento e sem pontuação repetida: para comparar descrição de produto com o texto da lei."""
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9/ -]", " ", t)).strip()


def r2(v: float) -> float:
    return round(float(v or 0.0) + 0.0, 2)


def to_frame(rows: list, cols: list[str]) -> pl.DataFrame:
    schema = {c: (pl.Float64 if c in NUM_COLS else pl.Utf8) for c in cols}
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame([tuple(r) for r in rows], schema=schema, orient="row").with_columns(
        [pl.col(c).fill_null(0.0) for c in cols if c in NUM_COLS]
    )


# ---------------------------------------------------------------- prazo de 5 anos

def data_corte(hoje: date) -> date:
    try:
        return hoje.replace(year=hoje.year - config.PRAZO_ANOS)
    except ValueError:  # 29/02
        return hoje.replace(year=hoje.year - config.PRAZO_ANOS, day=28)


def data_pagamento(periodo: str) -> date:
    """Vencimento estimado de PIS/COFINS: dia 25 do mês seguinte à competência."""
    a, m = int(periodo[:4]), int(periodo[5:7])
    a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return date(a, m, config.DIA_VENCIMENTO_PIS_COFINS)


def prescrito_restituicao(periodo: str | None, hoje: date) -> bool:
    if not periodo:
        return False
    return data_pagamento(periodo) < data_corte(hoje)


def prescrito_credito(data_doc: str | None, hoje: date) -> bool:
    if not data_doc:
        return False
    return date.fromisoformat(data_doc[:10]) < data_corte(hoje)


# ---------------------------------------------------------------- Selic

def _add_mes(a: int, m: int, n: int = 1) -> tuple[int, int]:
    t = a * 12 + (m - 1) + n
    return t // 12, t % 12 + 1


def fator_selic(pagamento: date, hoje: date, selic: dict[str, float]) -> float | None:
    """Percentual de correção: Selic acumulada do mês seguinte ao pagamento até o mês anterior ao da
    restituição, mais 1% no mês da restituição (Lei 9.250/1995, art. 39, § 4º).
    Devolve None se faltar alguma taxa mensal na tabela."""
    a, m = _add_mes(pagamento.year, pagamento.month, 1)
    fim = (hoje.year, hoje.month)
    total = 0.0
    while (a, m) < fim:
        k = f"{a:04d}-{m:02d}"
        if k not in selic:
            return None
        total += selic[k]
        a, m = _add_mes(a, m, 1)
    return total + 1.0 if (pagamento.year, pagamento.month) < fim else 0.0
