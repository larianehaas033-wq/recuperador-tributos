"""Importação de arquivos para o banco: SPED (EFD-Contribuições e EFD ICMS/IPI) e XMLs."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from . import db
from .parsers.efd import parse_efd
from .parsers.nfe_xml import iter_xml_sources, parse_nfe_bytes
from .parsers.sped_common import identificar_tipo, sha256_file

ITEM_COLS = [
    "nota_id", "empresa_id", "arquivo_id", "origem", "periodo", "data", "chave", "num_doc", "ind_oper", "cnpj_part",
    "num_item", "cod_item", "descricao", "ncm", "cfop", "unidade", "qtd", "vl_item", "vl_desc", "cst_icms",
    "vl_bc_icms", "aliq_icms", "vl_icms", "vl_bc_icms_st", "vl_icms_st", "vl_ipi", "cst_pis", "vl_bc_pis",
    "aliq_pis", "vl_pis", "cst_cofins", "vl_bc_cofins", "aliq_cofins", "vl_cofins", "cst_ibscbs", "cclasstrib",
]
NOTA_COLS = [
    "empresa_id", "arquivo_id", "origem", "chave", "modelo", "serie", "numero", "data", "periodo", "ind_oper",
    "ind_emit", "cnpj_emit", "cnpj_part", "cod_sit", "cancelada", "vl_doc", "vl_icms", "vl_icms_st", "vl_pis",
    "vl_cofins",
]

REGIME = {"1": "LUCRO_REAL", "2": "LUCRO_PRESUMIDO", "3": "MISTO"}

Progress = Callable[[str, float], None]


def _upsert_empresa(con, cnpj: str, nome: str, uf: str, regime: str | None, ind_ativ: str | None) -> int:
    row = con.execute("SELECT id, regime, ind_ativ FROM empresas WHERE raiz_cnpj = ?", (cnpj[:8],)).fetchone()
    if row:
        if regime and not row["regime"]:
            con.execute("UPDATE empresas SET regime = ? WHERE id = ?", (regime, row["id"]))
        if ind_ativ and not row["ind_ativ"]:
            con.execute("UPDATE empresas SET ind_ativ = ? WHERE id = ?", (ind_ativ, row["id"]))
        return row["id"]
    cur = con.execute(
        "INSERT INTO empresas (cnpj, raiz_cnpj, nome, uf, regime, ind_ativ) VALUES (?,?,?,?,?,?)",
        (cnpj, cnpj[:8], nome, uf, regime, ind_ativ),
    )
    return cur.lastrowid


def gravar_produtos(con, empresa_id: int, produtos: dict) -> None:
    """Cadastro de produtos (registro 0200): tipo do item é a prova da destinação (revenda, insumo, uso e consumo)."""
    con.executemany(
        "INSERT INTO produtos (empresa_id, cod_item, descricao, ncm, tipo_item, unidade) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(empresa_id, cod_item) DO UPDATE SET descricao=excluded.descricao, ncm=excluded.ncm, "
        "tipo_item=COALESCE(NULLIF(excluded.tipo_item,''), produtos.tipo_item), unidade=excluded.unidade",
        [(empresa_id, k, v.get("descricao"), v.get("ncm"), v.get("tipo"), v.get("unidade")) for k, v in produtos.items()],
    )


def importar_sped(path: Path, progress: Progress | None = None) -> dict:
    tipo = identificar_tipo(path)
    if not tipo:
        return {"arquivo": path.name, "status": "IGNORADO", "motivo": "Não é um arquivo SPED reconhecido."}
    h = sha256_file(path)
    with db.tx() as con:
        if con.execute("SELECT 1 FROM arquivos_sped WHERE hash = ?", (h,)).fetchone():
            return {"arquivo": path.name, "status": "JA_IMPORTADO", "tipo": tipo}

    if progress:
        progress(f"Lendo {path.name}", 0.1)
    r = parse_efd(path, tipo)
    if not r.cnpj:
        return {"arquivo": path.name, "status": "ERRO", "motivo": "Arquivo sem CNPJ no registro 0000."}

    with db.tx() as con:
        regime = REGIME.get(r.regime_pis_cofins) if tipo == "EFD_CONTRIB" else None
        empresa_id = _upsert_empresa(con, r.cnpj, r.nome, r.uf, regime,
                                     r.ind_ativ if tipo == "EFD_CONTRIB" else None)
        substituido = None
        antigo = con.execute(
            "SELECT id, nome, finalidade FROM arquivos_sped WHERE empresa_id=? AND tipo=? AND periodo_ini=?",
            (empresa_id, tipo, r.dt_ini),
        ).fetchone()
        if antigo:
            if antigo["finalidade"] == "retificadora" and r.finalidade == "original":
                return {"arquivo": path.name, "status": "IGNORADO",
                        "motivo": f"Já existe retificadora para {r.dt_ini[:7]} ({antigo['nome']})."}
            con.execute("DELETE FROM arquivos_sped WHERE id = ?", (antigo["id"],))
            substituido = antigo["nome"]

        cur = con.execute(
            "INSERT INTO arquivos_sped (empresa_id, tipo, nome, caminho, hash, periodo_ini, periodo_fim, finalidade,"
            " qtd_registros) VALUES (?,?,?,?,?,?,?,?,?)",
            (empresa_id, tipo, path.name, str(path), h, r.dt_ini, r.dt_fin, r.finalidade, r.registros),
        )
        arquivo_id = cur.lastrowid
        origem_doc = "SPED_CONTRIB" if tipo == "EFD_CONTRIB" else "SPED_ICMS"

        nota_ids: dict[int, int] = {}
        for n in r.notas:
            vals = dict(n, empresa_id=empresa_id, arquivo_id=arquivo_id, origem=origem_doc,
                        cnpj_emit=r.cnpj if n.get("ind_emit") == "0" else n.get("cnpj_part"))
            cur = con.execute(
                f"INSERT INTO notas_fiscais ({','.join(NOTA_COLS)}) VALUES ({','.join('?' * len(NOTA_COLS))})",
                [vals.get(c) for c in NOTA_COLS],
            )
            nota_ids[n["_idx"]] = cur.lastrowid

        gravar_produtos(con, empresa_id, r.produtos)
        batch = []
        for it in r.itens:
            vals = dict(it, nota_id=nota_ids.get(it.get("_nota")), empresa_id=empresa_id, arquivo_id=arquivo_id)
            batch.append([vals.get(c) for c in ITEM_COLS])
        con.executemany(
            f"INSERT INTO itens_nota ({','.join(ITEM_COLS)}) VALUES ({','.join('?' * len(ITEM_COLS))})", batch
        )
        for a in r.apuracoes:
            con.execute(
                "INSERT INTO apuracoes (empresa_id, arquivo_id, periodo, tributo, debitos, creditos, valor_recolher,"
                " saldo_credor) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(empresa_id, periodo, tributo) DO UPDATE SET"
                " arquivo_id=excluded.arquivo_id, debitos=excluded.debitos, creditos=excluded.creditos,"
                " valor_recolher=excluded.valor_recolher, saldo_credor=excluded.saldo_credor",
                (empresa_id, arquivo_id, a["periodo"], a["tributo"], a["debitos"], a["creditos"],
                 a["valor_recolher"], a["saldo_credor"]),
            )

    return {
        "arquivo": path.name, "status": "IMPORTADO", "tipo": tipo, "empresa_id": empresa_id, "cnpj": r.cnpj,
        "nome": r.nome, "periodo": (r.dt_ini or "")[:7], "finalidade": r.finalidade, "notas": len(r.notas),
        "itens": len(r.itens), "substituiu": substituido, "avisos": r.avisos,
    }


def importar_xmls(paths: list[Path], progress: Progress | None = None) -> dict:
    """Importa XMLs (arquivos, pastas, zip). Cada nota vai para a empresa cujo CNPJ (raiz) é emitente
    ou destinatário. Notas repetidas (mesma chave) são ignoradas."""
    notas, cancel = [], set()
    for i, (nome, data) in enumerate(iter_xml_sources(paths)):
        n = parse_nfe_bytes(data, nome)
        if not n:
            continue
        if n["tipo"] == "CANCELAMENTO":
            cancel.add(n["chave"])
        else:
            notas.append(n)
        if progress and i % 500 == 0:
            progress(f"Lendo XMLs ({i})", 0.2)

    resumo = {"arquivo": "XMLs", "status": "IMPORTADO", "tipo": "XML_NFE", "lidas": len(notas),
              "canceladas": len(cancel), "importadas": 0, "repetidas": 0, "sem_empresa": 0, "empresas": []}
    if not notas and not cancel:
        resumo["status"] = "IGNORADO"
        resumo["motivo"] = "Nenhum XML de NF-e/NFC-e válido encontrado."
        return resumo

    with db.tx() as con:
        empresas = {r["raiz_cnpj"]: r["id"] for r in con.execute("SELECT id, raiz_cnpj FROM empresas")}
        existentes = {r["chave"] for r in con.execute("SELECT chave FROM notas_fiscais WHERE origem='XML'")}
        h = hashlib.sha256("|".join(sorted(n["chave"] for n in notas)).encode()).hexdigest()
        if con.execute("SELECT 1 FROM arquivos_sped WHERE hash=?", (h,)).fetchone() and not cancel:
            resumo["status"] = "JA_IMPORTADO"
            return resumo
        arquivos: dict[int, int] = {}
        itens_batch = []
        for n in notas:
            emp_emit = empresas.get(n["cnpj_emit"][:8])
            emp_dest = empresas.get(n["cnpj_dest"][:8]) if not n["dest_cpf"] else None
            empresa_id = emp_emit or emp_dest
            if not empresa_id:
                resumo["sem_empresa"] += 1
                continue
            if n["chave"] in existentes:
                resumo["repetidas"] += 1
                continue
            existentes.add(n["chave"])
            if empresa_id not in arquivos:
                cur = con.execute(
                    "INSERT INTO arquivos_sped (empresa_id, tipo, nome, caminho, hash, finalidade) VALUES"
                    " (?,?,?,?,?,?)",
                    (empresa_id, "XML_NFE", "Lote de XMLs", ";".join(str(p) for p in paths)[:500],
                     f"{h}-{empresa_id}", "original"),
                )
                arquivos[empresa_id] = cur.lastrowid
            # ponto de vista da empresa: emitente com tpNF=1 é saída; destinatário é entrada
            if emp_emit == empresa_id:
                ind_oper = "1" if n["tp_nf"] == "1" else "0"
                ind_emit, part = "0", n["cnpj_dest"]
            else:
                ind_oper, ind_emit, part = "0", "1", n["cnpj_emit"]
            cancelada = 1 if (n["chave"] in cancel or not n["autorizada"]) else 0
            vals = dict(
                empresa_id=empresa_id, arquivo_id=arquivos[empresa_id], origem="XML", chave=n["chave"],
                modelo=n["modelo"], serie=n["serie"], numero=n["numero"], data=n["data"], periodo=n["periodo"],
                ind_oper=ind_oper, ind_emit=ind_emit, cnpj_emit=n["cnpj_emit"], cnpj_part=part, cod_sit=n["cstat"],
                cancelada=cancelada, vl_doc=n["vl_doc"], vl_icms=n["vl_icms"], vl_icms_st=n["vl_icms_st"],
                vl_pis=n["vl_pis"], vl_cofins=n["vl_cofins"],
            )
            cur = con.execute(
                f"INSERT INTO notas_fiscais ({','.join(NOTA_COLS)}) VALUES ({','.join('?' * len(NOTA_COLS))})",
                [vals.get(c) for c in NOTA_COLS],
            )
            nota_id = cur.lastrowid
            resumo["importadas"] += 1
            for it in n["itens"]:
                v = dict(it, nota_id=nota_id, empresa_id=empresa_id, arquivo_id=arquivos[empresa_id], origem="XML",
                         periodo=n["periodo"], data=n["data"], chave=n["chave"], num_doc=n["numero"],
                         ind_oper=ind_oper, cnpj_part=part)
                itens_batch.append([v.get(c) for c in ITEM_COLS])
        if itens_batch:
            con.executemany(
                f"INSERT INTO itens_nota ({','.join(ITEM_COLS)}) VALUES ({','.join('?' * len(ITEM_COLS))})",
                itens_batch,
            )
        if cancel:
            con.executemany("UPDATE notas_fiscais SET cancelada=1 WHERE chave=? AND origem='XML'",
                            [(c,) for c in cancel])
        resumo["empresas"] = list(arquivos.keys())
    return resumo


def importar(paths: list[Path], progress: Progress | None = None) -> list[dict]:
    """Ponto de entrada: separa SPED e XML. SPED primeiro, para as empresas existirem quando os XMLs chegarem."""
    sped, xml = [], []
    for p in paths:
        if p.is_dir():
            sped += [s for s in p.rglob("*.txt") if s.is_file()]
            if any(True for _ in p.rglob("*.xml")) or any(True for _ in p.rglob("*.zip")):
                xml.append(p)
        elif p.suffix.lower() in (".xml", ".zip"):
            xml.append(p)
        else:
            sped.append(p)
    resultados = []
    total = len(sped) + (1 if xml else 0)
    for i, p in enumerate(sorted(sped)):
        if progress:
            progress(f"Importando {p.name}", i / max(total, 1))
        try:
            resultados.append(importar_sped(p, progress=None))
        except Exception as e:  # um arquivo ruim não derruba o lote
            resultados.append({"arquivo": p.name, "status": "ERRO", "motivo": str(e)})
    if xml:
        if progress:
            progress("Importando XMLs", len(sped) / max(total, 1))
        try:
            resultados.append(importar_xmls(xml, progress=progress))
        except Exception as e:
            resultados.append({"arquivo": "XMLs", "status": "ERRO", "motivo": str(e)})
    return resultados
