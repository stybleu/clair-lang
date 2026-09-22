#!/data/data/com.termux/files/usr/bin/bash

set -e

cd ~/clair

./clair test_chaine_ne.clair >/dev/null

CFILE="$HOME/clair/test_chaine_ne.c"

if grep -q \
'nv_ne' \
"$CFILE"; then
    echo "[ECHEC] nv_ne encore présent"
    exit 1
fi

if grep -q \
'clair_string_box(clair_string_char' \
"$CFILE"; then
    echo "[ECHEC] Boxing de caractère encore présent"
    exit 1
fi

if ! grep -q \
'!(clair_string_eq' \
"$CFILE"; then
    echo "[ECHEC] Comparaison != native absente"
    exit 1
fi

RESULT="$("$HOME/clair/test_chaine_ne")"

echo "$RESULT"

echo "$RESULT" | grep -q 'Somme : 16000000'

echo "[OK] Régression != chaînes natives validée"
