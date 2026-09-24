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


def split_top_level_ternary(expr):
    expr = strip_outer_parens(expr)

    depth = 0
    question = None
    nested = 0

    for index, ch in enumerate(expr):
        if ch == "(":
            depth += 1
            continue

        if ch == ")":
            depth -= 1
            continue

        if depth != 0:
            continue

        if ch == "?":
            if question is None:
                question = index
                nested = 1
            else:
                nested += 1

        elif ch == ":" and question is not None:
            nested -= 1

            if nested == 0:
                return (
                    expr[:question].strip(),
                    expr[question + 1:index].strip(),
                    expr[index + 1:].strip(),
                )

    return None


def infer_expr_type(expr, symbols):
    expr = strip_outer_parens(expr)

    conditional = split_top_level_ternary(expr)

    if conditional is not None:
        condition, yes_expr, no_expr = conditional

        if not infer_numeric_condition(
            condition,
            symbols,
        ):
            return None

        yes_type = infer_expr_type(
            yes_expr,
            symbols,
        )

        no_type = infer_expr_type(
            no_expr,
            symbols,
        )

        if (
            yes_type not in NUMERIC_TYPES
            or no_type not in NUMERIC_TYPES
        ):
            return None

        return promote(
            yes_type,
            no_type,
        )

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


def infer_numeric_condition(expr, symbols):
    expr = strip_outer_parens(expr)

    inner = unwrap(expr, "nv_truth")

    if inner is not None:
        return infer_numeric_condition(
            inner,
            symbols,
        )

    for fn in ("nv_and", "nv_or"):
        inner = unwrap(expr, fn)

        if inner is None:
            continue

        args = split_args(inner)

        if len(args) != 2:
            return False

        return (
            infer_numeric_condition(
                args[0],
                symbols,
            )
            and
            infer_numeric_condition(
                args[1],
                symbols,
            )
        )

    inner = unwrap(expr, "nv_not")

    if inner is not None:
        return infer_numeric_condition(
            inner,
            symbols,
        )

    for fn in (
        "nv_eq", "nv_ne",
        "nv_lt", "nv_le",
        "nv_gt", "nv_ge",
    ):
        inner = unwrap(expr, fn)

        if inner is None:
            continue

        args = split_args(inner)

        if len(args) != 2:
            return False

        left = infer_expr_type(
            args[0],
            symbols,
        )

        right = infer_expr_type(
            args[1],
            symbols,
        )

        return (
            left in NUMERIC_TYPES
            and right in NUMERIC_TYPES
        )

    return False


def replace_identifier(expr, name, value):
    return re.sub(
        rf'\b{re.escape(name)}\b',
        f'({value})',
        expr
    )


def expand_local_expr(expr, local_defs):
    """
    Remplace récursivement les temporaires locaux simples par
    leur expression d'origine.

    Exemple :

        y = nv_add(x, nv_float(1.0))
        __ret3 = y
        return __ret3

    devient conceptuellement :

        return nv_add(x, nv_float(1.0))

    Les cycles provoquent un abandon conservateur.
    """

    def resolve_name(name, stack):
        if name not in local_defs:
            return name

        if name in stack:
            return None

        value = local_defs[name]
        stack = stack | {name}

        identifiers = re.findall(
            r'\b[A-Za-z_][A-Za-z0-9_]*\b',
            value,
        )

        for dep in identifiers:
            if dep not in local_defs:
                continue

            resolved = resolve_name(dep, stack)

            if resolved is None:
                return None

            value = replace_identifier(
                value,
                dep,
                resolved,
            )

        return value

    result = expr

    identifiers = re.findall(
        r'\b[A-Za-z_][A-Za-z0-9_]*\b',
        result,
    )

    for name in identifiers:
        if name not in local_defs:
            continue

        resolved = resolve_name(name, set())

        if resolved is None:
            return None

        result = replace_identifier(
            result,
            name,
            resolved,
        )

    return result


def parse_return_block(
    block_lines,
    inherited_defs=None,
):
    local_defs = dict(
        inherited_defs or {}
    )

    return_expr = None

    for line in block_lines:
        stripped = line.strip()

        if not stripped:
            continue

        local_match = re.match(
            r'NvVal\s+'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.+);\s*$',
            stripped,
        )

        if local_match:
            name = local_match.group(1)
            expr = local_match.group(2)

            if name in local_defs:
                return None

            local_defs[name] = expr
            continue

        return_match = re.match(
            r'return\s+(.+);\s*$',
            stripped,
        )

        if return_match:
            expr = return_match.group(1)

            if expr == "nv_none()":
                continue

            if return_expr is not None:
                return None

            return_expr = expr
            continue

        return None

    if return_expr is None:
        return None

    return expand_local_expr(
        return_expr,
        local_defs,
    )


def collect_braced_block(lines, start_index):
    header = lines[start_index]

    depth = (
        header.count("{")
        - header.count("}")
    )

    if depth <= 0:
        return None

    block = []
    index = start_index + 1

    while index < len(lines):
        current = lines[index]

        next_depth = (
            depth
            + current.count("{")
            - current.count("}")
        )

        if next_depth == 0:
            return block, index

        block.append(current)

        depth = next_depth
        index += 1

    return None


def parse_conditional_return(lines):
    index = 0
    prefix_defs = {}

    def skip_blank(i):
        while (
            i < len(lines)
            and not lines[i].strip()
        ):
            i += 1

        return i

    index = skip_blank(index)

    # Variables numériques préparées avant le if.
    while index < len(lines):
        stripped = lines[index].strip()

        local_match = re.match(
            r'NvVal\s+'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.+);\s*$',
            stripped,
        )

        if not local_match:
            break

        name = local_match.group(1)

        if name in prefix_defs:
            return None

        prefix_defs[name] = (
            local_match.group(2)
        )

        index += 1
        index = skip_blank(index)

    if index >= len(lines):
        return None

    branches = []

    while index < len(lines):
        stripped = lines[index].strip()

        condition_match = re.match(
            r'^(?:if|else\s+if)'
            r'\s*\((.*)\)\s*\{\s*$',
            stripped,
        )

        else_match = re.match(
            r'^else\s*\{\s*$',
            stripped,
        )

        if condition_match:
            condition = expand_local_expr(
                condition_match.group(1),
                prefix_defs,
            )

            if condition is None:
                return None

        elif else_match:
            condition = None

        else:
            return None

        collected = collect_braced_block(
            lines,
            index,
        )

        if collected is None:
            return None

        block, close_index = collected

        branch_expr = parse_return_block(
            block,
            prefix_defs,
        )

        if branch_expr is None:
            return None

        branches.append(
            (condition, branch_expr)
        )

        index = skip_blank(
            close_index + 1
        )

        if condition is None:
            break

    # Un else final est obligatoire dans cette première
    # version : chaque chemin doit retourner une valeur.
    if (
        not branches
        or branches[-1][0] is not None
    ):
        return None

    # Après le else, seul le return nv_none() généré par
    # clarioxc est autorisé.
    while index < len(lines):
        stripped = lines[index].strip()

        if not stripped:
            index += 1
            continue

        if stripped == "return nv_none();":
            index += 1
            continue

        return None

    result = branches[-1][1]

    for condition, branch_expr in reversed(
        branches[:-1]
    ):
        result = (
            f"(({condition}) "
            f"? ({branch_expr}) "
            f": ({result}))"
        )

    return result


def parse_functions(lines):
    functions = {}
    i = 0

    while i < len(lines):
        m = re.match(
            r'\s*static NvVal clariox_fn_'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\(NvVal \*__args, int __argc, '
            r'NvDict \*__kwargs\)\s*\{\s*$',
            lines[i],
        )

        if not m:
            i += 1
            continue

        name = m.group(1)

        # Lecture du corps complet, y compris les blocs
        # if/else imbriqués.
        body = []
        depth = 1
        j = i + 1

        while j < len(lines):
            current = lines[j]

            next_depth = (
                depth
                + current.count("{")
                - current.count("}")
            )

            if next_depth == 0:
                break

            body.append(current)

            depth = next_depth
            j += 1

        if depth <= 0:
            i = j + 1
            continue

        params = []
        explicit_types = {}
        core = []

        for line in body:
            stripped = line.strip()

            if not stripped:
                core.append(line)
                continue

            pm = re.match(
                r'NvVal\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*nv_arg\('
                r'__args,\s*__argc,\s*__kwargs,\s*'
                r'(\d+),\s*"([^"]+)"\s*\);',
                stripped,
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
                stripped,
            )

            if tm:
                explicit_types[
                    tm.group(1)
                ] = tm.group(2)

                continue

            core.append(line)

        if not params or not all(params):
            i = j + 1
            continue

        # D'abord essayer la forme linéaire déjà supportée.
        return_expr = parse_return_block(
            core
        )

        # Sinon essayer un if/elif/else de retours numériques.
        if return_expr is None:
            return_expr = parse_conditional_return(
                core
            )

        if return_expr is not None:
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
    """
    Retourne uniquement les NvCall les plus internes.

    Exemple :

        print(classify(x))

    produit deux blocs NvCall imbriqués. L'ancienne version
    associait le début du NvCall externe avec la fin du NvCall
    interne.

    On spécialise maintenant les appels de l'intérieur vers
    l'extérieur. optimize_line() relance ensuite l'analyse
    jusqu'à stabilisation.
    """

    marker = "({ NvCall __c = nv_call_new();"
    end_marker = "__r; })"

    result = []
    stack = []
    pos = 0

    while pos < len(line):
        next_start = line.find(
            marker,
            pos,
        )

        next_end = line.find(
            end_marker,
            pos,
        )

        if next_start < 0 and next_end < 0:
            break

        if (
            next_start >= 0
            and (
                next_end < 0
                or next_start < next_end
            )
        ):
            if stack:
                stack[-1]["has_child"] = True

            stack.append({
                "start": next_start,
                "has_child": False,
            })

            pos = next_start + len(marker)
            continue

        if next_end >= 0:
            end = next_end + len(end_marker)

            if stack:
                frame = stack.pop()

                if not frame["has_child"]:
                    start_pos = frame["start"]

                    result.append((
                        start_pos,
                        end,
                        line[start_pos:end],
                    ))

            pos = end
            continue

        break

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

    # --------------------------------------------------------
    # Propagation avant des types numériques dans main().
    #
    # optimize_line() peut transformer :
    #
    #     NvVal b = step(a);
    #
    # en une expression numérique entièrement connue.
    #
    # L'ancienne version calculait local_types une seule fois
    # avant l'inlining. Le type nouvellement découvert pour b
    # n'était donc pas disponible pour :
    #
    #     c = step(b)
    #     d = step(c)
    #
    # On traite désormais main() séquentiellement et on
    # réinjecte le type d'une déclaration spécialisée dans
    # l'environnement des lignes suivantes.
    #
    # Pour rester conservateur, une variable réaffectée plus
    # tard n'est pas ajoutée par cette nouvelle propagation.
    # --------------------------------------------------------

    reassigned_names = set()

    scan_in_main = False
    scan_depth = 0

    for source_line in lines:
        if (
            not scan_in_main
            and re.match(
                r'\s*int\s+main\s*\(',
                source_line,
            )
        ):
            scan_in_main = True

        if scan_in_main and scan_depth >= 1:
            assignment = re.match(
                r'\s*'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*',
                source_line,
            )

            if assignment:
                reassigned_names.add(
                    assignment.group(1)
                )

        if scan_in_main:
            scan_depth += (
                source_line.count("{")
                - source_line.count("}")
            )

            if scan_depth <= 0:
                scan_in_main = False
                scan_depth = 0

    output = []

    in_main = False
    main_depth = 0

    for line in lines:
        if (
            not in_main
            and re.match(
                r'\s*int\s+main\s*\(',
                line,
            )
        ):
            in_main = True

        top_level_main = (
            in_main
            and main_depth == 1
        )

        optimized = optimize_line(
            line,
            functions,
            local_types,
            specializations
        )

        output.append(optimized)

        # Une déclaration située directement dans main() peut
        # maintenant transmettre son type aux appels suivants.
        #
        # Exemple :
        #
        #     a : float
        #     b = step(a)  -> float
        #     c = step(b)  -> float
        #     d = step(c)  -> float
        #
        if top_level_main:
            declaration = re.match(
                r'\s*NvVal\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*(.+);\s*$',
                optimized.strip(),
            )

            if declaration:
                name = declaration.group(1)
                expr = declaration.group(2)

                if name not in reassigned_names:
                    inferred = infer_expr_type(
                        expr,
                        local_types,
                    )

                    if inferred in NUMERIC_TYPES:
                        local_types[name] = inferred

        if in_main:
            main_depth += (
                optimized.count("{")
                - optimized.count("}")
            )

            if main_depth <= 0:
                in_main = False
                main_depth = 0

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
