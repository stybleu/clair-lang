#!/data/data/com.termux/files/usr/bin/bash

set -e

cd ~/clair

./clair test_index_chaine.clair >/dev/null

CFILE="$HOME/clair/test_index_chaine.c"

if grep -q \
'clair_string_box(clair_string_char' \
"$CFILE"; then
    echo "[ECHEC] Boxing d'indexation détecté"
    exit 1
fi

if grep -q \
'nv_get_index' \
"$CFILE"; then
    echo "[ECHEC] nv_get_index encore présent"
    exit 1
fi

if ! grep -q \
'clair_string_assign_char(&caractere' \
"$CFILE"; then
    echo "[ECHEC] Affectation caractère native absente"
    exit 1
fi

RESULT="$("$HOME/clair/test_index_chaine")"

echo "$RESULT"

echo "$RESULT" | grep -q 'Final : e'

echo "[OK] Régression indexation chaîne native validée"
