"""Atualização da base sem abrir o programa (usada pela tarefa diária do Agendador do Windows)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "sistema"))
from app import config, db, updater  # noqa: E402

log = open(config.DATA_DIR / "registro.log", "a", encoding="utf-8")  # noqa: SIM115
sys.stdout = sys.stderr = log
db.init()
print("Atualização agendada:", updater.atualizar_tudo())
