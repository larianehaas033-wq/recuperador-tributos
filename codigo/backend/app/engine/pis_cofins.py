"""Motor de PIS/COFINS.

Teses implementadas:
  PISCOF_MONO_SAIDA        revenda de produto monofásico com CST tributado (deveria ser 04)
  PISCOF_ALIQ_ZERO_SAIDA   venda de produto de alíquota zero com CST tributado (deveria ser 06)
  PISCOF_ICMS_BASE         ICMS destacado incluído na base das saídas (Tema 69 do STF)
  PISCOF_CREDITO_ENTRADA   compra para revenda/insumo sem crédito (CST 70/73/98/99) - Lucro Real
Riscos (valores que a empresa pode ter de devolver):
  RISCO_CRED_MONOFASICO    crédito na compra de monofásico para revenda (STJ, Tema 1.093)
  RISCO_CRED_ALIQ_ZERO     crédito na compra de produto com alíquota zero (Leis 10.637 e 10.833, art. 3º, § 2º, II)
  RISCO_CRED_ICMS_BASE     ICMS na base do crédito a partir de 05/2023 (Lei 14.592/2023)
  RISCO_SAIDA_ZERO_SEM_REGRA  saída com CST 04/06 sem regra que justifique
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

import polars as pl

from ..rules.loader import BaseRegras
from .coerencia import Conferencia, conferir, controle_interno
from .comum import ZERO, Credito, D, contem, linhas, norm, r2

CST_TRIBUTADO = {"01", "02", "03"}
CST_SEM_CREDITO = {"70", "98", "99"}
CST_CREDITO = {"50", "51", "52", "53", "54", "55", "56"}
TIPO_REVENDA = {"00"}
TIPO_INSUMO = {"01", "02", "06", "10"}
TIPO_SEM_CREDITO = {"07", "08", "09"}  # uso e consumo, ativo imobilizado (crédito próprio), serviços
INICIO_TEMA_69 = "2017-03-16"
INICIO_LEI_14592 = "2023-05-01"


def _tol(v: Decimal) -> Decimal:
    return max(Decimal("0.05"), abs(v) * Decimal("0.002"))


class MotorPisCofins:
    """Aplica as teses de PIS/COFINS a um conjunto de itens da EFD-Contribuições (e XMLs de saída,
    usados só quando a EFD do período está consolidada e não traz o ICMS por item)."""

    def __init__(self, base: BaseRegras, empresa: dict, itens: pl.DataFrame, xml_saidas: pl.DataFrame,
                 revisoes: dict[tuple[str, str], str], hoje: date, produtos: dict | None = None,
                 evidencias: dict | None = None):
        self.base = base
        self.empresa = empresa
        self.itens = itens
        self.xml_saidas = xml_saidas
        self.revisoes = revisoes
        self.hoje = hoje
        self.industrial = (empresa.get("ind_ativ") or "") == "0"
        # regime por competência (pode mudar de um ano para outro); sem informação do período, vale o atual
        self.regime_atual = empresa.get("regime") or ""
        self.regimes = empresa.get("regimes") or {}
        self.nao_cumulativo = self.regime_atual in ("LUCRO_REAL", "MISTO")
        self.cfop_revenda = base.cfops("saida_revenda")
        self.cfop_producao = base.cfops("saida_producao")
        # só venda efetiva entra nas teses de saída: remessa, bonificação, transferência e devolução de compra não
        self.cfop_venda = self.cfop_revenda | self.cfop_producao
        self.cfop_devolucao = base.cfops("devolucao_venda")
        self.cfop_entrada_revenda = base.cfops("entrada_revenda")
        self.simples = self.regime_atual == "SIMPLES_NACIONAL"
        self.cfop_entrada = base.cfops("entrada_credito")
        self.aliq = (Decimal("1.65"), Decimal("7.6")) if self.nao_cumulativo else (Decimal("0.65"), Decimal("3"))
        self.produtos = produtos or {}
        self.evid = evidencias or {"MONOFASICO": set(), "ALIQ_ZERO": set()}
        self._conf_cache: dict = {}
        self.revendidos = set(itens.filter(pl.col("ind_oper") == "1")["cod_item"].drop_nulls().unique().to_list())

    def verificar(self, regra, row: dict, tese: str) -> tuple[str, str]:
        """Conferência automática do enquadramento, sem depender do contador.

        ALTA quando: (1) a regra vale pelo NCM, sem 'Ex' nem condição; (2) a regra tem 'Ex' ou exige destinação e a
        descrição do produto confere com o texto da lei; (3) o fornecedor tratou o mesmo NCM da mesma forma no XML de
        compra (CST 02/04 para monofásico, 06 para alíquota zero). Fora disso fica BAIXA, fora dos totais."""
        ncm = row.get("ncm") or ""
        if self._revisao(ncm, tese) == "CONFIRMADO":
            return "ALTA", "Confirmado manualmente."
        if not regra.condicional:
            return "ALTA", "NCM consta da lista legal."
        desc = norm(row.get("descricao") or self.produtos.get(row.get("cod_item"), {}).get("descricao"))
        if regra.palavras and contem(desc, regra.palavras) and not contem(desc, regra.palavras_excluir):
            return "ALTA", "Descrição do produto confere com o texto legal."
        if ncm in self.evid.get(regra.tipo, set()):
            return "ALTA", "O fornecedor tratou o mesmo NCM da mesma forma no XML de compra."
        return "BAIXA", ("Não comprovado automaticamente: o código depende de 'Ex' ou da destinação do produto, "
                         "e nem a descrição nem os XMLs de compra confirmam.")

    def destinacao(self, row: dict) -> tuple[str | None, str]:
        """Prova da destinação da compra pelo cadastro 0200 e pelo comportamento do item (foi revendido?)."""
        tipo = (self.produtos.get(row.get("cod_item"), {}).get("tipo_item") or "").strip()
        tipo = tipo.zfill(2) if tipo else ""
        revendido = row.get("cod_item") in self.revendidos
        if tipo in TIPO_SEM_CREDITO:
            return None, ""
        if tipo in TIPO_REVENDA and (revendido or row.get("cfop") in self.cfop_entrada_revenda):
            return "ALTA", "Cadastrado como mercadoria para revenda" + (" e revendido no período." if revendido else ".")
        if tipo in TIPO_INSUMO and self.industrial:
            return "ALTA", "Cadastrado como insumo de empresa industrial."
        if revendido and row.get("cfop") in self.cfop_entrada_revenda:
            return "ALTA", "Comprado para revenda e revendido no período."
        return "BAIXA", "Não comprovado automaticamente: o cadastro do produto não mostra revenda nem insumo."

    # ------------------------------------------------------------------ utilidades
    def _ncm(self, row: dict) -> Conferencia:
        """NCM conferido com a descrição (extinto → vigente; incompatível → nada se comprova pelo código)."""
        desc = row.get("descricao") or self.produtos.get(row.get("cod_item"), {}).get("descricao")
        k = (row.get("ncm"), desc)
        if k not in self._conf_cache:
            self._conf_cache[k] = conferir(row.get("ncm"), desc, self.base)
        return self._conf_cache[k]

    def _revisao(self, ncm: str | None, tese: str) -> str | None:
        return self.revisoes.get((ncm or "", tese))

    def _confianca(self, base_conf: str, ncm: str | None, tese: str) -> str:
        return "ALTA" if self._revisao(ncm, tese) == "CONFIRMADO" else base_conf

    def _regra(self, ncm, data, tipo, descricao=None):
        return self.base.classificar(ncm, data, tipo, descricao)

    def _eh_revenda(self, cfop: str | None) -> bool:
        if cfop in self.cfop_producao:
            return False
        if cfop in self.cfop_revenda:
            return True
        return not self.industrial

    def regime(self, periodo: str | None) -> str:
        return self.regimes.get(periodo or "") or self.regime_atual

    def nao_cumulativo_em(self, periodo: str | None) -> bool:
        return self.regime(periodo) in ("LUCRO_REAL", "MISTO")

    def simples_em(self, periodo: str | None) -> bool:
        return self.regime(periodo) == "SIMPLES_NACIONAL"

    def aliq_em(self, periodo: str | None) -> tuple[Decimal, Decimal]:
        return (Decimal("1.65"), Decimal("7.6")) if self.nao_cumulativo_em(periodo) else (Decimal("0.65"), Decimal("3"))

    @staticmethod
    def _por_tributo(row: dict):
        """Uma linha C170 tem PIS e COFINS; C181/C191 só PIS; C185/C195 só COFINS."""
        if row.get("cst_pis"):
            yield "PIS", row["cst_pis"], row["vl_bc_pis"], row["aliq_pis"], row["vl_pis"]
        if row.get("cst_cofins"):
            yield "COFINS", row["cst_cofins"], row["vl_bc_cofins"], row["aliq_cofins"], row["vl_cofins"]

    # ------------------------------------------------------------------ teses
    def executar(self) -> tuple[list[Credito], set]:
        creditos: list[Credito] = []
        marcados: set = set()  # (id_linha, tributo) já usados por tese de débito indevido
        saidas = self.itens.filter((pl.col("ind_oper") == "1") & pl.col("cfop").is_in(list(self.cfop_venda)))
        entradas = self.itens.filter(pl.col("ind_oper") == "0")
        devolucoes = entradas.filter(pl.col("cfop").is_in(list(self.cfop_devolucao)))
        mono_zero = self._monofasico_aliq_zero(saidas, marcados)
        icms_base = self._icms_na_base(saidas, marcados)  # períodos do Simples ficam de fora (DAS, sem Tema 69)
        self._deduzir_devolucoes(mono_zero, devolucoes, "mono")
        self._deduzir_devolucoes(icms_base, devolucoes, "icms")
        creditos += mono_zero + icms_base
        periodos_nc = [p for p in entradas["periodo"].unique().to_list() if self.nao_cumulativo_em(p)]
        if periodos_nc:  # crédito de entradas só nas competências do regime não cumulativo (Lucro Real)
            entradas_nc = entradas.filter(pl.col("periodo").is_in(periodos_nc))
            creditos += self._creditos_entradas(entradas_nc)
            creditos += self._riscos_entradas(entradas_nc)
        creditos += self._risco_saida_sem_regra(saidas)
        periodos_consolidados = set(
            saidas.filter(pl.col("origem").is_in(["C181", "C185"]))["periodo"].unique().to_list()
        ) - set(saidas.filter(pl.col("origem") == "C170")["periodo"].unique().to_list())
        periodos_consolidados = {p for p in periodos_consolidados if not self.simples_em(p)}
        if periodos_consolidados and self.xml_saidas.height:
            creditos += self._icms_na_base_xml(periodos_consolidados)
        return creditos, periodos_consolidados

    def _monofasico_aliq_zero(self, saidas: pl.DataFrame, marcados: set) -> list[Credito]:
        out = []
        for row in linhas(saidas):
            cn = self._ncm(row)
            ncm, data, cfop = cn.ncm, row["data"], row["cfop"]
            mono = self._regra(ncm, data, "MONOFASICO", row["descricao"])
            zero = None if mono else self._regra(ncm, data, "ALIQ_ZERO", row["descricao"])
            regra = mono or zero
            if not regra:
                continue
            if regra.somente_revenda and not self._eh_revenda(cfop):
                continue  # fabricante/importador recolhe na alíquota concentrada (CST 02)
            tese = "PISCOF_MONO_SAIDA" if mono else "PISCOF_ALIQ_ZERO_SAIDA"
            if self._revisao(ncm, tese) == "DESCARTADO":
                continue
            conf, motivo = None, ""
            for trib, cst, bc, aliq, vl in self._por_tributo(row):
                if cst not in CST_TRIBUTADO or vl <= 0:
                    continue
                if conf is None:
                    conf, motivo = self.verificar(regra, dict(row, ncm=ncm), tese)
                    if cn.grave:
                        conf, motivo = "BAIXA", cn.alerta
                    elif cn.alerta:
                        motivo = f"{motivo} {cn.alerta}"
                marcados.add((row["rid"], trib))
                out.append(Credito(
                    modulo="PIS_COFINS", tese=tese, tributo=trib, periodo=row["periodo"], data=data,
                    chave=row["chave"], num_doc=row["num_doc"], num_item=row.get("num_item"), cod_item=row["cod_item"],
                    descricao=row["descricao"], ncm=row["ncm"], cfop=cfop, cst_escriturado=cst,
                    cst_correto="04" if mono else "06", base_original=r2(bc), base_correta=0.0,
                    valor_pago=r2(vl), valor_recuperar=r2(vl), natureza="RESTITUICAO",
                    via="ADMINISTRATIVO_FEDERAL", fundamento=regra.fundamento,
                    confianca=conf, regra_codigo=regra.codigo,
                    observacao=(f"{regra.grupo}. {motivo} {regra.observacao}"
                                + (" Valor pago conforme o resumo da nota na EFD-Contribuições (C175), rateado pelo "
                                   "valor do item: o XML da NFC-e veio sem PIS/COFINS." if row.get("pis_c175") else "")
                                ).strip(),
                ))
        return out

    def _icms_na_base(self, saidas: pl.DataFrame, marcados: set) -> list[Credito]:
        out = []
        c170 = saidas.filter(pl.col("origem").is_in(["C170", "XML"]) & (pl.col("vl_icms") > 0)
                             & (pl.col("data") >= INICIO_TEMA_69))
        for row in linhas(c170):
            if self.simples_em(row["periodo"]):
                continue
            bruto = row["vl_item"] - row["vl_desc"]
            for trib, cst, bc, aliq, vl in self._por_tributo(row):
                if cst not in CST_TRIBUTADO or vl <= 0 or (row["rid"], trib) in marcados or aliq <= 0:
                    continue
                icms = row["vl_icms"]
                if bc <= bruto - icms + _tol(bruto):
                    continue  # ICMS já excluído
                if bc >= bruto - _tol(bruto):
                    excesso, conf, obs = icms, "ALTA", "Base de cálculo igual ao valor do item: ICMS não foi excluído."
                else:
                    excesso = bc - (bruto - icms)
                    conf, obs = "BAIXA", "Exclusão parcial do ICMS na base; conferir composição da base."
                valor = min(vl, excesso * aliq / 100)
                if valor < 0.01:
                    continue
                out.append(Credito(
                    modulo="PIS_COFINS", tese="PISCOF_ICMS_BASE", tributo=trib, periodo=row["periodo"],
                    data=row["data"], chave=row["chave"], num_doc=row["num_doc"], num_item=row.get("num_item"), cod_item=row["cod_item"],
                    descricao=row["descricao"], ncm=row["ncm"], cfop=row["cfop"], cst_escriturado=cst,
                    cst_correto=cst, base_original=r2(bc), base_correta=r2(bc - min(icms, excesso)),
                    valor_pago=r2(vl), valor_recuperar=r2(valor), natureza="RESTITUICAO",
                    via="ADMINISTRATIVO_FEDERAL", fundamento=self.base.teses["PISCOF_ICMS_BASE"]["fundamento"],
                    confianca=conf, regra_codigo="TEMA_69", observacao=obs,
                ))
        return out

    def _deduzir_devolucoes(self, creditos: list[Credito], devolucoes: pl.DataFrame, modo: str) -> None:
        """Devolução de venda: o crédito que a empresa tomou na devolução já devolveu parte do que pagou a mais.

        Para cada item, o valor creditado na devolução (CST 50 a 56) é abatido das restituições do mesmo item e
        tributo: primeiro na competência da devolução, depois nas anteriores (da mais recente para a mais antiga).
        modo "mono": abate todo o PIS/COFINS creditado na devolução de produto monofásico/alíquota zero.
        modo "icms": abate só a parte do crédito calculada sobre o ICMS (Tema 69)."""
        if not creditos or not devolucoes.height:
            return
        por_item: dict[tuple, list[Credito]] = defaultdict(list)
        for c in creditos:
            por_item[(c.cod_item, c.tributo)].append(c)
        for row in linhas(devolucoes):
            for trib, cst, bc, aliq, vl in self._por_tributo(row):
                if cst not in CST_CREDITO or vl <= 0:
                    continue
                lista = por_item.get((row["cod_item"], trib))
                if not lista:
                    continue
                if modo == "icms":
                    bruto = row["vl_item"] - row["vl_desc"]
                    if not (row["vl_icms"] > 0 and bc >= bruto - _tol(bruto)):
                        continue  # a devolução já creditou sem o ICMS na base
                    abater = min(vl, row["vl_icms"] * aliq / 100)
                else:
                    abater = vl
                cand = sorted((c for c in lista if c.periodo <= row["periodo"] and c.valor_recuperar > 0),
                              key=lambda c: (c.periodo != row["periodo"], [-ord(x) for x in c.periodo]))
                for c in cand:
                    if abater < Decimal("0.005"):
                        break
                    parte = min(c.valor_recuperar, abater)
                    c.valor_recuperar = r2(c.valor_recuperar - parte)
                    abater -= parte
                    c.observacao = (f"{c.observacao} Abatida devolução de venda de R$ {parte:.2f} "
                                    f"(CFOP {row['cfop']}, {row['data']}).").strip()
        creditos[:] = [c for c in creditos if c.valor_recuperar >= 0.01]

    def _icms_na_base_xml(self, periodos: set) -> list[Credito]:
        """Estimativa pelos XMLs quando a EFD-Contribuições do período está consolidada (C180/C181)."""
        out = []
        ja = set(self.itens["chave"].drop_nulls().unique().to_list()) if self.itens.height else set()
        df = self.xml_saidas.filter(pl.col("periodo").is_in(list(periodos)) & (pl.col("vl_icms") > 0)
                                    & ~pl.col("chave").is_in(list(ja))
                                    & pl.col("cfop").is_in(list(self.cfop_venda))
                                    & (pl.col("data") >= INICIO_TEMA_69))
        for row in linhas(df):
            ncm_ef = self._ncm(row).ncm
            if (self._regra(ncm_ef, row["data"], "MONOFASICO", row["descricao"])
                    or self._regra(ncm_ef, row["data"], "ALIQ_ZERO", row["descricao"])):
                continue
            bruto = row["vl_item"] - row["vl_desc"]
            for trib, cst, bc, aliq, vl in self._por_tributo(row):
                if cst not in CST_TRIBUTADO or aliq <= 0 or vl <= 0:
                    continue
                if bc < bruto - _tol(bruto):
                    continue
                valor = min(vl, row["vl_icms"] * aliq / 100)
                out.append(Credito(
                    modulo="PIS_COFINS", tese="PISCOF_ICMS_BASE", tributo=trib, periodo=row["periodo"],
                    data=row["data"], chave=row["chave"], num_doc=row["num_doc"], num_item=row.get("num_item"), cod_item=row["cod_item"],
                    descricao=row["descricao"], ncm=row["ncm"], cfop=row["cfop"], cst_escriturado=cst,
                    cst_correto=cst, base_original=r2(bc), base_correta=r2(bc - row["vl_icms"]),
                    valor_pago=r2(vl), valor_recuperar=r2(valor), natureza="RESTITUICAO",
                    via="ADMINISTRATIVO_FEDERAL", fundamento=self.base.teses["PISCOF_ICMS_BASE"]["fundamento"],
                    confianca="MEDIA", regra_codigo="TEMA_69",
                    observacao="Estimado pelos XMLs: a EFD-Contribuições do período está consolidada (C180/C181).",
                ))
        return out

    def _creditos_entradas(self, entradas: pl.DataFrame) -> list[Credito]:
        out = []
        df = entradas.filter(pl.col("cfop").is_in(list(self.cfop_entrada)))
        tese = "PISCOF_CREDITO_ENTRADA"
        fund = self.base.teses[tese]["fundamento"]
        for row in linhas(df):
            cn = self._ncm(row)
            ncm, data, cfop = cn.ncm, row["data"], row["cfop"]
            if len(row["cnpj_part"] or "") != 14:
                continue  # compra de pessoa física não dá crédito básico
            if controle_interno(row["descricao"], self.base):
                continue  # perda/descarte da desossa: sai da carcaça comprada a alíquota zero, não gera crédito
            mono = self._regra(ncm, data, "MONOFASICO", row["descricao"])
            if mono and cfop in self.cfop_entrada_revenda:
                continue  # Tema 1.093: revenda de monofásico não gera crédito
            zero = self._regra(ncm, data, "ALIQ_ZERO", row["descricao"])
            if self._revisao(ncm, tese) == "DESCARTADO":
                continue
            conf, motivo = self.destinacao(row)
            if conf is None:
                continue  # uso e consumo, ativo ou serviço: fora desta tese
            if cn.grave:
                conf, motivo = "BAIXA", cn.alerta
            elif cn.alerta:
                motivo = f"{motivo} {cn.alerta}"
            if self._revisao(ncm, tese) == "CONFIRMADO":
                conf, motivo = "ALTA", "Confirmado manualmente."
            bruto = row["vl_item"] - row["vl_desc"] + (ZERO if self.industrial else row["vl_ipi"])
            icms_fora = row["vl_icms"] if (data or "") >= INICIO_LEI_14592 else ZERO
            base_cred = max(ZERO, bruto - icms_fora)
            for trib, cst, bc, aliq, vl in self._por_tributo(row):
                if cst == "73":
                    if zero:
                        continue  # aquisição a alíquota zero: sem crédito, CST correto
                elif cst not in CST_SEM_CREDITO:
                    continue
                elif zero:
                    continue
                aliq_c = self.aliq_em(row["periodo"])[0 if trib == "PIS" else 1]
                valor = base_cred * aliq_c / 100
                if valor < 0.01:
                    continue
                obs = motivo
                if icms_fora:
                    obs += " Base sem o ICMS da compra (Lei 14.592/2023)."
                if cst == "73":
                    obs += " CST 73 informado, mas o NCM não está na lista de alíquota zero."
                out.append(Credito(
                    modulo="PIS_COFINS", tese=tese, tributo=trib, periodo=row["periodo"], data=data,
                    chave=row["chave"], num_doc=row["num_doc"], num_item=row.get("num_item"), cod_item=row["cod_item"],
                    descricao=row["descricao"], ncm=row["ncm"], cfop=cfop, cst_escriturado=cst, cst_correto="50",
                    base_original=r2(bc), base_correta=r2(base_cred), valor_pago=0.0, valor_recuperar=r2(valor),
                    natureza="CREDITO_EXTEMPORANEO", via="ADMINISTRATIVO_FEDERAL", fundamento=fund,
                    confianca=conf, regra_codigo="ART3_LEIS_10637_10833",
                    observacao=obs,
                ))
        return out

    def _riscos_entradas(self, entradas: pl.DataFrame) -> list[Credito]:
        out = []
        df = entradas.filter(pl.col("cst_pis").is_in(list(CST_CREDITO)) | pl.col("cst_cofins").is_in(list(CST_CREDITO)))
        for row in linhas(df):
            cn = self._ncm(row)
            ncm, data, cfop = cn.ncm, row["data"], row["cfop"]
            mono = self._regra(ncm, data, "MONOFASICO", row["descricao"])
            risco_mono = bool(mono) and cfop in self.cfop_entrada_revenda and not self.industrial
            zero = None if mono else self._regra(ncm, data, "ALIQ_ZERO", row["descricao"])
            bruto = row["vl_item"] - row["vl_desc"]
            for trib, cst, bc, aliq, vl in self._por_tributo(row):
                if cst not in CST_CREDITO or vl <= 0:
                    continue
                if risco_mono:
                    out.append(Credito(
                        modulo="PIS_COFINS", tese="RISCO_CRED_MONOFASICO", tributo=trib, periodo=row["periodo"],
                        data=data, chave=row["chave"], num_doc=row["num_doc"], num_item=row.get("num_item"), cod_item=row["cod_item"],
                        descricao=row["descricao"], ncm=row["ncm"], cfop=cfop, cst_escriturado=cst, cst_correto="70",
                        base_original=r2(bc), base_correta=0.0, valor_pago=0.0, valor_recuperar=r2(vl),
                        natureza="RISCO", fundamento=self.base.teses["RISCO_CRED_MONOFASICO"]["fundamento"],
                        confianca=("BAIXA" if cn.grave else self.verificar(mono, dict(row, ncm=ncm),
                                                                           "RISCO_CRED_MONOFASICO")[0]),
                        regra_codigo=mono.codigo, observacao=cn.alerta,
                    ))
                    continue
                if zero:
                    out.append(Credito(
                        modulo="PIS_COFINS", tese="RISCO_CRED_ALIQ_ZERO", tributo=trib, periodo=row["periodo"],
                        data=data, chave=row["chave"], num_doc=row["num_doc"], num_item=row.get("num_item"), cod_item=row["cod_item"],
                        descricao=row["descricao"], ncm=row["ncm"], cfop=cfop, cst_escriturado=cst, cst_correto="73",
                        base_original=r2(bc), base_correta=0.0, valor_pago=0.0, valor_recuperar=r2(vl),
                        natureza="RISCO", fundamento=self.base.teses["RISCO_CRED_ALIQ_ZERO"]["fundamento"],
                        confianca=("BAIXA" if cn.grave else self.verificar(zero, dict(row, ncm=ncm),
                                                                           "RISCO_CRED_ALIQ_ZERO")[0]),
                        regra_codigo=zero.codigo, observacao=cn.alerta,
                    ))
                    continue
                if (data or "") >= INICIO_LEI_14592 and row["vl_icms"] > 0 and bc >= bruto - _tol(bruto) and aliq > 0:
                    excesso = min(vl, row["vl_icms"] * aliq / 100)
                    if excesso >= 0.01:
                        out.append(Credito(
                            modulo="PIS_COFINS", tese="RISCO_CRED_ICMS_BASE", tributo=trib, periodo=row["periodo"],
                            data=data, chave=row["chave"], num_doc=row["num_doc"], num_item=row.get("num_item"), cod_item=row["cod_item"],
                            descricao=row["descricao"], ncm=ncm, cfop=cfop, cst_escriturado=cst, cst_correto=cst,
                            base_original=r2(bc), base_correta=r2(bc - row["vl_icms"]), valor_pago=0.0,
                            valor_recuperar=r2(excesso), natureza="RISCO",
                            fundamento=self.base.teses["RISCO_CRED_ICMS_BASE"]["fundamento"], confianca="ALTA",
                            regra_codigo="LEI_14592_2023",
                        ))
        return out

    def _risco_saida_sem_regra(self, saidas: pl.DataFrame) -> list[Credito]:
        """Agrupa por NCM e competência para não poluir o relatório."""
        df = saidas.filter(pl.col("cst_pis").is_in(["04", "06"]) | pl.col("cst_cofins").is_in(["04", "06"]))
        if not df.height:
            return []
        grupos: dict[tuple, dict] = {}
        for r in linhas(df):  # soma em Decimal, não no float do Polars
            g = grupos.setdefault((r["ncm"], r["periodo"]), dict(
                ncm=r["ncm"], periodo=r["periodo"], descricao=r["descricao"], data=r["data"], cfop=r["cfop"],
                cod_item=r["cod_item"], cst=r["cst_pis"] or r["cst_cofins"], _bp=ZERO, _bc=ZERO))
            liq = r["vl_item"] - r["vl_desc"]
            g["data"] = min(g["data"] or r["data"], r["data"] or g["data"])
            if r["cst_pis"] in ("04", "06"):
                g["_bp"] += liq
            if r["cst_cofins"] in ("04", "06"):
                g["_bc"] += liq
        agg = list(grupos.values())
        out = []
        for row in agg:
            ncm, data = row["ncm"], row["data"]
            cn = self._ncm(row)
            ncm_ef = cn.ncm
            if not cn.grave and (self._regra(ncm_ef, data, "MONOFASICO", row["descricao"])
                                 or self._regra(ncm_ef, data, "ALIQ_ZERO", row["descricao"])):
                continue  # NCM a revisar: o CST 04/06 dado pelo código não se sustenta, vira risco a conferir
            if self._revisao(ncm, "RISCO_SAIDA_ZERO_SEM_REGRA") == "DESCARTADO":
                continue
            a_pis, a_cof = self.aliq_em(row["periodo"])
            for trib, base_v, aliq in (("PIS", row["_bp"], a_pis), ("COFINS", row["_bc"], a_cof)):
                if base_v <= 0:
                    continue
                out.append(Credito(
                    modulo="PIS_COFINS", tese="RISCO_SAIDA_ZERO_SEM_REGRA", tributo=trib, periodo=row["periodo"],
                    data=data, cod_item=row["cod_item"], descricao=row["descricao"], ncm=ncm, cfop=row["cfop"],
                    cst_escriturado=row["cst"], cst_correto="01?", base_original=0.0, base_correta=r2(base_v),
                    valor_recuperar=r2(base_v * aliq / 100), natureza="RISCO",
                    fundamento=self.base.teses["RISCO_SAIDA_ZERO_SEM_REGRA"]["fundamento"], confianca="BAIXA",
                    observacao=(cn.alerta if cn.grave else
                                "Valor agrupado por NCM no mês. Pode haver outro fundamento para o CST usado."),
                ))
        return out
