#!/usr/bin/env python3

import re
import subprocess
import sys
from pathlib import Path


def strip_outer(expr):
    expr = expr.strip()

    while expr.startswith("(") and expr.endswith(")"):
        depth = 0
        valid = True

        for i, ch in enumerate(expr):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1

                if depth == 0 and i != len(expr) - 1:
                    valid = False
                    break

        if not valid or depth != 0:
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
    expr = strip_outer(expr)
    prefix = name + "("

    if not expr.startswith(prefix) or not expr.endswith(")"):
        return None

    return expr[len(prefix):-1]


def safe_c_int(expr, native_ints):
    expr = strip_outer(expr)

    if expr in native_ints:
        return expr

    if re.fullmatch(r'-?\d+(?:LL)?', expr):
        return expr

    if re.fullmatch(
        r'[A-Za-z_][A-Za-z0-9_]*\.len',
        expr
    ):
        return expr

    # (long long)texte.len, (long long)(texte.len), etc.
    m = re.fullmatch(
        r'\(long long\)\s*(.+)',
        expr
    )

    if m:
        inner = strip_outer(m.group(1))

        if (
            inner in native_ints
            or re.fullmatch(
                r'[A-Za-z_][A-Za-z0-9_]*\.len',
                inner
            )
            or re.fullmatch(r'-?\d+(?:LL)?', inner)
        ):
            return f"(long long)({inner})"

    return None


def lower(expr, native_ints):
    expr = strip_outer(expr)

    raw = safe_c_int(expr, native_ints)

    if raw is not None:
        return raw, "int"

    inner = unwrap(expr, "nv_int")

    if inner is not None:
        raw = safe_c_int(inner, native_ints)

        if raw is not None:
            return raw, "int"

        nested = lower(inner, native_ints)

        if nested is not None:
            return nested

        return None

    binary = {
        "nv_add": "+",
        "nv_sub": "-",
        "nv_mul": "*",
        "nv_mod": "%",
    }

    for fn, op in binary.items():
        inner = unwrap(expr, fn)

        if inner is None:
            continue

        args = split_args(inner)

        if len(args) != 2:
            return None

        a = lower(args[0], native_ints)
        b = lower(args[1], native_ints)

        if (
            a is None
            or b is None
            or a[1] != "int"
            or b[1] != "int"
        ):
            return None

        if op == "%":
            return (
                f"((long long)({a[0]}) % "
                f"(long long)({b[0]}))",
                "int",
            )

        return (
            f"(({a[0]}) {op} ({b[0]}))",
            "int",
        )

    comparisons = {
        "nv_eq": "==",
        "nv_ne": "!=",
        "nv_lt": "<",
        "nv_le": "<=",
        "nv_gt": ">",
        "nv_ge": ">=",
    }

    for fn, op in comparisons.items():
        inner = unwrap(expr, fn)

        if inner is None:
            continue

        args = split_args(inner)

        if len(args) != 2:
            return None

        a = lower(args[0], native_ints)
        b = lower(args[1], native_ints)

        if (
            a is None
            or b is None
            or a[1] != "int"
            or b[1] != "int"
        ):
            return None

        return (
            f"(({a[0]}) {op} ({b[0]}))",
            "bool",
        )

    return None


def replace_balanced(line, function, callback):
    marker = function + "("
    pos = 0

    while True:
        start = line.find(marker, pos)

        if start < 0:
            break

        open_pos = start + len(function)
        depth = 0
        end = None

        for i in range(open_pos, len(line)):
            ch = line[i]

            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1

                if depth == 0:
                    end = i
                    break

        if end is None:
            break

        inner = line[open_pos + 1:end]
        replacement = callback(inner)

        if replacement is None:
            pos = end + 1
            continue

        line = (
            line[:start]
            + replacement
            + line[end + 1:]
        )

        pos = start + len(replacement)

    return line


def repair(lines):
    native_ints = set()
    native_floats = set()
    native_strings = set()

    def discover_native_types(source_lines):
        for line in source_lines:
            m = re.match(
                r'^\s*long long\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)\b',
                line
            )
            if m:
                native_ints.add(m.group(1))

            m = re.match(
                r'^\s*double\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)\b',
                line
            )
            if m:
                native_floats.add(m.group(1))

            m = re.match(
                r'^\s*ClarioxString\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)\b',
                line
            )
            if m:
                native_strings.add(m.group(1))

    discover_native_types(lines)

    changed = True

    # Première phase :
    # continuer l'abaissement numérique natif existant.
    while changed:
        changed = False
        new_output = []
        known = set(native_ints)

        for line in lines:
            # NvVal x = expression entière native;
            m = re.match(
                r'^(\s*)NvVal\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*(.*?)\s*;\s*$',
                line
            )

            if m:
                indent, name, rhs = (
                    m.group(1),
                    m.group(2),
                    m.group(3),
                )

                # Les temporaires de "selon" doivent rester NvVal :
                # ils sont utilisés ensuite par les comparaisons
                # dynamiques du runtime.
                if not name.startswith("__selon"):
                    lowered = lower(rhs, known)

                    if lowered and lowered[1] == "int":
                        line = (
                            f"{indent}long long {name} = "
                            f"{lowered[0]};\n"
                        )

                        known.add(name)
                        native_ints.add(name)
                        changed = True

            # if (nv_truth(expression numérique))
            def truth_callback(inner):
                lowered = lower(inner, known)

                if lowered is None:
                    return None

                if lowered[1] in ("bool", "int"):
                    return f"({lowered[0]})"

                return None

            new_line = replace_balanced(
                line,
                "nv_truth",
                truth_callback
            )

            if new_line != line:
                changed = True

            new_output.append(new_line)

        lines = new_output

    discover_native_types(lines)

    def box_native(expr):
        expr = strip_outer(expr)

        if expr in native_strings:
            return f"clariox_string_box({expr})"

        if expr in native_ints:
            return f"nv_int({expr})"

        if expr in native_floats:
            return f"nv_float({expr})"

        return None

    output = []

    # Deuxième phase :
    # réparer les frontières natif -> NvVal.
    for line in lines:

        # Réparer une frontière natif -> NvVal même lorsqu'elle
        # n'est pas au début de la ligne.
        #
        # Exemple généré par "selon" :
        # { NvVal __selon1 = couleur;
        def box_nvval_assignment(match):
            target = match.group(1)
            source = match.group(2)

            boxed = box_native(source)

            if boxed is None:
                return match.group(0)

            return f"NvVal {target} = {boxed};"

        line = re.sub(
            r'\bNvVal\s+'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*;',
            box_nvval_assignment,
            line
        )

        # Exemple :
        # NvVal __selon1 = couleur;
        #
        # devient :
        # NvVal __selon1 = clariox_string_box(couleur);
        m = re.match(
            r'^(\s*)NvVal\s+'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*;\s*$',
            line
        )

        if m:
            indent = m.group(1)
            target = m.group(2)
            source = m.group(3)

            boxed = box_native(source)

            if boxed is not None:
                line = (
                    f"{indent}NvVal {target} = "
                    f"{boxed};\n"
                )

        # nv_to_str(age)
        # nv_to_str(nom)
        def to_str_callback(inner):
            boxed = box_native(inner)

            if boxed is None:
                return None

            return f"nv_to_str({boxed})"

        line = replace_balanced(
            line,
            "nv_to_str",
            to_str_callback
        )

        # nv_dict_set_value(__d, "nom", nom)
        def dict_set_callback(inner):
            args = split_args(inner)

            if len(args) != 3:
                return None

            boxed = box_native(args[2])

            if boxed is None:
                return None

            return (
                "nv_dict_set_value("
                f"{args[0]}, "
                f"{args[1]}, "
                f"{boxed}"
                ")"
            )

        line = replace_balanced(
            line,
            "nv_dict_set_value",
            dict_set_callback
        )

        # nv_set_index(table, index, valeur)
        #
        # Les arguments index et valeur doivent être des NvVal.
        # Si l'optimiseur les a spécialisés en types C natifs,
        # il faut les boxer avant l'appel au runtime.
        def set_index_callback(inner):
            args = split_args(inner)

            if len(args) != 3:
                return None

            changed = False

            for index in (1, 2):
                boxed = box_native(args[index])

                if boxed is not None:
                    args[index] = boxed
                    changed = True

            if not changed:
                return None

            return (
                "nv_set_index("
                f"{args[0]}, "
                f"{args[1]}, "
                f"{args[2]}"
                ")"
            )

        line = replace_balanced(
            line,
            "nv_set_index",
            set_index_callback
        )

        # nv_call_add(&__c, valeur)
        #
        # Le constructeur d'appel attend toujours un NvVal.
        def call_add_callback(inner):
            args = split_args(inner)

            if len(args) != 2:
                return None

            boxed = box_native(args[1])

            if boxed is None:
                return None

            return (
                "nv_call_add("
                f"{args[0]}, "
                f"{boxed}"
                ")"
            )

        line = replace_balanced(
            line,
            "nv_call_add",
            call_add_callback
        )

        # Les opérations arithmétiques du runtime travaillent
        # exclusivement avec des NvVal. Boxer les opérandes
        # éventuellement transformés en types C natifs.
        for numeric_fn in (
            "nv_add",
            "nv_sub",
            "nv_mul",
            "nv_div",
            "nv_mod",
            "nv_pow",
        ):
            def numeric_binary_callback(inner, fn=numeric_fn):
                args = split_args(inner)

                if len(args) != 2:
                    return None

                changed = False

                for index in (0, 1):
                    boxed = box_native(args[index])

                    if boxed is not None:
                        args[index] = boxed
                        changed = True

                if not changed:
                    return None

                return (
                    f"{fn}("
                    f"{args[0]}, "
                    f"{args[1]}"
                    ")"
                )

            line = replace_balanced(
                line,
                numeric_fn,
                numeric_binary_callback
            )

        # nv_neg(...) possède un seul opérande.
        def numeric_unary_callback(inner):
            args = split_args(inner)

            if len(args) != 1:
                return None

            boxed = box_native(args[0])

            if boxed is None:
                return None

            return f"nv_neg({boxed})"

        line = replace_balanced(
            line,
            "nv_neg",
            numeric_unary_callback
        )

        # Frontière inverse : NvVal -> type C natif.
        #
        # Exemple :
        #
        # somme = nv_add(nv_int(somme), nv_get_index(...));
        #
        # devient :
        #
        # somme = (long long)nv_num(
        #     nv_add(nv_int(somme), nv_get_index(...))
        # );
        #
        # nv_num() vérifie que le résultat est numérique.
        numeric_result = re.match(
            r'^(\s*)'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*'
            r'(nv_(?:add|sub|mul|div|mod|pow|neg|get_index)'
            r'\(.*\))'
            r'\s*;\s*$',
            line
        )

        if numeric_result:
            indent = numeric_result.group(1)
            target = numeric_result.group(2)
            expression = numeric_result.group(3)

            if target in native_ints:
                line = (
                    f"{indent}{target} = "
                    f"(long long)nv_num({expression});\n"
                )

            elif target in native_floats:
                line = (
                    f"{indent}{target} = "
                    f"nv_num({expression});\n"
                )

        output.append(line)

    return output

def main():
    if len(sys.argv) != 3:
        print(
            "Usage: optimise_numeriques_mixte_c.py "
            "entree.c sortie.c"
        )
        sys.exit(2)

    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])

    base_optimizer = (
        Path(__file__).with_name(
            "optimise_numeriques_c.py"
        )
    )

    temporary = destination.with_suffix(
        destination.suffix + ".numeric"
    )

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(base_optimizer),
                str(source),
                str(temporary),
            ],
            check=False,
        )

        if result.returncode != 0:
            sys.exit(result.returncode)

        lines = temporary.read_text(
            encoding="utf-8"
        ).splitlines(keepends=True)

        repaired = repair(lines)

        destination.write_text(
            "".join(repaired),
            encoding="utf-8"
        )

        print(
            "[Clariox OPT] Raccord numérique/natif appliqué"
        )

    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
