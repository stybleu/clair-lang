#!/usr/bin/env python3

import re
import sys


HELPERS = r'''
#include <string.h>

typedef struct ClarioxStringStorage {
    long long refs;
    long long cap;
    char data[];
} ClarioxStringStorage;

typedef struct {
    const char *data;
    long long len;
    ClarioxStringStorage *storage;
} ClarioxString;


static ClarioxString clariox_string_literal(const char *s)
{
    ClarioxString r;
    r.data = s;
    r.len = (long long)strlen(s);
    r.storage = NULL;
    return r;
}


static ClarioxString clariox_string_concat_many(
    const ClarioxString *parts,
    long long count
) {
    long long total = 0;

    for (long long i = 0; i < count; ++i) {
        total += parts[i].len;
    }

    ClarioxStringStorage *storage = nv_xmalloc(
        sizeof(ClarioxStringStorage)
        + (size_t)total
        + 1
    );

    storage->refs = 1;
    storage->cap = total;

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

    ClarioxString r;
    r.data = buffer;
    r.len = total;
    r.storage = storage;

    return r;
}


static int clariox_string_eq(
    ClarioxString a,
    ClarioxString b
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


static ClarioxString clariox_string_char(
    ClarioxString s,
    long long index
) {
    if (index < 0) {
        index = s.len + index;
    }

    if (index < 0 || index >= s.len) {
        nv_throw("Indice de chaîne hors limites");
    }

    ClarioxString r;

    r.data = s.data + index;
    r.len = 1;
    r.storage = NULL;

    return r;
}


static ClarioxString clariox_string_copy(
    ClarioxString s
) {
    if (s.storage) {
        s.storage->refs++;
    }

    return s;
}


static void clariox_string_release(
    ClarioxString *s
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
static void clariox_string_assign_concat_many(
    ClarioxString *dst,
    const ClarioxString *parts,
    long long count
) {
    long long total = 0;
    int aliases_dst = 0;

    for (long long i = 0; i < count; ++i) {
        total += parts[i].len;

        if (
            dst->storage
            && parts[i].storage == dst->storage
        ) {
            aliases_dst = 1;
        }
    }

    ClarioxStringStorage *target = NULL;
    int reused = 0;

    /*
     * Cas idéal :
     * le buffer appartient uniquement à dst et aucune
     * partie de la concaténation ne dépend de celui-ci.
     */
    if (
        dst->storage
        && dst->storage->refs == 1
        && !aliases_dst
    ) {
        target = dst->storage;

        if (target->cap < total) {
            long long new_cap = target->cap;

            if (new_cap < 16) {
                new_cap = 16;
            }

            while (new_cap < total) {
                new_cap *= 2;
            }

            ClarioxStringStorage *p = realloc(
                target,
                sizeof(ClarioxStringStorage)
                + (size_t)new_cap
                + 1
            );

            if (!p) {
                nv_throw("Mémoire insuffisante");
            }

            target = p;
            target->cap = new_cap;
        }

        reused = 1;
    }
    else {
        long long cap = total;

        if (cap < 16) {
            cap = 16;
        }

        target = nv_xmalloc(
            sizeof(ClarioxStringStorage)
            + (size_t)cap
            + 1
        );

        target->refs = 1;
        target->cap = cap;
    }

    long long pos = 0;

    for (long long i = 0; i < count; ++i) {
        if (parts[i].len > 0) {
            memcpy(
                target->data + pos,
                parts[i].data,
                (size_t)parts[i].len
            );

            pos += parts[i].len;
        }
    }

    target->data[total] = '\0';

    /*
     * Si on a créé un nouveau stockage, l'ancien peut
     * maintenant être relâché. On le fait après les copies
     * pour préserver les éventuelles sources aliasées.
     */
    if (!reused) {
        clariox_string_release(dst);
    }

    dst->storage = target;
    dst->data = target->data;
    dst->len = total;
}


static void clariox_string_append_char(
    ClarioxString *dst,
    ClarioxString ch
) {
    if (ch.len != 1) {
        nv_throw(
            "Un caractère était attendu"
        );
    }

    /*
     * Lire le caractère avant une éventuelle
     * réallocation. Cela reste sûr même pour :
     *
     *     texte = texte + texte[i]
     */
    char value = ch.data[0];

    long long old_len = dst->len;
    long long needed = old_len + 1;

    /*
     * Cas rapide : buffer propriétaire avec
     * suffisamment de capacité.
     */
    if (
        dst->storage
        && dst->storage->refs == 1
        && dst->storage->cap >= needed
    ) {
        dst->storage->data[old_len] = value;
        dst->storage->data[needed] = '\0';

        dst->data = dst->storage->data;
        dst->len = needed;

        return;
    }

    /*
     * Croissance géométrique :
     *
     * 16, 32, 64, 128...
     *
     * On évite ainsi de recopier toute la chaîne
     * à chaque caractère ajouté.
     */
    long long cap = 16;

    if (
        dst->storage
        && dst->storage->cap > cap
    ) {
        cap = dst->storage->cap;
    }

    while (cap < needed) {
        long long next = cap * 2;

        if (next <= cap) {
            cap = needed;
            break;
        }

        cap = next;
    }

    ClarioxStringStorage *storage = nv_xmalloc(
        sizeof(ClarioxStringStorage)
        + (size_t)cap
        + 1
    );

    storage->refs = 1;
    storage->cap = cap;

    if (old_len > 0) {
        memcpy(
            storage->data,
            dst->data,
            (size_t)old_len
        );
    }

    storage->data[old_len] = value;
    storage->data[needed] = '\0';

    clariox_string_release(dst);

    dst->storage = storage;
    dst->data = storage->data;
    dst->len = needed;
}


static void clariox_string_assign_char(
    ClarioxString *dst,
    ClarioxString src,
    long long index
) {
    if (index < 0) {
        index = src.len + index;
    }

    if (index < 0 || index >= src.len) {
        nv_throw("Indice de chaîne hors limites");
    }

    /*
     * Lire le caractère AVANT toute modification de dst.
     * Cela rend également sûr :
     *
     *     texte = texte[i]
     */
    char ch = src.data[index];

    /*
     * Réutiliser le buffer existant lorsqu'il appartient
     * exclusivement à dst.
     */
    if (
        dst->storage
        && dst->storage->refs == 1
        && dst->storage->cap >= 1
    ) {
        dst->storage->data[0] = ch;
        dst->storage->data[1] = '\0';

        dst->data = dst->storage->data;
        dst->len = 1;

        return;
    }

    /*
     * Premier passage ou stockage partagé :
     * créer un minuscule buffer propriétaire.
     *
     * Les affectations suivantes pourront le réutiliser.
     */
    clariox_string_release(dst);

    ClarioxStringStorage *storage = nv_xmalloc(
        sizeof(ClarioxStringStorage) + 2
    );

    storage->refs = 1;
    storage->cap = 1;
    storage->data[0] = ch;
    storage->data[1] = '\0';

    dst->storage = storage;
    dst->data = storage->data;
    dst->len = 1;
}


static void clariox_string_assign_move(
    ClarioxString *dst,
    ClarioxString src
) {
    clariox_string_release(dst);
    *dst = src;
}


static NvVal clariox_string_box(
    ClarioxString s
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

    NvVal boxed = nv_str(buffer);
    free(buffer);
    return boxed;
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
        f"clariox_string_literal({m.group(1)})"
    )


def native_index_code(expr):
    """
    Abaisse une expression entière utilisée comme indice
    vers une expression C native.

    Exemples :

        i
        3
        -1
        nv_int(5)
        nv_neg(nv_int(1))
        nv_mod(i, nv_int(source.len))
    """
    expr = strip_outer_parens(expr)

    if re.fullmatch(
        r'-?\d+(?:LL)?',
        expr
    ):
        return expr

    if re.fullmatch(
        r'[A-Za-z_][A-Za-z0-9_]*',
        expr
    ):
        return expr

    if re.fullmatch(
        r'[A-Za-z_][A-Za-z0-9_]*\.len',
        expr
    ):
        return expr

    # Cast C déjà présent.
    m = re.fullmatch(
        r'\(long long\)\s*(.+)',
        expr,
        re.S
    )

    if m:
        return native_index_code(
            m.group(1)
        )

    inner = unwrap(
        expr,
        "nv_int"
    )

    if inner is not None:
        return native_index_code(inner)

    inner = unwrap(
        expr,
        "nv_neg"
    )

    if inner is not None:
        value = native_index_code(inner)

        if value is None:
            return None

        return f"(-({value}))"

    binary = {
        "nv_add": "+",
        "nv_sub": "-",
        "nv_mul": "*",
        "nv_mod": "%",
    }

    for function_name, operator in binary.items():
        inner = unwrap(
            expr,
            function_name
        )

        if inner is None:
            continue

        args = split_top_args(inner)

        if len(args) != 2:
            return None

        left = native_index_code(args[0])
        right = native_index_code(args[1])

        if left is None or right is None:
            return None

        if operator == "%":
            return (
                f"((long long)({left}) % "
                f"(long long)({right}))"
            )

        return (
            f"(({left}) {operator} ({right}))"
        )

    return None


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

    # Indexation d'une chaîne native.
    index_inner = unwrap(
        expr,
        "nv_get_index"
    )

    if index_inner is not None:
        args = split_top_args(index_inner)

        if len(args) != 2:
            return None

        source = string_code(
            args[0],
            native
        )

        if source is None:
            return None

        index = native_index_code(
            args[1]
        )

        if index is None:
            return None

        return [
            "clariox_string_char("
            f"{source}, "
            f"(long long)({index})"
            ")"
        ]

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
        "clariox_string_concat_many("
        "(ClarioxString[]){"
        + ", ".join(terms)
        + "}, "
        + str(len(terms))
        + "LL)"
    )


def c_brace_delta(line):
    """Compte les accolades C en ignorant chaînes et caractères."""
    scrubbed = re.sub(
        r'"(?:\\.|[^"\\])*"',
        '""',
        line,
    )
    scrubbed = re.sub(
        r"'(?:\\.|[^'\\])*'",
        "''",
        scrubbed,
    )
    scrubbed = re.sub(r'//.*$', '', scrubbed)
    return scrubbed.count("{") - scrubbed.count("}")


def discover_direct_nvval_return_declarations(lines):
    """
    Repere les declarations NvVal locales qui sont retournees
    directement par une fonction C retournant NvVal.

    Ces valeurs doivent rester boxees en NvVal. Les convertir en
    ClarioxString ferait produire un `return` avec un type C
    incompatible et demanderait en plus une gestion de duree de
    vie specifique avant chaque sortie de fonction.
    """
    excluded = set()
    index = 0

    function_header = re.compile(
        r'^\s*static\s+NvVal\s+'
        r'[A-Za-z_][A-Za-z0-9_]*\s*\('
    )

    declaration = re.compile(
        r'^\s*NvVal\s+'
        r'([A-Za-z_][A-Za-z0-9_]*)'
        r'\s*=.*;\s*$'
    )

    direct_return = re.compile(
        r'^\s*return\s+'
        r'([A-Za-z_][A-Za-z0-9_]*)'
        r'\s*;\s*$'
    )

    while index < len(lines):
        line = lines[index]

        if not function_header.match(line):
            index += 1
            continue

        depth = c_brace_delta(line)

        # Les helpers compacts sur une seule ligne n'ont aucun
        # local a analyser ici.
        if depth <= 0:
            index += 1
            continue

        start = index + 1
        cursor = start

        while cursor < len(lines) and depth > 0:
            depth += c_brace_delta(lines[cursor])

            if depth == 0:
                break

            cursor += 1

        end = cursor
        returned_names = set()

        for body_index in range(start, end):
            match = direct_return.match(lines[body_index])

            if match:
                returned_names.add(match.group(1))

        if returned_names:
            for body_index in range(start, end):
                match = declaration.match(lines[body_index])

                if (
                    match
                    and match.group(1) in returned_names
                ):
                    excluded.add(body_index)

        index = max(end + 1, index + 1)

    return excluded


def discover_strings(lines):
    native = {}
    returned_nvval_declarations = (
        discover_direct_nvval_return_declarations(lines)
    )

    changed = True

    while changed:
        changed = False

        for index, line in enumerate(lines):
            if index in returned_nvval_declarations:
                continue

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
        r'"len",\s*'
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


def native_string_index(expr, native):
    expr = strip_outer_parens(expr)

    inner = unwrap(
        expr,
        "nv_get_index"
    )

    if inner is None:
        return None

    args = split_top_args(inner)

    if len(args) != 2:
        return None

    string = string_code(
        args[0],
        native
    )

    if string is None:
        return None

    index = native_index_code(
        args[1]
    )

    if index is None:
        return None

    return string, index


def replace_native_index_assignment(
    line,
    native
):
    m = re.match(
        r'^(\s*)'
        r'([A-Za-z_][A-Za-z0-9_]*)'
        r'\s*=\s*(.*?)\s*;\s*$',
        line
    )

    if not m:
        return line

    indent = m.group(1)
    name = m.group(2)
    rhs = m.group(3)

    if name not in native:
        return line

    result = native_string_index(
        rhs,
        native
    )

    if result is None:
        return line

    string, index = result

    return (
        f"{indent}clariox_string_assign_char("
        f"&{name}, "
        f"{string}, "
        f"(long long)({index})"
        f");\n"
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

        index = native_index_code(
            args[1]
        )

        if index is None:
            return None

        return (
            "clariox_string_box("
            "clariox_string_char("
            f"{string}, "
            f"(long long)({index})"
            "))"
        )

    return replace_balanced_calls(
        line,
        "nv_get_index",
        callback
    )


def discover_string_literals(lines):
    """
    Retrouve les littéraux générés par le compilateur :

        clariox_literal_2 = nv_str("A");

    et permet ensuite de les utiliser comme ClarioxString
    sans passer par NvVal.
    """
    literals = {}

    pattern = re.compile(
        r'^\s*'
        r'(clariox_literal_[A-Za-z0-9_]+)'
        r'\s*=\s*'
        r'nv_str\('
        r'("(?:\\.|[^"\\])*")'
        r'\)'
        r'\s*;\s*$'
    )

    for line in lines:
        m = pattern.match(line)

        if m:
            literals[m.group(1)] = m.group(2)

    return literals


def native_string_operand(expr, native, literals):
    """
    Convertit une expression qui représente une chaîne
    vers son équivalent ClarioxString natif lorsque c'est sûr.
    """
    expr = strip_outer_parens(expr)

    # Variable native ou littéral nv_str("...")
    code = string_code(
        expr,
        native
    )

    if code is not None:
        return code

    # Littéraux pré-générés :
    # clariox_literal_2 -> clariox_string_literal("A")
    if expr in literals:
        return (
            "clariox_string_literal("
            f"{literals[expr]}"
            ")"
        )

    # Une opération précédente a éventuellement produit :
    #
    # clariox_string_box(
    #     clariox_string_char(...)
    # )
    #
    # Dans une comparaison de chaînes, le boxing est inutile.
    inner = unwrap(
        expr,
        "clariox_string_box"
    )

    if inner is not None:
        inner = strip_outer_parens(inner)

        code = string_code(
            inner,
            native
        )

        if code is not None:
            return code

        # Expressions ClarioxString produites directement
        # par l'optimiseur.
        native_functions = (
            "clariox_string_char",
            "clariox_string_concat_many",
            "clariox_string_literal",
            "clariox_string_copy",
        )

        for function_name in native_functions:
            if unwrap(
                inner,
                function_name
            ) is not None:
                return inner

    return None


def replace_eq_calls(
    line,
    native,
    literals
):
    """
    Optimise les comparaisons de chaînes :

        a == b
        a != b

    sans repasser par NvVal.
    """

    def make_callback(negate):

        def callback(inner):
            args = split_top_args(inner)

            if len(args) != 2:
                return None

            a = native_string_operand(
                args[0],
                native,
                literals
            )

            b = native_string_operand(
                args[1],
                native,
                literals
            )

            if a is None or b is None:
                return None

            comparison = (
                "clariox_string_eq("
                f"{a}, {b}"
                ")"
            )

            if negate:
                comparison = (
                    f"!({comparison})"
                )

            return (
                f"nv_bool({comparison})"
            )

        return callback

    # ==
    line = replace_balanced_calls(
        line,
        "nv_eq",
        make_callback(False)
    )

    # !=
    line = replace_balanced_calls(
        line,
        "nv_ne",
        make_callback(True)
    )

    return line


def replace_native_string_truth(line):
    """
    Supprime nv_truth(nv_bool(...)) lorsque la condition
    provient d'une comparaison de chaînes native.

    Supporte :

        ==
        !=
    """

    def callback(inner):
        expr = strip_outer_parens(inner)

        bool_inner = unwrap(
            expr,
            "nv_bool"
        )

        if bool_inner is None:
            return None

        bool_inner = strip_outer_parens(
            bool_inner
        )

        # ==
        if unwrap(
            bool_inner,
            "clariox_string_eq"
        ) is not None:
            return f"({bool_inner})"

        # != devient :
        #
        # !(clariox_string_eq(...))
        if bool_inner.startswith("!"):
            negated = strip_outer_parens(
                bool_inner[1:].strip()
            )

            if unwrap(
                negated,
                "clariox_string_eq"
            ) is not None:
                return f"(!({negated}))"

        return None

    return replace_balanced_calls(
        line,
        "nv_truth",
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
    string_literals = discover_string_literals(lines)

    if native:
        print(
            "[Clariox OPT] Chaînes natives :"
        )

        for name in native:
            print(f"  {name}")

    else:
        print(
            "[Clariox OPT] Aucune chaîne "
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
                '#include "clariox_runtime.h"'
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
                        f"clariox_string_copy({code})"
                    )

                declaration = (
                    f"ClarioxString {name} = "
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
        # clariox_string_assign_move() libère l'ancienne.
        for name in native:
            m_assign = re.match(
                rf'^(\s*){re.escape(name)}'
                rf'\s*=\s*(.*?)\s*;\s*$',
                new_line
            )

            if not m_assign:
                continue

            rhs = m_assign.group(2)
            # CLAIR_NORMALISE_LONGUEUR_AVANT_STRING_CODE
            # len(chaine_native) doit être abaissé avant
            # l'analyse d'une indexation/concaténation.
            for native_name in native:
                rhs = replace_length(rhs, native_name)

            # CLAIR_INDEX_ASSIGN_AVANT_STRING_CODE
            # Une indexation affectée à une chaîne native doit
            # COPIER le caractère, et non déplacer une vue
            # pointant dans le stockage de la chaîne source.
            index_assignment = native_string_index(
                rhs,
                native
            )

            if index_assignment is not None:
                source_code, index_code = index_assignment
                indent = m_assign.group(1)

                new_line = (
                    f"{indent}clariox_string_assign_char("
                    f"&{name}, "
                    f"{source_code}, "
                    f"(long long)({index_code})"
                    f");\n"
                )

                break

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
                    f"clariox_string_copy({native_rhs})"
                )

            indent = m_assign.group(1)

            terms = string_terms(
                rhs,
                native
            )

            append_char = (
                terms is not None
                and len(terms) == 2
                and terms[0] == name
                and unwrap(
                    terms[1],
                    "clariox_string_char"
                ) is not None
            )

            if append_char:
                new_line = (
                    f"{indent}"
                    f"clariox_string_append_char("
                    f"&{name}, "
                    f"{terms[1]}"
                    f");\n"
                )

            elif terms is not None and len(terms) > 1:
                new_line = (
                    f"{indent}"
                    f"clariox_string_assign_concat_many("
                    f"&{name}, "
                    f"(ClarioxString[]){{"
                    + ", ".join(terms)
                    + f"}}, "
                    f"{len(terms)}LL);\n"
                )

            else:
                new_line = (
                    f"{indent}clariox_string_assign_move("
                    f"&{name}, {native_rhs});\n"
                )

            break

        for name in native:
            new_line = replace_length(
                new_line,
                name
            )

        new_line = replace_native_index_assignment(
            new_line,
            native
        )

        new_line = replace_index_calls(
            new_line,
            native
        )

        new_line = replace_eq_calls(
            new_line,
            native,
            string_literals
        )

        new_line = replace_native_string_truth(
            new_line
        )

        # Passage d'une chaîne native vers
        # une fonction dynamique comme print().
        for name in native:
            new_line = re.sub(
                rf'nv_call_add\(&__c,\s*'
                rf'{re.escape(name)}\)',
                (
                    'nv_call_add(&__c, '
                    f'clariox_string_box({name}))'
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
                    f"    clariox_string_release("
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
        "[Clariox OPT] C chaînes optimisé : "
        f"{destination}"
    )


if __name__ == "__main__":
    main()
