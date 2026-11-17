"""Motor de PIS/COFINS.

Teses implementadas:
  PISCOF_MONO_SAIDA        revenda de produto monofásico com CST tributado (deveria ser 04)
  PISCOF_ALIQ_ZERO_SAIDA   venda de produto de alíquota zero com CST tributado (deveria ser 06)
  PISCOF_ICMS_BASE         ICMS destacado incluído na base das saídas (Tema 69 do STF)
  PISCOF_CREDITO_ENTRADA   compra para revenda/insumo sem crédito (CST 70/73/98/99) - Lucro Real
Riscos (valores que a empresa pode ter de devolver):
  RISCO_CRED_MONOFASICO    crédito na compra de monofásico para revenda (STJ, Tema 1.093)
  RISCO_CRED_ICMS_BASE     ICMS na base do crédito a partir de 05/2023 (Lei 14.592/2023)
  RISCO_SAIDA_ZERO_SEM_REGRA  saída com CST 04/06 sem regra que justifique
"""
from __future__ import annotations

from datetime import date

import polars as pl

from ..rules.loader import BaseRegras
from .coerencia import Conferencia, conferir, controle_interno
from .comum import Credito, contem, norm, r2

CST_TRIBUTADO = {"01", "02", "03"}
CST_SEM_CREDITO = {"70", "98", "99"}
CST_CREDITO = {"50", "51", "52", "53", "54", "55", "56"}
CFOP_ENTRADA_REVENDA = {"1102", "2102", "1403", "2403", "1652", "2652", "1117", "2117", "1113", "2113", "1121",
                        "2121", "3102"}
TIPO_REVENDA = {"00"}
TIPO_INSUMO = {"01", "02", "06", "10"}
TIPO_SEM_CREDITO = {"07", "08", "09"}  # uso e consumo, ativo imobilizado (crédito próprio), serviços
INICIO_TEMA_69 = "2017-03-16"
INICIO_LEI_14592 = "2023-05-01"


def _tol(v: float) -> float:
    return max(0.05, abs(v) * 0.002)


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
        self.nao_cumulativo = (empresa.get("regime") or "") in ("LUCRO_REAL", "MISTO")
        self.cfop_revenda = base.cfops("saida_revenda")
        self.cfop_producao = base.cfops("saida_producao")
        self.cfop_entrada = base.cfops("entrada_credito")
        self.aliq = (1.65, 7.6) if self.nao_cumulativo else (0.65, 3.0)
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
        if tipo in TIPO_REVENDA and (revendido or row.get("cfop") in CFOP_ENTRADA_REVENDA):
            return "ALTA", "Cadastrado como mercadoria para revenda" + (" e revendido no período." if revendido else ".")
        if tipo in TIPO_INSUMO and self.industrial:
            return "ALTA", "Cadastrado como insumo de empresa industrial."
        if revendido and row.get("cfop") in CFOP_ENTRADA_REVENDA:
            return "ALTA", "Comprado para revenda e revendido no período."
        return "BAIXA", "Não comprovado automaticamente: o cadastro do produto não mostra revenda nem insumo."

    # ------------------------------------------------------------------ utilidades
    def _ncm(self, row: dict) -> Conferencia:
        """NCM conferido com a descrição (extinto → vigente; incompatível → nada se comprova pelo código)."""
        desc = row.get("descricao") or self.produtos.get(row.get("cod_item"), {}).get("descricao")
        k = (row.get("ncm"), desc)
        if k not in self._conf_cache:
            self._conf_cache[k] = conferir(row.get("ncm"), desc)
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
        saidas = self.itens.filter(pl.col("ind_oper") == "1")
        entradas = self.itens.filter(pl.col("ind_oper") == "0")
        creditos += self._monofasico_aliq_zero(saidas, marcados)
        creditos += self._icms_na_base(saidas, marcados)
        if self.nao_cumulativo:
            creditos += self._creditos_entradas(entradas)
            creditos += self._riscos_entradas(entradas)
        creditos += self._risco_saida_sem_regra(saidas)
        periodos_consolidados = set(
            saidas.filter(pl.col("origem").is_in(["C181", "C185"]))["periodo"].unique().to_list()
        ) - set(saidas.filter(pl.col("origem") == "C170")["periodo"].unique().to_list())
        if periodos_consolidados and self.xml_saidas.height:
            creditos += self._icms_na_base_xml(periodos_consolidados)
        return creditos, periodos_consolidados

    def _monofasico_aliq_zero(self, saidas: pl.DataFrame, marcados: set) -> list[Credito]:
        out = []
        for row in saidas.iter_rows(named=True):
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
                    chave=row["chave"], num_doc=row["num_doc"], cod_item=row["cod_item"],
                    descricao=row["descricao"], ncm=row["ncm"], cfop=cfop, cst_escriturado=cst,
                    cst_correto="04" if mono else "06", base_original=r2(bc), base_correta=0.0,
                    valor_pago=r2(vl), valor_recuperar=r2(vl), natureza="RESTITUICAO",
                    via="ADMINISTRATIVO_FEDERAL", fundamento=regra.fundamento,
                    confianca=conf, regra_codigo=regra.codigo,
                    observacao=f"{regra.grupo}. {motivo} {regra.observacao}".strip(),
                ))
        return out

    def _icms_na_base(self, saidas: pl.DataFrame, marcados: set) -> list[Credito]:
        out = []
        c170 = saidas.filter((pl.col("origem") == "C170") & (pl.col("vl_icms") > 0)
                             & (pl.col("data") >= INICIO_TEMA_69))
        for row in c170.iter_rows(named=True):
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
                    data=row["data"], chave=row["chave"], num_doc=row["num_doc"], cod_item=row["cod_item"],
                    descricao=row["descricao"], ncm=row["ncm"], cfop=row["cfop"], cst_escriturado=cst,
                    cst_correto=cst, base_original=r2(bc), base_correta=r2(bc - min(icms, excesso)),
                    valor_pago=r2(vl), valor_recuperar=r2(valor), natureza="RESTITUICAO",
                    via="ADMINISTRATIVO_FEDERAL", fundamento=self.base.teses["PISCOF_ICMS_BASE"]["fundamento"],
                    confianca=conf, regra_codigo="TEMA_69", observacao=obs,
                ))
        return out

    def _icms_na_base_xml(self, periodos: set) -> list[Credito]:
        """Estimativa pelos XMLs quando a EFD-Contribuições do período está consolidada (C180/C181)."""
        out = []
        df = self.xml_saidas.filter(pl.col("periodo").is_in(list(periodos)) & (pl.col("vl_icms") > 0)
                                    & (pl.col("data") >= INICIO_TEMA_69))
        for row in df.iter_rows(named=True):
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
                    data=row["data"], chave=row["chave"], num_doc=row["num_doc"], cod_item=row["cod_item"],
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
        for row in df.iter_rows(named=True):
            cn = self._ncm(row)
            ncm, data, cfop = cn.ncm, row["data"], row["cfop"]
            if len(row["cnpj_part"] or "") != 14:
                continue  # compra de pessoa física não dá crédito básico
            if controle_interno(row["descricao"]):
                continue  # perda/descarte da desossa: sai da carcaça comprada a alíquota zero, não gera crédito
            mono = self._regra(ncm, data, "MONOFASICO", row["descricao"])
            if mono and cfop in CFOP_ENTRADA_REVENDA:
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
            bruto = row["vl_item"] - row["vl_desc"] + (0.0 if self.industrial else row["vl_ipi"])
            icms_fora = row["vl_icms"] if (data or "") >= INICIO_LEI_14592 else 0.0
            base_cred = max(0.0, bruto - icms_fora)
            for trib, cst, bc, aliq, vl in self._por_tributo(row):
                if cst == "73":
                    if zero:
                        continue  # aquisição a alíquota zero: sem crédito, CST correto
                elif cst not in CST_SEM_CREDITO:
                    continue
                elif zero:
                    continue
                aliq_c = self.aliq[0] if trib == "PIS" else self.aliq[1]
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
                    chave=row["chave"], num_doc=row["num_doc"], cod_item=row["cod_item"],
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
        for row in df.iter_rows(named=True):
            cn = self._ncm(row)
            ncm, data, cfop = cn.ncm, row["data"], row["cfop"]
            mono = self._regra(ncm, data, "MONOFASICO", row["descricao"])
            risco_mono = bool(mono) and cfop in CFOP_ENTRADA_REVENDA and not self.industrial
            bruto = row["vl_item"] - row["vl_desc"]
            for trib, cst, bc, aliq, vl in self._por_tributo(row):
                if cst not in CST_CREDITO or vl <= 0:
                    continue
                if risco_mono:
                    out.append(Credito(
                        modulo="PIS_COFINS", tese="RISCO_CRED_MONOFASICO", tributo=trib, periodo=row["periodo"],
                        data=data, chave=row["chave"], num_doc=row["num_doc"], cod_item=row["cod_item"],
                        descricao=row["descricao"], ncm=row["ncm"], cfop=cfop, cst_escriturado=cst, cst_correto="70",
                        base_original=r2(bc), base_correta=0.0, valor_pago=0.0, valor_recuperar=r2(vl),
                        natureza="RISCO", fundamento=self.base.teses["RISCO_CRED_MONOFASICO"]["fundamento"],
                        confianca=("BAIXA" if cn.grave else self.verificar(mono, dict(row, ncm=ncm),
                                                                           "RISCO_CRED_MONOFASICO")[0]),
                        regra_codigo=mono.codigo, observacao=cn.alerta,
                    ))
                    continue
                if (data or "") >= INICIO_LEI_14592 and row["vl_icms"] > 0 and bc >= bruto - _tol(bruto) and aliq > 0:
                    excesso = min(vl, row["vl_icms"] * aliq / 100)
                    if excesso >= 0.01:
                        out.append(Credito(
                            modulo="PIS_COFINS", tese="RISCO_CRED_ICMS_BASE", tributo=trib, periodo=row["periodo"],
                            data=data, chave=row["chave"], num_doc=row["num_doc"], cod_item=row["cod_item"],
                            descricao=row["descricao"], ncm=ncm, cfop=cfop, cst_escriturado=cst, cst_correto=cst,
                            base_original=r2(bc), base_correta=r2(bc - row["vl_icms"]), valor_pago=0.0,
                            valor_recuperar=r2(excesso), natureza="RISCO",
                            fundamento=self.base.teses["RISCO_CRED_ICMS_BASE"]["fundamento"], confianca="ALTA",
                            regra_codigo="LEI_14592_2023",
                        ))
        return out

    def _risco_saida_sem_regra(self, saidas: pl.DataFrame) -> list[Credito]:
        """Agrupa por NCM e competência para não poluir o relatório."""
        df = saidas.with_columns(
            pl.when(pl.col("cst_pis").is_in(["04", "06"])).then(pl.col("vl_item") - pl.col("vl_desc"))
            .otherwise(0.0).alias("_bp"),
            pl.when(pl.col("cst_cofins").is_in(["04", "06"])).then(pl.col("vl_item") - pl.col("vl_desc"))
            .otherwise(0.0).alias("_bc"),
        ).filter((pl.col("_bp") > 0) | (pl.col("_bc") > 0))
        if not df.height:
            return []
        agg = df.group_by(["ncm", "periodo"]).agg(
            pl.col("_bp").sum(), pl.col("_bc").sum(), pl.col("descricao").first(), pl.col("data").min(),
            pl.col("cfop").first(), pl.col("cod_item").first(),
            pl.when(pl.col("cst_pis").is_not_null()).then(pl.col("cst_pis")).otherwise(pl.col("cst_cofins")).first().alias("cst"),
        )
        out = []
        for row in agg.iter_rows(named=True):
            ncm, data = row["ncm"], row["data"]
            ncm_ef = self._ncm(row).ncm
            if (self._regra(ncm_ef, data, "MONOFASICO", row["descricao"])
                    or self._regra(ncm_ef, data, "ALIQ_ZERO", row["descricao"])):
                continue
            if self._revisao(ncm, "RISCO_SAIDA_ZERO_SEM_REGRA") == "DESCARTADO":
                continue
            for trib, base_v, aliq in (("PIS", row["_bp"], self.aliq[0]), ("COFINS", row["_bc"], self.aliq[1])):
                if base_v <= 0:
                    continue
                out.append(Credito(
                    modulo="PIS_COFINS", tese="RISCO_SAIDA_ZERO_SEM_REGRA", tributo=trib, periodo=row["periodo"],
                    data=data, cod_item=row["cod_item"], descricao=row["descricao"], ncm=ncm, cfop=row["cfop"],
                    cst_escriturado=row["cst"], cst_correto="01?", base_original=0.0, base_correta=r2(base_v),
                    valor_recuperar=r2(base_v * aliq / 100), natureza="RISCO",
                    fundamento=self.base.teses["RISCO_SAIDA_ZERO_SEM_REGRA"]["fundamento"], confianca="BAIXA",
                    observacao="Valor agrupado por NCM no mês. Pode haver outro fundamento para o CST usado.",
                ))
        return out
