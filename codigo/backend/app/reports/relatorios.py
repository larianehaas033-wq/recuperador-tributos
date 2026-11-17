"""Relatórios da análise: Excel (memória de cálculo completa) e PDF (resumo para o cliente)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.worksheet.worksheet import Worksheet

_append_original = Worksheet.append


def _append_limpo(self, linha):
    """Remove caracteres de controle que alguns sistemas gravam no SPED e que o Excel não aceita."""
    return _append_original(self, [ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v for v in linha])


Worksheet.append = _append_limpo
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .. import config, db
from ..rules.loader import carregar

NAVY = "0B1F3A"
GOLD = "C9A24B"
VIA = {"ADMINISTRATIVO_FEDERAL": "Administrativo (Receita Federal)",
       "ADMINISTRATIVO_ESTADUAL": "Administrativo (Sefaz da UF)", "JUDICIAL": "Judicial"}
NAT = {"RESTITUICAO": "Restituição/compensação", "CREDITO_EXTEMPORANEO": "Crédito a aproveitar", "RISCO": "Risco"}


def _carregar(analise_id: int) -> tuple[dict, dict, list[dict]]:
    with db.tx() as con:
        a = dict(con.execute("SELECT * FROM analises WHERE id=?", (analise_id,)).fetchone())
        e = dict(con.execute("SELECT * FROM empresas WHERE id=?", (a["empresa_id"],)).fetchone())
        c = db.rows(con, "SELECT * FROM creditos_identificados WHERE analise_id=? ORDER BY tributo, periodo, tese",
                    (analise_id,))
    a["resumo"] = json.loads(a["resumo_json"] or "{}")
    a["avisos"] = json.loads(a["avisos_json"] or "[]")
    return a, e, c


def _cnpj(c: str) -> str:
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if c and len(c) == 14 else (c or "")


def _brl(v: float) -> str:
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _livre(out: Path) -> Path:
    """Se o arquivo anterior ainda está aberto no Excel (bloqueado), grava com outro nome."""
    try:
        if out.exists():
            out.rename(out)  # falha no Windows se outro programa estiver com o arquivo aberto
        return out
    except OSError:
        return out.with_name(f"{out.stem}_{datetime.now():%H%M%S}{out.suffix}")


def _nome_arquivo(e: dict, analise_id: int, ext: str) -> Path:
    nome = "".join(ch for ch in (e["nome"] or "empresa") if ch.isalnum() or ch in " -_")[:40].strip().replace(" ", "_")
    return _livre(config.DATA_DIR / "relatorios" / f"Recuperacao_{nome}_analise{analise_id}.{ext}")


# ------------------------------------------------------------------------------------------ Excel
def gerar_excel(analise_id: int) -> Path:
    a, e, creds = _carregar(analise_id)
    base = carregar()
    wb = Workbook()
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor=NAVY)
    thin = Side(style="thin", color="D0D5DD")
    money = '#,##0.00'

    def cabecalho(ws, cols, widths):
        ws.append(cols)
        for i, w in enumerate(widths, 1):
            c = ws.cell(row=ws.max_row, column=i)
            c.font, c.fill = head, fill
            c.alignment = Alignment(vertical="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = ws.cell(row=ws.max_row + 1, column=1)

    # Resumo
    ws = wb.active
    ws.title = "Resumo"
    r = a["resumo"]
    ws["A1"] = "Recuperação de créditos tributários"
    ws["A1"].font = Font(bold=True, size=15, color=NAVY)
    linhas = [
        ("Empresa", e["nome"]), ("CNPJ", _cnpj(e["cnpj"])), ("UF", e["uf"]),
        ("Regime PIS/COFINS", (e["regime"] or "não identificado").replace("_", " ").title()),
        ("Períodos analisados", f"{a['periodo_ini'] or '-'} a {a['periodo_fim'] or '-'}"),
        ("Data da análise", a["criado_em"]), ("Base de regras", a["versao_regras"]),
        ("Selic carregada até", a["selic_ate"] or "não carregada"),
        ("Prazo de 5 anos: considerados pagamentos/documentos a partir de", a["data_corte_prescricao"]),
        ("", ""),
        ("Total restituível corrigido pela Selic", r.get("total_corrigido", 0)),
        ("Créditos a aproveitar (saldo credor)", r.get("total_saldo_credor", 0)),
        ("Não comprovado automaticamente (fora dos totais)", r.get("a_verificar", 0)),
        ("Riscos comprovados (valores que podem ser cobrados)", r.get("riscos", 0)),
        ("Riscos não comprovados (conferir)", r.get("riscos_a_verificar", 0)),
        ("Valores perdidos pelo prazo de 5 anos", r.get("prescrito", 0)),
    ]
    for i, (k, v) in enumerate(linhas, start=3):
        ws.cell(row=i, column=1, value=k).font = Font(bold=bool(k))
        c = ws.cell(row=i, column=2, value=v)
        if isinstance(v, (int, float)):
            c.number_format = money
    ws.column_dimensions["A"].width = 62
    ws.column_dimensions["B"].width = 42
    row = len(linhas) + 5
    ws.cell(row=row, column=1, value="Por tese").font = Font(bold=True, color=NAVY, size=12)
    row += 1
    cols = ["Tese", "Via", "Itens", "Restituível", "Corrigido (Selic)", "Saldo credor", "Não comprovado", "Risco"]
    for i, h in enumerate(cols, 1):
        c = ws.cell(row=row, column=i, value=h)
        c.font, c.fill = head, fill
    for t in r.get("teses", []):
        row += 1
        vals = [t["nome"], VIA.get(t["via"], t["via"]), t["qtd"], t["restituivel"], t["corrigido"],
                t["saldo_credor"], t["baixa"], t["risco"]]
        for i, v in enumerate(vals, 1):
            c = ws.cell(row=row, column=i, value=v)
            if i >= 4:
                c.number_format = money
    for col, w in zip("CDEFGH", (8, 16, 18, 16, 14, 14)):
        ws.column_dimensions[col].width = w
    if a["avisos"]:
        row += 2
        ws.cell(row=row, column=1, value="Avisos da análise").font = Font(bold=True, color="B42318")
        for av in a["avisos"]:
            row += 1
            ws.cell(row=row, column=1, value=av).alignment = Alignment(wrap_text=True)

    # Analítico
    ws = wb.create_sheet("Créditos")
    cols = ["Tributo", "Tese", "Natureza", "Via", "Competência", "Data", "Chave da NF-e", "Nº doc", "Cód. item",
            "Descrição", "NCM", "CFOP", "CST escriturado", "CST correto", "Base original", "Base correta",
            "Valor pago", "Valor a recuperar", "Restituível", "Saldo credor", "Corrigido (Selic)", "Confiança",
            "Prazo de 5 anos", "Fundamento", "Observação"]
    cabecalho(ws, cols, [9, 34, 18, 22, 11, 11, 46, 10, 12, 30, 11, 7, 9, 9, 13, 13, 13, 13, 13, 13, 14, 10, 12,
                         60, 50])
    for c in creds:
        if c["natureza"] == "RISCO":
            continue
        ws.append([c["tributo"], base.teses.get(c["tese"], {}).get("nome", c["tese"]), NAT.get(c["natureza"]),
                   VIA.get(c["via"]), c["periodo"], c["data"], c["chave"], c["num_doc"], c["cod_item"],
                   c["descricao"], c["ncm"], c["cfop"], c["cst_escriturado"], c["cst_correto"], c["base_original"],
                   c["base_correta"], c["valor_pago"], c["valor_recuperar"], c["valor_restituivel"],
                   c["valor_saldo_credor"], c["valor_corrigido"], c["confianca"],
                   "Prescrito" if c["prescrito"] else ("Excluído" if c["excluido"] else "No prazo"), c["fundamento"],
                   c["observacao"]])
    for row in ws.iter_rows(min_row=2, min_col=15, max_col=21):
        for cell in row:
            cell.number_format = money
    ws.auto_filter.ref = ws.dimensions

    # Riscos
    ws = wb.create_sheet("Riscos")
    cabecalho(ws, ["Tributo", "Risco", "Competência", "Data", "Chave", "Cód. item", "Descrição", "NCM", "CFOP",
                   "CST", "Valor em risco", "Confiança", "Fundamento", "Observação"],
              [9, 40, 11, 11, 46, 12, 30, 11, 7, 7, 14, 10, 60, 50])
    for c in creds:
        if c["natureza"] != "RISCO":
            continue
        ws.append([c["tributo"], base.teses.get(c["tese"], {}).get("nome", c["tese"]), c["periodo"], c["data"],
                   c["chave"], c["cod_item"], c["descricao"], c["ncm"], c["cfop"], c["cst_escriturado"],
                   c["valor_recuperar"], c["confianca"], c["fundamento"], c["observacao"]])
        ws.cell(row=ws.max_row, column=11).number_format = money
    ws.auto_filter.ref = ws.dimensions

    # Por competência
    ws = wb.create_sheet("Por competência")
    cabecalho(ws, ["Competência", "PIS", "COFINS", "ICMS", "Total"], [13, 16, 16, 16, 16])
    for s in r.get("serie", []):
        ws.append([s["periodo"], s["PIS"], s["COFINS"], s["ICMS"], s["PIS"] + s["COFINS"] + s["ICMS"]])
        for i in range(2, 6):
            ws.cell(row=ws.max_row, column=i).number_format = money

    # Roteiro
    ws = wb.create_sheet("Como recuperar")
    ws.column_dimensions["A"].width = 120
    ws.append(["Passo a passo por tese encontrada"])
    ws["A1"].font = Font(bold=True, size=13, color=NAVY)
    for t in r.get("teses", []):
        info = base.teses.get(t["tese"], {})
        ws.append([""])
        ws.append([info.get("nome", t["tese"])])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True, color=NAVY)
        ws.append([f"Fundamento: {info.get('fundamento', '')}"])
        ws.cell(row=ws.max_row, column=1).alignment = Alignment(wrap_text=True)
        for i, p in enumerate(info.get("roteiro", []), 1):
            ws.append([f"{i}. {p}"])
            ws.cell(row=ws.max_row, column=1).alignment = Alignment(wrap_text=True)

    # Cadastro tributário sugerido
    _aba_cadastro(wb, e["id"], cabecalho)

    # Metodologia
    ws = wb.create_sheet("Metodologia")
    ws.column_dimensions["A"].width = 120
    textos = [
        "Como os valores foram calculados",
        "Fontes: EFD-Contribuições, EFD ICMS/IPI e XMLs de NF-e/NFC-e importados. Notas canceladas são ignoradas.",
        "PIS/COFINS: o que reduz a contribuição devida só vira restituição até o valor recolhido na competência "
        "(registros M200 e M600, campo 13). O excedente aparece como saldo credor.",
        "Correção: Selic acumulada do mês seguinte ao pagamento até o mês anterior ao da análise, mais 1% "
        "(Lei 9.250/1995, art. 39, § 4º). Vencimento estimado no dia 25 do mês seguinte à competência. "
        "Para ICMS a correção é uma estimativa: cada UF tem índice e rito próprios.",
        "Créditos a aproveitar (extemporâneos) não são corrigidos.",
        "Prazo: 5 anos contados do pagamento (restituição) ou da emissão do documento (crédito). CTN, art. 168.",
        "Comprovação automática: um valor só entra nos totais quando o NCM consta da lista legal (leis e Tabelas 4.3.10, "
        "4.3.11 e 4.3.13 da EFD-Contribuições); nos códigos com 'Ex' ou que dependem da destinação, quando a descrição "
        "do produto confere com o texto legal ou o fornecedor tratou o mesmo NCM da mesma forma no XML de compra; "
        "nos créditos de compra, quando o cadastro 0200 mostra revenda/insumo e o item foi revendido. "
        "O que não se comprova fica listado com o motivo, fora dos totais.",
        "PIS e COFINS são extintos em 01/01/2027 (LC 214/2025); valores de competências até 12/2026 continuam "
        "recuperáveis dentro do prazo de 5 anos.",
        f"Base de regras usada: {a['versao_regras']}.",
    ]
    for i, t in enumerate(textos):
        ws.append([t])
        ws.cell(row=ws.max_row, column=1).alignment = Alignment(wrap_text=True)
        if i == 0:
            ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=13, color=NAVY)

    borda = Border(bottom=thin)
    for sh in (wb["Créditos"], wb["Riscos"]):
        for row in sh.iter_rows(min_row=2):
            for cell in row:
                cell.border = borda
    out = _nome_arquivo(e, analise_id, "xlsx")
    wb.save(out)
    return out


CAD_COLS = [("Cód. item", "cod_item", 12), ("Descrição", "descricao", 34), ("NCM", "ncm", 11), ("Tipo", "tipo_item", 13),
            ("Vendido no período", "valor_vendido", 15), ("Divergências com o uso atual", "divergencias", 40),
            ("CST PIS/COFINS atual", "atual_cst_pis_cofins", 10), ("CST PIS/COFINS sugerido", "cst_pis_cofins", 10),
            ("Enquadramento PIS/COFINS", "grupo_pis_cofins", 28), ("CST ICMS atual", "atual_cst_icms", 9),
            ("CST ICMS sugerido", "cst_icms", 9), ("CSOSN sugerido (Simples)", "csosn", 10),
            ("cClassTrib atual", "atual_cclasstrib", 11), ("CST IBS/CBS", "cst_ibscbs", 8), ("cClassTrib", "cclasstrib", 11),
            ("Redução IBS/CBS (%)", "reducao_ibscbs", 9), ("Enquadramento IBS/CBS", "grupo_ibscbs", 30),
            ("Fundamento IBS/CBS", "fundamento_ibscbs", 45), ("NBS", "nbs", 22), ("Comprovação", "comprovacao", 12),
            ("Observação", "observacao", 60)]


def _aba_cadastro(wb, empresa_id: int, cabecalho) -> None:
    from ..engine.runner import gerar_cadastro
    linhas = gerar_cadastro(empresa_id)
    ws = wb.create_sheet("Cadastro tributário")
    cabecalho(ws, [c[0] for c in CAD_COLS], [c[2] for c in CAD_COLS])
    for ln in linhas:
        vals = []
        for _, k, _w in CAD_COLS:
            v = ln.get(k)
            if k == "divergencias":
                v = "; ".join(v) if v else ""
            elif k == "comprovacao":
                v = {"ALTA": "Comprovado", "Revisar NCM": "Revisar NCM"}.get(v, "Não comprovado")
            vals.append(v)
        ws.append(vals)
        ws.cell(row=ws.max_row, column=5).number_format = "#,##0.00"
        if ln["divergencias"]:
            ws.cell(row=ws.max_row, column=6).font = Font(bold=True, color="B42318")
    ws.auto_filter.ref = ws.dimensions


def gerar_excel_cadastro(empresa_id: int) -> Path:
    with db.tx() as con:
        e = dict(con.execute("SELECT * FROM empresas WHERE id=?", (empresa_id,)).fetchone())
    wb = Workbook()
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor=NAVY)

    def cabecalho(ws, cols, widths):
        ws.append(cols)
        for i, w in enumerate(widths, 1):
            c = ws.cell(row=ws.max_row, column=i)
            c.font, c.fill = head, fill
            c.alignment = Alignment(vertical="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = ws.cell(row=ws.max_row + 1, column=1)

    _aba_cadastro(wb, empresa_id, cabecalho)
    del wb["Sheet"]
    nome = "".join(ch for ch in (e["nome"] or "empresa") if ch.isalnum() or ch in " -_")[:40].strip().replace(" ", "_")
    out = _livre(config.DATA_DIR / "relatorios" / f"Cadastro_tributario_{nome}.xlsx")
    wb.save(out)
    return out


# ------------------------------------------------------------------------------------------ PDF
def _texto_pdf(v) -> str:
    """Tira caracteres de controle e símbolos fora da fonte (emoji etc.) para o PDF não falhar."""
    import unicodedata
    t = ILLEGAL_CHARACTERS_RE.sub("", str(v or ""))
    return "".join(ch for ch in t if ord(ch) < 0x2100 or unicodedata.category(ch).startswith("P"))


def gerar_pdf(analise_id: int) -> Path:
    from fpdf import FPDF

    a, e, creds = _carregar(analise_id)
    e = {k: (_texto_pdf(v) if isinstance(v, str) else v) for k, v in e.items()}
    a["avisos"] = [_texto_pdf(x) for x in a["avisos"]]
    base = carregar()
    r = a["resumo"]
    fonts = Path(__file__).parent / "fonts"

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, 18)
    pdf.add_font("Figtree", "", str(fonts / "Figtree-Regular.ttf"))
    pdf.add_font("Figtree", "B", str(fonts / "Figtree-Bold.ttf"))
    pdf.add_page()
    navy, gold = (11, 31, 58), (201, 162, 75)

    pdf.set_fill_color(*navy)
    pdf.rect(0, 0, 210, 34, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Figtree", "B", 17)
    pdf.set_xy(14, 10)
    pdf.cell(0, 8, "Relatório de recuperação de créditos tributários")
    pdf.set_font("Figtree", "", 10)
    pdf.set_xy(14, 20)
    pdf.cell(0, 6, f"{e['nome']}  |  CNPJ {_cnpj(e['cnpj'])}  |  {e['uf'] or ''}")
    pdf.set_text_color(30, 30, 30)
    pdf.set_y(42)

    pdf.set_font("Figtree", "", 9)
    pdf.multi_cell(0, 5, f"Períodos analisados: {a['periodo_ini'] or '-'} a {a['periodo_fim'] or '-'}. "
                         f"Análise em {a['criado_em'][:10]}. Base de regras {a['versao_regras']}. "
                         f"Selic até {a['selic_ate'] or 'não carregada'}.", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    cards = [("Restituível corrigido", r.get("total_corrigido", 0)),
             ("Créditos a aproveitar", r.get("total_saldo_credor", 0)),
             ("Não comprovado", r.get("a_verificar", 0)), ("Riscos", r.get("riscos", 0))]
    x0, y0, w = 14, pdf.get_y(), 44.5
    for i, (k, v) in enumerate(cards):
        x = x0 + i * (w + 2)
        pdf.set_fill_color(244, 246, 250)
        pdf.rect(x, y0, w, 20, "F")
        pdf.set_fill_color(*gold) if i == 0 else pdf.set_fill_color(*navy)
        pdf.rect(x, y0, 1.2, 20, "F")
        pdf.set_xy(x + 4, y0 + 3)
        pdf.set_font("Figtree", "", 8)
        pdf.cell(w - 6, 4, k)
        pdf.set_xy(x + 4, y0 + 9)
        pdf.set_font("Figtree", "B", 11.5)
        pdf.cell(w - 6, 7, _brl(v))
    pdf.set_y(y0 + 26)

    pdf.set_font("Figtree", "B", 12)
    pdf.set_text_color(*navy)
    pdf.cell(0, 8, "Valores por tributo", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Figtree", "", 10)
    for t, v in r.get("por_tributo", {}).items():
        pdf.cell(60, 6, t)
        pdf.cell(0, 6, _brl(v), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Figtree", "B", 12)
    pdf.set_text_color(*navy)
    pdf.cell(0, 8, "Oportunidades e riscos por tese", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Figtree", "B", 8.5)
    pdf.set_fill_color(*navy)
    pdf.set_text_color(255, 255, 255)
    cols = [("Tese", 96), ("Via", 28), ("Itens", 12), ("Valor", 30), ("Situação", 24)]
    via_curta = {"ADMINISTRATIVO_FEDERAL": "Receita Federal", "ADMINISTRATIVO_ESTADUAL": "Sefaz da UF",
                 "JUDICIAL": "Judicial"}
    for h, wd in cols:
        pdf.cell(wd, 7, h, fill=True)
    pdf.ln()
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Figtree", "", 8.5)
    for t in r.get("teses", []):
        if t["risco"]:
            valor, sit = t["risco"], "Risco"
        elif t["baixa"] and not (t["corrigido"] or t["saldo_credor"]):
            valor, sit = t["baixa"], "Não comprovado"
        else:
            valor, sit = t["corrigido"] + t["saldo_credor"], "Identificado"
        nome = t["nome"] if pdf.get_string_width(t["nome"]) < 94 else t["nome"][:62] + "..."
        pdf.cell(96, 6, nome)
        pdf.cell(28, 6, via_curta.get(t["via"], ""))
        pdf.cell(12, 6, str(t["qtd"]))
        pdf.cell(30, 6, _brl(valor))
        pdf.cell(24, 6, sit, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    if a["avisos"]:
        pdf.set_font("Figtree", "B", 11)
        pdf.set_text_color(180, 35, 24)
        pdf.cell(0, 7, "Avisos", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Figtree", "", 8.5)
        pdf.set_text_color(30, 30, 30)
        for av in a["avisos"]:
            pdf.multi_cell(0, 4.6, f"- {av}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    pdf.add_page()
    pdf.set_font("Figtree", "B", 13)
    pdf.set_text_color(*navy)
    pdf.cell(0, 8, "Como recuperar", new_x="LMARGIN", new_y="NEXT")
    for t in r.get("teses", []):
        info = base.teses.get(t["tese"], {})
        pdf.set_font("Figtree", "B", 10)
        pdf.set_text_color(*navy)
        pdf.multi_cell(0, 6, info.get("nome", t["tese"]), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(30, 30, 30)
        pdf.set_font("Figtree", "", 8.5)
        pdf.multi_cell(0, 4.5, "Fundamento: " + info.get("fundamento", ""), new_x="LMARGIN", new_y="NEXT")
        for i, p in enumerate(info.get("roteiro", []), 1):
            pdf.multi_cell(0, 4.5, f"{i}. {p}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    pdf.set_font("Figtree", "", 7.5)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(0, 4, "Valores apurados a partir dos arquivos fiscais importados e das listas legais vigentes. "
                         "Os totais incluem só valores comprovados automaticamente. "
                         f"Gerado em {datetime.now():%d/%m/%Y %H:%M}.", new_x="LMARGIN", new_y="NEXT")
    out = _nome_arquivo(e, analise_id, "pdf")
    pdf.output(str(out))
    return out
