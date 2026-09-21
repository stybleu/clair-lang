#!/usr/bin/env python3

import re
import sys


PATTERN = re.compile(
    r'nv_str\(("(?:\\.|[^"\\])*")\)'
)


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: optimise_litteraux_c.py "
            "entree.c sortie.c"
        )
        sys.exit(2)

    source_path = sys.argv[1]
    dest_path = sys.argv[2]

    with open(
        source_path,
        "r",
        encoding="utf-8"
    ) as f:
        source = f.read()

    # Littéraux uniques dans leur ordre d'apparition.
    literals = []
    seen = set()

    for match in PATTERN.finditer(source):
        literal = match.group(1)

        if literal not in seen:
            seen.add(literal)
            literals.append(literal)

    if not literals:
        with open(
            dest_path,
            "w",
            encoding="utf-8"
        ) as f:
            f.write(source)

        print(
            "[Clair OPT] Aucun littéral de chaîne "
            "à mettre en cache"
        )
        return

    names = {
        literal: f"clair_literal_{i + 1}"
        for i, literal in enumerate(literals)
    }

    # Remplace les nv_str("texte") existants.
    def replacement(match):
        literal = match.group(1)
        return names[literal]

    optimized = PATTERN.sub(
        replacement,
        source
    )

    # Variables globales : valides dans main() et dans
    # les fonctions Clair générées.
    declarations = "\n".join(
        f"static NvVal {names[literal]};"
        for literal in literals
    )

    include_marker = '#include "clair_runtime.h"'

    if include_marker not in optimized:
        raise SystemExit(
            "Include clair_runtime.h introuvable"
        )

    optimized = optimized.replace(
        include_marker,
        include_marker
        + "\n\n"
        + declarations,
        1
    )

    # Initialisation une seule fois au démarrage.
    initializations = "\n".join(
        f"    {names[literal]} = nv_str({literal});"
        for literal in literals
    )

    main_marker = "int main(void){"

    if main_marker not in optimized:
        raise SystemExit(
            "main() introuvable"
        )

    optimized = optimized.replace(
        main_marker,
        main_marker
        + "\n"
        + initializations,
        1
    )

    with open(
        dest_path,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(optimized)

    print(
        f"[Clair OPT] Littéraux de chaînes mis en cache : "
        f"{len(literals)}"
    )

    for literal in literals:
        print(
            f"  {literal} -> {names[literal]}"
        )


if __name__ == "__main__":
    main()
