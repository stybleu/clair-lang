#!/data/data/com.termux/files/usr/bin/bash

set -e

cd ~/clariox

./clariox bench_chaine_buffer.clx >/dev/null

CFILE="$HOME/clair/bench_chaine_buffer_native.c"

if [ ! -f "$CFILE" ]; then
    CFILE="$HOME/clair/bench_chaine_buffer.c"
fi

if grep -q \
'clair_string_box(clair_string_char' \
"$CFILE"; then
    echo "[ECHEC] Boxing de caractère détecté"
    exit 1
fi

if ! grep -q \
'clair_string_eq(clair_string_char' \
"$CFILE"; then
    echo "[ECHEC] Comparaison native absente"
    exit 1
fi

RESULT="$("$HOME/clair/bench_chaine_buffer")"

echo "$RESULT"

echo "$RESULT" | grep -q 'Somme : 2000000'
echo "$RESULT" | grep -q 'Final : Alexandria'

echo "[OK] Régression chaînes natives validée"
