"""Caminhos e parâmetros gerais do Recuperador de Tributos."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "RecuperadorTributos"
VERSION = "1.4.4"

REPO_RAW = "https://raw.githubusercontent.com/larianehaas033-wq/recuperador-tributos/main"
URL_VERSAO = f"{REPO_RAW}/versao.json"
# API do GitHub: entrega o arquivo na hora (o endereço "raw" fica até 5 minutos em cache)
URL_VERSAO_API = "https://api.github.com/repos/larianehaas033-wq/recuperador-tributos/contents/versao.json"
URL_REGRAS = f"{REPO_RAW}/regras/regras.json"


def versao_tupla(v: str) -> tuple:
    return tuple(int(x) for x in (v or "0").split(".") if x.isdigit())


APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend_dist"
RULES_BUNDLED = APP_DIR / "rules" / "regras_base.json"
MONITOR_BUNDLED = APP_DIR / "rules" / "fontes_oficiais.json"


def data_dir() -> Path:
    base = os.environ.get("RECUPERADOR_DATA")
    if not base:
        if sys.platform.startswith("win"):
            base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        else:
            base = str(Path.home() / ".local" / "share")
        base = str(Path(base) / APP_NAME)
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    (p / "regras").mkdir(exist_ok=True)
    (p / "relatorios").mkdir(exist_ok=True)
    (p / "uploads").mkdir(exist_ok=True)
    return p


DATA_DIR = data_dir()
DB_PATH = DATA_DIR / "recuperador.db"
RULES_LOCAL = DATA_DIR / "regras" / "regras.json"
SETTINGS_PATH = DATA_DIR / "configuracoes.json"

# Prazo de restituição/compensação: 5 anos (CTN, art. 168, I; LC 118/2005, art. 3º)
PRAZO_ANOS = 5
# Dia de vencimento de PIS/COFINS não cumulativos: 25 do mês seguinte (Lei 10.637/2002, art. 10;
# Lei 10.833/2003, art. 11). Usado para estimar a data do pagamento quando o DARF não é informado.
DIA_VENCIMENTO_PIS_COFINS = 25
