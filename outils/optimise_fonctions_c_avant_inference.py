#!/usr/bin/env python3

import re
import sys


SUPPORTED_TYPES = {
    "entier",
    "decimal",
}


def replace_identifier(expr, name, value):
    return re.sub(
        rf'\b{re.escape(name)}\b',
        f'({value})',
        expr
    )


def parse_functions(lines):
    functions = {}

    i = 0

    while i < len(lines):
        m = re.match(
            r'\s*static NvVal clair_fn_'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\(NvVal \*__args, int __argc, '
            r'NvDict \*__kwargs\)\s*\{\s*$',
            lines[i]
        )

        if not m:
            i += 1
            continue

        name = m.group(1)
        body = []
        j = i + 1

        while j < len(lines):
            if re.match(r'^\}\s*$', lines[j]):
                break

            body.append(lines[j])
            j += 1

        if j >= len(lines):
            i += 1
            continue

        params = []
        types = {}
        return_expr = None
        safe = True

        for line in body:
            stripped = line.strip()

            if not stripped:
                continue

            pm = re.match(
                r'NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*nv_arg\('
                r'__args,\s*__argc,\s*__kwargs,\s*'
                r'(\d+),\s*"([^"]+)"\s*\);',
                stripped
            )

            if pm:
                param = pm.group(1)
                pos = int(pm.group(2))

                while len(params) <= pos:
                    params.append(None)

                params[pos] = param
                continue

            tm = re.match(
                r'nv_expect_type\('
                r'([A-Za-z_][A-Za-z0-9_]*),\s*'
                r'"([^"]+)",\s*"[^"]+"\s*\);',
                stripped
            )

            if tm:
                types[tm.group(1)] = tm.group(2)
                continue

            rm = re.match(
                r'return\s+(.+);\s*$',
                stripped
            )

            if rm:
                expr = rm.group(1)

                if expr == "nv_none()":
                    continue

                if return_expr is not None:
                    safe = False
                    break

                return_expr = expr
                continue

            # Toute autre instruction rend la fonction
            # trop complexe pour cette première optimisation.
            safe = False
            break

        if safe and return_expr and all(params):
            for param in params:
                if types.get(param) not in SUPPORTED_TYPES:
                    safe = False
                    break

        if safe:
            functions[name] = {
                "params": params,
                "types": types,
                "expr": return_expr,
            }

        i = j + 1

    return functions


def find_call_chunks(line):
    marker = "({ NvCall __c = nv_call_new();"
    end_marker = "__r; })"

    chunks = []
    pos = 0

    while True:
        start = line.find(marker, pos)

        if start < 0:
            break

        end = line.find(end_marker, start)

        if end < 0:
            break

        end += len(end_marker)

        chunks.append((start, end, line[start:end]))
        pos = end

    return chunks


def extract_arguments(chunk):
    return re.findall(
        r'nv_call_add\(&__c,\s*(.*?)\);\s*',
        chunk
    )


def inline_chunk(chunk, functions):
    dm = re.search(
        r'nv_dispatch_call\("'
        r'([A-Za-z_][A-Za-z0-9_]*)"\s*,',
        chunk
    )

    if not dm:
        return None

    name = dm.group(1)

    if name not in functions:
        return None

    info = functions[name]
    args = extract_arguments(chunk)

    if len(args) != len(info["params"]):
        return None

    expr = info["expr"]

    # Remplacement paramètres -> arguments.
    # Parenthèses ajoutées pour conserver les priorités.
    for param, arg in zip(info["params"], args):
        expr = replace_identifier(
            expr,
            param,
            arg.strip()
        )

    return f"({expr})"


def optimize_line(line, functions):
    # Plusieurs appels peuvent exister sur une même ligne.
    while True:
        chunks = find_call_chunks(line)

        replacement_done = False

        for start, end, chunk in reversed(chunks):
            replacement = inline_chunk(
                chunk,
                functions
            )

            if replacement is None:
                continue

            line = (
                line[:start]
                + replacement
                + line[end:]
            )

            replacement_done = True

        if not replacement_done:
            break

    return line


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: optimise_fonctions_c.py "
            "entree.c sortie.c"
        )
        sys.exit(2)

    source = sys.argv[1]
    destination = sys.argv[2]

    with open(source, "r", encoding="utf-8") as f:
        lines = f.readlines()

    functions = parse_functions(lines)

    if functions:
        print(
            "[Clariox OPT] Fonctions numériques "
            "spécialisables :"
        )

        for name, info in sorted(functions.items()):
            signature = ", ".join(
                f"{p}:{info['types'][p]}"
                for p in info["params"]
            )

            print(
                f"  {name}({signature})"
            )
    else:
        print(
            "[Clariox OPT] Aucune fonction numérique "
            "spécialisable"
        )

    output = [
        optimize_line(line, functions)
        for line in lines
    ]

    with open(destination, "w", encoding="utf-8") as f:
        f.writelines(output)

    print(
        "[Clariox OPT] Spécialisation fonctions : "
        f"{destination}"
    )


if __name__ == "__main__":
    main()
