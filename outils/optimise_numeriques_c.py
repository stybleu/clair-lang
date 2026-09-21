#!/usr/bin/env python3

import re
import sys


def strip_outer_parens(expr):
    expr = expr.strip()

    while expr.startswith("(") and expr.endswith(")"):
        depth = 0
        wraps = True

        for i, ch in enumerate(expr):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1

                if depth < 0:
                    wraps = False
                    break

                if depth == 0 and i != len(expr) - 1:
                    wraps = False
                    break

        if not wraps or depth != 0:
            break

        expr = expr[1:-1].strip()

    return expr


def split_args(text):
    args = []
    current = []
    depth = 0

    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1

        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    args.append("".join(current).strip())
    return args


def unwrap(expr, name):
    expr = strip_outer_parens(expr)
    prefix = name + "("

    if not expr.startswith(prefix) or not expr.endswith(")"):
        return None

    return expr[len(prefix):-1]


def promote(a, b):
    if a == "double" or b == "double":
        return "double"
    return "int"


def convert_expr(expr, types):
    expr = strip_outer_parens(expr)

    # Variable déjà connue
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', expr):
        if expr in types:
            return expr, types[expr]
        return None

    # Entier C
    if re.fullmatch(r'-?\d+(?:LL)?', expr):
        return expr, "int"

    # Décimal C
    if re.fullmatch(
        r'-?(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?',
        expr
    ):
        return expr, "double"

    # nv_int(...)
    inner = unwrap(expr, "nv_int")
    if inner is not None:
        r = convert_expr(inner, types)

        if r is not None:
            return r[0], "int"

        if re.fullmatch(r'-?\d+(?:LL)?', inner.strip()):
            return inner.strip(), "int"

        return None

    # nv_float(...)
    inner = unwrap(expr, "nv_float")
    if inner is not None:
        inner = strip_outer_parens(inner)

        if re.fullmatch(
            r'-?(?:\d+\.\d*|\d*\.\d+|\d+)'
            r'(?:[eE][+-]?\d+)?',
            inner
        ):
            return inner, "double"

        r = convert_expr(inner, types)

        if r is not None:
            return r[0], "double"

        return None

    # Négation
    inner = unwrap(expr, "nv_neg")
    if inner is not None:
        r = convert_expr(inner, types)

        if r:
            return f"(-{r[0]})", r[1]

        return None

    # Addition / soustraction / multiplication
    operations = {
        "nv_add": "+",
        "nv_sub": "-",
        "nv_mul": "*",
    }

    for fn, op in operations.items():
        inner = unwrap(expr, fn)

        if inner is None:
            continue

        args = split_args(inner)

        if len(args) != 2:
            return None

        a = convert_expr(args[0], types)
        b = convert_expr(args[1], types)

        if not a or not b:
            return None

        typ = promote(a[1], b[1])

        return f"({a[0]} {op} {b[0]})", typ

    # Division Clair : toujours décimale
    inner = unwrap(expr, "nv_div")
    if inner is not None:
        args = split_args(inner)

        if len(args) != 2:
            return None

        a = convert_expr(args[0], types)
        b = convert_expr(args[1], types)

        if not a or not b:
            return None

        return (
            f"((double)({a[0]}) / (double)({b[0]}))",
            "double"
        )

    # Modulo Clair : le runtime travaille en entier
    inner = unwrap(expr, "nv_mod")
    if inner is not None:
        args = split_args(inner)

        if len(args) != 2:
            return None

        a = convert_expr(args[0], types)
        b = convert_expr(args[1], types)

        if not a or not b:
            return None

        return (
            f"((long long)({a[0]}) % (long long)({b[0]}))",
            "int"
        )

    # Puissance
    inner = unwrap(expr, "nv_pow")
    if inner is not None:
        args = split_args(inner)

        if len(args) != 2:
            return None

        a = convert_expr(args[0], types)
        b = convert_expr(args[1], types)

        if not a or not b:
            return None

        return f"pow({a[0]}, {b[0]})", "double"

    # Comparaisons
    comparisons = {
        "nv_lt": "<",
        "nv_le": "<=",
        "nv_gt": ">",
        "nv_ge": ">=",
        "nv_eq": "==",
        "nv_ne": "!=",
    }

    for fn, op in comparisons.items():
        inner = unwrap(expr, fn)

        if inner is None:
            continue

        args = split_args(inner)

        if len(args) != 2:
            return None

        a = convert_expr(args[0], types)
        b = convert_expr(args[1], types)

        if not a or not b:
            return None

        return f"({a[0]} {op} {b[0]})", "int"

    # nv_truth(...)
    inner = unwrap(expr, "nv_truth")
    if inner is not None:
        r = convert_expr(inner, types)

        if r:
            return f"({r[0]})", "int"

    return None


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: optimise_numeriques_c.py "
            "entree.c sortie.c"
        )
        sys.exit(2)

    source, destination = sys.argv[1], sys.argv[2]

    with open(source, "r", encoding="utf-8") as f:
        lines = f.readlines()

    main_index = None

    for i, line in enumerate(lines):
        if re.match(r'\s*int\s+main\s*\(', line):
            main_index = i
            break

    if main_index is None:
        print("[Clair OPT] main() introuvable")
        sys.exit(1)

    body = lines[main_index:]

    types = {}

    # Compteurs générés par plage()
    for line in body:
        m = re.match(
            r'\s*NvVal\s+'
            r'(clair_range_(?:index|fin|pas)_\d+)'
            r'\s*=\s*nv_int\(',
            line
        )

        if m:
            types[m.group(1)] = "int"

    # Variables d'itération
    for line in body:
        m = re.match(
            r'\s*NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(clair_range_index_\d+)\s*;',
            line
        )

        if m and m.group(2) in types:
            types[m.group(1)] = "int"

    # Déclarations numériques littérales
    for line in body:
        m = re.match(
            r'\s*NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*nv_int\(',
            line
        )

        if m:
            types.setdefault(m.group(1), "int")

        m = re.match(
            r'\s*NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*nv_float\(',
            line
        )

        if m:
            types.setdefault(m.group(1), "double")

    # Variables avec affectation non numérique :
    # elles restent dynamiques.
    unsafe = set()

    for line in body:
        m = re.match(
            r'\s*([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.+);\s*$',
            line
        )

        if not m:
            continue

        name, rhs = m.groups()

        if name not in types:
            continue

        trial = dict(types)
        converted = convert_expr(rhs, trial)

        if converted is None:
            unsafe.add(name)
        elif converted[1] == "double":
            types[name] = "double"

    for name in unsafe:
        # Ne jamais retirer les compteurs internes.
        if not name.startswith("clair_range_"):
            types.pop(name, None)

    print("[Clair OPT] Types natifs :")

    for name in sorted(types):
        print(f"  {name} -> {types[name]}")

    output = []

    for line in lines:
        # NvVal x = nv_int(...)
        m = re.match(
            r'(\s*)NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*nv_int\((.+)\)\s*;\s*$',
            line
        )

        if m and types.get(m.group(2)) == "int":
            indent, name, value = m.groups()

            r = convert_expr(
                f"nv_int({value})",
                types
            )

            if r:
                output.append(
                    f"{indent}long long {name} = {r[0]};\n"
                )
                continue

        # NvVal x = nv_float(...)
        m = re.match(
            r'(\s*)NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*nv_float\((.+)\)\s*;\s*$',
            line
        )

        if m and types.get(m.group(2)) == "double":
            indent, name, value = m.groups()

            r = convert_expr(
                f"nv_float({value})",
                types
            )

            if r:
                output.append(
                    f"{indent}double {name} = {r[0]};\n"
                )
                continue

        # NvVal i = compteur;
        m = re.match(
            r'(\s*)NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*;\s*$',
            line
        )

        if (
            m
            and m.group(2) in types
            and m.group(3) in types
        ):
            indent, name, rhs = m.groups()

            ctype = (
                "double"
                if types[name] == "double"
                else "long long"
            )

            output.append(
                f"{indent}{ctype} {name} = {rhs};\n"
            )
            continue

        # while (...)
        m = re.match(
            r'(\s*)while\s*\((.+)\)\s*\{\s*$',
            line
        )

        if m:
            converted = convert_expr(m.group(2), types)

            if converted:
                output.append(
                    f"{m.group(1)}while ({converted[0]}) {{\n"
                )
                continue

        # Affectations natives
        m = re.match(
            r'(\s*)([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.+);\s*$',
            line
        )

        if m and m.group(2) in types:
            converted = convert_expr(m.group(3), types)

            if converted:
                output.append(
                    f"{m.group(1)}{m.group(2)} = "
                    f"{converted[0]};\n"
                )
                continue

        # Passage d'un nombre natif au runtime dynamique
        for name in sorted(
            types,
            key=len,
            reverse=True
        ):
            if types[name] == "double":
                wrapper = f"nv_float({name})"
            else:
                wrapper = f"nv_int({name})"

            line = re.sub(
                rf'nv_call_add\(([^,]+),\s*'
                rf'{re.escape(name)}\)',
                rf'nv_call_add(\1, {wrapper})',
                line
            )

        output.append(line)

    with open(destination, "w", encoding="utf-8") as f:
        f.writelines(output)

    print(
        f"[Clair OPT] C numérique optimisé : "
        f"{destination}"
    )


if __name__ == "__main__":
    main()
