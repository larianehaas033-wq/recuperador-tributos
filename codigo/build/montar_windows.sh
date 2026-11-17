#!/usr/bin/env bash
# Monta a versão portátil para Windows: Python 3.12 + bibliotecas + sistema + atalhos.
set -euo pipefail
cd "$(dirname "$0")"
OUT=dist/RecuperadorTributos
rm -rf dist && mkdir -p "$OUT"

tar xzf cache/pywin.tar.gz -C "$OUT"                     # cria $OUT/python
rm -rf "$OUT/python/include" "$OUT/python/libs" "$OUT/python/Scripts"
find "$OUT/python" -name "*.pdb" -delete
rm -rf "$OUT/python/Lib/test" "$OUT/python/Lib/idlelib" "$OUT/python/Lib/ensurepip" "$OUT/python/Lib/lib2to3"
cp -r sitewin/. "$OUT/python/Lib/site-packages/"
rm -rf "$OUT/python/Lib/site-packages/bin" "$OUT/python/Lib/site-packages/share"
find "$OUT/python" -name "__pycache__" -type d -prune -exec rm -rf {} +

mkdir -p "$OUT/sistema"
cp -r ../backend/app ../backend/frontend_dist ../backend/launcher.py "$OUT/sistema/"
find "$OUT/sistema" -name "__pycache__" -type d -prune -exec rm -rf {} +
cp -r ../docs "$OUT/documentacao"
cp windows/* "$OUT/"
# finais de linha do Windows; .vbs precisa estar em ANSI (Windows-1252) por causa dos acentos
for f in "$OUT"/*.vbs; do iconv -f UTF-8 -t WINDOWS-1252 "$f" | sed 's/$/\r/' > "$f.tmp" && mv "$f.tmp" "$f"; done
sed -i 's/$/\r/' "$OUT/LEIA-ME.txt"

(cd dist && rm -f RecuperadorTributos.zip && zip -qr -9 RecuperadorTributos.zip RecuperadorTributos)
du -sh "$OUT" dist/RecuperadorTributos.zip
