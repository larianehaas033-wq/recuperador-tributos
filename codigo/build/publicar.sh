#!/usr/bin/env bash
# Publica uma versão no repositório de atualizações:
#   versao.json                     versão atual, notas e assinatura do pacote
#   atualizacoes/sistema-X.Y.Z.zip  pasta "sistema" (código + interface), baixada pelo botão "Atualizar programa"
#   regras/regras.json              base de regras, baixada na atualização diária
#   codigo/                         código-fonte para manutenção
# Uso: build/publicar.sh "nota 1" "nota 2" ...
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=/home/claude/recuperador-tributos
VER=$(python3 -c "import re;print(re.search(r'VERSION = \"([0-9.]+)\"', open('backend/app/config.py').read()).group(1))")

(cd frontend && npx vite build >/dev/null)
(cd backend && python3 -m pytest -q tests >/dev/null)   # não publica com teste falhando

mkdir -p "$REPO/atualizacoes" "$REPO/regras" "$REPO/codigo"
TMP=$(mktemp -d)
cp -r backend/app backend/frontend_dist backend/launcher.py "$TMP/"
find "$TMP" -name "__pycache__" -type d -prune -exec rm -rf {} +
PKG="atualizacoes/sistema-$VER.zip"
rm -f "$REPO/$PKG"
(cd "$TMP" && zip -qr -9 -X "$REPO/$PKG" .)
rm -rf "$TMP"
SHA=$(sha256sum "$REPO/$PKG" | cut -d' ' -f1)

python3 - "$VER" "$PKG" "$SHA" "$@" <<'PY'
import json, sys, datetime
ver, pkg, sha, *notas = sys.argv[1:]
repo = "/home/claude/recuperador-tributos"
regras = json.load(open("backend/app/rules/regras_base.json", encoding="utf-8"))
regras["programa_minimo"] = "1.3.5"
json.dump(regras, open(f"{repo}/regras/regras.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({"versao": ver, "publicado_em": datetime.date.today().isoformat(), "pacote": pkg, "sha256": sha,
           "exige_pacote_completo": False, "versao_regras": regras["versao"], "notas": notas},
          open(f"{repo}/versao.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY

rm -rf "$REPO/codigo" && mkdir -p "$REPO/codigo"
tar -c --exclude=node_modules --exclude=frontend_dist --exclude=__pycache__ --exclude=.pytest_cache \
  --exclude=build/dist --exclude=build/cache --exclude=build/sitewin --exclude=build/py312 \
  backend frontend build docs | tar -x -C "$REPO/codigo/"
# mantém só o pacote da versão atual e da anterior
ls -1t "$REPO"/atualizacoes/sistema-*.zip | tail -n +3 | xargs -r rm -f
echo "Publicado $VER  ($PKG, sha256 $SHA)"
