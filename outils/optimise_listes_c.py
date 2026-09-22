#!/usr/bin/env python3

import re
import sys


HELPERS = r'''
typedef struct {
    long long *data;
    long long len;
    long long cap;
} ClairIntList;

typedef struct {
    double *data;
    long long len;
    long long cap;
} ClairDoubleList;


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


static ClairDoubleList clair_double_list_make(
    const double *src,
    long long len
) {
    ClairDoubleList l;

    l.len = len;
    l.cap = len > 4 ? len : 4;
    l.data = nv_xmalloc(sizeof(double) * l.cap);

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


static void clair_double_list_append(
    ClairDoubleList *l,
    double value
) {
    if (l->len >= l->cap) {
        l->cap = l->cap ? l->cap * 2 : 4;

        double *p = realloc(
            l->data,
            sizeof(double) * l->cap
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


static double clair_double_list_get(
    ClairDoubleList *l,
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


static NvVal clair_double_list_box(
    const ClairDoubleList *l
) {
    NvVal v = nv_list_new();

    for (long long i = 0; i < l->len; ++i) {
        nv_list_append(v, nv_float(l->data[i]));
    }

    return v;
}
'''


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

    if re.fullmatch(
        r'[A-Za-z_][A-Za-z0-9_]*',
        expr
    ):
        return expr

    if re.fullmatch(r'-?\d+(?:LL)?', expr):
        return expr

    inner = unwrap(expr, "nv_int")

    if inner is not None:
        return convert_index_expr(inner)

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

    inner = unwrap(expr, "nv_neg")

    if inner is not None:
        value = convert_index_expr(inner)

        if value is not None:
            return f"(-({value}))"

    return None


def numeric_value(expr):
    expr = expr.strip()

    inner = unwrap(expr, "nv_int")

    if inner is not None:
        return "int", inner.strip()

    inner = unwrap(expr, "nv_float")

    if inner is not None:
        return "double", inner.strip()

    return None


def discover_lists(lines):
    result = {}

    pattern = re.compile(
        r'^\s*NvVal\s+'
        r'([A-Za-z_][A-Za-z0-9_]*)'
        r'\s*=\s*\(\{\s*'
        r'NvVal __l = nv_list_new\(\);'
        r'(.*?)'
        r'__l;\s*\}\);\s*$'
    )

    for index, line in enumerate(lines):
        m = pattern.match(line)

        if not m:
            continue

        name = m.group(1)
        body = m.group(2)

        appends = re.findall(
            r'nv_list_append\(__l,\s*(.*?)\);',
            body
        )

        if not appends:
            continue

        values = []
        has_double = False
        valid = True

        for expr in appends:
            parsed = numeric_value(expr)

            if parsed is None:
                valid = False
                break

            typ, value = parsed

            if typ == "double":
                has_double = True

            values.append((typ, value))

        if not valid:
            continue

        list_type = (
            "double"
            if has_double
            else "int"
        )

        result[name] = {
            "line": index,
            "items": values,
            "type": list_type,
        }

    return result


def replace_indexes(line, name, list_type):
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

        if len(args) != 2:
            pos = end + 1
            continue

        if args[0].strip() != name:
            pos = end + 1
            continue

        native_index = convert_index_expr(args[1])

        if native_index is None:
            pos = end + 1
            continue

        if list_type == "int":
            replacement = (
                f"nv_int(clair_int_list_get("
                f"&{name}, "
                f"(long long)({native_index})))"
            )

        else:
            replacement = (
                f"nv_float(clair_double_list_get("
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


def append_value(line):
    matches = re.findall(
        r'nv_call_add\(&__c,\s*(.*?)\);',
        line
    )

    if len(matches) != 1:
        return None

    return numeric_value(matches[0])


def is_safe(name, info, lines):
    word = re.compile(
        rf'\b{re.escape(name)}\b'
    )

    for index, line in enumerate(lines):
        if index == info["line"]:
            continue

        if not word.search(line):
            continue

        if f"nv_get_index({name}," in line:
            converted = replace_indexes(
                line,
                name,
                info["type"]
            )

            if f"nv_get_index({name}," in converted:
                return False

            continue

        if (
            f'nv_dispatch_method({name}, "ajoute"'
            in line
        ):
            value = append_value(line)

            if value is None:
                return False

            typ, _ = value

            if info["type"] == "int":
                if typ != "int":
                    return False

            else:
                if typ not in ("int", "double"):
                    return False

            continue

        if (
            'nv_dispatch_call("longueur"' in line
            and f"nv_call_add(&__c, {name})"
            in line
        ):
            continue

        if (
            'nv_dispatch_call("ecris"' in line
            and f"nv_call_add(&__c, {name})"
            in line
        ):
            continue

        return False

    return True


def replace_length(line, name):
    pattern = re.compile(
        r'\(\{\s*'
        r'NvCall __c = nv_call_new\(\);\s*'
        rf'nv_call_add\(&__c,\s*'
        rf'{re.escape(name)}\);\s*'
        r'NvVal __r = nv_dispatch_call\('
        r'"longueur",\s*'
        r'__c\.args,\s*'
        r'__c\.argc,\s*'
        r'__c\.kw'
        r'\);\s*'
        r'nv_call_free\(&__c\);\s*'
        r'__r;\s*'
        r'\}\)'
    )

    return pattern.sub(
        f'nv_int((long long){name}.len)',
        line
    )


def replace_append(line, name, list_type):
    if (
        f'nv_dispatch_method({name}, "ajoute"'
        not in line
    ):
        return None

    value = append_value(line)

    if value is None:
        return None

    typ, expr = value

    indent = re.match(
        r'^(\s*)',
        line
    ).group(1)

    if list_type == "int":
        return (
            f'{indent}clair_int_list_append('
            f'&{name}, '
            f'(long long)({expr}));\n'
        )

    return (
        f'{indent}clair_double_list_append('
        f'&{name}, '
        f'(double)({expr}));\n'
    )


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: optimise_listes_c.py "
            "entree.c sortie.c"
        )

        sys.exit(2)

    source, destination = sys.argv[1], sys.argv[2]

    with open(
        source,
        "r",
        encoding="utf-8"
    ) as f:
        lines = f.readlines()

    candidates = discover_lists(lines)

    native = {}

    for name, info in candidates.items():
        if is_safe(name, info, lines):
            native[name] = info

    if native:
        print("[Clariox OPT] Listes numériques natives :")

        for name in sorted(native):
            typ = native[name]["type"]

            print(
                f"  {name} -> "
                f"{'entier' if typ == 'int' else 'decimal'}"
            )

    else:
        print(
            "[Clariox OPT] Aucune liste numérique "
            "spécialisable"
        )

    output = []
    helpers_inserted = False

    for index, line in enumerate(lines):

        if (
            not helpers_inserted
            and native
            and line.startswith(
                '#include "clair_runtime.h"'
            )
        ):
            output.append(line)
            output.append(HELPERS)
            output.append("\n")

            helpers_inserted = True
            continue

        declaration_done = False

        for name, info in native.items():
            if index != info["line"]:
                continue

            if info["type"] == "int":
                values = ", ".join(
                    value
                    for _, value in info["items"]
                )

                output.append(
                    f'ClairIntList {name} = '
                    f'clair_int_list_make('
                    f'(long long[]){{{values}}}, '
                    f'{len(info["items"])}LL);\n'
                )

            else:
                values = []

                for typ, value in info["items"]:
                    if typ == "int":
                        values.append(
                            f'(double)({value})'
                        )
                    else:
                        values.append(value)

                output.append(
                    f'ClairDoubleList {name} = '
                    f'clair_double_list_make('
                    f'(double[]){{'
                    f'{", ".join(values)}'
                    f'}}, '
                    f'{len(info["items"])}LL);\n'
                )

            declaration_done = True
            break

        if declaration_done:
            continue

        new_line = line

        for name, info in native.items():

            append_line = replace_append(
                new_line,
                name,
                info["type"]
            )

            if append_line is not None:
                new_line = append_line
                break

            new_line = replace_length(
                new_line,
                name
            )

            new_line = replace_indexes(
                new_line,
                name,
                info["type"]
            )

            if info["type"] == "int":
                boxing = (
                    f'clair_int_list_box(&{name})'
                )

            else:
                boxing = (
                    f'clair_double_list_box(&{name})'
                )

            new_line = re.sub(
                rf'nv_call_add\(&__c,\s*'
                rf'{re.escape(name)}\)',
                f'nv_call_add(&__c, {boxing})',
                new_line
            )

        output.append(new_line)

    with open(
        destination,
        "w",
        encoding="utf-8"
    ) as f:
        f.writelines(output)

    print(
        "[Clariox OPT] Optimisation listes : "
        f"{destination}"
    )


if __name__ == "__main__":
    main()
