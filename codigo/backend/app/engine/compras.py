"""Lista de todos os produtos de compra auditados: o que o fornecedor destacou (XML ou planilha do DF-e) ao lado do
que a EFD ICMS/IPI escriturou como crédito, item a item. Serve para o contador conferir o que o motor concluiu."""
from __future__ import annotations

from .icms import _eh_st

CENT = 0.01

SITUACOES = {
    "CREDITADO": "Creditado igual ao destacado",
    "MENOR": "Crédito menor que o destacado",
    "MAIOR": "Crédito maior que o destacado",
    "SEM_DESTAQUE": "Sem ICMS próprio destacado (ST, isento, Simples)",
    "SIMPLES": "Fornecedor do Simples: crédito pelo total da nota (vCredICMSSN)",
    "FORA_EFD": "Nota fora da EFD ICMS/IPI",
    "SEM_XML": "Sem XML/DF-e para conferir",
    "SEM_C170": "EFD sem os itens (C170): conferir pelo total da nota",
}


def _r(v):
    return round(v or 0.0, 2)


def listar(con, empresa_id: int, ini: str, fim: str) -> list[dict]:
    per = (ini or "0000-00", fim or "9999-99")
    efd = con.execute(
        "SELECT i.chave, i.num_doc, i.data, i.num_item, i.cod_item, i.descricao, i.ncm, i.cfop, i.cst_icms, "
        "i.vl_item, i.vl_desc, i.vl_icms, n.cnpj_emit "
        "FROM itens_nota i JOIN arquivos_sped a ON a.id=i.arquivo_id LEFT JOIN notas_fiscais n ON n.id=i.nota_id "
        "WHERE i.empresa_id=? AND a.tipo='EFD_ICMS_IPI' AND i.ind_oper='0' AND COALESCE(n.cancelada,0)=0 "
        "AND i.periodo BETWEEN ? AND ?", (empresa_id, *per)).fetchall()
    notas_efd = {r["chave"] for r in con.execute(
        "SELECT chave FROM notas_fiscais WHERE empresa_id=? AND origem='SPED_ICMS' AND ind_oper='0' "
        "AND periodo BETWEEN ? AND ?", (empresa_id, *per)) if r["chave"]}
    xml = con.execute(
        "SELECT i.chave, i.num_doc, i.data, i.num_item, i.cod_item, i.descricao, i.ncm, i.cfop, i.cst_icms, "
        "i.vl_item, i.vl_desc, i.vl_icms, n.cnpj_emit, n.crt_emit "
        "FROM itens_nota i JOIN arquivos_sped a ON a.id=i.arquivo_id JOIN notas_fiscais n ON n.id=i.nota_id "
        "WHERE i.empresa_id=? AND a.tipo='XML_NFE' AND i.ind_oper='0' AND n.ind_emit='1' AND n.cancelada=0 "
        "AND i.periodo BETWEEN ? AND ?", (empresa_id, *per)).fetchall()
    por_item = {(r["chave"], str(int(r["num_item"])) if str(r["num_item"] or "").isdigit() else r["num_item"]): r
                for r in xml}
    usados, out = set(), []

    def _dest(x):
        if x is None:
            return None
        if (x["crt_emit"] or "") in ("1", "4") or len(x["cst_icms"] or "") == 4:
            return 0.0
        return 0.0 if _eh_st(x["cst_icms"]) else (x["vl_icms"] or 0.0)

    for e in efd:
        k = (e["chave"], str(int(e["num_item"])) if str(e["num_item"] or "").isdigit() else e["num_item"])
        x = por_item.get(k)
        if x is not None:
            usados.add(k)
        dest, cred = _dest(x), e["vl_icms"] or 0.0
        if x is None:
            sit = "SEM_XML"
        elif (x["crt_emit"] or "") in ("1", "4") or len(x["cst_icms"] or "") == 4:
            sit = "SIMPLES"
        elif dest - cred > CENT:
            sit = "MENOR"
        elif cred - dest > CENT:
            sit = "MAIOR"
        elif dest > CENT:
            sit = "CREDITADO"
        else:
            sit = "SEM_DESTAQUE"
        out.append(dict(
            nota=e["num_doc"], data=e["data"], chave=e["chave"], item=e["num_item"], cnpj_emit=e["cnpj_emit"],
            cod_item=e["cod_item"], descricao=e["descricao"] or (x["descricao"] if x else ""), ncm=e["ncm"],
            cfop=e["cfop"], cst_efd=e["cst_icms"], cst_fornecedor=x["cst_icms"] if x else None,
            valor=_r((e["vl_item"] or 0) - (e["vl_desc"] or 0)), destacado=None if dest is None else _r(dest),
            creditado=_r(cred), diferenca=None if dest is None or sit == "SIMPLES" else _r(dest - cred),
            situacao=sit))
    for k, x in por_item.items():
        if k in usados:
            continue
        sit = "SEM_C170" if x["chave"] in notas_efd else "FORA_EFD"
        dest = _dest(x)
        out.append(dict(
            nota=x["num_doc"], data=x["data"], chave=x["chave"], item=x["num_item"], cnpj_emit=x["cnpj_emit"],
            cod_item=x["cod_item"], descricao=x["descricao"], ncm=x["ncm"], cfop=x["cfop"], cst_efd=None,
            cst_fornecedor=x["cst_icms"], valor=_r((x["vl_item"] or 0) - (x["vl_desc"] or 0)), destacado=_r(dest),
            creditado=None, diferenca=_r(dest) if sit == "FORA_EFD" else None, situacao=sit))
    out.sort(key=lambda r: (r["data"] or "", r["nota"] or "", int(r["item"]) if str(r["item"] or "").isdigit() else 0))
    return out


def resumo(linhas: list[dict]) -> list[dict]:
    tot = {}
    for r in linhas:
        t = tot.setdefault(r["situacao"], dict(situacao=r["situacao"], nome=SITUACOES[r["situacao"]], itens=0,
                                                destacado=0.0, creditado=0.0))
        t["itens"] += 1
        t["destacado"] += r["destacado"] or 0
        t["creditado"] += r["creditado"] or 0
    return [dict(t, destacado=_r(t["destacado"]), creditado=_r(t["creditado"])) for t in tot.values()]
