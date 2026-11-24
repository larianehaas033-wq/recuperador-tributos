"""O relatório pode ser baixado pela janela (vai para Downloads); nada fora da pasta de relatórios sai."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("RECUPERADOR_DATA", str(Path(tempfile.mkdtemp()) / "dados"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from app import config  # noqa: E402
from app.main import app  # noqa: E402


def test_baixa_relatorio_e_bloqueia_fora_da_pasta():
    pasta = config.DATA_DIR / "relatorios"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "Recuperacao_X_analise1.xlsx").write_bytes(b"conteudo")
    c = TestClient(app)
    r = c.get("/api/relatorios/Recuperacao_X_analise1.xlsx")
    assert r.status_code == 200 and r.content == b"conteudo"
    assert "attachment" in r.headers["content-disposition"]
    assert c.get("/api/relatorios/..%2Frecuperador.db").status_code == 404
