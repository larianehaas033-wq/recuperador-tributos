"""Tipos e regras comuns aos motores: crédito identificado, prazo de 5 anos e correção pela Selic."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import polars as pl

from .. import config

TEXT_COLS = ["cst_ibscbs", "cclasstrib", "origem", "periodo", "data", "chave", "num_doc", "ind_oper", "cnpj_part", "num_item", "cod_item",
             "descricao", "ncm", "cfop", "unidade", "cst_icms", "cst_pis", "cst_cofins", "modelo", "tipo_arquivo"]
NUM_COLS = ["qtd", "vl_item", "vl_desc", "vl_bc_icms", "aliq_icms", "vl_icms", "vl_bc_icms_st", "vl_icms_st",
            "vl_ipi", "vl_bc_pis", "aliq_pis", "vl_pis", "vl_bc_cofins", "aliq_cofins", "vl_cofins"]


ZERO = Decimal("0")
CENTAVO = Decimal("0.01")


def D(v) -> Decimal:
    """Valor monetário ou alíquota em Decimal. Floats vindos do arquivo passam pelo texto (repr), que devolve
    exatamente o número escrito no SPED/XML (até 15 dígitos significativos): 13.02 → Decimal('13.02')."""
    if v is None or v == "":
        return ZERO
    if isinstance(v, Decimal):
        return v
    if isinstance(v, float):
        return Decimal(repr(v))
    return Decimal(str(v))


def linhas(df):
    """iter_rows com todos os números convertidos para Decimal: nenhuma conta de dinheiro é feita em float."""
    for row in df.iter_rows(named=True):
        yield {k: (D(v) if isinstance(v, float) else v) for k, v in row.items()}


MONEY_FIELDS = ("base_original", "base_correta", "valor_pago", "valor_recuperar", "valor_restituivel",
                "valor_saldo_credor", "valor_corrigido")


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
    base_original: Decimal = ZERO
    base_correta: Decimal = ZERO
    valor_pago: Decimal = ZERO
    valor_recuperar: Decimal = ZERO
    valor_restituivel: Decimal = ZERO
    valor_saldo_credor: Decimal = ZERO
    valor_corrigido: Decimal = ZERO
    natureza: str = "RESTITUICAO"
    via: str = "ADMINISTRATIVO_FEDERAL"
    fundamento: str = ""
    confianca: str = "MEDIA"
    regra_codigo: str | None = None
    prescrito: int = 0
    excluido: int = 0
    observacao: str = ""

    def __post_init__(self):
        for f in MONEY_FIELDS:
            setattr(self, f, r2(getattr(self, f)))

    def __setattr__(self, nome, valor):
        if nome in MONEY_FIELDS:
            valor = r2(valor)
        object.__setattr__(self, nome, valor)

    def dict(self) -> dict:
        return asdict(self)


def norm(texto: str | None) -> str:
    """Maiúsculas, sem acento e sem pontuação repetida: para comparar descrição de produto com o texto da lei."""
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9/ -]", " ", t)).strip()


def termo(t: str) -> str:
    """Normaliza um termo de busca como a descrição, preservando espaço no início/fim (marca de palavra inteira):
    " NATA" casa com "NATA AURORA" mas não com "DESNATADO"."""
    t = t or ""
    return (" " if t[:1] == " " else "") + norm(t) + (" " if t[-1:] == " " else "")


def contem(desc_norm: str, termos) -> bool:
    """A descrição (já normalizada) contém algum dos termos? Compara com espaço nas bordas da descrição."""
    if not desc_norm or not termos:
        return False
    d = f" {desc_norm} "
    return any(t and t in d for t in termos)


def r2(v) -> Decimal:
    """Arredonda em centavos, meio para cima (regra de arredondamento dos tributos), sempre em Decimal."""
    return D(v).quantize(CENTAVO, rounding=ROUND_HALF_UP) + ZERO


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


def fator_selic(pagamento: date, hoje: date, selic: dict) -> Decimal | None:
    """Percentual de correção: Selic acumulada do mês seguinte ao pagamento até o mês anterior ao da
    restituição, mais 1% no mês da restituição (Lei 9.250/1995, art. 39, § 4º).
    Devolve None se faltar alguma taxa mensal na tabela."""
    a, m = _add_mes(pagamento.year, pagamento.month, 1)
    fim = (hoje.year, hoje.month)
    total = ZERO
    while (a, m) < fim:
        k = f"{a:04d}-{m:02d}"
        if k not in selic:
            return None
        total += D(selic[k])
        a, m = _add_mes(a, m, 1)
    return total + 1 if (pagamento.year, pagamento.month) < fim else ZERO
