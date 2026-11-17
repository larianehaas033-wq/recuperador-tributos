"""Funções comuns aos arquivos SPED (EFD ICMS/IPI e EFD-Contribuições).

Formato: uma linha por registro, campos separados por "|", começando e terminando
com "|". O campo 1 é o código do registro (ex.: C170). Valores numéricos usam
vírgula decimal e datas o formato DDMMAAAA. A codificação oficial é ISO-8859-1,
mas há sistemas que geram em UTF-8; a detecção abaixo trata os dois casos.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterator

_DATE = re.compile(r"^\d{8}$")


def detect_encoding(path: Path) -> str:
    raw = path.open("rb").read(256 * 1024)
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def iter_registros(path: Path) -> Iterator[list[str]]:
    enc = detect_encoding(path)
    with path.open("r", encoding=enc, errors="replace", newline="") as fh:
        for line in fh:
            line = line.strip("\r\n﻿ ")
            if not line.startswith("|"):
                continue
            # campo [0] é vazio; [1] é o registro
            yield line.split("|")


def num(v: str | None) -> float:
    if not v:
        return 0.0
    v = v.strip()
    if not v:
        return 0.0
    try:
        return float(v.replace(".", "").replace(",", ".")) if "," in v else float(v)
    except ValueError:
        return 0.0


def data_iso(v: str | None) -> str | None:
    if v and _DATE.match(v):
        return f"{v[4:8]}-{v[2:4]}-{v[0:2]}"
    return None


def periodo(iso: str | None) -> str | None:
    return iso[:7] if iso else None


def campo(f: list[str], i: int) -> str:
    return f[i].strip() if len(f) > i else ""


def only_digits(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def identificar_tipo(path: Path) -> str | None:
    """Retorna EFD_CONTRIB, EFD_ICMS_IPI ou None, olhando o registro 0000 e os blocos."""
    primeiro = None
    tem_m = False
    tem_e = False
    for i, f in enumerate(iter_registros(path)):
        reg = campo(f, 1)
        if reg == "0000" and primeiro is None:
            primeiro = f
        if reg.startswith("M"):
            tem_m = True
        if reg in ("E100", "E110", "E001"):
            tem_e = True
        if i > 400000 and primeiro:
            break
    if not primeiro:
        return None
    # EFD ICMS/IPI: |0000|COD_VER|COD_FIN|DT_INI|DT_FIN|NOME|CNPJ|...
    # EFD-Contribuições: |0000|COD_VER|TIPO_ESCRIT|IND_SIT_ESP|NUM_REC_ANT|DT_INI|DT_FIN|NOME|CNPJ|...
    if _DATE.match(campo(primeiro, 4)) and _DATE.match(campo(primeiro, 5)) and not tem_m:
        return "EFD_ICMS_IPI"
    if _DATE.match(campo(primeiro, 6)) and _DATE.match(campo(primeiro, 7)):
        return "EFD_CONTRIB"
    if tem_e:
        return "EFD_ICMS_IPI"
    return None
