#!/usr/bin/env python3

import re
import sys


HELPERS = r'''
#include <string.h>

typedef struct ClairStringStorage {
    long long refs;
    char data[];
} ClairStringStorage;

typedef struct {
    const char *data;
    long long len;
    ClairStringStorage *storage;
} ClairString;


static ClairString clair_string_literal(const char *s)
{
    ClairString r;
    r.data = s;
    r.len = (long long)strlen(s);
    r.storage = NULL;
    return r;
}


static ClairString clair_string_concat_many(
    const ClairString *parts,
    long long count
) {
    long long total = 0;

    for (long long i = 0; i < count; ++i) {
        total += parts[i].len;
    }

    ClairStringStorage *storage = nv_xmalloc(
        sizeof(ClairStringStorage)
        + (size_t)total
        + 1
    );

    storage->refs = 1;

    char *buffer = storage->data;

    long long pos = 0;

    for (long long i = 0; i < count; ++i) {
        if (parts[i].len > 0) {
            memcpy(
                buffer + pos,
                parts[i].data,
                (size_t)parts[i].len
            );

            pos += parts[i].len;
        }
    }

    buffer[total] = '\0';

    ClairString r;
    r.data = buffer;
    r.len = total;
    r.storage = storage;

    return r;
}


static int clair_string_eq(
    ClairString a,
    ClairString b
) {
    if (a.len != b.len) {
        return 0;
    }

    if (a.len == 0) {
        return 1;
    }

    return memcmp(
        a.data,
        b.data,
        (size_t)a.len
    ) == 0;
}


static ClairString clair_string_char(
    ClairString s,
    long long index
) {
    if (index < 0) {
        index = s.len + index;
    }

    if (index < 0 || index >= s.len) {
        nv_throw("Indice de chaîne hors limites");
    }

    ClairString r;

    r.data = s.data + index;
    r.len = 1;
    r.storage = NULL;

    return r;
}


static ClairString clair_string_copy(
    ClairString s
) {
    if (s.storage) {
        s.storage->refs++;
    }

    return s;
}


static void clair_string_release(
    ClairString *s
) {
    if (!s) {
        return;
    }

    if (s->storage) {
        s->storage->refs--;

        if (s->storage->refs == 0) {
            free(s->storage);
        }
    }

    s->data = "";
    s->len = 0;
    s->storage = NULL;
}


/*
 * L'expression src est évaluée avant l'appel.
 * C'est donc sûr pour :
 *
 *     texte = texte + "x"
 *
 * La concaténation lit d'abord l'ancien texte,
 * puis seulement l'ancien stockage est libéré.
 */
static void clair_string_assign_move(
    ClairString *dst,
    ClairString src
) {
    clair_string_release(dst);
    *dst = src;
}


static NvVal clair_string_box(
    ClairString s
) {
    char *buffer = nv_xmalloc(
        (size_t)s.len + 1
    );

    if (s.len > 0) {
        memcpy(
            buffer,
            s.data,
            (size_t)s.len
        );
    }

    buffer[s.len] = '\0';

    /*
     * On laisse volontairement le buffer vivant.
     * Cela reste sûr même si nv_str conserve le pointeur.
     * La gestion de propriété sera traitée plus tard.
     */
    return nv_str(buffer);
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
    in_string = False
    escaped = False

    for ch in text:

        if in_string:
            current.append(ch)

            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False

            continue

        if ch == '"':
            in_string = True
            current.append(ch)
            continue

        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1

        if ch == "," and depth == 0:
            args.append(
                "".join(current).strip()
            )
            current = []
        else:
            current.append(ch)

    args.append(
        "".join(current).strip()
    )

    return args


def unwrap(expr, name):
    expr = strip_outer_parens(expr)

    prefix = name + "("

    if not expr.startswith(prefix):
        return None

    if not expr.endswith(")"):
        return None

    return expr[len(prefix):-1]


def literal_code(expr):
    expr = strip_outer_parens(expr)

    m = re.fullmatch(
        r'nv_str\(("(?:\\.|[^"\\])*")\)',
        expr
    )

    if not m:
        return None

    return (
        f"clair_string_literal({m.group(1)})"
    )


def string_terms(expr, native):
    expr = strip_outer_parens(expr)

    if re.fullmatch(
        r'[A-Za-z_][A-Za-z0-9_]*',
        expr
    ):
        if expr in native:
            return [expr]

        return None

    literal = literal_code(expr)

    if literal is not None:
        return [literal]

    inner = unwrap(expr, "nv_add")

    if inner is not None:
        args = split_top_args(inner)

        if len(args) != 2:
            return None

        left = string_terms(
            args[0],
            native
        )

        right = string_terms(
            args[1],
            native
        )

        if left is None or right is None:
            return None

        return left + right

    return None


def string_code(expr, native):
    terms = string_terms(
        expr,
        native
    )

    if terms is None:
        return None

    if len(terms) == 1:
        return terms[0]

    return (
        "clair_string_concat_many("
        "(ClairString[]){"
        + ", ".join(terms)
        + "}, "
        + str(len(terms))
        + "LL)"
    )


def discover_strings(lines):
    native = {}

    changed = True

    while changed:
        changed = False

        for index, line in enumerate(lines):
            m = re.match(
                r'^(\s*)NvVal\s+'
                r'([A-Za-z_][A-Za-z0-9_]*)'
                r'\s*=\s*(.*?)\s*;\s*$',
                line
            )

            if not m:
                continue

            name = m.group(2)

            if name in native:
                continue

            rhs = m.group(3)

            code = string_code(
                rhs,
                native
            )

            if code is None:
                continue

            native[name] = {
                "line": index,
                "code": code,
            }

            changed = True

    return native


def replace_balanced_calls(
    line,
    function_name,
    callback
):
    marker = function_name + "("
    pos = 0

    while True:
        start = line.find(
            marker,
            pos
        )

        if start < 0:
            break

        open_pos = start + len(function_name)

        depth = 0
        in_string = False
        escaped = False
        end = None

        for i in range(open_pos, len(line)):
            ch = line[i]

            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False

                continue

            if ch == '"':
                in_string = True
                continue

            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1

                if depth == 0:
                    end = i
                    break

        if end is None:
            break

        inner = line[
            open_pos + 1:end
        ]

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


def replace_index_calls(line, native):

    def callback(inner):
        args = split_top_args(inner)

        if len(args) != 2:
            return None

        string = string_code(
            args[0],
            native
        )

        if string is None:
            return None

        index = strip_outer_parens(
            args[1]
        )

        m = re.fullmatch(
            r'nv_int\((.*?)\)',
            index
        )

        if m:
            index = m.group(1)

        elif re.fullmatch(
            r'[A-Za-z_][A-Za-z0-9_]*',
            index
        ):
            pass

        else:
            return None

        return (
            "clair_string_box("
            "clair_string_char("
            f"{string}, "
            f"(long long)({index})"
            "))"
        )

    return replace_balanced_calls(
        line,
        "nv_get_index",
        callback
    )


def replace_eq_calls(line, native):

    def callback(inner):
        args = split_top_args(inner)

        if len(args) != 2:
            return None

        a = string_code(
            args[0],
            native
        )

        b = string_code(
            args[1],
            native
        )

        if a is None or b is None:
            return None

        return (
            "nv_bool(clair_string_eq("
            f"{a}, {b}"
            "))"
        )

    return replace_balanced_calls(
        line,
        "nv_eq",
        callback
    )


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: optimise_chaines_c.py "
            "entree.c sortie.c"
        )
        sys.exit(2)

    source = sys.argv[1]
    destination = sys.argv[2]

    with open(
        source,
        "r",
        encoding="utf-8"
    ) as f:
        lines = f.readlines()

    native = discover_strings(lines)

    if native:
        print(
            "[Clair OPT] Chaînes natives :"
        )

        for name in native:
            print(f"  {name}")

    else:
        print(
            "[Clair OPT] Aucune chaîne "
            "spécialisable"
        )

    main_start = None
    main_end = None

    for i, line in enumerate(lines):
        if "int main(void){" in line:
            main_start = i
            break

    if main_start is not None:
        for i in range(main_start + 1, len(lines)):
            if re.match(r'^\s*return 0;\s*$', lines[i]):
                main_end = i
                break

    main_strings = []

    if main_start is not None and main_end is not None:
        for name, info in native.items():
            if main_start < info["line"] < main_end:
                main_strings.append(name)

    output = []
    helpers_inserted = False

    for index, line in enumerate(lines):

        if (
            native
            and not helpers_inserted
            and line.startswith(
                '#include "clair_runtime.h"'
            )
        ):
            output.append(line)
            output.append(HELPERS)
            output.append("\n")

            helpers_inserted = True
            continue

        declaration = None

        for name, info in native.items():
            if info["line"] == index:
                code = info["code"]

                if (
                    re.fullmatch(
                        r'[A-Za-z_][A-Za-z0-9_]*',
                        code
                    )
                    and code in native
                ):
                    code = (
                        f"clair_string_copy({code})"
                    )

                declaration = (
                    f"ClairString {name} = "
                    f"{code};\n"
                )
                break

        if declaration is not None:
            output.append(declaration)
            continue

        new_line = line

        # Réaffectation d'une chaîne déjà native.
        #
        # Exemple :
        #     texte = texte + "x"
        #
        # On calcule d'abord la nouvelle valeur puis
        # clair_string_assign_move() libère l'ancienne.
        for name in native:
            m_assign = re.match(
                rf'^(\s*){re.escape(name)}'
                rf'\s*=\s*(.*?)\s*;\s*$',
                new_line
            )

            if not m_assign:
                continue

            rhs = m_assign.group(2)
            native_rhs = string_code(
                rhs,
                native
            )

            if native_rhs is None:
                continue

            if (
                re.fullmatch(
                    r'[A-Za-z_][A-Za-z0-9_]*',
                    native_rhs
                )
                and native_rhs in native
            ):
                native_rhs = (
                    f"clair_string_copy({native_rhs})"
                )

            indent = m_assign.group(1)

            new_line = (
                f"{indent}clair_string_assign_move("
                f"&{name}, {native_rhs});\n"
            )

            break

        for name in native:
            new_line = replace_length(
                new_line,
                name
            )

        new_line = replace_index_calls(
            new_line,
            native
        )

        new_line = replace_eq_calls(
            new_line,
            native
        )

        # Passage d'une chaîne native vers
        # une fonction dynamique comme ecris().
        for name in native:
            new_line = re.sub(
                rf'nv_call_add\(&__c,\s*'
                rf'{re.escape(name)}\)',
                (
                    'nv_call_add(&__c, '
                    f'clair_string_box({name}))'
                ),
                new_line
            )

        if (
            main_end is not None
            and index == main_end
            and main_strings
        ):
            for string_name in reversed(main_strings):
                output.append(
                    f"    clair_string_release("
                    f"&{string_name});\n"
                )

        output.append(new_line)

    with open(
        destination,
        "w",
        encoding="utf-8"
    ) as f:
        f.writelines(output)

    print(
        "[Clair OPT] C chaînes optimisé : "
        f"{destination}"
    )


if __name__ == "__main__":
    main()
