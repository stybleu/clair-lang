#!/data/data/com.termux/files/usr/bin/bash

set -e

cd ~/clair

./clair bench_append_chaine.clair >/dev/null

CFILE="$HOME/clair/bench_append_chaine.c"

if grep -q \
'nv_get_index' \
"$CFILE"; then
    echo "[ECHEC] nv_get_index encore présent"
    exit 1
fi

if grep -q \
'nv_mod' \
"$CFILE"; then
    echo "[ECHEC] nv_mod encore présent"
    exit 1
fi

if grep -q \
'nv_neg' \
"$CFILE"; then
    echo "[ECHEC] nv_neg encore présent"
    exit 1
fi

if ! grep -q \
'clair_string_append_char(&resultat' \
"$CFILE"; then
    echo "[ECHEC] append caractère natif absent"
    exit 1
fi

if ! grep -q \
'source.len' \
"$CFILE"; then
    echo "[ECHEC] longueur(source) non native"
    exit 1
fi

RESULT="$("$HOME/clair/bench_append_chaine")"

echo "$RESULT"

echo "$RESULT" | grep -q 'Longueur : 5000000'
echo "$RESULT" | grep -q 'Premier : A'
echo "$RESULT" | grep -q 'Dernier : E'

echo "[OK] Régression append chaîne native validée"
