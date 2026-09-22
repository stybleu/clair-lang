#!/usr/bin/env python3

import re
import sys


HELPERS = r'''
typedef struct {
    long long *data;
    long long len;
    long long cap;
} ClairIntList;

static ClairIntList clair_int_list_make(
    const long long *src,
    long long len
) {
    ClairIntList l;

    l.len = len;
    l.cap = len > 4 ? len : 4;
    l.data = nv_xmalloc(sizeof(long long) * l.cap);

    for (long long i = 0; i < len; ++i) {
        l.data[i] = src[i];
    }

    return l;
}

static void clair_int_list_append(
    ClairIntList *l,
    long long value
) {
    if (l->len >= l->cap) {
        l->cap = l->cap ? l->cap * 2 : 4;

        long long *p = realloc(
            l->data,
            sizeof(long long) * l->cap
        );

        if (!p) {
            nv_throw("Mémoire insuffisante");
        }

        l->data = p;
    }

    l->data[l->len++] = value;
}

static long long clair_int_list_get(
    ClairIntList *l,
    long long index
) {
    if (index < 0) {
        index = l->len + index;
    }

    if (index < 0 || index >= l->len) {
        nv_throw("Indice de liste hors limites");
    }

    return l->data[index];
}

static NvVal clair_int_list_box(
    const ClairIntList *l
) {
    NvVal v = nv_list_new();

    for (long long i = 0; i < l->len; ++i) {
        nv_list_append(v, nv_int(l->data[i]));
    }

    return v;
}
'''


def discover_lists(lines):
    result = {}

    pattern = re.compile(
        r'^\s*NvVal\s+([A-Za-z_][A-Za-z0-9_]*)'
        r'\s*=\s*\(\{\s*NvVal __l = nv_list_new\(\);'
        r'(.*?)'
        r'__l;\s*\}\);\s*$'
    )

    for index, line in enumerate(lines):
        m = pattern.match(line)

        if not m:
            continue

        name = m.group(1)
        body = m.group(2)

        all_appends = re.findall(
            r'nv_list_append\(__l,\s*(.*?)\);',
            body
        )

        int_appends = re.findall(
            r'nv_list_append\(__l,\s*nv_int\((.*?)\)\);',
            body
        )

        if not all_appends:
            continue

        # Seulement une liste 100 % entière.
        if len(all_appends) != len(int_appends):
            continue

        result[name] = {
            "line": index,
            "items": int_appends,
        }

    return result


def is_safe(name, declaration_line, lines):
    word = re.compile(rf'\b{re.escape(name)}\b')

    for index, line in enumerate(lines):
        if index == declaration_line:
            continue

        if not word.search(line):
            continue

        # Lecture par index.
        if f"nv_get_index({name}," in line:
            converted_line = replace_indexes(line, name)

            if f"nv_get_index({name}," in converted_line:
                return False

            continue

        # Ajout entier.
        if (
            f'nv_dispatch_method({name}, "ajoute"' in line
        ):
            args = re.findall(
                r'nv_call_add\(&__c,\s*(.*?)\);',
                line
            )

            if len(args) != 1:
                return False

            if not args[0].strip().startswith("nv_int("):
                return False

            continue

        # longueur(liste)
        if (
            'nv_dispatch_call("longueur"' in line
            and f"nv_call_add(&__c, {name})" in line
        ):
            continue

        # ecris(..., liste)
        if (
            'nv_dispatch_call("ecris"' in line
            and f"nv_call_add(&__c, {name})" in line
        ):
            continue

        # Toute autre utilisation reste dynamique.
        return False

    return True


def replace_length(line, name):
    pattern = re.compile(
        r'\(\{\s*'
        r'NvCall __c = nv_call_new\(\);\s*'
        rf'nv_call_add\(&__c,\s*{re.escape(name)}\);\s*'
        r'NvVal __r = nv_dispatch_call\('
        r'"longueur",\s*'
        r'__c\.args,\s*__c\.argc,\s*__c\.kw'
        r'\);\s*'
        r'nv_call_free\(&__c\);\s*'
        r'__r;\s*'
        r'\}\)'
    )

    return pattern.sub(
        f'nv_int((long long){name}.len)',
        line
    )


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

                if depth == 0 and i != len(expr) - 1:
                    wraps = False
                    break

        if not wraps or depth != 0:
            break

        expr = expr[1:-1].strip()

    return expr


def split_top_args(text):
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


def convert_index_expr(expr):
    expr = strip_outer_parens(expr)

    # Variable native future : i, index, etc.
    if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', expr):
        return expr

    # Littéral entier.
    if re.fullmatch(r'-?\d+(?:LL)?', expr):
        return expr

    inner = unwrap(expr, "nv_int")
    if inner is not None:
        return convert_index_expr(inner)

    inner = unwrap(expr, "nv_float")
    if inner is not None:
        value = convert_index_expr(inner)

        if value is not None:
            return f"((double)({value}))"

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

        args = split_top_args(inner)

        if len(args) != 2:
            return None

        a = convert_index_expr(args[0])
        b = convert_index_expr(args[1])

        if a is None or b is None:
            return None

        return f"(({a}) {op} ({b}))"

    inner = unwrap(expr, "nv_mod")
    if inner is not None:
        args = split_top_args(inner)

        if len(args) != 2:
            return None

        a = convert_index_expr(args[0])
        b = convert_index_expr(args[1])

        if a is None or b is None:
            return None

        return (
            f"((long long)({a}) % "
            f"(long long)({b}))"
        )

    inner = unwrap(expr, "nv_div")
    if inner is not None:
        args = split_top_args(inner)

        if len(args) != 2:
            return None

        a = convert_index_expr(args[0])
        b = convert_index_expr(args[1])

        if a is None or b is None:
            return None

        return (
            f"((double)({a}) / "
            f"(double)({b}))"
        )

    inner = unwrap(expr, "nv_neg")
    if inner is not None:
        value = convert_index_expr(inner)

        if value is not None:
            return f"(-({value}))"

    return None


def replace_indexes(line, name):
    marker = f"nv_get_index({name},"
    pos = 0

    while True:
        start = line.find(marker, pos)

        if start < 0:
            break

        open_pos = line.find("(", start)
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
        args = split_top_args(inner)

        if len(args) != 2 or args[0].strip() != name:
            pos = end + 1
            continue

        native_index = convert_index_expr(args[1])

        if native_index is None:
            pos = end + 1
            continue

        replacement = (
            f"nv_int(clair_int_list_get("
            f"&{name}, "
            f"(long long)({native_index})))"
        )

        line = (
            line[:start]
            + replacement
            + line[end + 1:]
        )

        pos = start + len(replacement)

    return line


def replace_append(line, name):
    if f'nv_dispatch_method({name}, "ajoute"' not in line:
        return None

    m = re.search(
        r'nv_call_add\(&__c,\s*nv_int\((.*?)\)\);',
        line
    )

    if not m:
        return None

    indent = re.match(r'^(\s*)', line).group(1)
    value = m.group(1)

    return (
        f'{indent}clair_int_list_append('
        f'&{name}, (long long)({value}));\n'
    )


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: optimise_listes_c.py "
            "entree.c sortie.c"
        )
        sys.exit(2)

    source, destination = sys.argv[1], sys.argv[2]

    with open(source, "r", encoding="utf-8") as f:
        lines = f.readlines()

    candidates = discover_lists(lines)

    native = {}

    for name, info in candidates.items():
        if is_safe(name, info["line"], lines):
            native[name] = info

    if native:
        print("[Clariox OPT] Listes entières natives :")

        for name in sorted(native):
            print(f"  {name}")
    else:
        print(
            "[Clariox OPT] Aucune liste entière "
            "spécialisable"
        )

    output = []

    helpers_inserted = False

    for index, line in enumerate(lines):
        # Injecte le runtime spécialisé juste après l'include.
        if (
            not helpers_inserted
            and native
            and line.startswith('#include "clair_runtime.h"')
        ):
            output.append(line)
            output.append(HELPERS)
            output.append("\n")
            helpers_inserted = True
            continue

        declaration_done = False

        for name, info in native.items():
            if index == info["line"]:
                values = ", ".join(info["items"])

                output.append(
                    f'ClairIntList {name} = '
                    f'clair_int_list_make('
                    f'(long long[]){{{values}}}, '
                    f'{len(info["items"])}LL);\n'
                )

                declaration_done = True
                break

        if declaration_done:
            continue

        new_line = line

        for name in native:
            append_line = replace_append(new_line, name)

            if append_line is not None:
                new_line = append_line
                break

            new_line = replace_length(new_line, name)
            new_line = replace_indexes(new_line, name)

            # Passage vers ecris() : box uniquement à la frontière.
            new_line = re.sub(
                rf'nv_call_add\(&__c,\s*'
                rf'{re.escape(name)}\)',
                f'nv_call_add(&__c, '
                f'clair_int_list_box(&{name}))',
                new_line
            )

        output.append(new_line)

    with open(destination, "w", encoding="utf-8") as f:
        f.writelines(output)

    print(
        "[Clariox OPT] Optimisation listes : "
        f"{destination}"
    )


if __name__ == "__main__":
    main()
