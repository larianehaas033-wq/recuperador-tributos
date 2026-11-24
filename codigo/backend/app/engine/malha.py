"""Alertas de possível malha fiscal.

Confere a escrituração do próprio cliente (EFD ICMS/IPI, EFD-Contribuições e XMLs) contra os cruzamentos que o fisco
faz: nota autorizada x escriturada, valores e ICMS destacados, devoluções, créditos vedados, apuração x documentos e
receita declarada nas duas escriturações. Não é crédito a recuperar: é o que pode gerar intimação, auto de infração
ou malha, para o contador corrigir (retificar) antes do fisco.

Cada alerta: codigo, gravidade (ALTA = cruzamento automático do fisco / imposto a menor; MEDIA = inconsistência que
costuma gerar intimação), tributo, periodo, documento, valor, detalhe, fundamento e como corrigir.
"""
from __future__ import annotations

from collections import defaultdict

TOL = 0.01

# CFOPs de devolução (Ajuste SINIEF s/n/1970, Anexo — tabela de CFOP)
DEV_VENDA = {  # entrada: devolução de venda / retorno de mercadoria vendida
    "1201", "1202", "1203", "1204", "1208", "1209", "1410", "1411", "1503", "1504", "1553", "1660", "1661", "1662",
    "2201", "2202", "2203", "2204", "2208", "2209", "2410", "2411", "2503", "2504", "2553", "2660", "2661", "2662",
    "3201", "3202", "3211", "3503", "3553",
}
DEV_COMPRA = {  # saída: devolução de compra
    "5201", "5202", "5208", "5209", "5210", "5410", "5411", "5412", "5413", "5503", "5553", "5555", "5556", "5660",
    "5661", "5662", "6201", "6202", "6208", "6209", "6210", "6410", "6411", "6412", "6413", "6503", "6553", "6555",
    "6556", "6660", "6661", "6662", "7201", "7202", "7210", "7211", "7553", "7556",
}
DEVOLUCAO = DEV_VENDA | DEV_COMPRA
USO_CONSUMO = {"1407", "2407", "1556", "2556", "3556"}
CST_PISCOF_CREDITO = {str(c) for c in range(50, 67)}
CST_PISCOF_SEM_TRIBUTO = {"04", "05", "06", "07", "08", "09"}
CANCELADA_SPED = {"02", "03", "04", "05"}  # cancelada, cancelada extemporânea, denegada, inutilizada

INFO = {
    "SAIDA_NAO_ESCRITURADA": dict(
        titulo="Nota de saída autorizada e não escriturada", tributo="ICMS",
        fundamento="RICMS/SC-01, Anexo 11 (EFD), e Convênio ICMS 143/2006: todo documento emitido deve ser escriturado. "
                   "A SEF cruza as NF-e/NFC-e autorizadas com a EFD (omissão de saída presume receita não declarada).",
        corrigir="Retificar a EFD ICMS/IPI do mês incluindo a nota (C100/C190) e recolher a diferença de ICMS, se houver, "
                 "com denúncia espontânea."),
    "ENTRADA_NAO_ESCRITURADA": dict(
        titulo="Nota de entrada (emitida contra a empresa) não escriturada", tributo="ICMS",
        fundamento="RICMS/SC-01, Anexo 11; a SEF cruza as NF-e destinadas ao CNPJ com a EFD. Entrada não registrada "
                   "permite presumir saída sem nota (RICMS/SC-01, art. 37 e Lei 10.297/96, art. 52).",
        corrigir="Escriturar a nota (ou registrar a manifestação de desconhecimento/operação não realizada, se não for "
                 "da empresa)."),
    "CHAVE_DUPLICADA": dict(
        titulo="Mesma nota escriturada mais de uma vez", tributo="ICMS",
        fundamento="Guia Prático da EFD ICMS/IPI, registro C100: cada documento é escriturado uma única vez. "
                   "Duplicidade dobra crédito ou débito.",
        corrigir="Retificar a EFD excluindo o lançamento repetido."),
    "CREDITO_MAIOR_DESTAQUE": dict(
        titulo="Crédito de ICMS escriturado maior que o destacado na nota", tributo="ICMS",
        fundamento="LC 87/96, art. 23, e RICMS/SC-01, art. 29: o crédito é o imposto destacado no documento idôneo "
                   "(no Simples Nacional, só o valor informado em vCredICMSSN — LC 123/2006, art. 23).",
        corrigir="Estornar o crédito excedente na EFD (retificação ou ajuste E111) e recolher a diferença."),
    "DEBITO_MENOR_DESTAQUE": dict(
        titulo="Débito de ICMS escriturado menor que o destacado na nota", tributo="ICMS",
        fundamento="Lei 10.297/96, art. 2º; o ICMS destacado na NF-e é o devido na operação. A SEF compara o destaque "
                   "do XML com a EFD.",
        corrigir="Retificar a EFD com o ICMS destacado e recolher a diferença."),
    "VALOR_DIVERGENTE": dict(
        titulo="Valor da nota na EFD diferente do XML", tributo="ICMS",
        fundamento="Guia Prático da EFD ICMS/IPI, registro C100: valores devem reproduzir o documento fiscal.",
        corrigir="Conferir o lançamento e retificar a EFD com os valores do documento."),
    "CANCELADA_ESCRITURADA": dict(
        titulo="Nota cancelada escriturada como regular", tributo="ICMS",
        fundamento="Guia Prático da EFD ICMS/IPI, C100: documento cancelado vai com COD_SIT 02/03 e sem valores. "
                   "Crédito ou débito de nota cancelada é indevido.",
        corrigir="Retificar a EFD com a situação de cancelada."),
    "AUTORIZADA_ESCRITURADA_CANCELADA": dict(
        titulo="Nota autorizada escriturada como cancelada", tributo="ICMS",
        fundamento="Sem evento de cancelamento homologado a nota é válida (Ajuste SINIEF 07/2005, cl. 14ª); "
                   "escriturá-la como cancelada omite a operação.",
        corrigir="Confirmar se houve cancelamento; se não houve, retificar a EFD lançando a nota com valores."),
    "DEV_ESCRITURADA_COMO_COMPRA": dict(
        titulo="Devolução de venda escriturada com CFOP de compra", tributo="ICMS/PIS/COFINS",
        fundamento="Tabela de CFOP (Convênio s/nº/1970): devolução de venda usa 1.201/1.202/1.410/1.411 (2.xxx "
                   "interestadual). Como compra, gera crédito de ICMS e de PIS/COFINS fora das regras da devolução e "
                   "distorce o custo e a receita.",
        corrigir="Retificar a EFD ICMS/IPI e a EFD-Contribuições com o CFOP de devolução; crédito de ICMS limitado ao "
                 "débito da venda original."),
    "DEV_ESCRITURADA_COMO_VENDA": dict(
        titulo="Devolução de compra escriturada com CFOP de venda", tributo="ICMS/PIS/COFINS",
        fundamento="Tabela de CFOP: devolução de compra usa 5.201/5.202/5.410/5.411 (6.xxx interestadual). Como venda, "
                   "infla o faturamento e a base de PIS/COFINS (devolução de compra não é receita).",
        corrigir="Retificar as duas EFD com o CFOP de devolução e excluir o valor da receita."),
    "CFOP_DEV_SEM_FINALIDADE": dict(
        titulo="CFOP de devolução em nota que não é de devolução", tributo="ICMS",
        fundamento="Ajuste SINIEF 07/2005 (finNFe = 4 na devolução) e tabela de CFOP: CFOP de devolução só em nota de "
                   "devolução.",
        corrigir="Conferir a nota; corrigir o CFOP na EFD."),
    "DEV_CREDITO_MAIOR_ORIGINAL": dict(
        titulo="Crédito na devolução de venda maior que o débito da venda original", tributo="ICMS",
        fundamento="RICMS/SC-01, art. 33 (devolução): o crédito se limita ao imposto debitado na saída.",
        corrigir="Estornar o excedente (E111) e recolher a diferença."),
    "DEV_SEM_NOTA_ORIGINAL": dict(
        titulo="Devolução de venda sem a nota de venda original nos arquivos", tributo="ICMS",
        fundamento="RICMS/SC-01, art. 33: o crédito da devolução depende da prova da saída original (nota referenciada).",
        corrigir="Importar o XML/EFD do mês da venda ou conferir a nota referenciada (refNFe)."),
    "DEV_CREDITO_ST": dict(
        titulo="Crédito de ICMS em devolução de mercadoria com ST", tributo="ICMS",
        fundamento="RICMS/SC-01, Anexo 3: mercadoria com ST encerrada não gera débito na saída, logo a devolução não "
                   "gera crédito pelo regime normal (o ressarcimento da ST tem rito próprio).",
        corrigir="Estornar o crédito lançado e, se for o caso, pedir o ressarcimento/restituição da ST pelo rito do Anexo 3."),
    "DEV_COMPRA_SEM_ESTORNO": dict(
        titulo="Devolução de compra tributada sem destaque do ICMS", tributo="ICMS",
        fundamento="LC 87/96, art. 21, e RICMS/SC-01: na devolução de compra o crédito da entrada tem de ser anulado "
                   "(destaque na nota de devolução).",
        corrigir="Emitir nota complementar de ICMS ou estornar o crédito da compra (E111) e recolher a diferença."),
    "DEV_PISCOF_CREDITO_SEM_TRIBUTO": dict(
        titulo="Crédito de PIS/COFINS na devolução de produto vendido sem tributação", tributo="PIS/COFINS",
        fundamento="Lei 10.637/2002 e 10.833/2003, art. 3º, VIII: a devolução só gera crédito se a receita da venda "
                   "foi tributada. Venda monofásica/alíquota zero (CST 04-09) não gera crédito na devolução.",
        corrigir="Retificar a EFD-Contribuições (CST 98/99 na devolução) e recolher a diferença."),
    "DEV_COMPRA_COMO_RECEITA": dict(
        titulo="Devolução de compra tributada como receita no PIS/COFINS", tributo="PIS/COFINS",
        fundamento="Devolução de compra não é receita (Lei 10.637 e 10.833, art. 1º); deve reduzir o crédito da compra "
                   "e não ser tributada (CST 49/98/99). Gera pagamento a maior e inconsistência com a EFD ICMS.",
        corrigir="Retificar a EFD-Contribuições: devolução de compra sem débito e com estorno do crédito da compra."),
    "CREDITO_PISCOF_CUMULATIVO": dict(
        titulo="Crédito de PIS/COFINS no regime cumulativo", tributo="PIS/COFINS",
        fundamento="Lei 9.718/98 e Lei 10.833/2003, art. 10: no regime cumulativo (Lucro Presumido/Arbitrado) não há "
                   "crédito de PIS/COFINS sobre entradas.",
        corrigir="Retificar a EFD-Contribuições com CST 70-99 nas entradas e recolher a diferença."),
    "CREDITO_ICMS_USO_CONSUMO": dict(
        titulo="Crédito de ICMS em material de uso e consumo", tributo="ICMS",
        fundamento="LC 87/96, art. 33, I (crédito de uso e consumo só a partir de 2033): vedado.",
        corrigir="Estornar o crédito (E111) e recolher a diferença."),
    "CREDITO_ICMS_ST": dict(
        titulo="Crédito de ICMS em compra com substituição tributária", tributo="ICMS",
        fundamento="RICMS/SC-01, Anexo 3: com a ST o imposto da cadeia já foi retido; a entrada não dá crédito "
                   "(CST x60 / CSOSN 500).",
        corrigir="Estornar o crédito (E111) e recolher a diferença."),
    "CFOP_CST_ST_INCOERENTE": dict(
        titulo="Venda com CST de ST mas CFOP de mercadoria tributada (ou o contrário)", tributo="ICMS",
        fundamento="Tabela de CFOP: 5.405/5.403 para mercadoria com ST; 5.102 para tributada. Combinação errada é "
                   "critério de malha de CFOP x CST.",
        corrigir="Corrigir o cadastro do produto e retificar a EFD."),
    "APURACAO_MENOR_DOCUMENTOS": dict(
        titulo="Débitos da apuração (E110) menores que o ICMS dos documentos", tributo="ICMS",
        fundamento="Guia Prático da EFD ICMS/IPI, E110: VL_TOT_DEBITOS = soma do ICMS das saídas (C190/D190...). "
                   "Diferença indica imposto declarado a menor.",
        corrigir="Conferir ajustes; retificar a EFD e recolher a diferença."),
    "RECEITA_DIVERGENTE_EFDS": dict(
        titulo="Faturamento diferente entre EFD ICMS/IPI e EFD-Contribuições", tributo="PIS/COFINS",
        fundamento="A Receita e a SEF cruzam as duas escriturações (e a DCTF/PGDAS). Receita menor na EFD-Contribuições "
                   "indica PIS/COFINS declarado a menor.",
        corrigir="Conciliar as saídas do mês e retificar a escrituração errada."),
    "SAIDA_SEM_TRIBUTO_INDEVIDA": dict(
        titulo="Venda sem PIS/COFINS de produto que não é monofásico nem alíquota zero", tributo="PIS/COFINS",
        fundamento="CST 04/06/07 exige previsão legal (Lei 10.147/2000, 10.925/2004, 10.865/2004 e outras). Sem ela, a "
                   "receita é tributada: PIS/COFINS declarado a menor.",
        corrigir="Corrigir o CST no cadastro, retificar a EFD-Contribuições e recolher a diferença."),
    "COMPRA_COMO_ST_FORA_DA_ST": dict(
        titulo="Compra escriturada como ST de produto que não tem mais ST", tributo="ICMS",
        fundamento="RICMS/SC-01, Anexo 1-A: o produto não consta da lista de ST vigente na data (medicamentos, "
                   "perfumaria, higiene e cosméticos saíram em 01/01/2021 pelo Decreto SC 982/2020; alimentos em "
                   "01/04/2018; sorvetes em 01/04/2023, entre outros). A venda é tributada normalmente e a compra dá "
                   "direito ao crédito do ICMS destacado (LC 87/96, art. 20).",
        corrigir="Corrigir o CST/acumulador de entrada desses produtos (CST 00/20). Crédito de ICMS (não de PIS/COFINS): "
                 "vale para empresa no regime normal de ICMS, seja Lucro Real ou Lucro Presumido, porque o regime do "
                 "IRPJ não muda a não cumulatividade do ICMS (LC 87/96, arts. 19 e 20); no Simples Nacional não há "
                 "crédito (LC 123/2006, art. 23). Se o fornecedor destacou ICMS próprio, o crédito não aproveitado pode "
                 "ser recuperado como extemporâneo (5 anos); se reteve ST indevidamente, a restituição é pedida pelo "
                 "fornecedor (substituto)."),
    "NUMERACAO_FALTANTE": dict(
        titulo="Números de nota próprios faltando na sequência", tributo="ICMS",
        fundamento="Ajuste SINIEF 07/2005 (cl. 14ª-A): número não utilizado deve ser inutilizado. Lacuna sem "
                   "inutilização é tratada pelo fisco como possível nota emitida e não escriturada.",
        corrigir="Conferir se os números foram inutilizados na SEFAZ; se a nota existe, escriturá-la."),
}


OPERACAO = {"0": "Entrada", "1": "Saída"}


def _alerta(codigo, gravidade, periodo=None, documento=None, valor=None, detalhe="", operacao=None, numeros=None,
            **extra):
    i = INFO[codigo]
    nums = [str(x) for x in (numeros or []) if x not in (None, "")]
    return dict(codigo=codigo, gravidade=gravidade, titulo=i["titulo"], tributo=i["tributo"], periodo=periodo,
                operacao=OPERACAO.get(operacao, operacao), numero=", ".join(nums), documento=documento,
                valor=round(valor, 2) if valor is not None else None, detalhe=detalhe,
                fundamento=i["fundamento"], corrigir=i["corrigir"], **extra)


def _doc(n) -> str:
    num = n["numero"] or "s/n"
    return f"Nota {num}" + (f" (mod. {n['modelo']})" if n["modelo"] else "")


def _ordem_num(x):
    x = str(x or "")
    return (0, int(x)) if x.isdigit() else (1, x)


def verificar(con, empresa_id: int, regras=None) -> list[dict]:
    """Roda todas as verificações para a empresa. Só confere meses que têm a escrituração correspondente."""
    alertas: list[dict] = []
    q = lambda sql, *a: con.execute(sql, a).fetchall()  # noqa: E731

    tem_icms = {r["p"] for r in q("SELECT DISTINCT substr(periodo_ini,1,7) p FROM arquivos_sped WHERE empresa_id=? "
                                  "AND tipo='EFD_ICMS_IPI' AND periodo_ini IS NOT NULL", empresa_id)}
    contrib = {r["p"]: r["regime"] for r in q(
        "SELECT substr(a.periodo_ini,1,7) p, coalesce(a.regime, e.regime) regime FROM arquivos_sped a "
        "JOIN empresas e ON e.id=a.empresa_id WHERE a.empresa_id=? AND a.tipo='EFD_CONTRIB' AND a.periodo_ini IS NOT NULL",
        empresa_id)}

    sped = defaultdict(list)
    for n in q("SELECT * FROM notas_fiscais WHERE empresa_id=? AND origem='SPED_ICMS' AND chave IS NOT NULL AND chave<>''",
               empresa_id):
        sped[n["chave"]].append(n)
    xml = {n["chave"]: n for n in q("SELECT * FROM notas_fiscais WHERE empresa_id=? AND origem='XML'", empresa_id)}

    # CFOPs e CSTs de ICMS de cada nota da EFD ICMS (C190 e C170)
    cfops = defaultdict(set)
    for r in q("SELECT n.chave, a.cfop, a.cst_icms, a.vl_icms FROM analitico_icms a JOIN notas_fiscais n ON n.id=a.nota_id "
               "WHERE a.empresa_id=?", empresa_id):
        cfops[r["chave"]].add(r["cfop"])
    for r in q("SELECT i.chave, i.cfop FROM itens_nota i JOIN arquivos_sped a ON a.id=i.arquivo_id "
               "WHERE i.empresa_id=? AND a.tipo='EFD_ICMS_IPI' AND i.chave IS NOT NULL", empresa_id):
        cfops[r["chave"]].add(r["cfop"])

    # ---------------------------------------------------------------- nota a nota (XML x EFD ICMS)
    for chave, regs in sped.items():
        validos = [n for n in regs if (n["cod_sit"] or "00") not in CANCELADA_SPED]
        if len(validos) > 1:
            n = validos[0]
            alertas.append(_alerta("CHAVE_DUPLICADA", "ALTA", n["periodo"], _doc(n), n["vl_doc"],
                                   f"Escriturada {len(validos)} vezes.", chave=chave,
                                   operacao=n["ind_oper"], numeros=[n["numero"]]))
    for chave, x in xml.items():
        if x["periodo"] not in tem_icms:
            continue
        regs = sped.get(chave)
        propria = x["ind_emit"] == "0"
        if not regs:
            if x["cancelada"]:
                continue
            if propria and x["ind_oper"] == "1":
                alertas.append(_alerta("SAIDA_NAO_ESCRITURADA", "ALTA", x["periodo"], _doc(x), x["vl_doc"],
                                       f"ICMS destacado {x['vl_icms'] or 0:.2f}.", chave=chave,
                                       operacao="1", numeros=[x["numero"]]))
            elif not propria:
                alertas.append(_alerta("ENTRADA_NAO_ESCRITURADA", "MEDIA", x["periodo"], _doc(x), x["vl_doc"],
                                       f"Emitente {x['cnpj_emit']}. Pode ter sido escriturada em mês seguinte "
                                       "ainda não importado.", chave=chave,
                                       operacao="0", numeros=[x["numero"]]))
            continue
        s = regs[0]
        sit_cancel = (s["cod_sit"] or "00") in CANCELADA_SPED
        if x["cancelada"] and not sit_cancel:
            alertas.append(_alerta("CANCELADA_ESCRITURADA", "ALTA", s["periodo"], _doc(s), s["vl_doc"], chave=chave, operacao=s["ind_oper"], numeros=[s["numero"]]))
            continue
        if not x["cancelada"] and sit_cancel and (s["cod_sit"] or "") in ("02", "03"):
            alertas.append(_alerta("AUTORIZADA_ESCRITURADA_CANCELADA", "ALTA", s["periodo"], _doc(s), x["vl_doc"],
                                   "O XML importado não tem evento de cancelamento.", chave=chave, operacao=s["ind_oper"], numeros=[s["numero"]]))
            continue
        if sit_cancel:
            continue
        if abs((s["vl_doc"] or 0) - (x["vl_doc"] or 0)) > TOL:
            alertas.append(_alerta("VALOR_DIVERGENTE", "MEDIA", s["periodo"], _doc(s), (s["vl_doc"] or 0) - (x["vl_doc"] or 0),
                                   f"EFD {s['vl_doc'] or 0:.2f}; XML {x['vl_doc'] or 0:.2f}.", chave=chave, operacao=s["ind_oper"], numeros=[s["numero"]]))
        icms_e, icms_x = s["vl_icms"] or 0, x["vl_icms"] or 0
        if s["ind_oper"] == "0":
            simples = (x["crt_emit"] or "") in ("1", "4")
            permitido = (x["vl_cred_sn"] or 0) if simples else icms_x
            if icms_e > permitido + TOL:
                alertas.append(_alerta("CREDITO_MAIOR_DESTAQUE", "ALTA", s["periodo"], _doc(s), icms_e - permitido,
                                       f"Escriturado {icms_e:.2f}; permitido {permitido:.2f}"
                                       + (" (fornecedor do Simples Nacional)." if simples else "."), chave=chave, operacao=s["ind_oper"], numeros=[s["numero"]]))
        elif propria and icms_e < icms_x - TOL:
            alertas.append(_alerta("DEBITO_MENOR_DESTAQUE", "ALTA", s["periodo"], _doc(s), icms_x - icms_e,
                                   f"Destacado {icms_x:.2f}; escriturado {icms_e:.2f}.", chave=chave, operacao=s["ind_oper"], numeros=[s["numero"]]))

        # devoluções pela finalidade do XML (finNFe 4)
        cf = {c for c in cfops.get(chave, set()) if c}
        if x["fin_nfe"] == "4" and cf:
            if s["ind_oper"] == "0" and not (cf & DEVOLUCAO):
                alertas.append(_alerta("DEV_ESCRITURADA_COMO_COMPRA", "ALTA", s["periodo"], _doc(s), s["vl_doc"],
                                       f"CFOP escriturado {', '.join(sorted(cf))}.", chave=chave, operacao=s["ind_oper"], numeros=[s["numero"]]))
            elif s["ind_oper"] == "1" and not (cf & DEVOLUCAO):
                alertas.append(_alerta("DEV_ESCRITURADA_COMO_VENDA", "ALTA", s["periodo"], _doc(s), s["vl_doc"],
                                       f"CFOP escriturado {', '.join(sorted(cf))}.", chave=chave, operacao=s["ind_oper"], numeros=[s["numero"]]))
        elif x["fin_nfe"] in ("1", "2", "3") and cf and cf <= DEVOLUCAO:
            alertas.append(_alerta("CFOP_DEV_SEM_FINALIDADE", "MEDIA", s["periodo"], _doc(s), s["vl_doc"],
                                   f"CFOP {', '.join(sorted(cf))}; XML com finalidade {x['fin_nfe']}.", chave=chave, operacao=s["ind_oper"], numeros=[s["numero"]]))
        # devolução de venda: crédito limitado ao débito da venda original
        if s["ind_oper"] == "0" and (x["fin_nfe"] == "4" or cf & DEV_VENDA) and icms_e > TOL:
            orig = xml.get(x["chave_ref"]) if x["chave_ref"] else None
            if x["chave_ref"] and orig is None:
                alertas.append(_alerta("DEV_SEM_NOTA_ORIGINAL", "MEDIA", s["periodo"], _doc(s), icms_e,
                                       f"Nota referenciada {x['chave_ref']} não está nos arquivos importados.",
                                       chave=chave, operacao=s["ind_oper"], numeros=[s["numero"]]))
            elif orig is not None and orig["ind_oper"] == "1" and icms_e > (orig["vl_icms"] or 0) + TOL:
                alertas.append(_alerta("DEV_CREDITO_MAIOR_ORIGINAL", "ALTA", s["periodo"], _doc(s),
                                       icms_e - (orig["vl_icms"] or 0),
                                       f"Crédito {icms_e:.2f}; débito da venda {orig['numero']} {orig['vl_icms'] or 0:.2f}.",
                                       chave=chave, operacao=s["ind_oper"], numeros=[s["numero"]]))

    # ---------------------------------------------------------------- item / C190 da EFD ICMS
    linhas_icms = q(
        "SELECT n.periodo, n.numero, n.modelo, n.chave, n.ind_oper, n.ind_emit, a.cfop, a.cst_icms, a.vl_icms, a.vl_opr "
        "FROM analitico_icms a JOIN notas_fiscais n ON n.id=a.nota_id WHERE a.empresa_id=? "
        "AND coalesce(n.cod_sit,'00') NOT IN ('02','03','04','05')", empresa_id)
    agrup = defaultdict(lambda: [0.0, 0, None])
    numeros_grupo = defaultdict(list)
    for r in linhas_icms:
        cfop, cst, icms = r["cfop"] or "", (r["cst_icms"] or "")[-2:], r["vl_icms"] or 0
        if r["ind_oper"] == "0" and icms > TOL:
            if cfop in USO_CONSUMO:
                k = ("CREDITO_ICMS_USO_CONSUMO", r["periodo"])
            elif cst == "60" and cfop in DEV_VENDA:
                k = ("DEV_CREDITO_ST", r["periodo"])
            elif cst == "60":
                k = ("CREDITO_ICMS_ST", r["periodo"])
            else:
                k = None
            if k:
                agrup[k][0] += icms
                agrup[k][1] += 1
                agrup[k][2] = agrup[k][2] or _doc(r)
                numeros_grupo[k].append(r["numero"])
        if r["ind_oper"] == "1" and cfop in DEV_COMPRA and cst in ("00", "10", "20", "70", "90") and icms <= TOL \
                and (r["vl_opr"] or 0) > TOL:
            k = ("DEV_COMPRA_SEM_ESTORNO", r["periodo"])
            agrup[k][0] += r["vl_opr"] or 0
            agrup[k][1] += 1
            agrup[k][2] = agrup[k][2] or _doc(r)
            numeros_grupo[k].append(r["numero"])
        if r["ind_oper"] == "1" and r["ind_emit"] == "0" and (
                (cst == "60" and cfop[1:] in ("102", "101")) or (cst in ("00", "20") and cfop[1:] in ("405", "403"))):
            k = ("CFOP_CST_ST_INCOERENTE", r["periodo"])
            agrup[k][0] += r["vl_opr"] or 0
            agrup[k][1] += 1
            agrup[k][2] = agrup[k][2] or _doc(r)
            numeros_grupo[k].append(r["numero"])
    for (codigo, per), (valor, qtd, doc) in sorted(agrup.items(), key=lambda x: (x[0][1] or "", x[0][0])):
        grav = "MEDIA" if codigo == "CFOP_CST_ST_INCOERENTE" else "ALTA"
        rotulo = "valor das operações" if codigo in ("DEV_COMPRA_SEM_ESTORNO", "CFOP_CST_ST_INCOERENTE") else "ICMS creditado"
        op = "1" if codigo in ("DEV_COMPRA_SEM_ESTORNO", "CFOP_CST_ST_INCOERENTE") else "0"
        alertas.append(_alerta(codigo, grav, per, doc if qtd == 1 else f"{qtd} lançamentos (ex.: {doc})", valor,
                               f"{rotulo.capitalize()}: {valor:.2f}.", operacao=op,
                               numeros=sorted(set(numeros_grupo[(codigo, per)]), key=_ordem_num)))

    # ---------------------------------------------------------------- compra como ST de produto fora da ST
    if regras is not None:
        uf = (con.execute("SELECT uf FROM empresas WHERE id=?", (empresa_id,)).fetchone() or {"uf": ""})["uf"]
        grupo = defaultdict(lambda: [0.0, set(), set(), None])
        for r in q("SELECT i.periodo, i.data, i.num_doc, i.ncm, i.descricao, i.cst_icms, i.vl_item, i.vl_desc "
                   "FROM itens_nota i JOIN arquivos_sped a ON a.id=i.arquivo_id WHERE i.empresa_id=? "
                   "AND a.tipo='EFD_ICMS_IPI' AND i.ind_oper='0' AND i.origem='C170'", empresa_id):
            cst = r["cst_icms"] or ""
            if not ((len(cst) == 3 and cst[1:] == "60") or cst == "500"):
                continue
            seg = regras.fora_da_st(uf, r["ncm"], r["data"], r["descricao"])
            if not seg:
                continue
            g = grupo[r["periodo"]]
            g[0] += (r["vl_item"] or 0) - (r["vl_desc"] or 0)
            g[1].add(r["num_doc"])
            if len(g[2]) < 3:
                g[2].add(f"{r['descricao']} (NCM {r['ncm']})")
            g[3] = seg["segmento"]
        for per, (valor, notas, ex, seg) in sorted(grupo.items()):
            alertas.append(_alerta("COMPRA_COMO_ST_FORA_DA_ST", "MEDIA", per, f"{len(notas)} nota(s) de compra", valor,
                                   f"Valor das compras {valor:.2f}. Ex.: {'; '.join(sorted(ex))}.", operacao="0",
                                   numeros=sorted(notas - {None, ""}, key=_ordem_num)))

    # ---------------------------------------------------------------- apuração x documentos (E110)
    deb_docs = defaultdict(float)
    for r in linhas_icms:
        if r["ind_oper"] == "1":
            deb_docs[r["periodo"]] += r["vl_icms"] or 0
    for a in q("SELECT periodo, debitos FROM apuracoes WHERE empresa_id=? AND tributo='ICMS'", empresa_id):
        docs = deb_docs.get(a["periodo"], 0)
        if docs > (a["debitos"] or 0) + max(1.0, 0.005 * docs):
            alertas.append(_alerta("APURACAO_MENOR_DOCUMENTOS", "ALTA", a["periodo"], "E110", docs - (a["debitos"] or 0),
                                   f"ICMS das saídas {docs:.2f}; débitos no E110 {a['debitos'] or 0:.2f}.", operacao="1"))

    # ---------------------------------------------------------------- EFD-Contribuições
    itens_c = q("SELECT i.* FROM itens_nota i JOIN arquivos_sped a ON a.id=i.arquivo_id "
                "WHERE i.empresa_id=? AND a.tipo='EFD_CONTRIB'", empresa_id)
    vendidos_sem_tributo = {r["cod_item"] for r in itens_c
                            if r["ind_oper"] == "1" and (r["cst_pis"] or "") in CST_PISCOF_SEM_TRIBUTO and r["cod_item"]}
    agrup = defaultdict(lambda: [0.0, 0, None])
    numeros_c = defaultdict(list)
    for r in itens_c:
        cfop, cst, per = r["cfop"] or "", r["cst_pis"] or "", r["periodo"]
        cred = (r["vl_pis"] or 0) + (r["vl_cofins"] or 0)
        k = None
        if r["ind_oper"] == "0" and cst in CST_PISCOF_CREDITO and cred > TOL:
            if contrib.get(per) == "LUCRO_PRESUMIDO":
                k = "CREDITO_PISCOF_CUMULATIVO"
            elif cfop in DEV_VENDA and r["cod_item"] in vendidos_sem_tributo:
                k = "DEV_PISCOF_CREDITO_SEM_TRIBUTO"
        elif r["ind_oper"] == "1" and cfop in DEV_COMPRA and cst in ("01", "02", "03") and cred > TOL:
            k = "DEV_COMPRA_COMO_RECEITA"
        if k:
            agrup[(k, per)][0] += cred
            agrup[(k, per)][1] += 1
            agrup[(k, per)][2] = agrup[(k, per)][2] or f"Nota {r['num_doc'] or 's/n'}"
            numeros_c[(k, per)].append(r["num_doc"])
    for (codigo, per), (valor, qtd, doc) in sorted(agrup.items(), key=lambda x: (x[0][1] or "", x[0][0])):
        alertas.append(_alerta(codigo, "ALTA", per, doc if qtd == 1 else f"{qtd} itens (ex.: {doc})", valor,
                               f"PIS + COFINS: {valor:.2f}.", operacao="1" if codigo == "DEV_COMPRA_COMO_RECEITA" else "0",
                               numeros=sorted(set(numeros_c[(codigo, per)]), key=_ordem_num)))

    # saída sem tributo sem previsão legal (usa as regras do programa)
    if regras is not None:
        from .coerencia import conferir

        cache: dict = {}

        def classificar_ncm(base, ncm, desc, data):
            k = (ncm, desc, (data or "")[:7])
            if k not in cache:
                cache[k] = _classificar(base, ncm, desc, data)
            return cache[k]

        def _classificar(base, ncm, desc, data):
            cn = conferir(ncm, desc, base)
            if cn.grave:
                return None
            return base.classificar(cn.ncm, data, "MONOFASICO", desc) or base.classificar(cn.ncm, data, "ALIQ_ZERO", desc)
        agrup = defaultdict(lambda: [0.0, 0, set()])
        nums_sai = defaultdict(set)
        for r in itens_c:
            if r["ind_oper"] != "1" or (r["cst_pis"] or "") not in ("04", "06", "07") or (r["cfop"] or "") in DEVOLUCAO:
                continue
            if classificar_ncm(regras, r["ncm"], r["descricao"], r["data"]) is not None:
                continue
            k = r["periodo"]
            agrup[k][0] += (r["vl_item"] or 0) - (r["vl_desc"] or 0)
            agrup[k][1] += 1
            nums_sai[k].add(r["num_doc"])
            if len(agrup[k][2]) < 3:
                agrup[k][2].add(f"{r['descricao'] or r['cod_item']} (NCM {r['ncm'] or '-'})")
        for per, (valor, qtd, ex) in sorted(agrup.items()):
            alertas.append(_alerta("SAIDA_SEM_TRIBUTO_INDEVIDA", "ALTA", per, f"{qtd} itens", valor,
                                   f"Receita sem PIS/COFINS {valor:.2f}. Ex.: {'; '.join(sorted(ex))}.", operacao="1",
                                   numeros=sorted(nums_sai[per] - {None, ""}, key=_ordem_num)))

    # faturamento EFD ICMS x EFD-Contribuições
    rec_icms, rec_contrib = defaultdict(float), defaultdict(float)
    for r in linhas_icms:
        if r["ind_oper"] == "1" and (r["cfop"] or "")[:1] in ("5", "6", "7") and (r["cfop"] or "") not in DEV_COMPRA:
            rec_icms[r["periodo"]] += r["vl_opr"] or 0
    for r in itens_c:
        if r["ind_oper"] == "1" and (r["cfop"] or "") not in DEV_COMPRA:
            rec_contrib[r["periodo"]] += (r["vl_item"] or 0) - (r["vl_desc"] or 0)
    for per in sorted(set(rec_icms) & set(rec_contrib)):
        a, b = rec_icms[per], rec_contrib[per]
        if a > 0 and b < a * 0.98:
            alertas.append(_alerta("RECEITA_DIVERGENTE_EFDS", "ALTA" if b < a * 0.9 else "MEDIA", per, "Saídas do mês",
                                   a - b, f"EFD ICMS/IPI {a:.2f}; EFD-Contribuições {b:.2f}.", operacao="1"))

    # ---------------------------------------------------------------- numeração própria
    nums = defaultdict(set)
    for n in q("SELECT periodo, modelo, serie, numero FROM notas_fiscais WHERE empresa_id=? AND ind_emit='0' "
               "AND origem IN ('SPED_ICMS','XML') AND modelo IN ('55','65')", empresa_id):
        if n["numero"] and str(n["numero"]).isdigit() and n["periodo"] in tem_icms:
            serie = (str(n["serie"] or "").lstrip("0")) or "0"  # EFD traz "001", XML traz "1"
            nums[(n["periodo"], n["modelo"], serie)].add(int(n["numero"]))
    for (per, mod, serie), ns in sorted(nums.items()):
        if len(ns) < 2:
            continue
        faltam = (max(ns) - min(ns) + 1) - len(ns)
        if 0 < faltam <= 5000:
            for i in range(min(ns), max(ns) + 1):
                if i in ns:
                    continue
                ant = max(x for x in ns if x < i)
                prox = min(x for x in ns if x > i)
                alertas.append(_alerta("NUMERACAO_FALTANTE", "MEDIA", per, f"Modelo {mod}, série {serie}", None,
                                       f"Nº {i} sem nota (sequência vai do {ant} ao {prox}).",
                                       operacao="Saída (emissão própria)",
                                       numeros=[i]))

    ordem = {"ALTA": 0, "MEDIA": 1}
    alertas.sort(key=lambda a: (ordem.get(a["gravidade"], 2), a["periodo"] or "", a["codigo"],
                                _ordem_num(a["numero"].split(",")[0] if a["numero"] else "")))
    return alertas


def resumo(alertas: list[dict]) -> dict:
    return dict(total=len(alertas), alta=sum(a["gravidade"] == "ALTA" for a in alertas),
                media=sum(a["gravidade"] == "MEDIA" for a in alertas))
