#!/usr/bin/env bash
# Pubblica la documentazione mkdocs su cryptoquantix.github.io/docs
# Prerequisito: clone di cryptoquantix.github.io accanto a questo repo.
# Uso: scripts/publish_docs.sh   (poi git push nel repo Pages)
set -euo pipefail
cd "$(dirname "$0")/.."

PAGES_REPO="../cryptoquantix.github.io"
[ -d "$PAGES_REPO/.git" ] || { echo "[FAIL] repo Pages non trovato in $PAGES_REPO"; exit 1; }

echo "[1/3] Build mkdocs..."
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT
python -m mkdocs build -d "$BUILD_DIR"

echo "[2/3] Copia in $PAGES_REPO/docs (+ strip pagina riservata da sitemap)..."
# la pagina riservata resta raggiungibile via URL ma NON in sitemap
python - "$BUILD_DIR/sitemap.xml" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
s = re.sub(r"\s*<url>(?:(?!</url>).)*strategie-1130b67ca8af0c353cdb(?:(?!</url>).)*</url>", "", s, flags=re.S)
open(p, "w", encoding="utf-8", newline="\n").write(s)
PYEOF
rm -rf "$PAGES_REPO/docs"
cp -r "$BUILD_DIR" "$PAGES_REPO/docs"

echo "[3/3] Commit nel repo Pages..."
cd "$PAGES_REPO"
git add docs
if git diff --cached --quiet; then
    echo "[OK] nessuna modifica ai docs"
else
    git commit -m "docs: aggiornamento documentazione CryptoQuantix"
    echo "[OK] Commit creato. Per pubblicare: (cd $PAGES_REPO && git push)"
fi
