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
from decimal import Decimal

import polars as pl

from ..rules.loader import BaseRegras
from .comum import CENTAVO, ZERO, Credito, D, linhas, r2

ST_CST = {"10", "30", "60", "70"}
ST_CSOSN = {"201", "202", "203", "500"}
TRIB_CST = {"00", "20"}
USO_CONSUMO_CFOP = {"1407", "2407", "1556", "2556", "3556"}
INICIO_TEMA_201 = "2016-10-19"


def _eh_st(cst: str | None) -> bool:
    """CST de ICMS com substituição tributária.
    EFD e XML de regime normal: 3 dígitos = origem + CST (Tabela B) → ST se o CST for 10, 30, 60 ou 70.
    "500" na EFD é origem 5 + CST 00 (tributado), NÃO o CSOSN 500.
    CSOSN (Simples) vem com 4 dígitos (origem + CSOSN) → ST se 201, 202, 203 ou 500. Em XMLs antigos o CSOSN
    veio sem a origem (3 dígitos): só 201/202/203 são inequívocos (não existe CST 01/02/03)."""
    if not cst:
        return False
    if len(cst) == 4:
        return cst[1:] in ST_CSOSN
    if len(cst) == 3:
        return cst[1:] in ST_CST or cst in ("201", "202", "203")
    return cst in ST_CST


def _fps(desc: str):
    """Número do FPS na descrição (ex.: 'FPS 50', 'FPS50', 'FPS-30'); None se não houver."""
    import re
    m = re.search(r"\bFPS\s*-?\s*(\d{1,3})", desc or "")
    return int(m.group(1)) if m else None


def _tributado(cst: str | None) -> bool:
    return bool(cst) and len(cst) in (2, 3) and cst[-2:] in TRIB_CST and cst not in ("900",)


class MotorIcms:
    def __init__(self, base: BaseRegras, empresa: dict, sped_entradas: pl.DataFrame, xml_itens: pl.DataFrame,
                 sped_notas: pl.DataFrame, xml_notas: pl.DataFrame, periodos_sped_icms: set[str],
                 revisoes: dict, hoje: date, produtos: dict | None = None, analitico: list | None = None,
                 apuracoes: list | None = None):
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
        self.analitico = analitico or []
        self.apuracoes = apuracoes or []

    def _destino_nota(self, chave: str) -> tuple[str, str]:
        """Comprova a destinação da compra pelos itens escriturados (C170) da própria nota na EFD ICMS/IPI."""
        itens = self.sped_entradas.filter(pl.col("chave") == chave)
        if not itens.height:
            return "BAIXA", "Não comprovado automaticamente: a nota não tem itens escriturados (C170)."
        for row in linhas(itens):
            tipo = (self.produtos.get(row["cod_item"], {}).get("tipo_item") or "").zfill(2)
            if row["cfop"] not in self.cfop_entrada or tipo in ("07", "08", "09"):
                return "BAIXA", f"Item {row['cod_item']} escriturado com CFOP {row['cfop']}: pode ser uso e consumo."
        return "ALTA", "Todos os itens da nota foram escriturados como revenda ou industrialização."

    def _credito_nao_apurado(self) -> list[Credito]:
        """ICMS creditado nas notas de entrada (C190) que não chegou à apuração (E110, VL_TOT_CREDITOS):
        o crédito foi escriturado no documento e não foi aproveitado no mês."""
        if self.empresa.get("regime") == "SIMPLES_NACIONAL":
            return []
        docs: dict[str, Decimal] = {}
        for a in self.analitico:
            if a.get("ind_oper") == "0" and not a.get("cancelada") and a.get("cfop") not in USO_CONSUMO_CFOP:
                docs[a["periodo"]] = docs.get(a["periodo"], ZERO) + D(a.get("vl_icms"))
        out = []
        for ap in self.apuracoes:
            per = ap["periodo"]
            dif = docs.get(per, ZERO) - D(ap.get("creditos"))
            if dif <= max(D("1.00"), docs.get(per, ZERO) * D("0.005")):
                continue
            out.append(Credito(
                modulo="ICMS", tese="ICMS_CREDITO_NAO_APURADO", tributo="ICMS", periodo=per, data=f"{per}-01",
                base_original=r2(D(ap.get("creditos"))), base_correta=r2(docs[per]), valor_pago=ZERO,
                valor_recuperar=r2(dif), natureza="CREDITO_EXTEMPORANEO", via="ADMINISTRATIVO_ESTADUAL",
                fundamento=self.fund.get("ICMS_CREDITO_NAO_APURADO", ""), confianca="MEDIA", regra_codigo="E110_X_C190",
                observacao=(f"ICMS das entradas escrituradas no mês {docs[per]:.2f}; créditos levados ao E110 "
                            f"{D(ap.get('creditos')):.2f}. Confirme se a diferença não foi estornada por ajuste "
                            "(E111) antes de lançar o crédito extemporâneo."),
            ))
        return out

    def _st_tributado_c190(self) -> list[Credito]:
        """Pelo resumo de cada venda no SPED Fiscal (C190): linha que a própria empresa declarou como ST
        (CST 60/CSOSN 500 ou CFOP 5405/6404) e mesmo assim debitou ICMS próprio."""
        out = []
        for a in self.analitico:
            if (a.get("ind_oper") != "1" or a.get("ind_emit") != "0" or a.get("cancelada")
                    or D(a.get("vl_icms")) <= 0):
                continue
            cst = a.get("cst_icms") or ""
            cst_st = _eh_st(cst)  # "500" no C190 é origem 5 + CST 00, não ST
            cfop_st = a.get("cfop") in ("5405", "6404")
            if not (cst_st or cfop_st):
                continue
            ambos = cst_st and cfop_st
            out.append(Credito(
                modulo="ICMS", tese="ICMS_ST_TRIBUTADO_C190", tributo="ICMS", periodo=a.get("periodo"),
                data=a.get("data"), chave=a.get("chave"), num_doc=a.get("numero"), cfop=a.get("cfop"),
                cst_escriturado=cst, cst_correto=cst if cst_st else "x60", base_original=D(a.get("vl_bc_icms")),
                base_correta=ZERO, valor_pago=D(a.get("vl_icms")), valor_recuperar=D(a.get("vl_icms")),
                natureza="RESTITUICAO", via="ADMINISTRATIVO_ESTADUAL",
                fundamento=self.fund.get("ICMS_ST_TRIBUTADO_C190", ""), confianca="ALTA" if ambos else "BAIXA",
                regra_codigo="C190_ST",
                observacao=(f"Resumo da nota (C190): CST {cst}, CFOP {a.get('cfop')}, ICMS debitado "
                            f"{D(a.get('vl_icms')):.2f}." + ("" if ambos else
                            " Só um dos indicadores de ST (CST ou CFOP) está presente: confira se o produto tem ST."))))
        return out

    def executar(self) -> tuple[list[Credito], list[str]]:
        avisos = []
        out: list[Credito] = []
        out += self._st_tributado_c190()
        out += self._credito_nao_apurado()
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
        for row in linhas(self.sped_entradas):
            if _eh_st(row["cst_icms"]):
                d = por_cod.get(row["cod_item"])
                por_cod[row["cod_item"]] = min(d, row["data"]) if d else row["data"]
        ent_xml = self.xml_itens.filter(pl.col("ind_oper") == "0")
        for row in linhas(ent_xml):
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
        for row in linhas(df):
            if not _tributado(row["cst_icms"]):
                continue
            if row["cfop"] and row["cfop"] not in self.cfop_revenda:
                continue
            data = row["data"] or ""
            conf = None
            if self.base.fora_da_st(self.uf, row["ncm"], data, row["descricao"]):
                continue  # produto fora da ST na UF: venda tributada é o correto, mesmo que a compra tenha vindo com CST 60
            if row["cod_item"] in por_cod and por_cod[row["cod_item"]] <= data:
                conf = "ALTA"
            elif row["ncm"] in por_ncm and por_ncm[row["ncm"]] <= data:
                conf = "MEDIA"
            if not conf or self.revisoes.get((row["ncm"] or "", "ICMS_ST_TRIBUTADO_SAIDA")) == "DESCARTADO":
                continue
            item_st = self.base.na_st(self.uf, row["ncm"], data, row["descricao"])
            obs_st = ""
            if not item_st:
                conf = "BAIXA"  # sem a lei dizendo que o produto tem ST na UF, a compra com CST 60 não basta
                obs_st = (f" Não comprovado: o NCM está na lista de ST de {self.uf}, mas a descrição não confere com o "
                          "item da lista (conferir o CEST)." if self.base._tem_lista_st(self.uf, data) else
                          f" Não comprovado: a lista de ST de {self.uf} ainda não está na base do programa.")
            elif conf == "ALTA":
                obs_st = f" CEST {item_st.get('cest', '')}: {item_st.get('descricao', '')[:90]}."
            out.append(Credito(
                modulo="ICMS", tese="ICMS_ST_TRIBUTADO_SAIDA", tributo="ICMS", periodo=row["periodo"], data=data,
                chave=row["chave"], num_doc=row["num_doc"], num_item=row.get("num_item"), cod_item=row["cod_item"], descricao=row["descricao"],
                ncm=row["ncm"], cfop=row["cfop"], cst_escriturado=row["cst_icms"], cst_correto="60",
                base_original=r2(row["vl_bc_icms"]), base_correta=0.0, valor_pago=r2(row["vl_icms"]),
                valor_recuperar=r2(row["vl_icms"]), natureza="RESTITUICAO", via="ADMINISTRATIVO_ESTADUAL",
                fundamento=self.fund["ICMS_ST_TRIBUTADO_SAIDA"], confianca=conf, regra_codigo="ST_ENTRADA",
                observacao=(("Produto entrou com ICMS-ST com o mesmo código." if row["cod_item"] in por_cod else
                             "Só o NCM coincide com uma compra com ST, não o código do produto.") + obs_st
                            + (f" Produto na ST: {item_st.get('segmento', '')} ({item_st.get('fundamento', '')})."
                               if item_st else "")),
            ))
        return out

    # -------------------------------------------------------------- ressarcimento ST (Tema 201)
    def _ressarcimento(self, saidas: pl.DataFrame) -> list[Credito]:
        ent = self.sped_entradas.filter((pl.col("vl_bc_icms_st") > 0) & (pl.col("qtd") > 0)
                                        & (pl.col("data") >= INICIO_TEMA_201))
        if not ent.height:
            return []
        # base presumida média por unidade, somada em Decimal
        acum: dict[str, list] = {}
        for r in linhas(ent):
            a = acum.setdefault(r["cod_item"], [ZERO, ZERO, (r["unidade"] or "").upper()])
            a[0] += r["vl_bc_icms_st"]
            a[1] += r["qtd"]
        vendas = saidas.filter((pl.col("modelo") == "65") & (pl.col("qtd") > 0)
                               & (pl.col("data") >= INICIO_TEMA_201))
        vendas = vendas.filter(pl.col("cst_icms").map_elements(_eh_st, return_dtype=pl.Boolean))
        if not vendas.height:
            return []
        grupos: dict[tuple, dict] = {}
        for r in linhas(vendas):
            a = acum.get(r["cod_item"])
            if not a or a[1] <= 0 or (r["unidade"] or "").upper() != a[2]:
                continue
            g = grupos.setdefault((r["cod_item"], r["periodo"]), dict(
                cod_item=r["cod_item"], periodo=r["periodo"], qtd=ZERO, vl_venda=ZERO, bc_unit=a[0] / a[1],
                ncm=r["ncm"], descricao=r["descricao"], data=r["data"]))
            g["qtd"] += r["qtd"]
            g["vl_venda"] += r["vl_item"] - r["vl_desc"]
            g["data"] = min(g["data"] or r["data"], r["data"] or g["data"])
        out = []
        for row in grupos.values():
            if self.base.fora_da_st(self.uf, row["ncm"], row["data"], row["descricao"]):
                continue
            row["bc_presumida"] = row["bc_unit"] * row["qtd"]
            dif = row["bc_presumida"] - row["vl_venda"]
            if dif <= CENTAVO * row["bc_presumida"]:
                continue
            aliq = self._aliq_esperada(row["ncm"], row["descricao"])[0]
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
    def _aliq_esperada(self, ncm: str | None, descricao: str | None = None):
        """Alíquota interna da UF para o produto. Regra com palavras (ex.: protetor solar dentro da 3304) só vale
        quando a descrição confere com o texto legal e vence a regra geral do NCM; empate: prefixo mais longo."""
        from .comum import contem, norm, termo
        desc = norm(descricao)
        melhor, nota = None, (-1, -1)
        for r in self.base.icms_ncm:
            if r.get("uf") != self.uf or not ncm or not any(ncm.startswith(p) for p in r["ncm_prefixos"]):
                continue
            palavras = tuple(termo(x) for x in r.get("palavras", []))
            fps = _fps(desc) if r.get("fps_minimo") else None
            if fps is not None:  # o FPS informado decide (protetor solar x bronzeador), não o nome do produto
                if fps < r["fps_minimo"]:
                    continue
            elif palavras and not (contem(desc, palavras)
                                   and not contem(desc, tuple(termo(x) for x in r.get("palavras_excluir", [])))):
                continue
            n = (1 if palavras else 0, max(len(p) for p in r["ncm_prefixos"] if ncm.startswith(p)))
            if n > nota:
                melhor, nota = r, n
        if melhor:
            return D(melhor["aliquota"]), melhor["fundamento"], melhor.get("confianca", "MEDIA"), True
        return D(self.modal["aliquota"]), self.modal["fundamento"], "BAIXA", False

    def _aliquota(self, saidas: pl.DataFrame) -> list[Credito]:
        df = saidas.filter(pl.col("cfop").str.starts_with("5") & (pl.col("aliq_icms") > 0) & (pl.col("vl_bc_icms") > 0))
        out = []
        for row in linhas(df):
            if not _tributado(row["cst_icms"]):
                continue
            esperada, fund, conf, especifica = self._aliq_esperada(row["ncm"], row.get("descricao"))
            acima = row["aliq_icms"] > esperada + CENTAVO
            # abaixo: só quando a lei fixa a alíquota do produto e ela é a de supérfluos (25%), que não tem a redução
            # para 12% nas vendas a contribuinte nem outra alíquota menor por destinatário
            abaixo = especifica and esperada >= 25 and row["aliq_icms"] < esperada - CENTAVO
            if not (acima or abaixo):
                continue
            tese = "ICMS_ALIQ_ACIMA" if acima else "ICMS_ALIQ_ABAIXO"
            if self.revisoes.get((row["ncm"] or "", tese)) == "DESCARTADO":
                continue
            if self.revisoes.get((row["ncm"] or "", tese)) == "CONFIRMADO":
                conf = "ALTA"
            valor = row["vl_bc_icms"] * abs(row["aliq_icms"] - esperada) / 100
            out.append(Credito(
                modulo="ICMS", tese=tese, tributo="ICMS", periodo=row["periodo"], data=row["data"],
                chave=row["chave"], num_doc=row["num_doc"], num_item=row.get("num_item"), cod_item=row["cod_item"], descricao=row["descricao"],
                ncm=row["ncm"], cfop=row["cfop"], cst_escriturado=row["cst_icms"], cst_correto=row["cst_icms"],
                base_original=r2(row["vl_bc_icms"]), base_correta=r2(row["vl_bc_icms"]), valor_pago=r2(row["vl_icms"]),
                valor_recuperar=r2(valor), natureza="RESTITUICAO" if acima else "RISCO", via="ADMINISTRATIVO_ESTADUAL",
                fundamento=f"{self.fund[tese]} Referência: {fund}.", confianca=conf,
                regra_codigo="ICMS_ALIQ",
                observacao=f"Aplicada {row['aliq_icms']:.2f}%, prevista em lei {esperada:.2f}%."
                           + (" Sem regra específica para o NCM: pode haver alíquota diferenciada legítima."
                              if conf == "BAIXA" else ""),
            ))
        return out

    # -------------------------------------------------------------- cruzamento XML x SPED
    @staticmethod
    def _simples(n) -> bool:
        return (n.get("crt_emit") or "") in ("1", "4")

    def _destaque(self, n):
        """Crédito que a nota de compra permite: ICMS destacado; de fornecedor do Simples, o vCredICMSSN."""
        return (n.get("vl_cred_sn") or 0) if self._simples(n) else (n["vl_icms"] or 0)

    def _motivo_st(self, n) -> str:
        """Itens lançados com CST de ST na entrada, mas que estão fora da ST na UF: causa típica do crédito perdido."""
        itens = self.sped_entradas.filter(pl.col("chave") == n["chave"])
        fora = []
        for r in linhas(itens):
            cst = r["cst_icms"] or ""
            if _eh_st(cst) and self.base.fora_da_st(self.uf, r["ncm"], r["data"] or n["data"], r["descricao"]):
                fora.append(r["descricao"] or r["cod_item"])
        if not fora:
            return ""
        return (f" Entrada lançada com CST de ST em produto fora da ST em {self.uf} (Decreto SC 982/2020): "
                f"{', '.join(fora[:3])}{'…' if len(fora) > 3 else ''}.")

    def _cruzamento(self) -> list[Credito]:
        sped = {r["chave"]: r for r in linhas(self.sped_notas) if r["chave"]}
        out = []
        xml = self.xml_notas.filter(pl.col("periodo").is_in(list(self.periodos)) & (pl.col("cancelada") == 0))
        for n in linhas(xml):
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
                elif self._destaque(n) > (s["vl_icms"] or 0) + CENTAVO:
                    conf, motivo = self._destino_nota(n["chave"])
                    motivo = (motivo + self._motivo_st(n)).strip()
                    out.append(Credito(
                        modulo="CRUZAMENTO", tese="ICMS_CREDITO_MENOR_DESTAQUE", tributo="ICMS", periodo=n["periodo"],
                        data=n["data"], chave=n["chave"], num_doc=n["numero"], base_original=r2(s["vl_icms"] or 0),
                        base_correta=r2(self._destaque(n)), valor_pago=r2(self._destaque(n)),
                        valor_recuperar=r2(self._destaque(n) - (s["vl_icms"] or 0)), natureza="CREDITO_EXTEMPORANEO",
                        via="ADMINISTRATIVO_ESTADUAL", fundamento=self.fund["ICMS_CREDITO_MENOR_DESTAQUE"],
                        confianca=conf, regra_codigo="XML_X_SPED",
                        observacao=(f"{'Crédito permitido (Simples, vCredICMSSN)' if self._simples(n) else 'XML destaca'} "
                                    f"{self._destaque(n):.2f}; EFD escriturou {(s['vl_icms'] or 0):.2f}. {motivo}"),
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
