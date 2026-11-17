"""Motor de ICMS e cruzamento XML x SPED.

Teses:
  ICMS_ST_TRIBUTADO_SAIDA      produto com ST na compra e ICMS próprio destacado na venda
  ICMS_ST_RESSARCIMENTO        venda ao consumidor abaixo da base presumida da ST (STF, Tema 201)
  ICMS_ALIQ_ACIMA              alíquota aplicada maior que a interna da UF
  ICMS_CREDITO_MENOR_DESTAQUE  ICMS destacado no XML de compra maior que o escriturado
  ICMS_NOTA_NAO_ESCRITURADA    XML de compra sem registro na EFD ICMS/IPI
  RISCO_SAIDA_NAO_ESCRITURADA  XML de venda sem registro na EFD ICMS/IPI
"""
from __future__ import annotations

from datetime import date

import polars as pl

from ..rules.loader import BaseRegras
from .comum import Credito, r2

ST_CST = {"10", "30", "60", "70"}
ST_CSOSN = {"201", "202", "203", "500"}
TRIB_CST = {"00", "20"}
INICIO_TEMA_201 = "2016-10-19"


def _eh_st(cst: str | None) -> bool:
    if not cst:
        return False
    return cst in ST_CSOSN or (len(cst) >= 2 and cst[-2:] in ST_CST and cst not in ("101", "102", "103", "300", "400", "900"))


def _tributado(cst: str | None) -> bool:
    return bool(cst) and len(cst) in (2, 3) and cst[-2:] in TRIB_CST and cst not in ("900",)


class MotorIcms:
    def __init__(self, base: BaseRegras, empresa: dict, sped_entradas: pl.DataFrame, xml_itens: pl.DataFrame,
                 sped_notas: pl.DataFrame, xml_notas: pl.DataFrame, periodos_sped_icms: set[str],
                 revisoes: dict, hoje: date, produtos: dict | None = None):
        self.base = base
        self.empresa = empresa
        self.sped_entradas = sped_entradas
        self.xml_itens = xml_itens
        self.sped_notas = sped_notas
        self.xml_notas = xml_notas
        self.periodos = periodos_sped_icms
        self.revisoes = revisoes
        self.hoje = hoje
        self.uf = (empresa.get("uf") or "").upper()
        self.modal = base.icms_modal.get(self.uf)
        self.cfop_revenda = base.cfops("saida_revenda")
        self.fund = {k: v["fundamento"] for k, v in base.teses.items()}
        self.produtos = produtos or {}
        self.cfop_entrada = base.cfops("entrada_credito")

    def _destino_nota(self, chave: str) -> tuple[str, str]:
        """Comprova a destinação da compra pelos itens escriturados (C170) da própria nota na EFD ICMS/IPI."""
        itens = self.sped_entradas.filter(pl.col("chave") == chave)
        if not itens.height:
            return "BAIXA", "Não comprovado automaticamente: a nota não tem itens escriturados (C170)."
        for row in itens.iter_rows(named=True):
            tipo = (self.produtos.get(row["cod_item"], {}).get("tipo_item") or "").zfill(2)
            if row["cfop"] not in self.cfop_entrada or tipo in ("07", "08", "09"):
                return "BAIXA", f"Item {row['cod_item']} escriturado com CFOP {row['cfop']}: pode ser uso e consumo."
        return "ALTA", "Todos os itens da nota foram escriturados como revenda ou industrialização."

    def executar(self) -> tuple[list[Credito], list[str]]:
        avisos = []
        out: list[Credito] = []
        saidas = self.xml_itens.filter(pl.col("ind_oper") == "1")
        if not self.xml_itens.height:
            avisos.append("Sem XMLs importados: as teses de ICMS que dependem do item da venda não foram analisadas.")
        out += self._st_tributado(saidas)
        if self.modal:
            out += self._ressarcimento(saidas)
            out += self._aliquota(saidas)
        else:
            avisos.append(f"Alíquota interna da UF '{self.uf or '?'}' não cadastrada: ressarcimento de ST e "
                          "alíquota não foram analisados.")
        if self.periodos and self.xml_notas.height:
            out += self._cruzamento()
        elif self.xml_notas.height:
            avisos.append("Sem EFD ICMS/IPI importada: o cruzamento XML x SPED não foi feito.")
        return out, avisos

    # -------------------------------------------------------------- ST tributada de novo
    def _itens_st(self) -> tuple[dict, dict]:
        """Produtos que entraram com ST: pelo código próprio (EFD ICMS/IPI) e pelo NCM (XMLs de compra)."""
        por_cod, por_ncm = {}, {}
        for row in self.sped_entradas.iter_rows(named=True):
            if _eh_st(row["cst_icms"]):
                d = por_cod.get(row["cod_item"])
                por_cod[row["cod_item"]] = min(d, row["data"]) if d else row["data"]
        ent_xml = self.xml_itens.filter(pl.col("ind_oper") == "0")
        for row in ent_xml.iter_rows(named=True):
            if _eh_st(row["cst_icms"]) and row["ncm"]:
                d = por_ncm.get(row["ncm"])
                por_ncm[row["ncm"]] = min(d, row["data"]) if d else row["data"]
        return por_cod, por_ncm

    def _st_tributado(self, saidas: pl.DataFrame) -> list[Credito]:
        por_cod, por_ncm = self._itens_st()
        if not por_cod and not por_ncm:
            return []
        out = []
        df = saidas.filter(pl.col("vl_icms") > 0)
        for row in df.iter_rows(named=True):
            if not _tributado(row["cst_icms"]):
                continue
            if row["cfop"] and row["cfop"] not in self.cfop_revenda:
                continue
            data = row["data"] or ""
            conf = None
            if row["cod_item"] in por_cod and por_cod[row["cod_item"]] <= data:
                conf = "ALTA"
            elif row["ncm"] in por_ncm and por_ncm[row["ncm"]] <= data:
                conf = "MEDIA"
            if not conf or self.revisoes.get((row["ncm"] or "", "ICMS_ST_TRIBUTADO_SAIDA")) == "DESCARTADO":
                continue
            out.append(Credito(
                modulo="ICMS", tese="ICMS_ST_TRIBUTADO_SAIDA", tributo="ICMS", periodo=row["periodo"], data=data,
                chave=row["chave"], num_doc=row["num_doc"], cod_item=row["cod_item"], descricao=row["descricao"],
                ncm=row["ncm"], cfop=row["cfop"], cst_escriturado=row["cst_icms"], cst_correto="60",
                base_original=r2(row["vl_bc_icms"]), base_correta=0.0, valor_pago=r2(row["vl_icms"]),
                valor_recuperar=r2(row["vl_icms"]), natureza="RESTITUICAO", via="ADMINISTRATIVO_ESTADUAL",
                fundamento=self.fund["ICMS_ST_TRIBUTADO_SAIDA"], confianca=conf, regra_codigo="ST_ENTRADA",
                observacao=("Produto entrou com ICMS-ST com o mesmo código." if conf == "ALTA" else
                             "Não comprovado automaticamente: só o NCM coincide com uma compra com ST, não o código do produto."),
            ))
        return out

    # -------------------------------------------------------------- ressarcimento ST (Tema 201)
    def _ressarcimento(self, saidas: pl.DataFrame) -> list[Credito]:
        ent = self.sped_entradas.filter((pl.col("vl_bc_icms_st") > 0) & (pl.col("qtd") > 0)
                                        & (pl.col("data") >= INICIO_TEMA_201))
        if not ent.height:
            return []
        base_unit = ent.group_by(["cod_item"]).agg(
            (pl.col("vl_bc_icms_st").sum() / pl.col("qtd").sum()).alias("bc_unit"),
            pl.col("unidade").first().str.to_uppercase().alias("un_ent"),
        )
        vendas = saidas.filter((pl.col("modelo") == "65") & (pl.col("qtd") > 0)
                               & (pl.col("data") >= INICIO_TEMA_201))
        vendas = vendas.filter(pl.col("cst_icms").map_elements(_eh_st, return_dtype=pl.Boolean))
        if not vendas.height:
            return []
        j = vendas.join(base_unit, on="cod_item", how="inner").filter(
            pl.col("unidade").str.to_uppercase() == pl.col("un_ent")
        )
        if not j.height:
            return []
        aliq = self.modal["aliquota"]
        agg = j.group_by(["cod_item", "periodo"]).agg(
            pl.col("qtd").sum(), (pl.col("vl_item") - pl.col("vl_desc")).sum().alias("vl_venda"),
            pl.col("bc_unit").first(), pl.col("ncm").first(), pl.col("descricao").first(), pl.col("data").min(),
        ).with_columns((pl.col("bc_unit") * pl.col("qtd")).alias("bc_presumida"))
        out = []
        for row in agg.iter_rows(named=True):
            dif = row["bc_presumida"] - row["vl_venda"]
            if dif <= 0.01 * row["bc_presumida"]:
                continue
            valor = dif * aliq / 100
            out.append(Credito(
                modulo="ICMS", tese="ICMS_ST_RESSARCIMENTO", tributo="ICMS", periodo=row["periodo"],
                data=row["data"], cod_item=row["cod_item"], descricao=row["descricao"], ncm=row["ncm"],
                cst_escriturado="60", cst_correto="60", base_original=r2(row["bc_presumida"]),
                base_correta=r2(row["vl_venda"]), valor_pago=r2(row["bc_presumida"] * aliq / 100),
                valor_recuperar=r2(valor), natureza="RESTITUICAO", via="ADMINISTRATIVO_ESTADUAL",
                fundamento=self.fund["ICMS_ST_RESSARCIMENTO"], confianca="MEDIA", regra_codigo="TEMA_201",
                observacao=(f"Base presumida média {row['bc_unit']:.2f}/un x {row['qtd']:.0f} un vendidas por "
                            f"{row['vl_venda']:.2f}. Alíquota interna {aliq:.0f}% ({self.uf}). Depende de "
                            "regulamentação da UF."),
            ))
        return out

    # -------------------------------------------------------------- alíquota
    def _aliq_esperada(self, ncm: str | None) -> tuple[float, str, str]:
        melhor = None
        for r in self.base.icms_ncm:
            if r.get("uf") == self.uf and ncm and any(ncm.startswith(p) for p in r["ncm_prefixos"]):
                if not melhor or max(map(len, r["ncm_prefixos"])) > max(map(len, melhor["ncm_prefixos"])):
                    melhor = r
        if melhor:
            return melhor["aliquota"], melhor["fundamento"], melhor.get("confianca", "MEDIA")
        return self.modal["aliquota"], self.modal["fundamento"], "BAIXA"

    def _aliquota(self, saidas: pl.DataFrame) -> list[Credito]:
        df = saidas.filter(pl.col("cfop").str.starts_with("5") & (pl.col("aliq_icms") > 0) & (pl.col("vl_bc_icms") > 0))
        out = []
        for row in df.iter_rows(named=True):
            if not _tributado(row["cst_icms"]):
                continue
            esperada, fund, conf = self._aliq_esperada(row["ncm"])
            if row["aliq_icms"] <= esperada + 0.01:
                continue
            if self.revisoes.get((row["ncm"] or "", "ICMS_ALIQ_ACIMA")) == "DESCARTADO":
                continue
            if self.revisoes.get((row["ncm"] or "", "ICMS_ALIQ_ACIMA")) == "CONFIRMADO":
                conf = "ALTA"
            valor = row["vl_bc_icms"] * (row["aliq_icms"] - esperada) / 100
            out.append(Credito(
                modulo="ICMS", tese="ICMS_ALIQ_ACIMA", tributo="ICMS", periodo=row["periodo"], data=row["data"],
                chave=row["chave"], num_doc=row["num_doc"], cod_item=row["cod_item"], descricao=row["descricao"],
                ncm=row["ncm"], cfop=row["cfop"], cst_escriturado=row["cst_icms"], cst_correto=row["cst_icms"],
                base_original=r2(row["vl_bc_icms"]), base_correta=r2(row["vl_bc_icms"]), valor_pago=r2(row["vl_icms"]),
                valor_recuperar=r2(valor), natureza="RESTITUICAO", via="ADMINISTRATIVO_ESTADUAL",
                fundamento=f"{self.fund['ICMS_ALIQ_ACIMA']} Referência: {fund}.", confianca=conf,
                regra_codigo="ICMS_ALIQ",
                observacao=f"Aplicada {row['aliq_icms']:.2f}%, esperada {esperada:.2f}%."
                           + (" Sem regra específica para o NCM: pode haver alíquota diferenciada legítima."
                              if conf == "BAIXA" else ""),
            ))
        return out

    # -------------------------------------------------------------- cruzamento XML x SPED
    def _cruzamento(self) -> list[Credito]:
        sped = {r["chave"]: r for r in self.sped_notas.iter_rows(named=True) if r["chave"]}
        out = []
        xml = self.xml_notas.filter(pl.col("periodo").is_in(list(self.periodos)) & (pl.col("cancelada") == 0))
        for n in xml.iter_rows(named=True):
            s = sped.get(n["chave"])
            if n["ind_oper"] == "0" and n["ind_emit"] == "1":
                if s is None:
                    out.append(Credito(
                        modulo="CRUZAMENTO", tese="ICMS_NOTA_NAO_ESCRITURADA", tributo="ICMS", periodo=n["periodo"],
                        data=n["data"], chave=n["chave"], num_doc=n["numero"], valor_pago=r2(n["vl_doc"]),
                        valor_recuperar=r2(n["vl_icms"]), natureza="CREDITO_EXTEMPORANEO",
                        via="ADMINISTRATIVO_ESTADUAL", fundamento=self.fund["ICMS_NOTA_NAO_ESCRITURADA"],
                        confianca="BAIXA", regra_codigo="XML_X_SPED",
                        observacao=f"Emitente {n['cnpj_emit']}. Confirmar entrada e destinação da mercadoria.",
                    ))
                elif n["vl_icms"] > (s["vl_icms"] or 0) + 0.01:
                    conf, motivo = self._destino_nota(n["chave"])
                    out.append(Credito(
                        modulo="CRUZAMENTO", tese="ICMS_CREDITO_MENOR_DESTAQUE", tributo="ICMS", periodo=n["periodo"],
                        data=n["data"], chave=n["chave"], num_doc=n["numero"], base_original=r2(s["vl_icms"] or 0),
                        base_correta=r2(n["vl_icms"]), valor_pago=r2(n["vl_icms"]),
                        valor_recuperar=r2(n["vl_icms"] - (s["vl_icms"] or 0)), natureza="CREDITO_EXTEMPORANEO",
                        via="ADMINISTRATIVO_ESTADUAL", fundamento=self.fund["ICMS_CREDITO_MENOR_DESTAQUE"],
                        confianca=conf, regra_codigo="XML_X_SPED",
                        observacao=f"XML destaca {n['vl_icms']:.2f}; EFD escriturou {(s['vl_icms'] or 0):.2f}. {motivo}",
                    ))
            elif n["ind_oper"] == "1" and n["ind_emit"] == "0" and s is None:
                out.append(Credito(
                    modulo="CRUZAMENTO", tese="RISCO_SAIDA_NAO_ESCRITURADA", tributo="ICMS", periodo=n["periodo"],
                    data=n["data"], chave=n["chave"], num_doc=n["numero"], valor_pago=r2(n["vl_doc"]),
                    valor_recuperar=r2(n["vl_icms"]), natureza="RISCO", via="ADMINISTRATIVO_ESTADUAL",
                    fundamento=self.fund["RISCO_SAIDA_NAO_ESCRITURADA"], confianca="MEDIA", regra_codigo="XML_X_SPED",
                    observacao=f"Valor da nota {n['vl_doc']:.2f}.",
                ))
        return out
