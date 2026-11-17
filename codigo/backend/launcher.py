"""Abre o Recuperador de Tributos: sobe a API local e abre a janela própria do programa.

A janela usa o Microsoft Edge em modo aplicativo (sem barra de endereço, abas ou favoritos), que já vem
instalado em todo Windows 10 e 11. Fechando a janela, o programa encerra.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def aplicar_atualizacao_pendente() -> None:
    """Se uma nova versão foi baixada (pasta sistema_nova), troca as pastas e reabre o programa.
    A versão anterior fica em 'sistema_anterior' para voltar atrás se precisar."""
    raiz = AQUI.parent
    nova = raiz / "sistema_nova"
    if not (nova / "launcher.py").exists():
        return
    anterior = raiz / "sistema_anterior"
    try:
        import shutil
        shutil.rmtree(anterior, ignore_errors=True)
        AQUI.rename(anterior)
        try:
            nova.rename(AQUI)
        except OSError:
            anterior.rename(AQUI)  # desfaz se não conseguir trocar
            raise
    except OSError as e:
        try:
            log = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RecuperadorTributos" / "registro.log"
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(f"Não foi possível aplicar a atualização: {e}\n")
        except OSError:
            pass
        return
    subprocess.Popen([sys.executable, str(AQUI / "launcher.py")], cwd=str(raiz))
    sys.exit(0)


if __name__ == "__main__":
    aplicar_atualizacao_pendente()

sys.path.insert(0, str(AQUI))

from app import config  # noqa: E402

LOG = config.DATA_DIR / "registro.log"
LOCK = config.DATA_DIR / "instancia.json"

if sys.stdout is None or sys.stderr is None:  # pythonw.exe não tem console
    fh = open(LOG, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = fh


def _ativo(porta: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/status", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _porta_livre() -> int:
    for p in range(8765, 8800):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise RuntimeError("Nenhuma porta livre entre 8765 e 8800.")


def _edge() -> str | None:
    candidatos = [
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for c in candidatos:
        if c.exists():
            return str(c)
    return None


def abrir_janela(url: str) -> subprocess.Popen | None:
    edge = _edge()
    if not edge:
        webbrowser.open(url)
        return None
    perfil = config.DATA_DIR / "janela"
    return subprocess.Popen([edge, f"--app={url}", f"--user-data-dir={perfil}", "--no-first-run",
                             "--no-default-browser-check", "--disable-features=Translate", "--window-size=1440,920"])


def aplicar_icone_atalho() -> None:
    """Coloca o ícone do programa no atalho da Área de Trabalho (uma vez por versão do ícone)."""
    if not sys.platform.startswith("win"):
        return
    icone = AQUI / "app" / "recuperador.ico"
    marca = config.DATA_DIR / "icone_aplicado.txt"
    if not icone.exists() or (marca.exists() and marca.read_text(encoding="utf-8") == str(icone)):
        return
    raiz = AQUI.parent

    def q(v) -> str:  # texto entre aspas simples do PowerShell
        return "'" + str(v).replace("'", "''") + "'"

    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "$l = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Recuperador de Tributos.lnk'; "
        f"$s = $ws.CreateShortcut($l); $s.TargetPath = {q(raiz / 'python' / 'pythonw.exe')}; "
        f"$s.Arguments = '\"' + {q(AQUI / 'launcher.py')} + '\"'; $s.WorkingDirectory = {q(raiz)}; "
        f"$s.IconLocation = {q(str(icone) + ',0')}; $s.Description = 'Recuperador de Tributos'; $s.Save()"
    )
    import base64
    codificado = base64.b64encode(ps.encode("utf-16-le")).decode()
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", codificado],
                           capture_output=True, text=True, creationflags=0x08000000, timeout=30)
        if r.returncode == 0:
            marca.write_text(str(icone), encoding="utf-8")
            # avisa o Windows para redesenhar os ícones
            subprocess.run(["ie4uinit.exe", "-show"], capture_output=True, creationflags=0x08000000, timeout=15)
        else:
            print("Ícone do atalho:", r.stderr)
    except Exception as e:
        print("Ícone do atalho:", e)


def main() -> None:
    if LOCK.exists():
        try:
            porta = json.loads(LOCK.read_text())["porta"]
            if _ativo(porta):
                abrir_janela(f"http://127.0.0.1:{porta}/")
                return
        except Exception:
            pass

    import uvicorn

    from app import updater
    from app.main import app

    porta = _porta_livre()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning",
                                           log_config=None))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if _ativo(porta):
            break
        time.sleep(0.1)
    LOCK.write_text(json.dumps({"porta": porta, "pid": os.getpid()}))

    def auto_atualizar():
        try:
            updater.verificar_versao()  # procura versão nova toda vez que o programa abre
        except Exception as e:
            print("Verificação de versão falhou:", e)
        try:
            cfg = updater.configuracoes()
            horas = updater.horas_desde_ultima()
            if cfg.get("atualizacao_automatica", True) and (horas is None or horas > 20):
                updater.atualizar_tudo()
        except Exception as e:  # sem internet, segue sem atualizar
            print("Atualização automática falhou:", e)

    threading.Thread(target=auto_atualizar, daemon=True).start()
    threading.Thread(target=aplicar_icone_atalho, daemon=True).start()

    janela = abrir_janela(f"http://127.0.0.1:{porta}/")
    try:
        if janela is not None:
            janela.wait()
            # o Edge às vezes devolve o processo inicial antes da janela fechar; espera a pasta do perfil liberar
            time.sleep(2)
            while _janela_aberta():
                time.sleep(2)
        else:
            t.join()
    finally:
        server.should_exit = True
        try:
            LOCK.unlink()
        except FileNotFoundError:
            pass


def _janela_aberta() -> bool:
    """Confere se ainda há um msedge usando o perfil do programa (Windows)."""
    if not sys.platform.startswith("win"):
        return False
    perfil = str(config.DATA_DIR / "janela").lower()
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='msedge.exe'", "get", "CommandLine"],
            capture_output=True, text=True, creationflags=0x08000000, timeout=10,
        ).stdout.lower()
        return perfil in out
    except Exception:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"name='msedge.exe'\" | Select -Expand CommandLine"],
                capture_output=True, text=True, creationflags=0x08000000, timeout=15,
            ).stdout.lower()
            return perfil in out
        except Exception:
            return False


if __name__ == "__main__":
    main()
