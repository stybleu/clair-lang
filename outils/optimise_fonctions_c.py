#!/usr/bin/env python3

import re
import sys


NUMERIC_TYPES = {"int", "float"}


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

    if current:
        args.append("".join(current).strip())

    return args


def unwrap(expr, name):
    expr = strip_outer_parens(expr)
    prefix = name + "("

    if not expr.startswith(prefix) or not expr.endswith(")"):
        return None

    return expr[len(prefix):-1]


def promote(a, b):
    if a == "float" or b == "float":
        return "float"
    return "int"


def infer_expr_type(expr, symbols):
    expr = strip_outer_parens(expr)

    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', expr):
        return symbols.get(expr)

    if re.fullmatch(r'-?\d+(?:LL)?', expr):
        return "int"

    if re.fullmatch(
        r'-?(?:\d+\.\d*|\d*\.\d+)'
        r'(?:[eE][+-]?\d+)?',
        expr
    ):
        return "float"

    inner = unwrap(expr, "nv_int")
    if inner is not None:
        return "int"

    inner = unwrap(expr, "nv_float")
    if inner is not None:
        return "float"

    inner = unwrap(expr, "nv_neg")
    if inner is not None:
        return infer_expr_type(inner, symbols)

    for fn in ("nv_add", "nv_sub", "nv_mul"):
        inner = unwrap(expr, fn)

        if inner is None:
            continue

        args = split_args(inner)

        if len(args) != 2:
            return None

        a = infer_expr_type(args[0], symbols)
        b = infer_expr_type(args[1], symbols)

        if a not in NUMERIC_TYPES or b not in NUMERIC_TYPES:
            return None

        return promote(a, b)

    inner = unwrap(expr, "nv_div")
    if inner is not None:
        args = split_args(inner)

        if len(args) != 2:
            return None

        a = infer_expr_type(args[0], symbols)
        b = infer_expr_type(args[1], symbols)

        if a not in NUMERIC_TYPES or b not in NUMERIC_TYPES:
            return None

        return "float"

    inner = unwrap(expr, "nv_mod")
    if inner is not None:
        args = split_args(inner)

        if len(args) != 2:
            return None

        a = infer_expr_type(args[0], symbols)
        b = infer_expr_type(args[1], symbols)

        if a not in NUMERIC_TYPES or b not in NUMERIC_TYPES:
            return None

        return "int"

    inner = unwrap(expr, "nv_pow")
    if inner is not None:
        args = split_args(inner)

        if len(args) != 2:
            return None

        a = infer_expr_type(args[0], symbols)
        b = infer_expr_type(args[1], symbols)

        if a not in NUMERIC_TYPES or b not in NUMERIC_TYPES:
            return None

        return "float"

    for fn in (
        "nv_lt", "nv_le",
        "nv_gt", "nv_ge",
        "nv_eq", "nv_ne"
    ):
        inner = unwrap(expr, fn)

        if inner is None:
            continue

        args = split_args(inner)

        if len(args) != 2:
            return None

        a = infer_expr_type(args[0], symbols)
        b = infer_expr_type(args[1], symbols)

        if a not in NUMERIC_TYPES or b not in NUMERIC_TYPES:
            return None

        return "int"

    return None


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
            r'\s*static NvVal clariox_fn_'
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

        params = []
        explicit_types = {}
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
                explicit_types[tm.group(1)] = tm.group(2)
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

            safe = False
            break

        if (
            safe
            and return_expr is not None
            and params
            and all(params)
        ):
            functions[name] = {
                "params": params,
                "explicit_types": explicit_types,
                "expr": return_expr,
            }

        i = j + 1

    return functions


def infer_local_types(lines):
    types = {}

    # Littéraux directs
    for line in lines:
        m = re.match(
            r'\s*NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*nv_int\(',
            line
        )

        if m:
            types[m.group(1)] = "int"

        m = re.match(
            r'\s*NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*nv_float\(',
            line
        )

        if m:
            types[m.group(1)] = "float"

    # Propagation simple : NvVal b = a;
    changed = True

    while changed:
        changed = False

        for line in lines:
            m = re.match(
                r'\s*NvVal\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*;',
                line
            )

            if not m:
                continue

            dst, src = m.groups()

            if src in types and dst not in types:
                types[dst] = types[src]
                changed = True

    return types


def find_call_chunks(line):
    marker = "({ NvCall __c = nv_call_new();"
    end_marker = "__r; })"

    result = []
    pos = 0

    while True:
        start = line.find(marker, pos)

        if start < 0:
            break

        end = line.find(end_marker, start)

        if end < 0:
            break

        end += len(end_marker)

        result.append((start, end, line[start:end]))
        pos = end

    return result


def extract_arguments(chunk):
    return re.findall(
        r'nv_call_add\(&__c,\s*(.*?)\);\s*',
        chunk
    )


def compatible(expected, actual):
    if expected == "int":
        return actual == "int"

    if expected == "float":
        return actual in ("int", "float")

    return False


def inline_chunk(
    chunk,
    functions,
    local_types,
    specializations
):
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

    arg_types = []

    for arg in args:
        typ = infer_expr_type(
            arg.strip(),
            local_types
        )

        if typ not in NUMERIC_TYPES:
            return None

        arg_types.append(typ)

    # Respecte les annotations explicites lorsqu'elles existent.
    for param, actual in zip(
        info["params"],
        arg_types
    ):
        expected = info["explicit_types"].get(param)

        if expected is not None:
            if not compatible(expected, actual):
                return None

    param_symbols = {}

    for param, actual in zip(
        info["params"],
        arg_types
    ):
        expected = info["explicit_types"].get(param)

        if expected == "float":
            param_symbols[param] = "float"
        elif expected == "int":
            param_symbols[param] = "int"
        else:
            param_symbols[param] = actual

    return_type = infer_expr_type(
        info["expr"],
        param_symbols
    )

    if return_type not in NUMERIC_TYPES:
        return None

    specializations.add(
        (
            name,
            tuple(arg_types),
            return_type
        )
    )

    expr = info["expr"]

    for param, arg in zip(
        info["params"],
        args
    ):
        expr = replace_identifier(
            expr,
            param,
            arg.strip()
        )

    return f"({expr})"


def optimize_line(
    line,
    functions,
    local_types,
    specializations
):
    while True:
        chunks = find_call_chunks(line)

        changed = False

        for start, end, chunk in reversed(chunks):
            replacement = inline_chunk(
                chunk,
                functions,
                local_types,
                specializations
            )

            if replacement is None:
                continue

            line = (
                line[:start]
                + replacement
                + line[end:]
            )

            changed = True

        if not changed:
            break

    return line


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: optimise_fonctions_c.py "
            "entree.c sortie.c"
        )
        sys.exit(2)

    source, destination = sys.argv[1], sys.argv[2]

    with open(source, "r", encoding="utf-8") as f:
        lines = f.readlines()

    functions = parse_functions(lines)
    local_types = infer_local_types(lines)

    specializations = set()

    output = [
        optimize_line(
            line,
            functions,
            local_types,
            specializations
        )
        for line in lines
    ]

    if specializations:
        print(
            "[Clariox OPT] Spécialisations numériques :"
        )

        for name, args, ret in sorted(
            specializations
        ):
            signature = ", ".join(args)

            print(
                f"  {name}({signature}) -> {ret}"
            )
    else:
        print(
            "[Clariox OPT] Aucune fonction "
            "numérique spécialisée"
        )

    with open(destination, "w", encoding="utf-8") as f:
        f.writelines(output)

    print(
        "[Clariox OPT] Inférence fonctions : "
        f"{destination}"
    )


if __name__ == "__main__":
    main()
