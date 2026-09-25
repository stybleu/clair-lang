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

    # --------------------------------------------------------
    # Types de retour garantis de certains builtins.
    #
    # Le générateur C représente également les builtins par un
    # nv_dispatch_call(). Jusqu'ici, l'inférence ne savait donc
    # pas que :
    #
    #     input_int(...)   -> int
    #     input_float(...) -> float
    #     int(...)         -> int
    #     float(...)       -> float
    #
    # On n'utilise cette information que si l'expression entière
    # correspond à UN SEUL appel dynamique. Cela évite d'inférer
    # abusivement le type d'une expression contenant plusieurs
    # appels imbriqués.
    # --------------------------------------------------------

    builtin_dispatches = re.findall(
        r'nv_dispatch_call\("([^"]+)"\s*,',
        expr,
    )

    if len(builtin_dispatches) == 1:
        builtin_name = builtin_dispatches[0]

        builtin_numeric_returns = {
            "input_int": "int",
            "input_float": "float",
            "int": "int",
            "float": "float",
        }

        builtin_type = builtin_numeric_returns.get(
            builtin_name
        )

        if builtin_type is not None:
            return builtin_type

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


def parse_hoisted_branch_return(
    block_lines,
    inherited_defs=None,
    hoisted_names=None,
):
    """
    Reconstruit l'expression retournée par une branche lorsque
    certaines variables de fonction ont été pré-déclarées :

        NvVal y = nv_none();

        if (...) {
            y = ...;
            return y;
        }

    Cette représentation sert à l'inférence de type.
    """

    local_defs = dict(
        inherited_defs or {}
    )

    hoisted = set(
        hoisted_names or ()
    )

    assigned_hoisted = set()
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

        assignment_match = re.match(
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.+);\s*$',
            stripped,
        )

        if assignment_match:
            name = assignment_match.group(1)
            expr = assignment_match.group(2)

            if (
                name not in hoisted
                or name in assigned_hoisted
            ):
                return None

            local_defs[name] = expr
            assigned_hoisted.add(name)
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


def parse_conditional_return(lines):
    index = 0
    prefix_defs = {}
    hoisted_names = set()

    def skip_blank(i):
        while (
            i < len(lines)
            and not lines[i].strip()
        ):
            i += 1

        return i

    index = skip_blank(index)

    # Valeurs préparées avant le if.
    #
    # Une déclaration à nv_none() provenant du nouveau frontend
    # est seulement une réservation de variable :
    #
    #     NvVal y = nv_none();
    #
    # Sa vraie valeur sera déterminée dans chaque branche.
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
        expr = local_match.group(2).strip()

        if (
            name in prefix_defs
            or name in hoisted_names
        ):
            return None

        if expr == "nv_none()":
            hoisted_names.add(name)
        else:
            prefix_defs[name] = expr

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

        branch_expr = parse_hoisted_branch_return(
            block,
            prefix_defs,
            hoisted_names,
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

    if (
        not branches
        or branches[-1][0] is not None
    ):
        return None

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



def parse_native_branch_block(
    block_lines,
    inherited_defs=None,
    hoisted_names=None,
):
    """
    Conserve les calculs locaux d'une branche.

    Accepte à la fois :

        NvVal y = expr;

    et le nouveau format frontend :

        y = expr;

    lorsque y a été pré-déclaré à nv_none() dans le
    prologue de la fonction.
    """

    inherited = dict(
        inherited_defs or {}
    )

    hoisted = set(
        hoisted_names or ()
    )

    locals_list = []
    local_names = set()

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

            if (
                name in inherited
                or name in local_names
            ):
                return None

            expr = expand_local_expr(
                expr,
                inherited,
            )

            if expr is None:
                return None

            locals_list.append(
                (name, expr)
            )

            local_names.add(name)
            continue

        assignment_match = re.match(
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.+);\s*$',
            stripped,
        )

        if assignment_match:
            name = assignment_match.group(1)
            expr = assignment_match.group(2)

            # Pour cette première version, seules les variables
            # explicitement pré-déclarées par le frontend sont
            # acceptées ici.
            if (
                name not in hoisted
                or name in local_names
            ):
                return None

            expr = expand_local_expr(
                expr,
                inherited,
            )

            if expr is None:
                return None

            locals_list.append(
                (name, expr)
            )

            local_names.add(name)
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

            return_expr = expand_local_expr(
                expr,
                inherited,
            )

            if return_expr is None:
                return None

            continue

        return None

    if return_expr is None:
        return None

    # Supprimer le temporaire artificiel généré par clarioxc :
    #
    #     NvVal __ret5 = z;
    #     return __ret5;
    #
    # devient simplement return z dans le helper.
    if (
        locals_list
        and re.fullmatch(
            r'__ret\d+',
            return_expr,
        )
        and locals_list[-1][0] == return_expr
    ):
        _, return_expr = locals_list.pop()

    return {
        "locals": locals_list,
        "return": return_expr,
    }



def parse_conditional_native_body(lines):
    """
    Conserve un if / else if / else numérique structuré.

    Les variables pré-déclarées à nv_none() par le frontend
    sont reconnues comme des locaux de fonction dont les
    affectations réelles apparaissent dans les branches.
    """

    index = 0
    prefix_defs = {}
    hoisted_names = set()

    def skip_blank(i):
        while (
            i < len(lines)
            and not lines[i].strip()
        ):
            i += 1

        return i

    index = skip_blank(index)

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
        expr = local_match.group(2).strip()

        if (
            name in prefix_defs
            or name in hoisted_names
        ):
            return None

        if expr == "nv_none()":
            hoisted_names.add(name)
        else:
            prefix_defs[name] = expr

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
            if not branches:
                return None

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

        branch_body = parse_native_branch_block(
            block,
            prefix_defs,
            hoisted_names,
        )

        if branch_body is None:
            return None

        branches.append(
            (condition, branch_body)
        )

        index = skip_blank(
            close_index + 1
        )

        if condition is None:
            break

    if (
        not branches
        or branches[-1][0] is not None
    ):
        return None

    while index < len(lines):
        stripped = lines[index].strip()

        if not stripped:
            index += 1
            continue

        if stripped == "return nv_none();":
            index += 1
            continue

        return None

    return {
        "branches": branches,
    }



def parse_linear_native_body(block_lines):
    """
    Conserve la structure d'une fonction numérique linéaire.

    Exemple Clariox :

        y = x * 2.0
        z = y + 3.0
        return z

    devient une représentation structurée :

        locals = [
            ("y", ...),
            ("z", ...),
        ]
        return = "z"

    Toute structure de contrôle ou réaffectation complexe
    provoque un abandon conservateur.
    """

    locals_list = []
    known_names = set()
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

            if name in known_names:
                return None

            known_names.add(name)

            locals_list.append(
                (name, expr)
            )

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

        # if / while / affectation / appel non représentable :
        # garder l'ancien mécanisme basé sur l'expression.
        return None

    if return_expr is None:
        return None

    # Le générateur C crée souvent un temporaire artificiel :
    #
    #     NvVal __ret7 = z;
    #     return __ret7;
    #
    # Dans un helper natif linéaire, cette copie intermédiaire
    # n'apporte rien. Si le dernier local est exactement ce
    # temporaire de retour, retourner directement son expression.
    if (
        locals_list
        and re.fullmatch(
            r'__ret\d+',
            return_expr,
        )
        and locals_list[-1][0] == return_expr
    ):
        _, return_expr = locals_list.pop()

    return {
        "locals": locals_list,
        "return": return_expr,
    }



def parse_native_loop_assignments(
    block_lines,
    known_names,
):
    """
    Analyse un bloc interne de boucle/condition.

    Pour cette première version structurée, seules les
    réaffectations de variables déjà déclarées avant le
    while sont acceptées.
    """

    operations = []

    for line in block_lines:
        stripped = line.strip()

        if not stripped:
            continue

        assignment = re.match(
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.+);\s*$',
            stripped,
        )

        if not assignment:
            return None

        target = assignment.group(1)
        expr = assignment.group(2)

        if target not in known_names:
            return None

        operations.append({
            "kind": "assign",
            "target": target,
            "expr": expr,
        })

    return operations


def parse_native_while_if_chain(
    lines,
    start_index,
    known_names,
):
    """
    Analyse :

        if (...) {
            ...
        }
        else if (...) {
            ...
        }
        else {
            ...
        }

    Le else final est optionnel.
    """

    branches = []
    index = start_index

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
            condition = condition_match.group(1)

        elif else_match:
            if not branches:
                return None

            condition = None

        else:
            break

        collected = collect_braced_block(
            lines,
            index,
        )

        if collected is None:
            return None

        branch_lines, close_index = collected

        branch_operations = (
            parse_native_loop_assignments(
                branch_lines,
                known_names,
            )
        )

        if branch_operations is None:
            return None

        branches.append({
            "condition": condition,
            "operations": branch_operations,
        })

        index = close_index + 1

        while (
            index < len(lines)
            and not lines[index].strip()
        ):
            index += 1

        if condition is None:
            break

        if index >= len(lines):
            break

        next_line = lines[index].strip()

        if not (
            re.match(
                r'^else\s+if\s*\(',
                next_line,
            )
            or re.match(
                r'^else\s*\{\s*$',
                next_line,
            )
        ):
            break

    if not branches:
        return None

    return {
        "kind": "if",
        "branches": branches,
    }, index


def parse_native_while_body(block_lines):
    """
    Reconnaît conservativement une fonction numérique :

        locaux initiaux

        while condition:
            affectations

            if condition:
                affectations
            elif condition:
                affectations
            else:
                affectations

            affectations

        return valeur

    Les structures imbriquées au-delà de ce premier niveau,
    break/continue et nouvelles variables créées dans la
    boucle restent volontairement refusés.
    """

    index = 0
    locals_list = []
    known_names = set()

    def skip_blank(i):
        while (
            i < len(block_lines)
            and not block_lines[i].strip()
        ):
            i += 1

        return i

    index = skip_blank(index)

    # --------------------------------------------------------
    # Variables locales initiales.
    # --------------------------------------------------------

    while index < len(block_lines):
        stripped = block_lines[index].strip()

        local_match = re.match(
            r'NvVal\s+'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.+);\s*$',
            stripped,
        )

        if not local_match:
            break

        name = local_match.group(1)
        expr = local_match.group(2)

        if re.fullmatch(r'__ret\d+', name):
            break

        if name in known_names:
            return None

        known_names.add(name)

        locals_list.append(
            (name, expr)
        )

        index += 1
        index = skip_blank(index)

    if index >= len(block_lines):
        return None

    # --------------------------------------------------------
    # while.
    # --------------------------------------------------------

    while_match = re.match(
        r'while\s*\((.*)\)\s*\{\s*$',
        block_lines[index].strip(),
    )

    if not while_match:
        return None

    condition = while_match.group(1)

    collected = collect_braced_block(
        block_lines,
        index,
    )

    if collected is None:
        return None

    loop_lines, close_index = collected

    # --------------------------------------------------------
    # Corps structuré de la boucle.
    # --------------------------------------------------------

    operations = []
    loop_index = 0

    while loop_index < len(loop_lines):
        stripped = loop_lines[
            loop_index
        ].strip()

        if not stripped:
            loop_index += 1
            continue

        # if / else if / else
        if re.match(
            r'^if\s*\(',
            stripped,
        ):
            parsed = parse_native_while_if_chain(
                loop_lines,
                loop_index,
                known_names,
            )

            if parsed is None:
                return None

            operation, loop_index = parsed

            operations.append(
                operation
            )

            continue

        # Un else isolé est invalide.
        if re.match(
            r'^else\b',
            stripped,
        ):
            return None

        # Affectation simple.
        assignment = re.match(
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.+);\s*$',
            stripped,
        )

        if not assignment:
            return None

        target = assignment.group(1)
        expr = assignment.group(2)

        if target not in known_names:
            return None

        operations.append({
            "kind": "assign",
            "target": target,
            "expr": expr,
        })

        loop_index += 1

    index = skip_blank(
        close_index + 1
    )

    # --------------------------------------------------------
    # Return après la boucle.
    # --------------------------------------------------------

    post_defs = {}
    return_expr = None

    while index < len(block_lines):
        stripped = block_lines[index].strip()

        if not stripped:
            index += 1
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

            if not re.fullmatch(
                r'__ret\d+',
                name,
            ):
                return None

            if name in post_defs:
                return None

            post_defs[name] = expr
            index += 1
            continue

        return_match = re.match(
            r'return\s+(.+);\s*$',
            stripped,
        )

        if return_match:
            expr = return_match.group(1)

            if expr == "nv_none()":
                index += 1
                continue

            if return_expr is not None:
                return None

            return_expr = expr
            index += 1
            continue

        return None

    if return_expr is None:
        return None

    return_expr = expand_local_expr(
        return_expr,
        post_defs,
    )

    if return_expr is None:
        return None

    return {
        "locals": locals_list,
        "condition": condition,
        "operations": operations,
        "return": return_expr,
    }



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

        # Conserver également la structure linéaire originale.
        # parse_return_block() continue à fournir l'expression
        # complètement développée nécessaire à l'inférence.
        linear_native_body = (
            parse_linear_native_body(
                core
            )
        )

        conditional_native_body = None
        while_native_body = None

        # D'abord essayer la forme linéaire déjà supportée.
        return_expr = parse_return_block(
            core
        )

        # Sinon essayer un if/elif/else de retours numériques.
        if return_expr is None:
            conditional_native_body = (
                parse_conditional_native_body(
                    core
                )
            )

            return_expr = parse_conditional_return(
                core
            )

        # Troisième forme structurée :
        #
        #     locaux
        #     while (...)
        #         réaffectations
        #     return ...
        #
        # Une boucle ne peut pas être aplatie correctement en
        # une expression unique. Son type de retour sera donc
        # déterminé par build_native_while_helper().
        if return_expr is None:
            while_native_body = (
                parse_native_while_body(
                    core
                )
            )

        if (
            return_expr is not None
            or while_native_body is not None
        ):
            functions[name] = {
                "params": params,
                "explicit_types": explicit_types,
                "expr": return_expr,
                "linear_native_body": linear_native_body,
                "conditional_native_body": (
                    conditional_native_body
                ),
                "while_native_body": (
                    while_native_body
                ),
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



def specialization_c_name(
    name,
    arg_types,
    return_type,
):
    args_tag = (
        "_".join(arg_types)
        if arg_types
        else "void"
    )

    return (
        f"clariox_spec_{name}_"
        f"{args_tag}_to_{return_type}"
    )


def numeric_c_type(typ):
    if typ == "float":
        return "double"

    if typ == "int":
        return "long long"

    return None


def lower_numeric_condition_c(
    expr,
    symbols,
):
    expr = strip_outer_parens(expr)

    inner = unwrap(expr, "nv_truth")

    if inner is not None:
        lowered = lower_numeric_expr_c(
            inner,
            symbols,
        )

        if lowered is None:
            return None

        return f"(({lowered[0]}) != 0)"

    logical = {
        "nv_and": "&&",
        "nv_or": "||",
    }

    for fn, op in logical.items():
        inner = unwrap(expr, fn)

        if inner is None:
            continue

        args = split_args(inner)

        if len(args) != 2:
            return None

        left = lower_numeric_condition_c(
            args[0],
            symbols,
        )

        right = lower_numeric_condition_c(
            args[1],
            symbols,
        )

        if left is None or right is None:
            return None

        return (
            f"(({left}) {op} ({right}))"
        )

    inner = unwrap(expr, "nv_not")

    if inner is not None:
        lowered = lower_numeric_condition_c(
            inner,
            symbols,
        )

        if lowered is None:
            return None

        return f"!({lowered})"

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

        left = lower_numeric_expr_c(
            args[0],
            symbols,
        )

        right = lower_numeric_expr_c(
            args[1],
            symbols,
        )

        if left is None or right is None:
            return None

        return (
            f"(({left[0]}) {op} ({right[0]}))"
        )

    return None


def lower_numeric_expr_c(
    expr,
    symbols,
):
    expr = strip_outer_parens(expr)

    conditional = split_top_level_ternary(
        expr
    )

    if conditional is not None:
        condition, yes_expr, no_expr = (
            conditional
        )

        lowered_condition = (
            lower_numeric_condition_c(
                condition,
                symbols,
            )
        )

        yes_value = lower_numeric_expr_c(
            yes_expr,
            symbols,
        )

        no_value = lower_numeric_expr_c(
            no_expr,
            symbols,
        )

        if (
            lowered_condition is None
            or yes_value is None
            or no_value is None
        ):
            return None

        result_type = promote(
            yes_value[1],
            no_value[1],
        )

        return (
            f"(({lowered_condition}) "
            f"? ({yes_value[0]}) "
            f": ({no_value[0]}))",
            result_type,
        )

    if re.fullmatch(
        r'[A-Za-z_][A-Za-z0-9_]*',
        expr,
    ):
        typ = symbols.get(expr)

        if typ in NUMERIC_TYPES:
            return expr, typ

        return None

    if re.fullmatch(
        r'-?\d+(?:LL)?',
        expr,
    ):
        return expr, "int"

    if re.fullmatch(
        r'-?(?:\d+\.\d*|\d*\.\d+)'
        r'(?:[eE][+-]?\d+)?',
        expr,
    ):
        return expr, "float"

    inner = unwrap(expr, "nv_int")

    if inner is not None:
        lowered = lower_numeric_expr_c(
            inner,
            symbols,
        )

        if lowered is not None:
            return (
                f"(long long)({lowered[0]})",
                "int",
            )

        if re.fullmatch(
            r'-?\d+(?:LL)?',
            inner.strip(),
        ):
            return inner.strip(), "int"

        return None

    inner = unwrap(expr, "nv_float")

    if inner is not None:
        literal = strip_outer_parens(
            inner
        )

        # Un littéral décimal est déjà un double C.
        # Éviter de générer :
        #
        #     (double)(0.0)
        #
        # car certaines passes de simplification de conditions
        # peuvent ensuite le déformer en :
        #
        #     double(0.0)
        #
        # qui est du C invalide.
        if re.fullmatch(
            r'-?(?:\d+\.\d*|\d*\.\d+)'
            r'(?:[eE][+-]?\d+)?',
            literal,
        ):
            return literal, "float"

        # nv_float(1) doit également être considéré comme float,
        # même si la représentation C peut rester 1.0.
        if re.fullmatch(
            r'-?\d+',
            literal,
        ):
            return f"{literal}.0", "float"

        lowered = lower_numeric_expr_c(
            inner,
            symbols,
        )

        if lowered is not None:
            return (
                f"(double)({lowered[0]})",
                "float",
            )

        return None

    inner = unwrap(expr, "nv_neg")

    if inner is not None:
        lowered = lower_numeric_expr_c(
            inner,
            symbols,
        )

        if lowered is None:
            return None

        return (
            f"-({lowered[0]})",
            lowered[1],
        )

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

        left = lower_numeric_expr_c(
            args[0],
            symbols,
        )

        right = lower_numeric_expr_c(
            args[1],
            symbols,
        )

        if left is None or right is None:
            return None

        result_type = promote(
            left[1],
            right[1],
        )

        return (
            f"(({left[0]}) {op} ({right[0]}))",
            result_type,
        )

    inner = unwrap(expr, "nv_div")

    if inner is not None:
        args = split_args(inner)

        if len(args) != 2:
            return None

        left = lower_numeric_expr_c(
            args[0],
            symbols,
        )

        right = lower_numeric_expr_c(
            args[1],
            symbols,
        )

        if left is None or right is None:
            return None

        return (
            f"((double)({left[0]}) "
            f"/ (double)({right[0]}))",
            "float",
        )

    inner = unwrap(expr, "nv_mod")

    if inner is not None:
        args = split_args(inner)

        if len(args) != 2:
            return None

        left = lower_numeric_expr_c(
            args[0],
            symbols,
        )

        right = lower_numeric_expr_c(
            args[1],
            symbols,
        )

        if left is None or right is None:
            return None

        return (
            f"((long long)({left[0]}) "
            f"% (long long)({right[0]}))",
            "int",
        )

    inner = unwrap(expr, "nv_pow")

    if inner is not None:
        args = split_args(inner)

        if len(args) != 2:
            return None

        left = lower_numeric_expr_c(
            args[0],
            symbols,
        )

        right = lower_numeric_expr_c(
            args[1],
            symbols,
        )

        if left is None or right is None:
            return None

        return (
            f"pow((double)({left[0]}), "
            f"(double)({right[0]}))",
            "float",
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

        left = lower_numeric_expr_c(
            args[0],
            symbols,
        )

        right = lower_numeric_expr_c(
            args[1],
            symbols,
        )

        if left is None or right is None:
            return None

        return (
            f"(({left[0]}) {op} ({right[0]}))",
            "int",
        )

    return None



def build_native_linear_helper(
    info,
    functions,
    param_symbols,
    active_functions,
    helper_name,
):
    """
    Produit le corps C natif structuré d'une fonction linéaire.

    Les appels numériques interprocéduraux restent développés
    à l'intérieur du helper pour cette première version.
    """

    structured = info.get(
        "linear_native_body"
    )

    if structured is None:
        return None

    symbols = dict(param_symbols)
    body_lines = []

    # Les noms des variables locales d'un helper natif ne
    # doivent jamais entrer en collision avec les NvVal du
    # fallback générique.
    native_local_names = {}

    scratch_specializations = set()

    for local_index, (name, raw_expr) in enumerate(
        structured["locals"]
    ):
        rewritten_source = raw_expr

        # Remplacer les références aux locaux précédents par
        # leurs noms C privés au helper.
        for original_name, native_name in (
            native_local_names.items()
        ):
            rewritten_source = replace_identifier(
                rewritten_source,
                original_name,
                native_name,
            )

        rewritten = optimize_line(
            rewritten_source,
            functions,
            symbols,
            scratch_specializations,
            active_functions,
            specialization_defs=None,
            emit_helper=False,
        )

        lowered = lower_numeric_expr_c(
            rewritten,
            symbols,
        )

        if lowered is None:
            return None

        c_type = numeric_c_type(
            lowered[1]
        )

        if c_type is None:
            return None

        safe_local_name = (
            f"__{helper_name}_local_"
            f"{local_index}_{name}"
        )

        body_lines.append(
            f"    {c_type} {safe_local_name} = "
            f"{lowered[0]};\n"
        )

        native_local_names[name] = safe_local_name
        symbols[safe_local_name] = lowered[1]

    return_source = structured["return"]

    for original_name, native_name in (
        native_local_names.items()
    ):
        return_source = replace_identifier(
            return_source,
            original_name,
            native_name,
        )

    rewritten_return = optimize_line(
        return_source,
        functions,
        symbols,
        scratch_specializations,
        active_functions,
        specialization_defs=None,
        emit_helper=False,
    )

    lowered_return = lower_numeric_expr_c(
        rewritten_return,
        symbols,
    )

    if lowered_return is None:
        return None

    return {
        "lines": body_lines,
        "return_expr": lowered_return[0],
        "return_type": lowered_return[1],
    }



def build_native_conditional_helper(
    info,
    functions,
    param_symbols,
    active_functions,
    helper_name,
):
    """
    Produit un helper C structuré avec :

        if (...) {
            double local = ...;
            return ...;
        }
        else if (...) {
            ...
        }
        else {
            ...
        }

    Chaque branche possède son propre environnement natif.
    """

    structured = info.get(
        "conditional_native_body"
    )

    if structured is None:
        return None

    base_symbols = dict(param_symbols)
    scratch_specializations = set()

    body_lines = []
    branch_types = []

    branches = structured["branches"]

    for branch_index, (
        raw_condition,
        branch_body,
    ) in enumerate(branches):

        branch_symbols = dict(
            base_symbols
        )

        native_local_names = {}
        local_lines = []

        # --------------------------------------------------
        # Variables locales propres à cette branche.
        # --------------------------------------------------

        for local_index, (
            local_name,
            raw_expr,
        ) in enumerate(
            branch_body["locals"]
        ):
            rewritten_source = raw_expr

            # Les références aux locaux précédents utilisent
            # leur nom C privé.
            for (
                original_name,
                native_name,
            ) in native_local_names.items():
                rewritten_source = replace_identifier(
                    rewritten_source,
                    original_name,
                    native_name,
                )

            rewritten = optimize_line(
                rewritten_source,
                functions,
                branch_symbols,
                scratch_specializations,
                active_functions,
                specialization_defs=None,
                emit_helper=False,
            )

            lowered = lower_numeric_expr_c(
                rewritten,
                branch_symbols,
            )

            if lowered is None:
                return None

            c_type = numeric_c_type(
                lowered[1]
            )

            if c_type is None:
                return None

            safe_local_name = (
                f"__{helper_name}_branch_"
                f"{branch_index}_local_"
                f"{local_index}_{local_name}"
            )

            local_lines.append(
                f"        {c_type} "
                f"{safe_local_name} = "
                f"{lowered[0]};\n"
            )

            native_local_names[
                local_name
            ] = safe_local_name

            branch_symbols[
                safe_local_name
            ] = lowered[1]

        # --------------------------------------------------
        # Return de la branche.
        # --------------------------------------------------

        return_source = branch_body[
            "return"
        ]

        for (
            original_name,
            native_name,
        ) in native_local_names.items():
            return_source = replace_identifier(
                return_source,
                original_name,
                native_name,
            )

        rewritten_return = optimize_line(
            return_source,
            functions,
            branch_symbols,
            scratch_specializations,
            active_functions,
            specialization_defs=None,
            emit_helper=False,
        )

        lowered_return = lower_numeric_expr_c(
            rewritten_return,
            branch_symbols,
        )

        if lowered_return is None:
            return None

        branch_types.append(
            lowered_return[1]
        )

        # --------------------------------------------------
        # else final
        # --------------------------------------------------

        if raw_condition is None:
            if branch_index == 0:
                return None

            body_lines.append(
                "    else {\n"
            )

            body_lines.extend(
                local_lines
            )

            body_lines.append(
                f"        return "
                f"{lowered_return[0]};\n"
            )

            body_lines.append(
                "    }\n"
            )

            continue

        # --------------------------------------------------
        # if / else if
        # --------------------------------------------------

        rewritten_condition = optimize_line(
            raw_condition,
            functions,
            base_symbols,
            scratch_specializations,
            active_functions,
            specialization_defs=None,
            emit_helper=False,
        )

        lowered_condition = (
            lower_numeric_condition_c(
                rewritten_condition,
                base_symbols,
            )
        )

        if lowered_condition is None:
            return None

        keyword = (
            "if"
            if branch_index == 0
            else "else if"
        )

        body_lines.append(
            f"    {keyword} "
            f"({lowered_condition}) {{\n"
        )

        body_lines.extend(
            local_lines
        )

        body_lines.append(
            f"        return "
            f"{lowered_return[0]};\n"
        )

        body_lines.append(
            "    }\n"
        )

    if not branch_types:
        return None

    result_type = branch_types[0]

    for branch_type in branch_types[1:]:
        result_type = promote(
            result_type,
            branch_type,
        )

    return {
        "lines": body_lines,
        "return_type": result_type,
        "terminal_returns": True,
    }



def build_native_while_helper(
    info,
    functions,
    param_symbols,
    active_functions,
    helper_name,
):
    """
    Produit une boucle C native structurée pouvant contenir
    des affectations et un premier niveau de if/elif/else.

    Toute réaffectation doit conserver exactement le type
    numérique initial de la variable.
    """

    structured = info.get(
        "while_native_body"
    )

    if structured is None:
        return None

    symbols = dict(param_symbols)

    native_local_names = {}
    native_local_types = {}

    scratch_specializations = set()
    body_lines = []

    # --------------------------------------------------------
    # Utilitaires.
    # --------------------------------------------------------

    def rewrite_native_names(source):
        result = source

        for (
            original_name,
            native_name,
        ) in native_local_names.items():
            result = replace_identifier(
                result,
                original_name,
                native_name,
            )

        return result

    def lower_assignment(
        target,
        raw_expr,
        indent,
    ):
        if target not in native_local_names:
            return None

        rewritten_source = (
            rewrite_native_names(
                raw_expr
            )
        )

        rewritten = optimize_line(
            rewritten_source,
            functions,
            symbols,
            scratch_specializations,
            active_functions,
            specialization_defs=None,
            emit_helper=False,
        )

        lowered = lower_numeric_expr_c(
            rewritten,
            symbols,
        )

        if lowered is None:
            return None

        expected_type = (
            native_local_types[target]
        )

        # Preuve de stabilité de type.
        if lowered[1] != expected_type:
            return None

        safe_target = (
            native_local_names[target]
        )

        return (
            f"{indent}{safe_target} = "
            f"{lowered[0]};\n"
        )

    # --------------------------------------------------------
    # Locaux initiaux.
    # --------------------------------------------------------

    for local_index, (
        local_name,
        raw_expr,
    ) in enumerate(
        structured["locals"]
    ):
        rewritten_source = (
            rewrite_native_names(
                raw_expr
            )
        )

        rewritten = optimize_line(
            rewritten_source,
            functions,
            symbols,
            scratch_specializations,
            active_functions,
            specialization_defs=None,
            emit_helper=False,
        )

        lowered = lower_numeric_expr_c(
            rewritten,
            symbols,
        )

        if lowered is None:
            return None

        typ = lowered[1]

        if typ not in NUMERIC_TYPES:
            return None

        c_type = numeric_c_type(
            typ
        )

        if c_type is None:
            return None

        safe_name = (
            f"__{helper_name}_while_local_"
            f"{local_index}_{local_name}"
        )

        body_lines.append(
            f"    {c_type} {safe_name} = "
            f"{lowered[0]};\n"
        )

        native_local_names[
            local_name
        ] = safe_name

        native_local_types[
            local_name
        ] = typ

        symbols[
            safe_name
        ] = typ

    # --------------------------------------------------------
    # Condition while.
    # --------------------------------------------------------

    condition_source = (
        rewrite_native_names(
            structured["condition"]
        )
    )

    rewritten_condition = optimize_line(
        condition_source,
        functions,
        symbols,
        scratch_specializations,
        active_functions,
        specialization_defs=None,
        emit_helper=False,
    )

    lowered_condition = (
        lower_numeric_condition_c(
            rewritten_condition,
            symbols,
        )
    )

    if lowered_condition is None:
        return None

    body_lines.append(
        f"    while ({lowered_condition}) {{\n"
    )

    # --------------------------------------------------------
    # Corps structuré.
    # --------------------------------------------------------

    for operation in structured[
        "operations"
    ]:
        kind = operation.get(
            "kind"
        )

        # Affectation simple.
        if kind == "assign":
            line = lower_assignment(
                operation["target"],
                operation["expr"],
                "        ",
            )

            if line is None:
                return None

            body_lines.append(
                line
            )

            continue

        # if / else if / else.
        if kind == "if":
            branches = operation[
                "branches"
            ]

            for branch_index, branch in enumerate(
                branches
            ):
                raw_condition = branch[
                    "condition"
                ]

                if raw_condition is None:
                    if branch_index == 0:
                        return None

                    body_lines.append(
                        "        else {\n"
                    )

                else:
                    condition_source = (
                        rewrite_native_names(
                            raw_condition
                        )
                    )

                    rewritten_branch_condition = (
                        optimize_line(
                            condition_source,
                            functions,
                            symbols,
                            scratch_specializations,
                            active_functions,
                            specialization_defs=None,
                            emit_helper=False,
                        )
                    )

                    lowered_branch_condition = (
                        lower_numeric_condition_c(
                            rewritten_branch_condition,
                            symbols,
                        )
                    )

                    if (
                        lowered_branch_condition
                        is None
                    ):
                        return None

                    keyword = (
                        "if"
                        if branch_index == 0
                        else "else if"
                    )

                    body_lines.append(
                        f"        {keyword} "
                        f"({lowered_branch_condition}) "
                        "{\n"
                    )

                for branch_operation in branch[
                    "operations"
                ]:
                    if (
                        branch_operation.get("kind")
                        != "assign"
                    ):
                        return None

                    line = lower_assignment(
                        branch_operation["target"],
                        branch_operation["expr"],
                        "            ",
                    )

                    if line is None:
                        return None

                    body_lines.append(
                        line
                    )

                body_lines.append(
                    "        }\n"
                )

            continue

        return None

    body_lines.append(
        "    }\n"
    )

    # --------------------------------------------------------
    # Return.
    # --------------------------------------------------------

    return_source = (
        rewrite_native_names(
            structured["return"]
        )
    )

    rewritten_return = optimize_line(
        return_source,
        functions,
        symbols,
        scratch_specializations,
        active_functions,
        specialization_defs=None,
        emit_helper=False,
    )

    lowered_return = lower_numeric_expr_c(
        rewritten_return,
        symbols,
    )

    if lowered_return is None:
        return None

    if lowered_return[1] not in NUMERIC_TYPES:
        return None

    return {
        "lines": body_lines,
        "return_expr": lowered_return[0],
        "return_type": lowered_return[1],
        "terminal_returns": False,
    }



def inline_chunk(
    chunk,
    functions,
    local_types,
    specializations,
    active_functions=None,
    specialization_defs=None,
    emit_helper=True,
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

    if active_functions is None:
        active_functions = set()

    # Protection contre :
    #
    #     A -> A
    #
    # mais aussi :
    #
    #     A -> B -> A
    #
    # Une fonction déjà présente dans la chaîne active n'est
    # pas spécialisée récursivement.
    if name in active_functions:
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

    # --------------------------------------------------------
    # Optimisation interprocédurale récursive.
    #
    # Exemple :
    #
    #     fn inner(x):
    #         return x + 1.0
    #
    #     fn outer(x):
    #         return inner(x) * 2.0
    #
    # Pour spécialiser outer(float), il faut d'abord
    # transformer inner(x) en expression numérique.
    #
    # Les spécialisations découvertes dans le corps ne sont
    # publiées que si outer() peut finalement être spécialisé.
    # --------------------------------------------------------

    nested_specializations = set()

    structured_helper = None
    structured_terminal_returns = False

    expr = None
    native_body = None
    return_type = None

    # --------------------------------------------------------
    # Fonction contenant un while structuré.
    #
    # Contrairement aux fonctions linéaires/conditionnelles,
    # elle ne peut pas être réduite à une expression unique.
    # Le builder fournit directement le type de retour.
    # --------------------------------------------------------

    if info.get("while_native_body") is not None:
        provisional_helper_name = (
            f"clariox_spec_{name}_native_while"
        )

        structured_helper = (
            build_native_while_helper(
                info,
                functions,
                param_symbols,
                active_functions | {name},
                provisional_helper_name,
            )
        )

        if structured_helper is None:
            return None

        return_type = structured_helper[
            "return_type"
        ]

        if return_type not in NUMERIC_TYPES:
            return None

        # Une fonction contenant une boucle ne peut pas être
        # textuellement inline pendant une analyse de preuve :
        # cela supprimerait sa sémantique de boucle.
        if not emit_helper:
            return None

        native_body = (
            structured_helper.get(
                "return_expr",
                "0",
            ),
            return_type,
        )

    else:
        # ----------------------------------------------------
        # Chemin historique :
        # fonction réductible à une expression numérique.
        # ----------------------------------------------------

        expr = optimize_line(
            info["expr"],
            functions,
            param_symbols,
            nested_specializations,
            active_functions | {name},
            specialization_defs=None,
            emit_helper=False,
        )

        return_type = infer_expr_type(
            expr,
            param_symbols
        )

        if return_type not in NUMERIC_TYPES:
            return None

        native_body = lower_numeric_expr_c(
            expr,
            param_symbols,
        )

        if native_body is None:
            return None

        if native_body[1] != return_type:
            return None

        structured_helper = build_native_linear_helper(
            info,
            functions,
            param_symbols,
            active_functions | {name},
            specialization_c_name(
                name,
                tuple(arg_types),
                return_type,
            ),
        )

        if structured_helper is None:
            structured_helper = (
                build_native_conditional_helper(
                    info,
                    functions,
                    param_symbols,
                    active_functions | {name},
                    specialization_c_name(
                        name,
                        tuple(arg_types),
                        return_type,
                    ),
                )
            )

            if structured_helper is not None:
                structured_terminal_returns = True

        if (
            structured_helper is not None
            and structured_helper["return_type"]
            != return_type
        ):
            structured_helper = None
            structured_terminal_returns = False

    # La spécialisation n'est publiée qu'après validation
    # complète du chemin natif.
    specializations.update(
        nested_specializations
    )

    specializations.add(
        (
            name,
            tuple(arg_types),
            return_type
        )
    )

    # --------------------------------------------------------
    # Lors d'une analyse de preuve (while/fixed-point), garder
    # l'ancien comportement d'inlining textuel.
    # --------------------------------------------------------

    if not emit_helper:
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

    helper_name = specialization_c_name(
        name,
        tuple(arg_types),
        return_type,
    )

    if specialization_defs is not None:
        specialization_defs.setdefault(
            helper_name,
            {
                "source_name": name,
                "params": tuple(info["params"]),
                "arg_types": tuple(arg_types),
                "return_type": return_type,
                "body": native_body[0],
                "body_lines": (
                    structured_helper["lines"]
                    if structured_helper is not None
                    else None
                ),
                "return_expr": (
                    structured_helper.get(
                        "return_expr",
                        native_body[0],
                    )
                    if structured_helper is not None
                    else native_body[0]
                ),
                "terminal_returns": (
                    structured_terminal_returns
                    if structured_helper is not None
                    else False
                ),
            },
        )

    # --------------------------------------------------------
    # Le premier C doit rester compilable AVANT la passe
    # numérique. Les arguments sont donc convertis depuis
    # NvVal vers leur représentation C native.
    #
    # Les passes suivantes reconnaîtront ces ponts et les
    # supprimeront lorsque les arguments sont déjà natifs.
    # --------------------------------------------------------

    bridged_args = []

    for arg, typ in zip(
        args,
        arg_types,
    ):
        argument = arg.strip()

        if typ == "float":
            bridged_args.append(
                f"nv_num({argument})"
            )
        else:
            bridged_args.append(
                f"(long long)nv_num({argument})"
            )

    call = (
        f"{helper_name}("
        + ", ".join(bridged_args)
        + ")"
    )

    if return_type == "float":
        return f"nv_float({call})"

    return f"nv_int({call})"


def optimize_line(
    line,
    functions,
    local_types,
    specializations,
    active_functions=None,
    specialization_defs=None,
    emit_helper=True,
):
    if active_functions is None:
        active_functions = set()

    while True:
        chunks = find_call_chunks(line)

        changed = False

        for start, end, chunk in reversed(chunks):
            replacement = inline_chunk(
                chunk,
                functions,
                local_types,
                specializations,
                active_functions,
                specialization_defs,
                emit_helper,
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
    specialization_defs = {}

    # --------------------------------------------------------
    # Propagation flow-sensitive des types dans main().
    #
    # Les variables réaffectées sont suivies dans l'ordre du
    # programme. Les boucles while nécessitent en plus un
    # point fixe : une information de type ne peut être
    # utilisée dans le corps que si elle reste vraie après
    # chaque tour possible.
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
                r'\s*=\s*(.*?)\s*;\s*$',
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

    # Une variable réaffectée ne doit jamais conserver un
    # type provenant de l'analyse globale.
    for name in reassigned_names:
        local_types.pop(name, None)

    # --------------------------------------------------------
    # Localisation de la fin d'un bloc C {...}.
    # --------------------------------------------------------

    def find_block_end(start_index):
        depth = (
            lines[start_index].count("{")
            - lines[start_index].count("}")
        )

        if depth <= 0:
            return None

        index = start_index + 1

        while index < len(lines):
            depth += (
                lines[index].count("{")
                - lines[index].count("}")
            )

            if depth == 0:
                return index

            index += 1

        return None

    # --------------------------------------------------------
    # Point fixe des types à travers un while.
    #
    # candidate_types contient les types connus à l'entrée.
    #
    # Pour qu'un type survive :
    #   - chaque réaffectation dans la boucle doit produire
    #     exactement le même type ;
    #   - cette preuve doit rester vraie après suppression des
    #     autres candidats instables.
    #
    # Exemple sûr :
    #
    #   a:int
    #   while ...:
    #       a = only_int(a)
    #
    # Exemple non sûr :
    #
    #   a:int
    #   while ...:
    #       only_int(a)
    #       a = 2.5
    #
    # Dans le second cas, a est éliminé avant l'optimisation
    # du corps.
    # --------------------------------------------------------

    def analyze_while_fixedpoint(
        start_index,
        entry_flow_types,
    ):
        loop_end = find_block_end(start_index)

        if loop_end is None:
            return start_index, {}

        candidates = dict(entry_flow_types)

        while True:
            removed = set()

            symbols = dict(local_types)
            symbols.update(candidates)

            for index in range(
                start_index + 1,
                loop_end,
            ):
                current = lines[index]

                assignment = re.match(
                    r'\s*'
                    r'([A-Za-z_][A-Za-z0-9_]*)'
                    r'\s*=\s*(.*?)\s*;\s*$',
                    current,
                )

                if not assignment:
                    continue

                name = assignment.group(1)

                if name not in candidates:
                    continue

                # Simuler l'inlining avec les types candidats,
                # mais sans enregistrer de spécialisation
                # définitive pendant cette phase de preuve.
                scratch_specializations = set()

                rewritten = optimize_line(
                    current,
                    functions,
                    symbols,
                    scratch_specializations,
                    specialization_defs=None,
                    emit_helper=False,
                )

                rewritten_assignment = re.match(
                    r'\s*'
                    r'([A-Za-z_][A-Za-z0-9_]*)'
                    r'\s*=\s*(.*?)\s*;\s*$',
                    rewritten,
                )

                if not rewritten_assignment:
                    removed.add(name)
                    continue

                rhs = rewritten_assignment.group(2)

                inferred = infer_expr_type(
                    rhs,
                    symbols,
                )

                if inferred != candidates[name]:
                    removed.add(name)

            if not removed:
                break

            for name in removed:
                candidates.pop(name, None)

        return loop_end, candidates

    output = []

    flow_types = {}

    in_main = False
    main_depth = 0

    active_while_end = None
    active_while_types = None

    for line_index, line in enumerate(lines):
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

        # ----------------------------------------------------
        # Entrée dans un while directement situé dans main().
        #
        # On calcule AVANT de transformer son corps les types
        # qui sont invariants sur le back-edge.
        # ----------------------------------------------------

        if (
            top_level_main
            and re.match(
                r'\s*while\s*\(',
                line,
            )
        ):
            (
                active_while_end,
                active_while_types,
            ) = analyze_while_fixedpoint(
                line_index,
                flow_types,
            )

        inside_active_while = (
            active_while_end is not None
            and line_index <= active_while_end
        )

        # Un else hors d'une boucle analysée représente un
        # chemin différent. Sans fusion complète des branches,
        # abandon conservateur des faits flow-sensitive.
        if (
            in_main
            and not inside_active_while
            and re.match(
                r'\s*else\b',
                line,
            )
        ):
            flow_types.clear()

        effective_types = dict(local_types)

        if in_main:
            if inside_active_while:
                effective_types.update(
                    active_while_types or {}
                )
            else:
                effective_types.update(
                    flow_types
                )

        optimized = optimize_line(
            line,
            functions,
            effective_types,
            specializations,
            specialization_defs=specialization_defs,
            emit_helper=True,
        )

        output.append(optimized)

        # ----------------------------------------------------
        # Hors boucle : mise à jour flow-sensitive normale.
        #
        # Dans un while actif, on n'apprend PAS les types ligne
        # après ligne : cela reproduirait précisément le bug du
        # premier tour. Seul le point fixe calculé plus haut
        # est autorisé.
        # ----------------------------------------------------

        if (
            in_main
            and main_depth >= 1
            and not inside_active_while
        ):
            stripped = optimized.strip()

            declaration = re.match(
                r'NvVal\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*(.+);\s*$',
                stripped,
            )

            if declaration:
                name = declaration.group(1)
                expr = declaration.group(2)

                inferred = infer_expr_type(
                    expr,
                    effective_types,
                )

                if name in reassigned_names:
                    if inferred in NUMERIC_TYPES:
                        flow_types[name] = inferred
                    else:
                        flow_types.pop(
                            name,
                            None,
                        )

                else:
                    if inferred in NUMERIC_TYPES:
                        local_types[name] = inferred
                    else:
                        local_types.pop(
                            name,
                            None,
                        )

            else:
                assignment = re.match(
                    r'([A-Za-z_][A-Za-z0-9_]*)'
                    r'\s*=\s*(.+);\s*$',
                    stripped,
                )

                if assignment:
                    name = assignment.group(1)

                    if name in reassigned_names:
                        expr = assignment.group(2)

                        inferred = infer_expr_type(
                            expr,
                            effective_types,
                        )

                        if inferred in NUMERIC_TYPES:
                            flow_types[name] = inferred
                        else:
                            flow_types.pop(
                                name,
                                None,
                            )

        if in_main:
            old_depth = main_depth

            main_depth += (
                optimized.count("{")
                - optimized.count("}")
            )

            # Fin du while : seuls les types prouvés invariants
            # restent valables après zéro, un ou plusieurs tours.
            if (
                active_while_end is not None
                and line_index == active_while_end
            ):
                flow_types = dict(
                    active_while_types or {}
                )

                active_while_end = None
                active_while_types = None

            elif (
                old_depth > 1
                and main_depth == 1
                and active_while_end is None
            ):
                # Sortie d'un autre bloc de contrôle.
                flow_types.clear()

            if main_depth <= 0:
                in_main = False
                main_depth = 0

                flow_types.clear()

                active_while_end = None
                active_while_types = None

    # --------------------------------------------------------
    # Génération des spécialisations natives réutilisables.
    #
    # Heuristique initiale :
    #   < 8 appels : laisser Clang décider ;
    #   >= 8 appels : noinline.
    #
    # Ce seuil est volontairement simple et pourra être
    # benchmarké/raffiné ultérieurement.
    # --------------------------------------------------------

    if specialization_defs:
        output_text = "".join(output)

        helper_lines = []

        print(
            "[Clariox OPT] Fonctions natives spécialisées :"
        )

        for helper_name in sorted(
            specialization_defs
        ):
            info = specialization_defs[
                helper_name
            ]

            call_count = output_text.count(
                helper_name + "("
            )

            noinline = call_count >= 8

            attribute = (
                "__attribute__((noinline)) "
                if noinline
                else ""
            )

            return_ctype = numeric_c_type(
                info["return_type"]
            )

            params = []

            for param, typ in zip(
                info["params"],
                info["arg_types"],
            ):
                params.append(
                    f"{numeric_c_type(typ)} "
                    f"{param}"
                )

            helper_lines.extend([
                "\n",
                f"static {attribute}"
                f"{return_ctype} "
                f"{helper_name}("
                f"{', '.join(params)}) {{\n",
            ])

            if info.get("body_lines"):
                helper_lines.extend(
                    info["body_lines"]
                )

            if not info.get(
                "terminal_returns",
                False,
            ):
                helper_lines.append(
                    f"    return "
                    f"{info.get('return_expr', info['body'])};\n"
                )

            helper_lines.extend([
                "}\n",
                "\n",
            ])

            policy = (
                "noinline"
                if noinline
                else "clang"
            )

            print(
                f"  {helper_name}: "
                f"{call_count} appel(s), "
                f"politique={policy}"
            )

        main_index = None

        for index, generated_line in enumerate(
            output
        ):
            if re.match(
                r'\s*int\s+main\s*\(',
                generated_line,
            ):
                main_index = index
                break

        if main_index is None:
            raise RuntimeError(
                "main() introuvable lors de "
                "l'insertion des spécialisations natives"
            )

        output = (
            output[:main_index]
            + helper_lines
            + output[main_index:]
        )

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
