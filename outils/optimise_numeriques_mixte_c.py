#!/usr/bin/env python3

import re
import math
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


def safe_c_int(expr, native_ints, dynamic_ints=None):
    expr = strip_outer(expr)

    if expr in native_ints:
        return expr

    # Variable dynamique connue entière à ce point précis
    # du flot d'exécution.
    if dynamic_ints and expr in dynamic_ints:
        return f"(long long)nv_num({expr})"

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

def lower(expr, native_ints, dynamic_ints=None):
    expr = strip_outer(expr)

    raw = safe_c_int(expr, native_ints, dynamic_ints)

    if raw is not None:
        return raw, "int"

    inner = unwrap(expr, "nv_int")

    if inner is not None:
        raw = safe_c_int(inner, native_ints, dynamic_ints)

        if raw is not None:
            return raw, "int"

        nested = lower(inner, native_ints, dynamic_ints)

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

        a = lower(args[0], native_ints, dynamic_ints)
        b = lower(args[1], native_ints, dynamic_ints)

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

        a = lower(args[0], native_ints, dynamic_ints)
        b = lower(args[1], native_ints, dynamic_ints)

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



def split_flow_ternary(expr):
    expr = strip_outer(expr)

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


def lower_flow_number(
    expr,
    native_ints,
    native_floats,
    dynamic_types=None,
):
    """
    Abaisse une expression numérique dans un contexte où
    certaines NvVal ont un type numérique connu localement.
    """

    expr = strip_outer(expr)

    conditional = split_flow_ternary(expr)

    if conditional is not None:
        condition, yes_expr, no_expr = conditional

        lowered_condition = lower_flow_condition(
            condition,
            native_ints,
            native_floats,
            dynamic_types,
        )

        yes_value = lower_flow_number(
            yes_expr,
            native_ints,
            native_floats,
            dynamic_types,
        )

        no_value = lower_flow_number(
            no_expr,
            native_ints,
            native_floats,
            dynamic_types,
        )

        if (
            lowered_condition is None
            or yes_value is None
            or no_value is None
        ):
            return None

        result_type = (
            "double"
            if "double" in (
                yes_value[1],
                no_value[1],
            )
            else "int"
        )

        return (
            f"(({strip_outer(lowered_condition)}) "
            f"? ({yes_value[0]}) "
            f": ({no_value[0]}))",
            result_type,
        )


    if expr in native_ints:
        return expr, "int"

    if expr in native_floats:
        return expr, "double"

    if dynamic_types and expr in dynamic_types:
        typ = dynamic_types[expr]

        if typ == "int":
            return f"(long long)nv_num({expr})", "int"

        if typ == "double":
            return f"nv_num({expr})", "double"

    if re.fullmatch(r'-?\d+(?:LL)?', expr):
        return expr, "int"

    if re.fullmatch(
        r'-?(?:\d+\.\d*|\d*\.\d+|\d+[eE][+-]?\d+)'
        r'(?:[eE][+-]?\d+)?',
        expr
    ):
        return expr, "double"

    # --------------------------------------------------------
    # Appel d'une spécialisation native Clariox.
    #
    # Les arguments possèdent encore un pont nv_num() afin que
    # le C intermédiaire pré-optimisation reste compilable.
    # Cette passe remplace ces ponts par les vraies expressions
    # C natives lorsque leur type est connu.
    # --------------------------------------------------------

    specialized = re.match(
        r'^(clariox_spec_'
        r'[A-Za-z_][A-Za-z0-9_]*'
        r'_to_(int|float))'
        r'\((.*)\)$',
        expr,
    )

    if specialized:
        helper = specialized.group(1)
        return_type = specialized.group(2)

        raw_args = split_args(
            specialized.group(3)
        )

        native_args = []

        for raw_arg in raw_args:
            argument = raw_arg.strip()

            float_bridge = unwrap(
                argument,
                "nv_num",
            )

            if float_bridge is not None:
                lowered = lower_flow_number(
                    float_bridge,
                    native_ints,
                    native_floats,
                    dynamic_types,
                )

                if lowered is None:
                    return None

                native_args.append(
                    lowered[0]
                )
                continue

            int_bridge = re.match(
                r'^\(long long\)nv_num\((.*)\)$',
                argument,
            )

            if int_bridge:
                lowered = lower_flow_number(
                    int_bridge.group(1),
                    native_ints,
                    native_floats,
                    dynamic_types,
                )

                if lowered is None:
                    return None

                native_args.append(
                    f"(long long)({lowered[0]})"
                )
                continue

            return None

        return (
            f"{helper}("
            + ", ".join(native_args)
            + ")",
            (
                "double"
                if return_type == "float"
                else "int"
            ),
        )

    # --------------------------------------------------------
    # nv_num(expr)
    #
    # nv_num() extrait une valeur numérique NvVal sous forme
    # de double. Si l'expression interne est elle-même
    # entièrement prouvée numérique, le wrapper runtime peut
    # disparaître.
    #
    # Exemple :
    #
    #     nv_num(
    #         nv_add(
    #             nv_float(total),
    #             nv_float(r0)
    #         )
    #     )
    #
    # devient :
    #
    #     total + r0
    # --------------------------------------------------------

    inner = unwrap(expr, "nv_num")

    if inner is not None:
        lowered = lower_flow_number(
            inner,
            native_ints,
            native_floats,
            dynamic_types,
        )

        if lowered is None:
            return None

        return (
            f"(double)({lowered[0]})",
            "double",
        )

    inner = unwrap(expr, "nv_int")

    if inner is not None:
        lowered = lower_flow_number(
            inner,
            native_ints,
            native_floats,
            dynamic_types,
        )

        if lowered is not None and lowered[1] == "int":
            return lowered

        return None

    inner = unwrap(expr, "nv_float")

    if inner is not None:
        lowered = lower_flow_number(
            inner,
            native_ints,
            native_floats,
            dynamic_types,
        )

        if lowered is not None:
            return lowered[0], "double"

        return None

    inner = unwrap(expr, "nv_neg")

    if inner is not None:
        lowered = lower_flow_number(
            inner,
            native_ints,
            native_floats,
            dynamic_types,
        )

        if lowered is not None:
            return f"-({lowered[0]})", lowered[1]

        return None

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

        a = lower_flow_number(
            args[0],
            native_ints,
            native_floats,
            dynamic_types,
        )

        b = lower_flow_number(
            args[1],
            native_ints,
            native_floats,
            dynamic_types,
        )

        if a is None or b is None:
            return None

        typ = (
            "double"
            if "double" in (a[1], b[1])
            else "int"
        )

        return (
            f"({a[0]} {op} {b[0]})",
            typ,
        )

    inner = unwrap(expr, "nv_div")

    if inner is not None:
        args = split_args(inner)

        if len(args) != 2:
            return None

        a = lower_flow_number(
            args[0],
            native_ints,
            native_floats,
            dynamic_types,
        )

        b = lower_flow_number(
            args[1],
            native_ints,
            native_floats,
            dynamic_types,
        )

        if a is None or b is None:
            return None

        return (
            f"((double)({a[0]}) / (double)({b[0]}))",
            "double",
        )

    # FLOW_NATIVE_MOD_V1
    #
    # Abaissement conservateur du modulo entier.
    #
    # Pour préserver l'erreur Clariox de division par zéro,
    # cette première version n'accepte qu'un diviseur entier
    # littéral et statiquement non nul.
    inner = unwrap(expr, "nv_mod")

    if inner is not None:
        args = split_args(inner)

        if len(args) != 2:
            return None

        a = lower_flow_number(
            args[0],
            native_ints,
            native_floats,
            dynamic_types,
        )

        b = lower_flow_number(
            args[1],
            native_ints,
            native_floats,
            dynamic_types,
        )

        if (
            a is None
            or b is None
            or a[1] != "int"
            or b[1] != "int"
        ):
            return None

        raw_divisor = strip_outer(args[1])

        divisor_inner = unwrap(
            raw_divisor,
            "nv_int",
        )

        if divisor_inner is not None:
            raw_divisor = strip_outer(
                divisor_inner
            )

        literal_divisor = re.fullmatch(
            r'(-?\d+)(?:LL)?',
            raw_divisor,
        )

        if literal_divisor is None:
            return None

        divisor_value = int(
            literal_divisor.group(1)
        )

        if divisor_value == 0:
            return None

        return (
            f"((long long)({a[0]}) % "
            f"(long long)({b[0]}))",
            "int",
        )

    return None


def lower_flow_condition(
    expr,
    native_ints,
    native_floats,
    dynamic_types=None,
):
    """
    Abaisse une condition numérique Clariox vers une
    expression booléenne C native.

    Version conservatrice :
    - comparaisons numériques ;
    - and / or entre conditions numériques ;
    - not sur une condition numérique.

    Toute expression inconnue provoque un abandon de
    l'abaissement natif.
    """

    expr = strip_outer(expr)

    inner = unwrap(expr, "nv_truth")

    if inner is not None:
        return lower_flow_condition(
            inner,
            native_ints,
            native_floats,
            dynamic_types,
        )

    # --------------------------------------------------------
    # Opérateurs logiques.
    #
    # Ils ne sont abaissés que si CHAQUE opérande est lui-même
    # une condition numérique entièrement comprise.
    # --------------------------------------------------------

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

        left = lower_flow_condition(
            args[0],
            native_ints,
            native_floats,
            dynamic_types,
        )

        right = lower_flow_condition(
            args[1],
            native_ints,
            native_floats,
            dynamic_types,
        )

        if left is None or right is None:
            return None

        return (
            f"(({strip_outer(left)}) "
            f"{op} "
            f"({strip_outer(right)}))"
        )

    inner = unwrap(expr, "nv_not")

    if inner is not None:
        lowered = lower_flow_condition(
            inner,
            native_ints,
            native_floats,
            dynamic_types,
        )

        if lowered is None:
            return None

        return (
            f"!({strip_outer(lowered)})"
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

        left = lower_flow_number(
            args[0],
            native_ints,
            native_floats,
            dynamic_types,
        )

        right = lower_flow_number(
            args[1],
            native_ints,
            native_floats,
            dynamic_types,
        )

        if left is None or right is None:
            return None

        return (
            f"(({left[0]}) {op} ({right[0]}))"
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



def simplify_control_condition(line):
    """
    Simplifie uniquement les conditions C de if/while.

    Exemples :
        while (((a < b))) {
    devient :
        while (a < b) {

        if ((i) == (2LL)) {
    devient :
        if (i == 2LL) {
    """

    m = re.match(
        r'^(\s*)(if|while)\s*\((.*)\)\s*\{\s*$',
        line.rstrip("\n")
    )

    if not m:
        return line

    indent, keyword, condition = m.groups()

    condition = strip_outer(condition)

    # Parenthèses autour d'un simple identifiant.
    #
    # Important : ne jamais modifier les arguments d'un
    # appel de fonction.
    #
    #     (a)        -> a
    #     nv_not(a)  -> nv_not(a)
    #
    condition = re.sub(
        r'(?<![A-Za-z0-9_])'
        r'\(([A-Za-z_][A-Za-z0-9_]*)\)',
        r'\1',
        condition
    )

    # Même protection pour les constantes entières :
    #
    #     (2LL)        -> 2LL
    #     nv_int(2LL)  -> nv_int(2LL)
    #
    condition = re.sub(
        r'(?<![A-Za-z0-9_])'
        r'\((-?\d+(?:LL)?)\)',
        r'\1',
        condition
    )

    return f"{indent}{keyword} ({condition}) {{\n"



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

    # --------------------------------------------------------
    # Spécialisation flow-sensitive numérique simple.
    #
    # Première étape pour les float :
    # suivre les NvVal numériques dans le flux linéaire de
    # main(), mais abandonner les faits dès qu'un bloc de
    # contrôle est rencontré.
    #
    # Une variable réaffectée reste NvVal. En revanche, une
    # nouvelle variable stable calculée à partir d'elle peut
    # devenir un double C natif.
    # --------------------------------------------------------

    reassigned_names = set()

    scan_in_main = False
    scan_depth = 0

    for source_line in lines:
        if (
            not scan_in_main
            and re.match(
                r'^\s*int\s+main\s*\(',
                source_line,
            )
        ):
            scan_in_main = True

        if scan_in_main and scan_depth >= 1:
            assignment = re.match(
                r'^\s*([A-Za-z_][A-Za-z0-9_]*)'
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

    # --------------------------------------------------------
    # Déballage définitif d'un input_float() typé et stable.
    #
    # Le générateur produit :
    #
    #     NvVal a = <appel input_float>;
    #     nv_expect_type(a, "float", "a");
    #
    # input_float() garantit lui-même un NV_FLOAT. Une variable
    # non réaffectée peut donc franchir une seule fois la
    # frontière NvVal -> double :
    #
    #     NvVal __clariox_boxed_a = <appel input_float>;
    #     nv_expect_type(__clariox_boxed_a, "float", "a");
    #     double a = nv_num(__clariox_boxed_a);
    #
    # Toutes les utilisations numériques suivantes peuvent
    # alors travailler directement en C natif.
    #
    # Restriction volontaire :
    # - uniquement directement dans main();
    # - uniquement input_float();
    # - uniquement une variable jamais réaffectée.
    # --------------------------------------------------------

    promoted_input_floats = []

    promoted_lines = []

    promote_in_main = False
    promote_depth = 0

    index = 0

    while index < len(lines):
        source_line = lines[index]

        if (
            not promote_in_main
            and re.match(
                r'^\s*int\s+main\s*\(',
                source_line,
            )
        ):
            promote_in_main = True

        top_level_main = (
            promote_in_main
            and promote_depth == 1
        )

        promoted = False

        if (
            top_level_main
            and index + 1 < len(lines)
        ):
            declaration = re.match(
                r'^(\s*)NvVal\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*(.*?)\s*;\s*$',
                source_line,
            )

            if declaration:
                indent = declaration.group(1)
                name = declaration.group(2)
                rhs = declaration.group(3)

                guard_line = lines[index + 1]

                guard = re.match(
                    r'^\s*nv_expect_type\(\s*'
                    + re.escape(name)
                    + r'\s*,\s*"float"\s*,\s*'
                    r'"([^"]+)"\s*\)\s*;\s*$',
                    guard_line,
                )

                is_input_float = (
                    'nv_dispatch_call("input_float"'
                    in rhs
                )

                if (
                    guard is not None
                    and is_input_float
                    and name not in reassigned_names
                ):
                    label = guard.group(1)

                    boxed_name = (
                        "__clariox_boxed_input_float_"
                        + name
                    )

                    promoted_lines.append(
                        f"{indent}NvVal {boxed_name} = "
                        f"{rhs};\n"
                    )

                    promoted_lines.append(
                        f'{indent}nv_expect_type('
                        f'{boxed_name}, "float", '
                        f'"{label}");\n'
                    )

                    promoted_lines.append(
                        f"{indent}double {name} = "
                        f"nv_num({boxed_name});\n"
                    )

                    promoted_input_floats.append(
                        name
                    )

                    # La ligne nv_expect_type originale est
                    # absorbée par la transformation.
                    index += 2
                    promoted = True

        if not promoted:
            promoted_lines.append(
                source_line
            )

            if promote_in_main:
                promote_depth += (
                    source_line.count("{")
                    - source_line.count("}")
                )

                if promote_depth <= 0:
                    promote_in_main = False
                    promote_depth = 0

            index += 1

    lines = promoted_lines

    # La nouvelle déclaration "double a" doit être visible
    # immédiatement par les passes numériques suivantes.
    discover_native_types(lines)

    if promoted_input_floats:
        print(
            "[Clariox OPT] input_float déballés en double :"
        )

        for name in sorted(
            set(promoted_input_floats)
        ):
            print(f"  {name}")

    flow_numeric_types = {}
    flow_float_specialized = []
    flow_float_loop_rewritten = []
    flow_float_loop_unboxed = []
    flow_float_if_conditions = 0

    numeric_output = []

    flow_in_main = False
    flow_depth = 0

    # --------------------------------------------------------
    # Fusion flow-sensitive des float à travers une chaîne
    # if / else if / else située directement dans main().
    #
    # Une information de type n'est conservée après la chaîne
    # que si elle est vraie sur TOUS les chemins possibles.
    #
    # Sans else final, l'état d'entrée constitue lui aussi un
    # chemin possible.
    # --------------------------------------------------------

    def analyze_float_if_chain(
        start_index,
        entry_types,
    ):
        tracked = set(entry_types)

        if not tracked:
            return start_index, {}

        branch_exits = []
        has_else = False

        index = start_index
        chain_end = start_index

        while index < len(lines):
            header = lines[index].strip()

            is_if = (
                re.match(
                    r'^(?:if|else\s+if)\s*\(',
                    header,
                )
                is not None
            )

            is_else = (
                re.match(
                    r'^else\s*\{',
                    header,
                )
                is not None
            )

            if not is_if and not is_else:
                break

            if is_else:
                has_else = True

            state = dict(entry_types)

            depth = (
                lines[index].count("{")
                - lines[index].count("}")
            )

            if depth <= 0:
                return start_index, {}

            nested_control = False

            index += 1

            while index < len(lines) and depth > 0:
                current = lines[index]
                old_depth = depth

                opens = current.count("{")
                closes = current.count("}")

                # Un bloc imbriqué dans une branche nécessitera
                # sa propre analyse de flot. Pour cette première
                # version, abandon conservateur de cette branche.
                if old_depth > 1 or (
                    old_depth == 1
                    and opens > 0
                ):
                    nested_control = True

                # Affectations directement dans la branche.
                if old_depth == 1:
                    assignment = re.match(
                        r'^\s*'
                        r'([A-Za-z_][A-Za-z0-9_]*)'
                        r'\s*=\s*(.*?)\s*;\s*$',
                        current,
                    )

                    if assignment:
                        name = assignment.group(1)
                        rhs = assignment.group(2)

                        if name in tracked:
                            lowered = lower_flow_number(
                                rhs,
                                native_ints,
                                native_floats,
                                state,
                            )

                            if lowered is None:
                                state.pop(name, None)
                            else:
                                state[name] = lowered[1]

                depth += opens - closes
                chain_end = index
                index += 1

            if depth != 0:
                return chain_end, {}

            if nested_control:
                state = {}

            branch_exits.append(state)

            # Chercher une éventuelle branche suivante.
            look = index

            while (
                look < len(lines)
                and not lines[look].strip()
            ):
                look += 1

            if look < len(lines):
                next_line = lines[look].strip()

                if (
                    re.match(
                        r'^else\s+if\s*\(',
                        next_line,
                    )
                    or re.match(
                        r'^else\s*\{',
                        next_line,
                    )
                ):
                    index = look
                    continue

            break

        # Sans else final, aucune branche peut être exécutée.
        if not has_else:
            branch_exits.append(
                dict(entry_types)
            )

        if not branch_exits:
            return chain_end, {}

        merged = {}

        for name in tracked:
            values = [
                state.get(name)
                for state in branch_exits
            ]

            if (
                all(value is not None for value in values)
                and len(set(values)) == 1
            ):
                merged[name] = values[0]

        return chain_end, merged

    def lower_float_if_header(
        source_line,
        entry_types,
    ):
        """
        Abaisse une condition if / else if numérique en C.

        entry_types représente l'état numérique garanti à
        l'entrée commune de toute la chaîne if/elif/else.
        """

        match = re.match(
            r'^(\s*)'
            r'(if|else\s+if)'
            r'\s*\((.*)\)\s*\{\s*$',
            source_line.rstrip("\n"),
        )

        if not match:
            return source_line, False

        indent = match.group(1)
        keyword = match.group(2)
        condition = match.group(3)

        lowered = lower_flow_condition(
            condition,
            native_ints,
            native_floats,
            entry_types,
        )

        if lowered is None:
            return source_line, False

        return (
            f"{indent}{keyword} "
            f"({strip_outer(lowered)}) {{\n",
            True,
        )

    # --------------------------------------------------------
    # Analyse à point fixe des float à travers while.
    #
    # On ne conserve ici que les variables connues double à
    # l'entrée de la boucle.
    #
    # Une variable reste garantie double après le while si :
    #
    # - elle est double avant la boucle ;
    # - chacune de ses réaffectations possibles reste double ;
    # - toutes ses dépendances restent elles-mêmes valides.
    #
    # Le calcul est répété jusqu'au point fixe afin de gérer :
    #
    #     a dépend de b
    #     b cesse d'être double
    #     => a cesse aussi d'être garanti double.
    #
    # Cela reste sûr même si la boucle effectue zéro itération.
    # --------------------------------------------------------

    def analyze_float_while_invariants(
        start_index,
        entry_types,
    ):
        candidates = {
            name: typ
            for name, typ in entry_types.items()
            if typ == "double"
        }

        if not candidates:
            return start_index, {}

        first = lines[start_index]

        depth = (
            first.count("{")
            - first.count("}")
        )

        if depth <= 0:
            return start_index, {}

        body = []
        index = start_index + 1
        loop_end = start_index

        while index < len(lines) and depth > 0:
            current = lines[index]

            body.append(current)

            depth += (
                current.count("{")
                - current.count("}")
            )

            loop_end = index
            index += 1

        # C incomplet ou mal structuré :
        # abandon conservateur.
        if depth != 0:
            return loop_end, {}

        while True:
            removed = set()

            for current in body:
                assignment = re.match(
                    r'^\s*'
                    r'([A-Za-z_][A-Za-z0-9_]*)'
                    r'\s*=\s*(.*?)\s*;\s*$',
                    current,
                )

                if not assignment:
                    continue

                name = assignment.group(1)

                if name not in candidates:
                    continue

                rhs = assignment.group(2)

                lowered = lower_flow_number(
                    rhs,
                    native_ints,
                    native_floats,
                    candidates,
                )

                if (
                    lowered is None
                    or lowered[1] != "double"
                ):
                    removed.add(name)

            if not removed:
                break

            for name in removed:
                candidates.pop(name, None)

        return loop_end, candidates

    def choose_float_while_unbox(
        start_index,
        loop_end,
        invariants,
        loop_id,
    ):
        """
        Sélection conservatrice pour le déballage local.

        Tous les float invariants de la boucle sont traités
        ensemble.

        On abandonne complètement l'unboxing si l'un d'eux :

        - apparaît dans la condition du while ;
        - apparaît dans print/appel/autre instruction ;
        - apparaît dans une affectation non numérique ;
        - est utilisé par une affectation dont la cible n'est
          pas elle-même un float invariant.

        Dans ce cas l'optimisation précédente reste active.
        """

        names = {
            name
            for name, typ in invariants.items()
            if typ == "double"
        }

        if not names:
            return {}

        header = lines[start_index]

        header_uses_candidate = any(
            re.search(
                rf'\b{re.escape(name)}\b',
                header,
            )
            is not None
            for name in names
        )

        if header_uses_candidate:
            header_match = re.match(
                r'^\s*while\s*\((.*)\)\s*\{\s*$',
                header.rstrip("\n"),
            )

            if not header_match:
                return {}

            lowered_condition = lower_flow_condition(
                header_match.group(1),
                native_ints,
                native_floats,
                invariants,
            )

            # Si la condition n'est pas entièrement numérique
            # et comprise par l'optimiseur, rester conservateur.
            if lowered_condition is None:
                return {}

        index = start_index + 1

        while index <= loop_end:
            current = lines[index]

            mentioned = {
                name
                for name in names
                if re.search(
                    rf'\b{re.escape(name)}\b',
                    current,
                )
            }

            if mentioned:
                assignment = re.match(
                    r'^\s*'
                    r'([A-Za-z_][A-Za-z0-9_]*)'
                    r'\s*=\s*(.*?)\s*;\s*$',
                    current,
                )

                if assignment:
                    target = assignment.group(1)
                    rhs = assignment.group(2)

                    # Une valeur déballée ne peut alimenter
                    # que les autres valeurs déballées de la
                    # même boucle.
                    if target not in names:
                        return {}

                    lowered = lower_flow_number(
                        rhs,
                        native_ints,
                        native_floats,
                        invariants,
                    )

                    if (
                        lowered is None
                        or lowered[1] != "double"
                    ):
                        return {}

                else:
                    # ------------------------------------------------
                    # Autoriser une condition IF / ELSE IF interne si
                    # elle est entièrement numérique et abaissable.
                    # ------------------------------------------------

                    condition_match = re.match(
                        r'^\s*'
                        r'(?:if|else\s+if)'
                        r'\s*\((.*)\)\s*\{\s*$',
                        current.rstrip("\n"),
                    )

                    if condition_match:
                        lowered_condition = (
                            lower_flow_condition(
                                condition_match.group(1),
                                native_ints,
                                native_floats,
                                invariants,
                            )
                        )

                        if lowered_condition is None:
                            return {}

                    else:
                        # print(a), appel(a), return a, etc.
                        return {}

            index += 1

        result = {}

        for name in sorted(names):
            result[name] = (
                f"__clariox_loop_float_"
                f"{loop_id}_{name}"
            )

        return result

    pending_if_end = None
    pending_if_types = None
    pending_if_entry_types = None

    pending_while_end = None
    pending_while_types = None

    active_while_unbox = {}
    while_unbox_counter = 0

    # --------------------------------------------------------
    # Variables float réaffectées mais invariantes en type.
    #
    # Une variable comme :
    #
    #     total = 0.0
    #     total = total + r0
    #     total = total + r1
    #
    # peut rester un double C natif si CHAQUE réaffectation
    # linéaire est prouvée double.
    #
    # Les structures de contrôle restent volontairement des
    # barrières pour cette première version.
    # --------------------------------------------------------

    linear_native_reassigned_floats = set()

    def can_promote_linear_reassigned_float(
        start_index,
        name,
    ):
        candidate_types = {
            name: "double",
        }

        depth = 1
        saw_assignment = False
        index = start_index + 1

        while index < len(lines):
            current = lines[index]
            stripped_current = current.strip()

            # Sortie de main().
            if (
                depth == 1
                and stripped_current == "}"
            ):
                break

            # Une structure de contrôle exige une analyse de
            # flot plus complexe. Abandon conservateur.
            if (
                depth == 1
                and re.match(
                    r'^(?:if|else(?:\s+if)?|while|for|switch)\b',
                    stripped_current,
                )
            ):
                return False

            if depth == 1:
                assignment = re.match(
                    r'^\s*'
                    + re.escape(name)
                    + r'\s*=\s*(.*?)\s*;\s*$',
                    current,
                )

                if assignment:
                    rhs = assignment.group(1)

                    lowered = lower_flow_number(
                        rhs,
                        native_ints,
                        native_floats,
                        candidate_types,
                    )

                    if (
                        lowered is None
                        or lowered[1] != "double"
                    ):
                        return False

                    saw_assignment = True

            depth += (
                current.count("{")
                - current.count("}")
            )

            if depth <= 0:
                break

            index += 1

        return saw_assignment

    for flow_line_index, source_line in enumerate(lines):
        if (
            not flow_in_main
            and re.match(
                r'^\s*int\s+main\s*\(',
                source_line,
            )
        ):
            flow_in_main = True

        top_level_main = (
            flow_in_main
            and flow_depth == 1
        )

        stripped = source_line.strip()

        # ----------------------------------------------------
        # Calculs float natifs à l'intérieur d'un while.
        #
        # analyze_float_while_invariants() a déjà prouvé que
        # les variables présentes dans pending_while_types
        # restent double sur toutes leurs réaffectations.
        #
        # La variable elle-même reste NvVal si nécessaire,
        # mais son calcul peut éviter nv_add/nv_sub/nv_mul/
        # nv_div et utiliser directement les opérateurs C.
        #
        # Exemple :
        #
        #     a = nv_add(a, nv_float(1.0));
        #
        # devient :
        #
        #     a = nv_float((nv_num(a) + 1.0));
        # ----------------------------------------------------

        if (
            pending_while_end is not None
            and pending_while_types
            and flow_line_index <= pending_while_end
        ):
            loop_assignment = re.match(
                r'^(\s*)'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*(.*?)\s*;\s*$',
                source_line,
            )

            if loop_assignment:
                loop_indent = loop_assignment.group(1)
                loop_name = loop_assignment.group(2)
                loop_rhs = loop_assignment.group(3)

                if (
                    pending_while_types.get(loop_name)
                    == "double"
                ):
                    loop_lowered = lower_flow_number(
                        loop_rhs,
                        native_ints,
                        native_floats,
                        pending_while_types,
                    )

                    if (
                        loop_lowered is not None
                        and loop_lowered[1] == "double"
                    ):
                        if (
                            active_while_unbox
                            and loop_name
                            in active_while_unbox
                        ):
                            native_expr = loop_lowered[0]

                            # lower_flow_number() représente un
                            # NvVal double connu par nv_num(x).
                            # Dans cette boucle, remplacer cette
                            # lecture par le vrai double local.
                            for (
                                original_name,
                                native_name,
                            ) in active_while_unbox.items():
                                native_expr = re.sub(
                                    rf'nv_num\(\s*'
                                    rf'{re.escape(original_name)}'
                                    rf'\s*\)',
                                    native_name,
                                    native_expr,
                                )

                            source_line = (
                                f"{loop_indent}"
                                f"{active_while_unbox[loop_name]}"
                                f" = {native_expr};\n"
                            )

                            flow_float_loop_unboxed.append(
                                loop_name
                            )

                        else:
                            source_line = (
                                f"{loop_indent}{loop_name} = "
                                f"nv_float({loop_lowered[0]});\n"
                            )

                            flow_float_loop_rewritten.append(
                                loop_name
                            )

                        stripped = source_line.strip()

        # ----------------------------------------------------
        # Conditions numériques imbriquées.
        #
        # Le traitement top-level ci-dessous optimise déjà les
        # if/elif directement dans main().
        #
        # Ici on traite les conditions situées dans un bloc
        # imbriqué, notamment :
        #
        #     while (...):
        #         if (...):
        #
        # lower_flow_condition() reste conservateur :
        # un appel dynamique ou une expression inconnue
        # entraîne simplement l'abandon de cette réécriture.
        # ----------------------------------------------------

        if (
            flow_in_main
            and flow_depth >= 2
            and re.match(
                r'^(?:if|else\s+if)\s*\(',
                stripped,
            )
        ):
            nested_entry_types = {}

            if (
                pending_while_end is not None
                and pending_while_types is not None
                and flow_line_index <= pending_while_end
            ):
                nested_entry_types = (
                    pending_while_types
                )

            nested_match = re.match(
                r'^(\s*)'
                r'(if|else\s+if)'
                r'\s*\((.*)\)\s*\{\s*$',
                source_line.rstrip("\n"),
            )

            if nested_match:
                nested_condition = lower_flow_condition(
                    nested_match.group(3),
                    native_ints,
                    native_floats,
                    nested_entry_types,
                )

                if nested_condition is not None:
                    # Si la boucle possède des temporaires
                    # locaux unboxés, utiliser directement
                    # ces double à la place des NvVal.
                    for (
                        original_name,
                        native_name,
                    ) in active_while_unbox.items():
                        nested_condition = re.sub(
                            rf'nv_num\(\s*'
                            rf'{re.escape(original_name)}'
                            rf'\s*\)',
                            native_name,
                            nested_condition,
                        )

                    source_line = (
                        f"{nested_match.group(1)}"
                        f"{nested_match.group(2)} "
                        f"({strip_outer(nested_condition)}) "
                        f"{{\n"
                    )

                    stripped = source_line.strip()
                    flow_float_if_conditions += 1

        if (
            top_level_main
            and re.match(
                r'^if\s*\(',
                stripped,
            )
        ):
            # Tous les elif de cette chaîne voient le même
            # état d'entrée : si un elif est évalué, aucune
            # branche précédente n'a été exécutée.
            pending_if_entry_types = dict(
                flow_numeric_types
            )

            (
                pending_if_end,
                pending_if_types,
            ) = analyze_float_if_chain(
                flow_line_index,
                flow_numeric_types,
            )

            (
                rewritten_if,
                if_condition_lowered,
            ) = lower_float_if_header(
                source_line,
                pending_if_entry_types,
            )

            if if_condition_lowered:
                source_line = rewritten_if
                stripped = source_line.strip()
                flow_float_if_conditions += 1

            # Les faits seront restaurés uniquement à la fin
            # de la chaîne, après fusion de tous les chemins.
            flow_numeric_types.clear()

        elif (
            top_level_main
            and re.match(
                r'^else\s+if\s*\(',
                stripped,
            )
        ):
            # Un elif peut toujours être abaissé lorsqu'il
            # repose uniquement sur des variables déjà natives.
            #
            # Si l'état d'entrée de la chaîne est encore
            # disponible, il peut également fournir les faits
            # dynamiques prouvés. Sinon {} force un repli
            # conservateur sur les seuls native_ints /
            # native_floats.
            elif_entry_types = (
                pending_if_entry_types
                if pending_if_entry_types is not None
                else {}
            )

            (
                rewritten_if,
                if_condition_lowered,
            ) = lower_float_if_header(
                source_line,
                elif_entry_types,
            )

            if if_condition_lowered:
                source_line = rewritten_if
                stripped = source_line.strip()
                flow_float_if_conditions += 1

        elif (
            top_level_main
            and re.match(
                r'^while\s*\(',
                stripped,
            )
        ):
            (
                pending_while_end,
                pending_while_types,
            ) = analyze_float_while_invariants(
                flow_line_index,
                flow_numeric_types,
            )

            active_while_unbox = {}

            if pending_while_types:
                while_unbox_counter += 1

                active_while_unbox = (
                    choose_float_while_unbox(
                        flow_line_index,
                        pending_while_end,
                        pending_while_types,
                        while_unbox_counter,
                    )
                )

            if active_while_unbox:
                while_indent = re.match(
                    r'^(\s*)',
                    source_line,
                ).group(1)

                for (
                    original_name,
                    native_name,
                ) in active_while_unbox.items():
                    numeric_output.append(
                        f"{while_indent}"
                        f"double {native_name} = "
                        f"nv_num({original_name});\n"
                    )

                # --------------------------------------------
                # La condition du while peut maintenant lire
                # directement les temporaires double.
                # --------------------------------------------

                header_match = re.match(
                    r'^(\s*)while\s*\((.*)\)\s*\{\s*$',
                    source_line.rstrip("\n"),
                )

                if header_match:
                    condition = lower_flow_condition(
                        header_match.group(2),
                        native_ints,
                        native_floats,
                        pending_while_types,
                    )

                    if condition is not None:
                        for (
                            original_name,
                            native_name,
                        ) in active_while_unbox.items():
                            condition = re.sub(
                                rf'nv_num\(\s*'
                                rf'{re.escape(original_name)}'
                                rf'\s*\)',
                                native_name,
                                condition,
                            )

                        source_line = (
                            f"{header_match.group(1)}"
                            f"while "
                            f"({strip_outer(condition)}) "
                            f"{{\n"
                        )

                        stripped = source_line.strip()

            # Les faits ne seront restaurés qu'à la sortie de
            # la boucle, après validation à point fixe.
            flow_numeric_types.clear()

        elif (
            top_level_main
            and re.match(
                r'^(?:for|switch)\b',
                stripped,
            )
        ):
            # for/switch restent des barrières conservatrices.
            flow_numeric_types.clear()

        if top_level_main:
            declaration = re.match(
                r'^(\s*)NvVal\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*(.*?)\s*;\s*$',
                source_line,
            )

            if declaration:
                indent = declaration.group(1)
                name = declaration.group(2)
                rhs = declaration.group(3)

                lowered = lower_flow_number(
                    rhs,
                    native_ints,
                    native_floats,
                    flow_numeric_types,
                )

                if name.startswith("__match"):
                    lowered = None

                if lowered is None:
                    flow_numeric_types.pop(
                        name,
                        None,
                    )

                elif name in reassigned_names:
                    # Une variable réaffectée reste normalement
                    # NvVal. Exception : si elle démarre en
                    # double et que toutes ses réaffectations
                    # linéaires sont elles aussi prouvées
                    # double, elle peut rester native.
                    if (
                        lowered[1] == "double"
                        and can_promote_linear_reassigned_float(
                            flow_line_index,
                            name,
                        )
                    ):
                        source_line = (
                            f"{indent}double {name} = "
                            f"{lowered[0]};\n"
                        )

                        native_floats.add(name)

                        linear_native_reassigned_floats.add(
                            name
                        )

                        flow_numeric_types.pop(
                            name,
                            None,
                        )

                        flow_float_specialized.append(
                            name
                        )

                    else:
                        # Type connu localement, mais
                        # représentation NvVal conservée.
                        flow_numeric_types[name] = (
                            lowered[1]
                        )

                elif lowered[1] == "double":
                    source_line = (
                        f"{indent}double {name} = "
                        f"{lowered[0]};\n"
                    )

                    native_floats.add(name)

                    flow_numeric_types.pop(
                        name,
                        None,
                    )

                    flow_float_specialized.append(
                        name
                    )

                else:
                    # L'entier sera éventuellement spécialisé
                    # par la passe entière existante.
                    flow_numeric_types[name] = "int"

            else:
                assignment = re.match(
                    r'^(\s*)'
                    r'([A-Za-z_][A-Za-z0-9_]*)'
                    r'\s*=\s*(.*?)\s*;\s*$',
                    source_line,
                )

                if assignment:
                    assignment_indent = assignment.group(1)
                    name = assignment.group(2)
                    rhs = assignment.group(3)

                    if (
                        name
                        in linear_native_reassigned_floats
                    ):
                        lowered = lower_flow_number(
                            rhs,
                            native_ints,
                            native_floats,
                            flow_numeric_types,
                        )

                        # Cette propriété a déjà été prouvée
                        # par can_promote_linear_reassigned_float().
                        # Garder malgré tout une vérification
                        # conservatrice.
                        if (
                            lowered is not None
                            and lowered[1] == "double"
                        ):
                            source_line = (
                                f"{assignment_indent}"
                                f"{name} = "
                                f"{lowered[0]};\n"
                            )

                            stripped = (
                                source_line.strip()
                            )

                    elif name in flow_numeric_types:
                        lowered = lower_flow_number(
                            rhs,
                            native_ints,
                            native_floats,
                            flow_numeric_types,
                        )

                        if lowered is None:
                            flow_numeric_types.pop(
                                name,
                                None,
                            )
                        else:
                            flow_numeric_types[name] = (
                                lowered[1]
                            )

        numeric_output.append(source_line)

        if flow_in_main:
            flow_depth += (
                source_line.count("{")
                - source_line.count("}")
            )

            # Fin d'une chaîne if analysée :
            # restaurer uniquement les types garantis sur
            # tous ses chemins de sortie.
            if (
                pending_if_end is not None
                and flow_line_index == pending_if_end
            ):
                flow_numeric_types = dict(
                    pending_if_types or {}
                )

                pending_if_end = None
                pending_if_types = None
                pending_if_entry_types = None

            # Fin d'un while analysé :
            # restaurer uniquement les float garantis invariants
            # sur toutes les réaffectations possibles.
            if (
                pending_while_end is not None
                and flow_line_index == pending_while_end
            ):
                if active_while_unbox:
                    exit_indent = re.match(
                        r'^(\s*)',
                        source_line,
                    ).group(1)

                    for (
                        original_name,
                        native_name,
                    ) in active_while_unbox.items():
                        numeric_output.append(
                            f"{exit_indent}"
                            f"{original_name} = "
                            f"nv_float({native_name});\n"
                        )

                flow_numeric_types = dict(
                    pending_while_types or {}
                )

                pending_while_end = None
                pending_while_types = None
                active_while_unbox = {}

            if flow_depth <= 0:
                flow_in_main = False
                flow_depth = 0
                flow_numeric_types.clear()

                pending_if_end = None
                pending_if_types = None
                pending_if_entry_types = None

                pending_while_end = None
                pending_while_types = None

                active_while_unbox = {}

    # --------------------------------------------------------
    # Peephole : supprimer un réemballage float immédiatement
    # rendu inutile après une boucle unboxée.
    #
    # Motif :
    #
    #     a = nv_float(__clariox_loop_float_1_a);
    #     double result = nv_num(a);
    #     a = autre_valeur;
    #
    # devient :
    #
    #     double result = __clariox_loop_float_1_a;
    #     a = autre_valeur;
    #
    # On ne traverse aucun bloc de contrôle et aucun usage
    # dynamique de a.
    # --------------------------------------------------------

    def optimize_specialized_call_bridges(source_lines):
        """
        Supprime les ponts NvVal -> natif restés dans les
        arguments des spécialisations clariox_spec_* lorsque
        lower_flow_number() peut prouver l'expression numérique.

        Exemple :

            clariox_spec_f_float_to_float(
                nv_num(nv_float(5.0))
            )

        devient :

            clariox_spec_f_float_to_float(5.0)

        Cette passe ne touche pas aux wrappers NvVal entourant
        le résultat, nécessaires par exemple pour print().
        """

        helper_pattern = re.compile(
            r'clariox_spec_'
            r'[A-Za-z_][A-Za-z0-9_]*'
            r'_to_(?:int|float)\('
        )

        def find_matching_paren(source, open_index):
            depth = 0

            for index in range(
                open_index,
                len(source),
            ):
                char = source[index]

                if char == "(":
                    depth += 1

                elif char == ")":
                    depth -= 1

                    if depth == 0:
                        return index

            return None

        def simplify_argument(argument):
            argument = argument.strip()

            # Pont float :
            #
            #     nv_num(<NvVal numérique>)
            #
            float_bridge = unwrap(
                argument,
                "nv_num",
            )

            if float_bridge is not None:
                lowered = lower_flow_number(
                    float_bridge,
                    set(),
                    set(),
                    None,
                )

                if lowered is not None:
                    return lowered[0]

                return argument

            # Pont int :
            #
            #     (long long)nv_num(<NvVal numérique>)
            #
            int_bridge = re.fullmatch(
                r'\(long long\)nv_num\((.*)\)',
                argument,
            )

            if int_bridge:
                lowered = lower_flow_number(
                    int_bridge.group(1),
                    set(),
                    set(),
                    None,
                )

                if lowered is not None:
                    return (
                        f"(long long)"
                        f"({lowered[0]})"
                    )

            return argument

        optimized_lines = []

        for original_line in source_lines:
            line = original_line

            # Quelques passes suffisent aussi pour les appels
            # spécialisés éventuellement imbriqués.
            for _ in range(8):
                changed = False
                search_pos = 0

                while True:
                    match = helper_pattern.search(
                        line,
                        search_pos,
                    )

                    if match is None:
                        break

                    open_index = match.end() - 1

                    close_index = find_matching_paren(
                        line,
                        open_index,
                    )

                    if close_index is None:
                        break

                    raw_arguments = line[
                        open_index + 1:
                        close_index
                    ]

                    arguments = split_args(
                        raw_arguments
                    )

                    if not arguments:
                        search_pos = close_index + 1
                        continue

                    simplified = [
                        simplify_argument(arg)
                        for arg in arguments
                    ]

                    if simplified != [
                        arg.strip()
                        for arg in arguments
                    ]:
                        replacement = (
                            line[
                                match.start():
                                open_index + 1
                            ]
                            + ", ".join(simplified)
                            + ")"
                        )

                        line = (
                            line[:match.start()]
                            + replacement
                            + line[close_index + 1:]
                        )

                        changed = True

                        search_pos = (
                            match.start()
                            + len(replacement)
                        )

                    else:
                        search_pos = close_index + 1

                if not changed:
                    break

            optimized_lines.append(line)

        return optimized_lines


    def optimize_float_reboxes(source_lines):
        """
        Optimise la matérialisation des NvVal float après
        un while utilisant un temporaire double natif.

        Deux cas sûrs sont traités :

        1. La valeur NvVal est écrasée avant tout usage
           dynamique :
              -> supprimer complètement le réemballage.

        2. Des lectures purement numériques ont lieu avant
           un usage dynamique :
              -> utiliser directement le double natif ;
              -> retarder nv_float(...) jusqu'au premier
                 usage dynamique.

        Aucun déplacement n'est effectué à travers une
        structure de contrôle.
        """

        optimized = list(source_lines)

        eliminated = []
        delayed = []

        rebox_pattern = re.compile(
            r'^\s*'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*nv_float\('
            r'(__clariox_loop_float_'
            r'\d+_[A-Za-z_][A-Za-z0-9_]*)'
            r'\)\s*;\s*$'
        )

        index = 0

        while index < len(optimized):
            rebox_line = optimized[index]

            match = rebox_pattern.match(
                rebox_line
            )

            if not match:
                index += 1
                continue

            original_name = match.group(1)
            native_name = match.group(2)

            replacements = []
            native_reads = 0

            overwrite_index = None
            dynamic_index = None
            blocked = False

            scan = index + 1

            while scan < len(optimized):
                current = optimized[scan]
                stripped = current.strip()

                if not stripped:
                    scan += 1
                    continue

                # Ne jamais déplacer un réemballage à travers
                # une structure de contrôle.
                if (
                    stripped == "}"
                    or re.match(
                        r'^(?:if|while|for|switch|else)\b',
                        stripped,
                    )
                    or stripped.startswith("return ")
                ):
                    blocked = True
                    break

                # ------------------------------------------------
                # Réaffectation de la NvVal originale.
                # ------------------------------------------------

                overwrite = re.match(
                    rf'^(\s*)'
                    rf'{re.escape(original_name)}'
                    rf'\s*=\s*(.*?)\s*;\s*$',
                    current,
                )

                if overwrite:
                    rhs = overwrite.group(2)

                    # Si l'ancienne valeur est utilisée dans le
                    # RHS, elle doit déjà être matérialisée.
                    if re.search(
                        rf'\b'
                        rf'{re.escape(original_name)}'
                        rf'\b',
                        rhs,
                    ):
                        dynamic_index = scan
                    else:
                        overwrite_index = scan

                    break

                # ------------------------------------------------
                # Lecture native :
                #
                # double result = nv_num(a);
                #
                # devient :
                #
                # double result = __clariox_loop_float_...;
                # ------------------------------------------------

                declaration = re.match(
                    r'^(\s*)double\s+'
                    r'([A-Za-z_][A-Za-z0-9_]*)'
                    r'\s*=\s*(.*?)\s*;\s*$',
                    current,
                )

                if declaration:
                    indent = declaration.group(1)
                    target = declaration.group(2)
                    rhs = declaration.group(3)

                    contains_original = (
                        re.search(
                            rf'\b'
                            rf'{re.escape(original_name)}'
                            rf'\b',
                            rhs,
                        )
                        is not None
                    )

                    if contains_original:
                        converted_rhs, count = re.subn(
                            rf'nv_num\(\s*'
                            rf'{re.escape(original_name)}'
                            rf'\s*\)',
                            native_name,
                            rhs,
                        )

                        # Si le nom existe encore après
                        # substitution, l'expression nécessite
                        # réellement la NvVal.
                        if (
                            count == 0
                            or re.search(
                                rf'\b'
                                rf'{re.escape(original_name)}'
                                rf'\b',
                                converted_rhs,
                            )
                        ):
                            dynamic_index = scan
                            break

                        replacements.append(
                            (
                                scan,
                                f"{indent}double {target} = "
                                f"{converted_rhs};\n",
                            )
                        )

                        native_reads += count

                    scan += 1
                    continue

                # ------------------------------------------------
                # Toute autre lecture de a est considérée comme
                # dynamique.
                # ------------------------------------------------

                if re.search(
                    rf'\b'
                    rf'{re.escape(original_name)}'
                    rf'\b',
                    current,
                ):
                    dynamic_index = scan
                    break

                # Instruction indépendante de a.
                scan += 1

            # ----------------------------------------------------
            # CAS 1 :
            # a est écrasé avant tout usage dynamique.
            # Le réemballage est complètement mort.
            # ----------------------------------------------------

            if (
                not blocked
                and overwrite_index is not None
                and native_reads > 0
            ):
                optimized[index] = ""

                for (
                    line_index,
                    replacement,
                ) in replacements:
                    optimized[line_index] = replacement

                eliminated.append(
                    original_name
                )

            # ----------------------------------------------------
            # CAS 2 :
            # il existe des lectures natives avant un véritable
            # usage dynamique.
            #
            # Déplacer nv_float(...) juste avant cet usage.
            # ----------------------------------------------------

            elif (
                not blocked
                and dynamic_index is not None
                and native_reads > 0
            ):
                for (
                    line_index,
                    replacement,
                ) in replacements:
                    optimized[line_index] = replacement

                optimized[index] = ""

                optimized[dynamic_index] = (
                    rebox_line
                    + optimized[dynamic_index]
                )

                delayed.append(
                    original_name
                )

            index += 1

        return (
            optimized,
            eliminated,
            delayed,
        )

    (
        numeric_output,
        flow_float_rebox_eliminated,
        flow_float_rebox_delayed,
    ) = optimize_float_reboxes(
        numeric_output
    )

    # --------------------------------------------------------
    # Nettoyage final des réaffectations de double dans main().
    #
    # À ce stade toutes les déclarations natives créées pendant
    # cette passe sont connues :
    #
    #     double r0 = ...;
    #     double total = 0.0;
    #
    # Certaines réaffectations ont toutefois été produites plus
    # tôt sous une forme encore dynamique :
    #
    #     total =
    #         nv_num(
    #             nv_add(
    #                 nv_float(total),
    #                 nv_float(r0)
    #             )
    #         );
    #
    # Comme total et r0 sont maintenant réellement des double C,
    # cette dernière étape peut les abaisser sans ambiguïté.
    #
    # Restriction volontaire :
    # - uniquement au niveau principal de main();
    # - uniquement des variables déjà déclarées double/long long;
    # - abandon immédiat si le RHS n'est pas entièrement compris.
    # --------------------------------------------------------

    def simplify_native_int_builtin_dispatch(source_lines):
        """
        Simplifie un appel dynamique int() lorsque son argument
        a déjà été abaissé en numérique C natif.

        Avant :

            NvVal value = ({
                NvCall __c = nv_call_new();
                nv_call_add(&__c, nv_float(poly));
                NvVal __r = nv_dispatch_call(
                    "int",
                    __c.args,
                    __c.argc,
                    __c.kw
                );
                nv_call_free(&__c);
                __r;
            });

        Après :

            NvVal value =
                nv_integer_from_double((double)(poly));

        nv_integer_from_double() est volontairement conservé :
        il maintient les contrôles de finitude, de plage et la
        sémantique entière du runtime.
        """

        optimized = []
        rewritten = 0

        pattern = re.compile(
            r'^(\s*)'
            r'NvVal\s+'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*'
            r'\(\{\s*'
            r'NvCall\s+__c\s*=\s*nv_call_new\(\);\s*'
            r'nv_call_add\('
            r'&__c,\s*'
            r'nv_float\((.*?)\)'
            r'\);\s*'
            r'NvVal\s+__r\s*=\s*'
            r'nv_dispatch_call\('
            r'"int",\s*'
            r'__c\.args,\s*'
            r'__c\.argc,\s*'
            r'__c\.kw'
            r'\);\s*'
            r'nv_call_free\(&__c\);\s*'
            r'__r;\s*'
            r'\}\);\s*$'
        )

        for source_line in source_lines:
            match = pattern.match(source_line)

            if not match:
                optimized.append(source_line)
                continue

            indent = match.group(1)
            name = match.group(2)
            argument = match.group(3).strip()

            lowered = lower_flow_number(
                argument,
                native_ints,
                native_floats,
                {},
            )

            if lowered is None:
                optimized.append(source_line)
                continue

            source_line = (
                f"{indent}NvVal {name} = "
                f"nv_integer_from_double("
                f"(double)({lowered[0]}));\n"
            )

            optimized.append(source_line)
            rewritten += 1

        return optimized, rewritten


    def promote_proven_int_from_double(source_lines):
        """
        Abaisse :

            NvVal p = nv_integer_from_double((double)(x));

        en :

            long long p = (long long)(x);

        uniquement lorsque l'analyse de plage prouve que x
        reste dans une plage finie et sûre.

        La limite volontaire de +/- (2**53 - 1) est plus
        conservative que la plage int64. Elle évite toute
        ambiguïté de représentation aux frontières du double.
        """

        SAFE_FLOAT_INT = (1 << 53) - 1

        def clean_expr(expr):
            expr = expr.strip()

            previous = None

            while previous != expr:
                previous = expr

                expr = re.sub(
                    r'\(\s*(?:long long|double)\s*\)',
                    '',
                    expr,
                )

                expr = strip_outer(expr)

            return expr.strip()

        def split_binary(expr, operators):
            expr = clean_expr(expr)

            depth = 0

            for index in range(len(expr) - 1, -1, -1):
                ch = expr[index]

                if ch == ')':
                    depth += 1
                    continue

                if ch == '(':
                    depth -= 1
                    continue

                if depth != 0 or ch not in operators:
                    continue

                if ch in '+-':
                    if index == 0:
                        continue

                    previous = expr[index - 1]

                    if previous in '(,+-*/%':
                        continue

                    # signe d'exposant : 1e-3
                    if previous in 'eE':
                        continue

                return (
                    expr[:index].strip(),
                    ch,
                    expr[index + 1:].strip(),
                )

            return None

        helper_defs = {}

        current_helper = None
        helper_depth = 0

        helper_header = re.compile(
            r'^\s*static\s+'
            r'(?:__attribute__\(\(noinline\)\)\s+)?'
            r'long long\s+'
            r'(clariox_spec_[A-Za-z_][A-Za-z0-9_]*)'
            r'\s*\((.*?)\)\s*\{'
        )

        for source_line in source_lines:
            if current_helper is None:
                match = helper_header.match(source_line)

                if match:
                    helper_name = match.group(1)
                    raw_params = split_args(match.group(2))
                    params = []

                    for raw_param in raw_params:
                        words = raw_param.strip().split()

                        if words:
                            params.append(words[-1])

                    helper_defs[helper_name] = {
                        "params": params,
                        "returns": [],
                    }

                    current_helper = helper_name
                    helper_depth = (
                        source_line.count("{")
                        - source_line.count("}")
                    )

                continue

            return_match = re.search(
                r'\breturn\s+(.*?)\s*;',
                source_line,
            )

            if return_match:
                helper_defs[current_helper][
                    "returns"
                ].append(
                    return_match.group(1).strip()
                )

            helper_depth += (
                source_line.count("{")
                - source_line.count("}")
            )

            if helper_depth <= 0:
                current_helper = None
                helper_depth = 0

        def union_bounds(a, b):
            if a is None:
                return b

            if b is None:
                return a

            return (
                min(a[0], b[0]),
                max(a[1], b[1]),
            )

        def eval_range(expr, facts, stack=None):
            if stack is None:
                stack = set()

            expr = clean_expr(expr)

            literal = re.fullmatch(
                r'[-+]?'
                r'(?:'
                r'\d+(?:\.\d*)?'
                r'|\.\d+'
                r')'
                r'(?:[eE][+-]?\d+)?'
                r'(?:LL)?',
                expr,
            )

            if literal:
                raw = expr

                if raw.endswith("LL"):
                    raw = raw[:-2]

                try:
                    if (
                        "." in raw
                        or "e" in raw.lower()
                    ):
                        value = float(raw)
                    else:
                        value = int(raw)
                except ValueError:
                    return None

                return (value, value)

            if re.fullmatch(
                r'[A-Za-z_][A-Za-z0-9_]*',
                expr,
            ):
                return facts.get(expr)

            if expr.startswith("-"):
                inner = eval_range(
                    expr[1:],
                    facts,
                    stack,
                )

                if inner is None:
                    return None

                return (-inner[1], -inner[0])

            split = split_binary(expr, "+-")

            if split is not None:
                left_expr, op, right_expr = split

                left = eval_range(
                    left_expr,
                    facts,
                    stack,
                )
                right = eval_range(
                    right_expr,
                    facts,
                    stack,
                )

                if left is None or right is None:
                    return None

                if op == "+":
                    return (
                        left[0] + right[0],
                        left[1] + right[1],
                    )

                return (
                    left[0] - right[1],
                    left[1] - right[0],
                )

            split = split_binary(expr, "*/%")

            if split is not None:
                left_expr, op, right_expr = split

                left = eval_range(
                    left_expr,
                    facts,
                    stack,
                )
                right = eval_range(
                    right_expr,
                    facts,
                    stack,
                )

                if op == "%":
                    if (
                        right is None
                        or right[0] != right[1]
                    ):
                        return None

                    modulus = abs(right[0])

                    if modulus == 0:
                        return None

                    limit = modulus - 1

                    if left is None:
                        return (-limit, limit)

                    if left[0] >= 0:
                        return (0, limit)

                    if left[1] <= 0:
                        return (-limit, 0)

                    return (-limit, limit)

                if left is None or right is None:
                    return None

                if op == "*":
                    products = (
                        left[0] * right[0],
                        left[0] * right[1],
                        left[1] * right[0],
                        left[1] * right[1],
                    )

                    return (
                        min(products),
                        max(products),
                    )

                # division
                if right[0] <= 0 <= right[1]:
                    return None

                quotients = (
                    left[0] / right[0],
                    left[0] / right[1],
                    left[1] / right[0],
                    left[1] / right[1],
                )

                return (
                    min(quotients),
                    max(quotients),
                )

            call = re.fullmatch(
                r'(clariox_spec_'
                r'[A-Za-z_][A-Za-z0-9_]*)'
                r'\((.*)\)',
                expr,
            )

            if call:
                helper_name = call.group(1)

                if (
                    helper_name not in helper_defs
                    or helper_name in stack
                ):
                    return None

                info = helper_defs[helper_name]
                args = split_args(call.group(2))

                if len(args) != len(info["params"]):
                    return None

                local_facts = dict(facts)

                for param, argument in zip(
                    info["params"],
                    args,
                ):
                    local_facts[param] = eval_range(
                        argument,
                        facts,
                        stack,
                    )

                result = None
                child_stack = set(stack)
                child_stack.add(helper_name)

                for return_expr in info["returns"]:
                    bounds = eval_range(
                        return_expr,
                        local_facts,
                        child_stack,
                    )

                    if bounds is None:
                        return None

                    result = union_bounds(
                        result,
                        bounds,
                    )

                return result

            return None

        facts = {}
        unknown = set()

        declaration = re.compile(
            r'^\s*(long long|double)\s+'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.*?)\s*;\s*$'
        )

        assignment = re.compile(
            r'^\s*'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.*?)\s*;\s*$'
        )

        def record(name, bounds):
            # Les compteurs de range sont loop-carried.
            # Ne jamais déduire leur plage par un seul passage
            # linéaire.
            if name.startswith("clariox_range_"):
                facts.pop(name, None)
                unknown.add(name)
                return

            if bounds is None:
                facts.pop(name, None)
                unknown.add(name)
                return

            if name in unknown:
                return

            if name in facts:
                facts[name] = union_bounds(
                    facts[name],
                    bounds,
                )
            else:
                facts[name] = bounds

        for source_line in source_lines:
            match = declaration.match(source_line)

            if match:
                name = match.group(2)
                rhs = match.group(3)

                record(
                    name,
                    eval_range(rhs, facts),
                )
                continue

            match = assignment.match(source_line)

            if match:
                name = match.group(1)

                if (
                    name not in facts
                    and name not in unknown
                ):
                    continue

                rhs = match.group(2)

                record(
                    name,
                    eval_range(rhs, facts),
                )

        optimized = []
        promoted = []

        nv_decl = re.compile(
            r'^(\s*)NvVal\s+'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.*?)\s*;\s*$'
        )

        for source_line in source_lines:
            match = nv_decl.match(source_line)

            if not match:
                optimized.append(source_line)
                continue

            indent = match.group(1)
            name = match.group(2)
            rhs = match.group(3)

            inner = unwrap(
                rhs,
                "nv_integer_from_double",
            )

            if inner is None:
                optimized.append(source_line)
                continue

            numeric_expr = clean_expr(inner)
            bounds = eval_range(
                numeric_expr,
                facts,
            )

            if bounds is None:
                optimized.append(source_line)
                continue

            low, high = bounds

            if not (
                math.isfinite(float(low))
                and math.isfinite(float(high))
                and low >= -SAFE_FLOAT_INT
                and high <= SAFE_FLOAT_INT
            ):
                optimized.append(source_line)
                continue

            source_line = (
                f"{indent}long long {name} = "
                f"(long long)({numeric_expr});\n"
            )

            native_ints.add(name)
            promoted.append(
                (name, low, high)
            )

            optimized.append(source_line)

        return optimized, promoted


    def promote_late_int_accumulators(source_lines):
        """
        Promotion conservative d'un accumulateur NvVal entier.

        Exemple :

            NvVal subtotal = nv_int(0LL);

        peut devenir :

            long long subtotal = 0LL;

        uniquement si toutes ses réaffectations restent
        entièrement abaissables vers un entier C natif.

        Aucun type ambigu n'est promu.
        """

        declaration_re = re.compile(
            r'^(\s*)NvVal\s+'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*nv_int\(\s*'
            r'(-?\d+(?:LL)?)'
            r'\s*\)\s*;\s*$'
        )

        assignment_re = re.compile(
            r'^\s*'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.*?)\s*;\s*$'
        )

        candidates = {}

        for source_line in source_lines:
            match = declaration_re.match(source_line)

            if match:
                candidates[match.group(2)] = (
                    match.group(1),
                    match.group(3),
                )

        promoted = {}

        # Point fixe : une promotion peut en rendre
        # une autre possible.
        changed = True

        while changed:
            changed = False

            for name, declaration_info in list(
                candidates.items()
            ):
                if name in promoted:
                    continue

                trial_ints = set(native_ints)
                trial_ints.update(promoted)
                trial_ints.add(name)

                valid = True
                saw_assignment = False

                name_pattern = re.compile(
                    rf'\b{re.escape(name)}\b'
                )

                for source_line in source_lines:
                    if not name_pattern.search(source_line):
                        continue

                    declaration_match = (
                        declaration_re.match(source_line)
                    )

                    if (
                        declaration_match
                        and declaration_match.group(2) == name
                    ):
                        continue

                    assignment_match = (
                        assignment_re.match(source_line)
                    )

                    if assignment_match:
                        target = assignment_match.group(1)
                        rhs = assignment_match.group(2)

                        lowered = lower_flow_number(
                            rhs,
                            trial_ints,
                            native_floats,
                            {},
                        )

                        if target == name:
                            saw_assignment = True

                            if (
                                lowered is None
                                or lowered[1] != "int"
                            ):
                                valid = False
                                break

                            continue

                        # Usage de l'accumulateur dans une autre
                        # variable : accepter uniquement si cette
                        # cible est elle-même déjà entière native
                        # et si tout le RHS est abaissable.
                        if target in trial_ints:
                            if (
                                lowered is None
                                or lowered[1] != "int"
                            ):
                                valid = False
                                break

                            continue

                    # Condition numérique entièrement comprise.
                    condition_match = re.match(
                        r'^\s*(?:if|while)\s*'
                        r'\((.*)\)\s*\{\s*$',
                        source_line,
                    )

                    if condition_match:
                        lowered_condition = (
                            lower_flow_condition(
                                condition_match.group(1),
                                trial_ints,
                                native_floats,
                                {},
                            )
                        )

                        if lowered_condition is not None:
                            continue

                    # Toute autre utilisation peut exiger un NvVal.
                    valid = False
                    break

                if valid and saw_assignment:
                    promoted[name] = declaration_info
                    native_ints.add(name)
                    changed = True

        if not promoted:
            return source_lines, []

        optimized = []

        for source_line in source_lines:
            match = declaration_re.match(source_line)

            if (
                match
                and match.group(2) in promoted
            ):
                indent = match.group(1)
                name = match.group(2)
                literal = match.group(3)

                source_line = (
                    f"{indent}long long {name} = "
                    f"{literal};\n"
                )

            optimized.append(source_line)

        return optimized, sorted(promoted)


    def cleanup_all_native_int_assignments(source_lines):
        """
        Termine l'abaissement des variables déjà devenues
        long long, y compris dans les while/if imbriqués.

        Exemple :

            subtotal =
                nv_add(
                    nv_add(subtotal, p),
                    nv_mod(nv_int(value), nv_int(97LL))
                );

        devient :

            subtotal =
                (subtotal + p) + (value % 97LL);

        Cette passe ne crée aucun nouveau type natif :
        elle ne travaille que sur des variables déjà déclarées
        long long dans le C produit.
        """

        known_ints = set(native_ints)
        known_floats = set(native_floats)

        # Repartir du C réellement produit : certaines variables
        # peuvent avoir été rendues natives par une passe tardive.
        for source_line in source_lines:
            int_decl = re.match(
                r'^\s*long long\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)\b',
                source_line,
            )

            if int_decl:
                known_ints.add(
                    int_decl.group(1)
                )

            float_decl = re.match(
                r'^\s*double\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)\b',
                source_line,
            )

            if float_decl:
                known_floats.add(
                    float_decl.group(1)
                )

        optimized = []
        rewritten = []

        in_main = False
        depth = 0

        int_declaration = re.compile(
            r'^(\s*)long long\s+'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.*?)\s*;\s*$'
        )

        assignment = re.compile(
            r'^(\s*)'
            r'([A-Za-z_][A-Za-z0-9_]*)'
            r'\s*=\s*(.*?)\s*;\s*$'
        )

        for source_line in source_lines:
            if (
                not in_main
                and re.match(
                    r'^\s*int\s+main\s*\(',
                    source_line,
                )
            ):
                in_main = True

            if in_main and depth >= 1:
                declaration_match = (
                    int_declaration.match(source_line)
                )

                if declaration_match:
                    indent = declaration_match.group(1)
                    name = declaration_match.group(2)
                    rhs = declaration_match.group(3)

                    lowered = lower_flow_number(
                        rhs,
                        known_ints,
                        known_floats,
                        {},
                    )

                    if (
                        lowered is not None
                        and lowered[1] == "int"
                    ):
                        source_line = (
                            f"{indent}long long {name} = "
                            f"(long long)({lowered[0]});\n"
                        )

                        rewritten.append(name)

                else:
                    assignment_match = (
                        assignment.match(source_line)
                    )

                    if assignment_match:
                        indent = assignment_match.group(1)
                        name = assignment_match.group(2)
                        rhs = assignment_match.group(3)

                        if name in known_ints:
                            lowered = lower_flow_number(
                                rhs,
                                known_ints,
                                known_floats,
                                {},
                            )

                            if (
                                lowered is not None
                                and lowered[1] == "int"
                            ):
                                source_line = (
                                    f"{indent}{name} = "
                                    f"(long long)"
                                    f"({lowered[0]});\n"
                                )

                                rewritten.append(name)

            optimized.append(source_line)

            if in_main:
                depth += (
                    source_line.count("{")
                    - source_line.count("}")
                )

                if depth <= 0:
                    in_main = False
                    depth = 0

        return optimized, rewritten


    def cleanup_native_main_assignments(source_lines):
        optimized = []
        rewritten_floats = []

        in_main = False
        depth = 0

        main_native_floats = set()
        main_native_ints = set()

        for source_line in source_lines:
            if (
                not in_main
                and re.match(
                    r'^\s*int\s+main\s*\(',
                    source_line,
                )
            ):
                in_main = True

            top_level_main = (
                in_main
                and depth == 1
            )

            if top_level_main:
                float_decl = re.match(
                    r'^\s*double\s+'
                    r'([A-Za-z_][A-Za-z0-9_]*)\b',
                    source_line,
                )

                if float_decl:
                    main_native_floats.add(
                        float_decl.group(1)
                    )

                int_decl = re.match(
                    r'^\s*long long\s+'
                    r'([A-Za-z_][A-Za-z0-9_]*)\b',
                    source_line,
                )

                if int_decl:
                    main_native_ints.add(
                        int_decl.group(1)
                    )

                assignment = re.match(
                    r'^(\s*)'
                    r'([A-Za-z_][A-Za-z0-9_]*)'
                    r'\s*=\s*(.*?)\s*;\s*$',
                    source_line,
                )

                if assignment:
                    indent = assignment.group(1)
                    name = assignment.group(2)
                    rhs = assignment.group(3)

                    if name in main_native_floats:
                        lowered = lower_flow_number(
                            rhs,
                            main_native_ints,
                            main_native_floats,
                            {},
                        )

                        if (
                            lowered is not None
                            and lowered[1] == "double"
                        ):
                            source_line = (
                                f"{indent}{name} = "
                                f"{lowered[0]};\n"
                            )

                            rewritten_floats.append(
                                name
                            )

            optimized.append(source_line)

            if in_main:
                depth += (
                    source_line.count("{")
                    - source_line.count("}")
                )

                if depth <= 0:
                    in_main = False
                    depth = 0

                    main_native_floats.clear()
                    main_native_ints.clear()

        return optimized, rewritten_floats

    (
        numeric_output,
        native_int_builtin_dispatches,
    ) = simplify_native_int_builtin_dispatch(
        numeric_output
    )

    if native_int_builtin_dispatches:
        print(
            "[Clariox OPT] Dispatch int(float) directs : "
            f"{native_int_builtin_dispatches}"
        )

    (
        numeric_output,
        proven_native_int_casts,
    ) = promote_proven_int_from_double(
        numeric_output
    )

    if proven_native_int_casts:
        print(
            "[Clariox OPT] int(float) natifs avec "
            "preuve de plage :"
        )

        for name, low, high in proven_native_int_casts:
            print(
                f"  {name}: [{low}, {high}]"
            )

    (
        numeric_output,
        late_native_int_accumulators,
    ) = promote_late_int_accumulators(
        numeric_output
    )

    if late_native_int_accumulators:
        print(
            "[Clariox OPT] Accumulateurs int natifs tardifs :"
        )

        for name in late_native_int_accumulators:
            print(f"  {name} -> int")

    (
        numeric_output,
        final_native_float_assignments,
    ) = cleanup_native_main_assignments(
        numeric_output
    )

    if final_native_float_assignments:
        print(
            "[Clariox OPT] Réaffectations double "
            "finales simplifiées : "
            f"{len(final_native_float_assignments)}"
        )

    (
        numeric_output,
        final_native_int_assignments,
    ) = cleanup_all_native_int_assignments(
        numeric_output
    )

    if final_native_int_assignments:
        print(
            "[Clariox OPT] Affectations int natives "
            "finales simplifiées : "
            f"{len(final_native_int_assignments)}"
        )

    numeric_output = optimize_specialized_call_bridges(
        numeric_output
    )

    lines = numeric_output

    if flow_float_rebox_eliminated:
        print(
            "[Clariox OPT] Réemballages float éliminés :"
        )

        for name in sorted(
            set(flow_float_rebox_eliminated)
        ):
            print(f"  {name}")

    if flow_float_rebox_delayed:
        print(
            "[Clariox OPT] Réemballages float retardés :"
        )

        for name in sorted(
            set(flow_float_rebox_delayed)
        ):
            print(f"  {name}")

    if flow_float_if_conditions:
        print(
            "[Clariox OPT] Conditions float natives "
            "dans if/elif : "
            f"{flow_float_if_conditions}"
        )

    if flow_float_specialized:
        print(
            "[Clariox OPT] Floats flow-sensitive :"
        )

        for name in sorted(
            set(flow_float_specialized)
        ):
            print(f"  {name}")

    if flow_float_loop_rewritten:
        print(
            "[Clariox OPT] Calculs float natifs dans while :"
        )

        for name in sorted(
            set(flow_float_loop_rewritten)
        ):
            print(f"  {name}")

    if flow_float_loop_unboxed:
        print(
            "[Clariox OPT] Float loop-local unboxing :"
        )

        for name in sorted(
            set(flow_float_loop_unboxed)
        ):
            print(f"  {name}")

    # --------------------------------------------------------
    # Détection des variables numériques instables.
    #
    # Une variable Clariox non typée peut légalement changer
    # de type :
    #
    #     value = 26
    #     value = "Alice"
    #
    # Elle ne doit donc jamais être abaissée en long long.
    #
    # On détermine d'abord les variables qui pourraient être
    # des entiers natifs, puis on vérifie toutes leurs
    # réaffectations avant de modifier le C.
    # --------------------------------------------------------

    # Les variables déjà natives ont été validées par
    # optimise_numeriques_c.py. Cette passe ne doit pas
    # remettre en cause cette décision.
    already_native_ints = set(native_ints)

    candidate_ints = set(native_ints)

    candidate_changed = True

    while candidate_changed:
        candidate_changed = False

        for line in lines:
            m = re.match(
                r'^\s*NvVal\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*(.*?)\s*;\s*$',
                line
            )

            if not m:
                continue

            name = m.group(1)
            rhs = m.group(2)

            if name.startswith("__match"):
                continue

            lowered = lower(rhs, candidate_ints)

            if (
                lowered is not None
                and lowered[1] == "int"
                and name not in candidate_ints
            ):
                candidate_ints.add(name)
                candidate_changed = True

    unsafe_ints = set()

    # La propagation des variables instables doit elle aussi
    # atteindre un point fixe.
    #
    # Exemple :
    #
    #     a = 1
    #     b = a
    #
    #     a = "bad"
    #     b = a
    #
    # Le premier passage découvre que a est instable.
    # Le passage suivant doit alors découvrir que b dépend
    # d'une valeur qui n'est plus garantie entière.
    unsafe_changed = True

    while unsafe_changed:
        unsafe_changed = False

        safe_candidates = (
            set(candidate_ints)
            - set(unsafe_ints)
        )

        for line in lines:
            # Affectation simple, sans déclaration.
            m = re.match(
                r'^\s*([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*(.*?)\s*;\s*$',
                line
            )

            if not m:
                continue

            name = m.group(1)
            rhs = m.group(2)

            if name not in candidate_ints:
                continue

            # Déjà spécialisé par l'optimiseur numérique
            # principal : conserver sa décision.
            if name in already_native_ints:
                continue

            lowered = lower(
                rhs,
                safe_candidates,
            )

            if (
                lowered is None
                or lowered[1] != "int"
            ):
                if name not in unsafe_ints:
                    unsafe_ints.add(name)
                    unsafe_changed = True

    if unsafe_ints:
        print(
            "[Clariox OPT] Variables dynamiques "
            "conservées :"
        )

        for name in sorted(unsafe_ints):
            print(f"  {name}")

    changed = True

    # Première phase :
    # spécialisation numérique sensible au flot.
    #
    # Une chaîne if / else if / else possède :
    #
    # - un état d'entrée commun ;
    # - un état de sortie pour chaque branche ;
    # - éventuellement un chemin implicite si aucun else
    #   final n'existe.
    #
    # Après la chaîne, seules les variables connues entières
    # sur TOUS les chemins restent connues entières.
    while changed:
        changed = False
        new_output = []
        known = set(native_ints)

        flow_dynamic_ints = set()

        # État de la branche actuellement analysée.
        branch_dynamic_ints = None
        branch_depth = None

        # État global d'une chaîne if / elif / else.
        chain_entry_ints = None
        chain_branch_exits = []
        chain_has_else = False
        chain_pending_close = False

        # Etat de la boucle while actuellement analysee.
        loop_dynamic_ints = None
        loop_depth = None

        in_main = False
        main_depth = 0

        def merge_chain():
            nonlocal chain_entry_ints
            nonlocal chain_branch_exits
            nonlocal chain_has_else
            nonlocal chain_pending_close
            nonlocal flow_dynamic_ints

            if chain_entry_ints is None:
                return

            exits = [
                set(values)
                for values in chain_branch_exits
            ]

            # Sans else final, la condition peut être fausse
            # pour toutes les branches : l'état d'entrée est
            # donc lui-même un chemin de sortie possible.
            if not chain_has_else:
                exits.append(set(chain_entry_ints))

            if exits:
                merged = set(exits[0])

                for values in exits[1:]:
                    merged.intersection_update(values)
            else:
                merged = set()

            flow_dynamic_ints = merged

            chain_entry_ints = None
            chain_branch_exits = []
            chain_has_else = False
            chain_pending_close = False

        def analyze_while_int_invariants(
            start_index,
            entry_ints,
        ):
            """
            Calcule les variables dynamiques garanties entières
            pendant toute une boucle while.

            On part des faits connus à l'entrée, puis on retire
            toute variable ayant au moins une réaffectation qui
            ne peut pas être prouvée entière.

            Le calcul est répété jusqu'au point fixe afin de
            propager les dépendances :

                a dépend de b
                b cesse d'être entier
                => a cesse aussi d'être garanti entier.
            """

            candidates = set(entry_ints)

            if not candidates:
                return set()

            first = lines[start_index]

            depth = (
                first.count("{")
                - first.count("}")
            )

            if depth <= 0:
                return set()

            body = []
            index = start_index + 1

            while index < len(lines) and depth > 0:
                current = lines[index]

                body.append(current)

                depth += (
                    current.count("{")
                    - current.count("}")
                )

                index += 1

            # C mal structuré ou boucle non terminée :
            # abandon conservateur.
            if depth != 0:
                return set()

            while True:
                removed = set()

                for current in body:
                    assignment = re.match(
                        r'^\s*'
                        r'([A-Za-z_][A-Za-z0-9_]*)'
                        r'\s*=\s*(.*?)\s*;\s*$',
                        current
                    )

                    if not assignment:
                        continue

                    name = assignment.group(1)

                    if name not in candidates:
                        continue

                    rhs = assignment.group(2)

                    lowered = lower(
                        rhs,
                        known,
                        candidates,
                    )

                    if (
                        lowered is None
                        or lowered[1] != "int"
                    ):
                        removed.add(name)

                if not removed:
                    break

                candidates.difference_update(removed)

            return candidates

        for line_index, line in enumerate(lines):
            if (
                not in_main
                and re.match(
                    r'^\s*int\s+main\s*\(',
                    line
                )
            ):
                in_main = True

            stripped = line.strip()

            # ------------------------------------------------
            # Une branche précédente vient de se fermer.
            #
            # Le C généré place généralement :
            #
            #     }
            #     else if (...) {
            #
            # sur deux lignes distinctes.
            #
            # On attend donc la ligne suivante avant de savoir
            # si la chaîne continue ou si elle est terminée.
            # ------------------------------------------------
            continuing_chain = False

            if (
                chain_pending_close
                and stripped
            ):
                is_else_if = (
                    re.match(
                        r'^else\s+if\s*\(',
                        stripped
                    )
                    is not None
                )

                is_else = (
                    re.match(
                        r'^else\s*\{',
                        stripped
                    )
                    is not None
                )

                if is_else_if or is_else:
                    chain_pending_close = False

                    branch_dynamic_ints = set(
                        chain_entry_ints
                        if chain_entry_ints is not None
                        else ()
                    )

                    continuing_chain = True

                    if is_else:
                        chain_has_else = True

                else:
                    # Première instruction située après toute
                    # la chaîne : fusionner avant de l'analyser.
                    merge_chain()

            top_level_main = (
                in_main
                and main_depth == 1
            )

            in_branch = (
                in_main
                and branch_dynamic_ints is not None
                and branch_depth is not None
                and main_depth == branch_depth
            )

            in_loop = (
                in_main
                and loop_dynamic_ints is not None
                and loop_depth is not None
                and main_depth >= loop_depth
            )

            if continuing_chain:
                flow_context = branch_dynamic_ints

            elif in_loop:
                flow_context = loop_dynamic_ints

            elif in_branch:
                flow_context = branch_dynamic_ints

            elif top_level_main:
                flow_context = flow_dynamic_ints

            else:
                flow_context = None

            # Nouveau if directement dans main().
            entering_if_chain = (
                top_level_main
                and chain_entry_ints is None
                and re.match(
                    r'^if\s*\(',
                    stripped
                ) is not None
            )

            # Boucle while directement dans main().
            #
            # Tant que l'analyse à point fixe des boucles
            # n'est pas appliquée, un while constitue une
            # barrière de flot : les faits connus avant la
            # boucle peuvent être utilisés pour sa condition,
            # mais ne doivent pas être supposés vrais après.
            entering_while = (
                top_level_main
                and re.match(
                    r'^while\s*\(',
                    stripped
                ) is not None
            )

            # --------------------------------------------
            # NvVal x = expression;
            # --------------------------------------------
            declaration = re.match(
                r'^(\s*)NvVal\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*(.*?)\s*;\s*$',
                line
            )

            # Cette spécialisation flow-sensitive concerne
            # uniquement main().
            #
            # Les fonctions génériques Clariox retournent NvVal.
            # Transformer un temporaire local comme :
            #
            #     NvVal __ret3 = nv_int(1LL);
            #
            # en :
            #
            #     long long __ret3 = 1LL;
            #
            # rendrait ensuite :
            #
            #     return __ret3;
            #
            # invalide dans une fonction retournant NvVal.
            #
            # Les fonctions spécialisées sont déjà optimisées
            # par optimise_fonctions_c.py avant cette passe.
            if declaration and in_main:
                indent, name, rhs = (
                    declaration.group(1),
                    declaration.group(2),
                    declaration.group(3),
                )

                lowered = lower(
                    rhs,
                    known,
                    flow_context,
                )

                if name.startswith("__match"):
                    pass

                # Variable globalement instable :
                # garder NvVal, mais suivre son type local.
                elif name in unsafe_ints:
                    if flow_context is not None:
                        if (
                            lowered is not None
                            and lowered[1] == "int"
                        ):
                            flow_context.add(name)
                        else:
                            flow_context.discard(name)

                # Variable stable :
                # abaissement en entier C natif.
                elif (
                    lowered is not None
                    and lowered[1] == "int"
                ):
                    line = (
                        f"{indent}long long {name} = "
                        f"{lowered[0]};\n"
                    )

                    known.add(name)
                    native_ints.add(name)

                    if flow_context is not None:
                        flow_context.discard(name)

                    changed = True

            # --------------------------------------------
            # Réaffectation simple.
            # --------------------------------------------
            if flow_context is not None:
                assignment = re.match(
                    r'^\s*([A-Za-z_][A-Za-z0-9_]*)'
                    r'\s*=\s*(.*?)\s*;\s*$',
                    line
                )

                if assignment:
                    name = assignment.group(1)
                    rhs = assignment.group(2)

                    if (
                        name in unsafe_ints
                        or name in flow_context
                    ):
                        reassigned = lower(
                            rhs,
                            known,
                            flow_context,
                        )

                        if (
                            reassigned is not None
                            and reassigned[1] == "int"
                        ):
                            flow_context.add(name)
                        else:
                            flow_context.discard(name)

            # --------------------------------------------
            # Conditions numériques.
            # --------------------------------------------
            def truth_callback(inner):
                lowered = lower(
                    inner,
                    known,
                    flow_context,
                )

                if lowered is None:
                    return None

                if lowered[1] in ("bool", "int"):
                    return strip_outer(lowered[0])

                return None

            new_line = replace_balanced(
                line,
                "nv_truth",
                truth_callback
            )

            new_line = simplify_control_condition(
                new_line
            )

            if new_line != line:
                changed = True

            new_output.append(new_line)

            # --------------------------------------------
            # Mise à jour de la profondeur C.
            # --------------------------------------------
            if in_main:
                opens = new_line.count("{")
                closes = new_line.count("}")

                old_depth = main_depth
                main_depth += opens - closes

                # Premier if de la chaîne.
                if (
                    entering_if_chain
                    and old_depth == 1
                    and main_depth == 2
                ):
                    chain_entry_ints = set(
                        flow_dynamic_ints
                    )

                    chain_branch_exits = []
                    chain_has_else = False
                    chain_pending_close = False

                    branch_dynamic_ints = set(
                        chain_entry_ints
                    )
                    branch_depth = 2

                    # L'état principal sera restauré par
                    # merge_chain() à la fin de la chaîne.
                    flow_dynamic_ints.clear()

                # Entrée dans un while directement sous main.
                #
                # Calculer le sous-ensemble des faits d'entrée
                # qui reste garanti entier sur toutes les
                # réaffectations possibles de la boucle.
                elif (
                    entering_while
                    and old_depth == 1
                    and main_depth == 2
                ):
                    loop_dynamic_ints = (
                        analyze_while_int_invariants(
                            line_index,
                            flow_dynamic_ints,
                        )
                    )

                    loop_depth = 2

                    # L'état principal sera restauré à la sortie
                    # avec uniquement les invariants prouvés.
                    flow_dynamic_ints.clear()

                # Nouvelle branche else / else if.
                elif (
                    continuing_chain
                    and old_depth == 1
                    and main_depth == 2
                ):
                    branch_depth = 2

                # Bloc imbriqué dans une branche :
                # abandon conservateur des faits locaux.
                if (
                    branch_dynamic_ints is not None
                    and branch_depth is not None
                    and old_depth == branch_depth
                    and main_depth > branch_depth
                ):
                    branch_dynamic_ints.clear()

                if (
                    branch_dynamic_ints is not None
                    and branch_depth is not None
                    and old_depth > branch_depth
                    and main_depth == branch_depth
                ):
                    branch_dynamic_ints.clear()

                # Fin d'une branche de la chaîne.
                if (
                    chain_entry_ints is not None
                    and branch_depth is not None
                    and old_depth == branch_depth
                    and main_depth == 1
                ):
                    chain_branch_exits.append(
                        set(
                            branch_dynamic_ints
                            if branch_dynamic_ints is not None
                            else ()
                        )
                    )

                    branch_dynamic_ints = None
                    branch_depth = None

                    # Ne pas fusionner immédiatement :
                    # la prochaine ligne peut être else/elif.
                    chain_pending_close = True

                # Sortie d'un while vers main().
                #
                # Une variable présente dans loop_dynamic_ints
                # était entière à l'entrée ET toutes ses
                # réaffectations possibles restent entières.
                #
                # Elle est donc également sûre sur une sortie
                # normale, un break ou après zéro itération.
                if (
                    loop_dynamic_ints is not None
                    and loop_depth is not None
                    and old_depth == loop_depth
                    and main_depth == 1
                ):
                    flow_dynamic_ints = set(
                        loop_dynamic_ints
                    )

                    loop_dynamic_ints = None
                    loop_depth = None

                # Sortie de main().
                if main_depth <= 0 and old_depth > 0:
                    if chain_pending_close:
                        merge_chain()

                    in_main = False
                    main_depth = 0

                    branch_dynamic_ints = None
                    branch_depth = None

                    loop_dynamic_ints = None
                    loop_depth = None

                    flow_dynamic_ints.clear()

        # Cas où une chaîne termine juste avant EOF.
        if chain_pending_close:
            merge_chain()

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
        # { NvVal __match1 = couleur;
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
        # NvVal __match1 = couleur;
        #
        # devient :
        # NvVal __match1 = clariox_string_box(couleur);
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

        # ----------------------------------------------------
        # Comparaisons et opérateurs logiques du runtime.
        #
        # Ils attendent eux aussi des NvVal.
        #
        # Ceci est notamment indispensable lorsqu'une variable
        # a été spécialisée en double/int natif mais qu'une
        # condition complète doit rester dynamique.
        # ----------------------------------------------------

        for predicate_fn in (
            "nv_eq",
            "nv_ne",
            "nv_lt",
            "nv_le",
            "nv_gt",
            "nv_ge",
            "nv_and",
            "nv_or",
        ):
            def predicate_binary_callback(
                inner,
                fn=predicate_fn,
            ):
                args = split_args(inner)

                if len(args) != 2:
                    return None

                changed = False

                for index in (0, 1):
                    boxed = box_native(
                        args[index]
                    )

                    if boxed is not None:
                        args[index] = boxed
                        changed = True

                if not changed:
                    return None

                return (
                    f"{fn}("
                    f"{args[0]}, "
                    f"{args[1]}"
                    f")"
                )

            line = replace_balanced(
                line,
                predicate_fn,
                predicate_binary_callback
            )

        # nv_not(...) et nv_truth(...) possèdent un seul
        # opérande NvVal.
        for predicate_fn in (
            "nv_not",
            "nv_truth",
        ):
            def predicate_unary_callback(
                inner,
                fn=predicate_fn,
            ):
                args = split_args(inner)

                if len(args) != 1:
                    return None

                boxed = box_native(
                    args[0]
                )

                if boxed is None:
                    return None

                return (
                    f"{fn}({boxed})"
                )

            line = replace_balanced(
                line,
                predicate_fn,
                predicate_unary_callback
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
