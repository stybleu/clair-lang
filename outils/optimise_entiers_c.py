#!/usr/bin/env python3

import re
import sys


def split_args(s):
    args = []
    start = 0
    depth = 0

    for i, ch in enumerate(s):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            args.append(s[start:i].strip())
            start = i + 1

    args.append(s[start:].strip())
    return args


def unwrap_call(expr, name):
    prefix = name + "("

    if not expr.startswith(prefix) or not expr.endswith(")"):
        return None

    inner = expr[len(prefix):-1]

    depth = 0
    for ch in inner:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1

        if depth < 0:
            return None

    if depth != 0:
        return None

    return inner


def strip_outer_parens(expr):
    expr = expr.strip()

    while expr.startswith("(") and expr.endswith(")"):
        depth = 0
        wraps_all = True

        for i, ch in enumerate(expr):
            if ch == "(":
                depth += 1

            elif ch == ")":
                depth -= 1

                if depth < 0:
                    wraps_all = False
                    break

                if depth == 0 and i != len(expr) - 1:
                    wraps_all = False
                    break

        if not wraps_all or depth != 0:
            break

        expr = expr[1:-1].strip()

    return expr


def convert_expr(expr, native):
    expr = strip_outer_parens(expr)

    # Variable native
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', expr):
        if expr in native:
            return expr
        return None

    # Littéral entier C
    if re.fullmatch(r'-?\d+(?:LL)?', expr):
        return expr

    # nv_int(...)
    inner = unwrap_call(expr, "nv_int")
    if inner is not None:
        if re.fullmatch(r'-?\d+(?:LL)?', inner.strip()):
            return inner.strip()
        converted = convert_expr(inner, native)
        return converted

    # Opérations entières
    operations = {
        "nv_add": "+",
        "nv_sub": "-",
        "nv_mul": "*",
        "nv_mod": "%",
        "nv_lt": "<",
        "nv_le": "<=",
        "nv_gt": ">",
        "nv_ge": ">=",
        "nv_eq": "==",
        "nv_ne": "!=",
    }

    for fn, op in operations.items():
        inner = unwrap_call(expr, fn)

        if inner is None:
            continue

        args = split_args(inner)

        if len(args) != 2:
            return None

        a = convert_expr(args[0], native)
        b = convert_expr(args[1], native)

        if a is None or b is None:
            return None

        return f"({a} {op} {b})"

    inner = unwrap_call(expr, "nv_neg")
    if inner is not None:
        a = convert_expr(inner, native)

        if a is not None:
            return f"(-{a})"

    inner = unwrap_call(expr, "nv_truth")
    if inner is not None:
        a = convert_expr(inner, native)

        if a is not None:
            return f"({a})"

    return None


def main():
    if len(sys.argv) != 3:
        print("Usage: optimise_entiers_c.py entree.c sortie.c")
        sys.exit(2)

    source = sys.argv[1]
    destination = sys.argv[2]

    with open(source, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # On ne touche qu'au main().
    main_index = None

    for i, line in enumerate(lines):
        if re.match(r'\s*int\s+main\s*\(', line):
            main_index = i
            break

    if main_index is None:
        print("[Clair OPT] main() introuvable")
        sys.exit(1)

    native = set()

    # Les compteurs générés par optimise_plage.py sont sûrs.
    for line in lines[main_index:]:
        m = re.match(
            r'\s*NvVal\s+(clair_range_(?:index|fin|pas)_\d+)'
            r'\s*=\s*nv_int\(',
            line
        )

        if m:
            native.add(m.group(1))

    # Variables d'itération : NvVal i = clair_range_index_X;
    for line in lines[main_index:]:
        m = re.match(
            r'\s*NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(clair_range_index_\d+)\s*;',
            line
        )

        if m and m.group(2) in native:
            native.add(m.group(1))

    # Variables entières modifiées dans une boucle plage().
    int_decls = {}

    for i, line in enumerate(lines[main_index:], start=main_index):
        m = re.match(
            r'\s*NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*nv_int\((-?\d+(?:LL)?)\)\s*;',
            line
        )

        if m:
            int_decls[m.group(1)] = i

    for line in lines[main_index:]:
        m = re.match(
            r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+);\s*$',
            line
        )

        if not m:
            continue

        name = m.group(1)

        if name in int_decls:
            # On l'ajoute provisoirement pour permettre x = nv_add(x,...)
            trial = set(native)
            trial.add(name)

            if convert_expr(m.group(2), trial) is not None:
                native.add(name)

    print(
        "[Clair OPT] Entiers natifs détectés : "
        + ", ".join(sorted(native))
    )

    output = []

    for line in lines:
        original = line

        # NvVal x = nv_int(123LL);
        m = re.match(
            r'(\s*)NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*nv_int\((-?\d+(?:LL)?)\)\s*;\s*$',
            line
        )

        if m and m.group(2) in native:
            indent, name, value = m.groups()
            output.append(f"{indent}long long {name} = {value};\n")
            continue

        # NvVal i = compteur;
        m = re.match(
            r'(\s*)NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*;\s*$',
            line
        )

        if (
            m
            and m.group(2) in native
            and m.group(3) in native
        ):
            indent, name, rhs = m.groups()
            output.append(f"{indent}long long {name} = {rhs};\n")
            continue

        # while (nv_truth(...))
        m = re.match(
            r'(\s*)while\s*\((.+)\)\s*\{\s*$',
            line
        )

        if m:
            converted = convert_expr(m.group(2), native)

            if converted is not None:
                output.append(
                    f"{m.group(1)}while ({converted}) {{\n"
                )
                continue

        # Affectation entière
        m = re.match(
            r'(\s*)([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+);\s*$',
            line
        )

        if m and m.group(2) in native:
            converted = convert_expr(m.group(3), native)

            if converted is not None:
                output.append(
                    f"{m.group(1)}{m.group(2)} = {converted};\n"
                )
                continue

        # Passage d'un entier natif vers une fonction dynamique :
        # nv_call_add(&__c, x) -> nv_call_add(&__c, nv_int(x))
        for name in sorted(native, key=len, reverse=True):
            line = re.sub(
                rf'nv_call_add\(([^,]+),\s*{re.escape(name)}\)',
                rf'nv_call_add(\1, nv_int({name}))',
                line
            )

        output.append(line)

    with open(destination, "w", encoding="utf-8") as f:
        f.writelines(output)

    print(f"[Clair OPT] C optimisé : {destination}")


if __name__ == "__main__":
    main()
