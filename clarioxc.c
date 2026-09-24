#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <stdarg.h>

#define MAX_LINE 4096
#define MAX_NAME 128
#define MAX_VARS 1024
#define MAX_BLOCKS 256
#define MAX_FUNCS 256
#define MAX_TYPES 128
#define MAX_FIELDS 128
#define MAX_METHODS 256
#define MAX_PARAMS 64

/* ============================
   Petits utilitaires
   ============================ */

static void die(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    exit(1);
}

static char *xstrdup(const char *s) {
    size_t n = strlen(s) + 1;
    char *p = (char*)malloc(n);
    if (!p) die("Out of memory");
    memcpy(p, s, n);
    return p;
}

static char *fmtdup(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    va_list cp;
    va_copy(cp, ap);
    int n = vsnprintf(NULL, 0, fmt, cp);
    va_end(cp);
    if (n < 0) die("Formatting error");
    char *buf = (char*)malloc((size_t)n + 1);
    if (!buf) die("Out of memory");
    vsnprintf(buf, (size_t)n + 1, fmt, ap);
    va_end(ap);
    return buf;
}

static char *trim(char *s) {
    while (isspace((unsigned char)*s)) s++;
    if (*s == '\0') return s;
    char *e = s + strlen(s) - 1;
    while (e > s && isspace((unsigned char)*e)) e--;
    e[1] = '\0';
    return s;
}

static int is_ident(const char *s) {
    if (!s || !*s) return 0;
    if (!(isalpha((unsigned char)s[0]) || s[0] == '_')) return 0;
    for (size_t i = 1; s[i]; i++) {
        if (!(isalnum((unsigned char)s[i]) || s[i] == '_')) return 0;
    }
    return 1;
}

static void emit_indent(FILE *out, int n) {
    for (int i = 0; i < n; i++) fputc(' ', out);
}

static void strip_comment(char *s) {
    int in_string = 0;
    int escape = 0;
    for (size_t i = 0; s[i]; i++) {
        if (escape) { escape = 0; continue; }
        if (s[i] == '\\' && in_string) { escape = 1; continue; }
        if (s[i] == '"') { in_string = !in_string; continue; }
        if (s[i] == '#' && !in_string) {
            s[i] = '\0';
            return;
        }
    }
}


static int bracket_balance(const char *s) {
    int b = 0, in_string = 0, esc = 0;
    for (size_t i = 0; s[i]; i++) {
        char c = s[i];
        if (esc) { esc = 0; continue; }
        if (in_string && c == '\\') { esc = 1; continue; }
        if (c == '"') { in_string = !in_string; continue; }
        if (in_string) continue;
        if (c=='(' || c=='[' || c=='{') b++;
        else if (c==')' || c==']' || c=='}') b--;
    }
    return b;
}
static int safe_filename(const char *s) {
    if (!s || !*s) return 0;
    for (size_t i = 0; s[i]; i++) {
        unsigned char c = (unsigned char)s[i];
        if (!(isalnum(c) || c=='_' || c=='-' || c=='.' || c=='/' )) return 0;
    }
    return 1;
}

/* ============================
   Métadonnées du programme
   ============================ */

typedef struct {
    char name[MAX_NAME];
    char type[MAX_NAME];
} ParamMeta;

typedef struct {
    char name[MAX_NAME];
    char internal[MAX_NAME * 2];
    char owner[MAX_NAME]; /* vide pour fonction globale */
    int param_count;
    ParamMeta params[MAX_PARAMS];
    char return_type[MAX_NAME];
} FuncMeta;

static FuncMeta funcs[MAX_FUNCS];
static int func_count = 0;

typedef struct {
    char name[MAX_NAME];
    char type[MAX_NAME];
} FieldMeta;

typedef enum { TYPE_STRUCTURE, TYPE_OBJECT } UserTypeKind;

typedef struct {
    char name[MAX_NAME];
    UserTypeKind kind;
    int field_count;
    FieldMeta fields[MAX_FIELDS];
} TypeMeta;

static TypeMeta types[MAX_TYPES];
static int type_count = 0;

static TypeMeta *find_type(const char *name) {
    for (int i = 0; i < type_count; i++) {
        if (strcmp(types[i].name, name) == 0) return &types[i];
    }
    return NULL;
}


static FuncMeta *find_method(const char *owner, const char *name) {
    for (int i = 0; i < func_count; i++) {
        if (strcmp(funcs[i].owner, owner) == 0 && strcmp(funcs[i].name, name) == 0) return &funcs[i];
    }
    return NULL;
}

/* ============================
   Suivi des variables par portée
   ============================ */

typedef struct {
    char vars[MAX_VARS][MAX_NAME];
    char var_types[MAX_VARS][MAX_NAME];
    int count;
} VarScope;

static VarScope main_scope;
static VarScope func_scope;
static VarScope main_consts;
static VarScope func_consts;

static int scope_find_index(
    VarScope *s,
    const char *name
) {
    for (int i = 0; i < s->count; i++) {
        if (strcmp(s->vars[i], name) == 0) {
            return i;
        }
    }

    return -1;
}

static int scope_has(
    VarScope *s,
    const char *name
) {
    return scope_find_index(s, name) >= 0;
}

static const char *scope_get_type(
    VarScope *s,
    const char *name
) {
    int i = scope_find_index(s, name);

    if (i < 0 || !s->var_types[i][0]) {
        return NULL;
    }

    return s->var_types[i];
}

static void scope_add_typed(
    VarScope *s,
    const char *name,
    const char *type
) {
    int existing = scope_find_index(s, name);

    if (existing >= 0) {
        if (
            type &&
            *type &&
            !s->var_types[existing][0]
        ) {
            snprintf(
                s->var_types[existing],
                MAX_NAME,
                "%s",
                type
            );
        }

        return;
    }

    if (s->count >= MAX_VARS) {
        die("Trop de variables");
    }

    int i = s->count++;

    snprintf(
        s->vars[i],
        MAX_NAME,
        "%s",
        name
    );

    s->var_types[i][0] = '\0';

    if (type && *type) {
        snprintf(
            s->var_types[i],
            MAX_NAME,
            "%s",
            type
        );
    }
}

static void scope_add(
    VarScope *s,
    const char *name
) {
    scope_add_typed(s, name, NULL);
}

/* ============================
   Lexer d'expressions
   ============================ */

typedef enum {
    TK_EOF,
    TK_IDENT,
    TK_NUMBER,
    TK_STRING,
    TK_LPAREN, TK_RPAREN,
    TK_LBRACK, TK_RBRACK,
    TK_LBRACE, TK_RBRACE,
    TK_COMMA, TK_COLON, TK_DOT, TK_DDOT,
    TK_PLUS, TK_MINUS, TK_STAR, TK_DSTAR,
    TK_SLASH, TK_PERCENT,
    TK_EQ, TK_EQEQ, TK_NE,
    TK_LT, TK_LE, TK_GT, TK_GE
} TokenKind;

typedef struct {
    TokenKind kind;
    char text[1024];
} Token;

typedef struct {
    const char *src;
    size_t pos;
    Token cur;
    Token next;
    int lineno;
} Lexer;

static void lex_one(Lexer *lx, Token *t) {
    const char *s = lx->src;
    size_t i = lx->pos;
    while (isspace((unsigned char)s[i])) i++;
    char c = s[i];
    t->text[0] = '\0';
    if (!c) { t->kind = TK_EOF; lx->pos = i; return; }

    if (isalpha((unsigned char)c) || c=='_') {
        size_t st = i++;
        while (isalnum((unsigned char)s[i]) || s[i]=='_') i++;
        size_t n = i-st;
        if (n >= sizeof(t->text)) n = sizeof(t->text)-1;
        memcpy(t->text, s+st, n); t->text[n]='\0';
        t->kind = TK_IDENT; lx->pos = i; return;
    }

    if (isdigit((unsigned char)c) || (c=='.' && isdigit((unsigned char)s[i+1]))) {
        size_t st = i++;
        int dot = (c=='.');
        while (isdigit((unsigned char)s[i]) || (!dot && s[i]=='.')) {
            if (s[i]=='.' && s[i+1]=='.') break;
            if (s[i]=='.') dot = 1;
            i++;
        }
        if (s[i]=='e' || s[i]=='E') {
            i++;
            if (s[i]=='+' || s[i]=='-') i++;
            while (isdigit((unsigned char)s[i])) i++;
        }
        size_t n = i-st;
        if (n >= sizeof(t->text)) n = sizeof(t->text)-1;
        memcpy(t->text, s+st, n); t->text[n]='\0';
        t->kind = TK_NUMBER; lx->pos = i; return;
    }

    if (c=='"') {
        size_t st = i++;
        int esc = 0;
        while (s[i]) {
            if (esc) { esc=0; i++; continue; }
            if (s[i]=='\\') { esc=1; i++; continue; }
            if (s[i]=='"') { i++; break; }
            i++;
        }
        if (s[i-1] != '"') die("Line %d: unterminated string", lx->lineno);
        size_t n = i-st;
        if (n >= sizeof(t->text)) n = sizeof(t->text)-1;
        memcpy(t->text, s+st, n); t->text[n]='\0';
        t->kind = TK_STRING; lx->pos = i; return;
    }

    lx->pos = i+1;
    switch (c) {
        case '(': t->kind=TK_LPAREN; return;
        case ')': t->kind=TK_RPAREN; return;
        case '[': t->kind=TK_LBRACK; return;
        case ']': t->kind=TK_RBRACK; return;
        case '{': t->kind=TK_LBRACE; return;
        case '}': t->kind=TK_RBRACE; return;
        case ',': t->kind=TK_COMMA; return;
        case ':': t->kind=TK_COLON; return;
        case '.':
            if (s[i+1]=='.') { t->kind=TK_DDOT; lx->pos=i+2; }
            else t->kind=TK_DOT;
            return;
        case '+': t->kind=TK_PLUS; return;
        case '-': t->kind=TK_MINUS; return;
        case '/': t->kind=TK_SLASH; return;
        case '%': t->kind=TK_PERCENT; return;
        case '*':
            if (s[i+1]=='*') { t->kind=TK_DSTAR; lx->pos=i+2; }
            else t->kind=TK_STAR;
            return;
        case '=':
            if (s[i+1]=='=') { t->kind=TK_EQEQ; lx->pos=i+2; }
            else t->kind=TK_EQ;
            return;
        case '!':
            if (s[i+1]=='=') { t->kind=TK_NE; lx->pos=i+2; return; }
            break;
        case '<':
            if (s[i+1]=='=') { t->kind=TK_LE; lx->pos=i+2; }
            else t->kind=TK_LT;
            return;
        case '>':
            if (s[i+1]=='=') { t->kind=TK_GE; lx->pos=i+2; }
            else t->kind=TK_GT;
            return;
    }
    die("Line %d: unexpected character '%c'", lx->lineno, c);
}

static void lexer_init(Lexer *lx, const char *src, int lineno) {
    memset(lx, 0, sizeof(*lx));
    lx->src = src;
    lx->lineno = lineno;
    lex_one(lx, &lx->cur);
    lex_one(lx, &lx->next);
}

static void advance(Lexer *lx) {
    lx->cur = lx->next;
    lex_one(lx, &lx->next);
}

static int is_kw(Lexer *lx, const char *kw) {
    return lx->cur.kind == TK_IDENT && strcmp(lx->cur.text, kw)==0;
}

static void expect(Lexer *lx, TokenKind k, const char *what) {
    if (lx->cur.kind != k) die("Line %d: expected %s", lx->lineno, what);
}

/* ============================
   Génération d'expressions C
   Les valeurs dynamiques du prototype passent par NvVal.
   ============================ */

static char *parse_expr(Lexer *lx);

static char *compile_expr(const char *src, int lineno);
static int manual_alloc_context = 0;

/* Interpolation simple : "Bonjour {nom}". {{ et }} écrivent des accolades. */
static char *compile_interpolated_string(const char *token, int lineno) {
    size_t n = strlen(token);
    if (n < 2 || token[0] != '"' || token[n-1] != '"')
        return fmtdup("nv_str(%s)", token);

    int has_interp = 0;
    for (size_t i = 1; i + 1 < n; i++) {
        if (token[i] == '\\') { i++; continue; }
        if (token[i] == '{' && token[i+1] != '{') { has_interp = 1; break; }
    }
    if (!has_interp) return fmtdup("nv_str(%s)", token);

    char *acc = xstrdup("nv_str(\"\")");
    char lit[4096]; size_t li = 0;

    for (size_t i = 1; i + 1 < n; ) {
        char c = token[i];
        if (c == '\\' && i + 1 < n - 1) {
            if (li + 2 >= sizeof(lit)) die("Line %d: interpolated string is too long", lineno);
            lit[li++] = token[i++]; lit[li++] = token[i++]; continue;
        }
        if (c == '{' && token[i+1] == '{') { lit[li++] = '{'; i += 2; continue; }
        if (c == '}' && token[i+1] == '}') { lit[li++] = '}'; i += 2; continue; }
        if (c == '{') {
            if (li) {
                lit[li] = '\0';
                char *part = fmtdup("nv_str(\"%s\")", lit);
                char *tmp = fmtdup("nv_add(%s, %s)", acc, part);
                free(acc); free(part); acc = tmp; li = 0;
            }
            size_t j = i + 1;
            while (j < n - 1 && token[j] != '}') j++;
            if (j >= n - 1) die("Line %d: missing '}' in interpolated string", lineno);
            size_t en = j - i - 1;
            if (!en || en >= 2048) die("Line %d: invalid interpolation", lineno);
            char expr[2048]; memcpy(expr, token+i+1, en); expr[en] = '\0';
            char *e = compile_expr(trim(expr), lineno);
            char *part = fmtdup("nv_to_str(%s)", e);
            char *tmp = fmtdup("nv_add(%s, %s)", acc, part);
            free(e); free(part); free(acc); acc = tmp;
            i = j + 1; continue;
        }
        if (li + 1 >= sizeof(lit)) die("Line %d: interpolated string is too long", lineno);
        lit[li++] = c; i++;
    }
    if (li) {
        lit[li] = '\0';
        char *part = fmtdup("nv_str(\"%s\")", lit);
        char *tmp = fmtdup("nv_add(%s, %s)", acc, part);
        free(acc); free(part); acc = tmp;
    }
    return acc;
}

static char *join_binary(const char *fn, char *a, char *b) {
    char *r = fmtdup("%s(%s, %s)", fn, a, b);
    free(a); free(b); return r;
}

static char *build_call_expr(Lexer *lx, const char *name, char *receiver) {
    if (!receiver && strcmp(name, "alloc") == 0 && !manual_alloc_context)
        die("Line %d: alloc() requires a manual declaration", lx->lineno);
    expect(lx, TK_LPAREN, "(");
    advance(lx);

    char *body = xstrdup("({ NvCall __c = nv_call_new(); ");
    while (lx->cur.kind != TK_RPAREN) {
        char *piece = NULL;
        if (lx->cur.kind == TK_DSTAR) {
            advance(lx);
            char *e = parse_expr(lx);
            piece = fmtdup("nv_call_kwspread(&__c, %s); ", e);
            free(e);
        } else if (lx->cur.kind == TK_STAR) {
            advance(lx);
            char *e = parse_expr(lx);
            piece = fmtdup("nv_call_spread(&__c, %s); ", e);
            free(e);
        } else if (lx->cur.kind == TK_IDENT && lx->next.kind == TK_EQ) {
            char key[MAX_NAME];
            snprintf(key, sizeof(key), "%s", lx->cur.text);
            advance(lx); /* ident */
            advance(lx); /* = */
            char *e = parse_expr(lx);
            piece = fmtdup("nv_call_kw(&__c, \"%s\", %s); ", key, e);
            free(e);
        } else {
            char *e = parse_expr(lx);
            piece = fmtdup("nv_call_add(&__c, %s); ", e);
            free(e);
        }
        char *tmp = fmtdup("%s%s", body, piece);
        free(body); free(piece); body = tmp;
        if (lx->cur.kind == TK_COMMA) {
            advance(lx);
            if (lx->cur.kind == TK_RPAREN) break;
            continue;
        }
        break;
    }
    expect(lx, TK_RPAREN, ")");
    advance(lx);

    char *tail;
    if (receiver) {
        tail = fmtdup("NvVal __r = nv_dispatch_method(%s, \"%s\", __c.args, __c.argc, __c.kw); nv_call_free(&__c); __r; })", receiver, name);
    } else {
        tail = fmtdup("NvVal __r = nv_dispatch_call(\"%s\", __c.args, __c.argc, __c.kw); nv_call_free(&__c); __r; })", name);
    }
    char *r = fmtdup("%s%s", body, tail);
    free(body); free(tail);
    if (receiver) free(receiver);
    return r;
}


static int integer_literal_compare(
    const char *digits,
    const char *limit
){
    size_t a=strlen(digits);
    size_t b=strlen(limit);

    if(a<b)return -1;
    if(a>b)return 1;

    return strcmp(digits,limit);
}

static char *compile_integer_literal(
    const char *text,
    int lineno
){
    const char *digits=text;

    while(*digits=='0' && digits[1])
        digits++;

    if(
        integer_literal_compare(
            digits,
            "18446744073709551615"
        )>0
    ){
        die(
            "Line %d: integer literal out of range",
            lineno
        );
    }

    if(
        integer_literal_compare(
            digits,
            "9223372036854775807"
        )<=0
    ){
        return fmtdup(
            "nv_int(%sLL)",
            digits
        );
    }

    return fmtdup(
        "nv_uint(%sULL)",
        digits
    );
}

static char *parse_primary(Lexer *lx) {
    if (lx->cur.kind == TK_NUMBER) {
        char tmp[1024]; snprintf(tmp, sizeof(tmp), "%s", lx->cur.text);
        int is_float = strchr(tmp, '.') || strchr(tmp,'e') || strchr(tmp,'E');
        advance(lx);

        if(is_float)
            return fmtdup("nv_float(%s)",tmp);

        return compile_integer_literal(
            tmp,
            lx->lineno
        );
    }

    if (lx->cur.kind == TK_STRING) {
        char tmp[1024]; snprintf(tmp, sizeof(tmp), "%s", lx->cur.text);
        advance(lx);
        return compile_interpolated_string(tmp, lx->lineno);
    }

    if (is_kw(lx, "true")) { advance(lx); return xstrdup("nv_bool(1)"); }
    if (is_kw(lx, "false")) { advance(lx); return xstrdup("nv_bool(0)"); }
    if (is_kw(lx, "none")) { advance(lx); return xstrdup("nv_none()"); }

    if (lx->cur.kind == TK_LPAREN) {
        advance(lx);
        char *e = parse_expr(lx);
        expect(lx, TK_RPAREN, ")");
        advance(lx);
        char *r = fmtdup("(%s)", e);
        free(e);
        return r;
    }

    if (lx->cur.kind == TK_LBRACK) {
        advance(lx);
        char *body = xstrdup("({ NvVal __l = nv_list_new(); ");
        while (lx->cur.kind != TK_RBRACK) {
            if (lx->cur.kind == TK_STAR) {
                advance(lx);
                char *e = parse_expr(lx);
                char *tmp = fmtdup("%snv_list_extend(__l, %s); ", body, e);
                free(body); free(e); body = tmp;
            } else {
                char *e = parse_expr(lx);
                char *tmp = fmtdup("%snv_list_append(__l, %s); ", body, e);
                free(body); free(e); body = tmp;
            }
            if (lx->cur.kind == TK_COMMA) { advance(lx); if (lx->cur.kind==TK_RBRACK) break; }
            else break;
        }
        expect(lx, TK_RBRACK, "]"); advance(lx);
        char *r = fmtdup("%s__l; })", body); free(body); return r;
    }

    if (lx->cur.kind == TK_LBRACE) {
        advance(lx);
        char *body = xstrdup("({ NvVal __d = nv_dict_new_value(); ");
        while (lx->cur.kind != TK_RBRACE) {
            if (lx->cur.kind == TK_DSTAR) {
                advance(lx);
                char *e = parse_expr(lx);
                char *tmp = fmtdup("%snv_dict_merge_value(__d, %s); ", body, e);
                free(body); free(e); body = tmp;
            } else {
                char key[1024];
                if (lx->cur.kind == TK_STRING) {
                    snprintf(key, sizeof(key), "%s", lx->cur.text);
                    advance(lx);
                } else if (lx->cur.kind == TK_IDENT) {
                    snprintf(key, sizeof(key), "\"%s\"", lx->cur.text);
                    advance(lx);
                } else {
                    die("Line %d: invalid dict key", lx->lineno);
                }
                expect(lx, TK_COLON, ":"); advance(lx);
                char *e = parse_expr(lx);
                char *tmp = fmtdup("%snv_dict_set_value(__d, %s, %s); ", body, key, e);
                free(body); free(e); body = tmp;
            }
            if (lx->cur.kind == TK_COMMA) { advance(lx); if (lx->cur.kind==TK_RBRACE) break; }
            else break;
        }
        expect(lx, TK_RBRACE, "}"); advance(lx);
        char *r = fmtdup("%s__d; })", body); free(body); return r;
    }

    if (lx->cur.kind == TK_IDENT) {
        char name[MAX_NAME]; snprintf(name, sizeof(name), "%s", lx->cur.text);
        advance(lx);
        if (lx->cur.kind == TK_LPAREN) return build_call_expr(lx, name, NULL);
        return xstrdup(name);
    }

    die("Line %d: invalid expression", lx->lineno);
    return NULL;
}

static char *parse_postfix(Lexer *lx) {
    char *base = parse_primary(lx);
    for (;;) {
        if (lx->cur.kind == TK_LBRACK) {
            advance(lx);
            char *idx = parse_expr(lx);
            expect(lx, TK_RBRACK, "]"); advance(lx);
            char *r = fmtdup("nv_get_index(%s, %s)", base, idx);
            free(base); free(idx); base = r;
            continue;
        }
        if (lx->cur.kind == TK_DOT) {
            advance(lx);
            expect(lx, TK_IDENT, "nom après .");
            char member[MAX_NAME]; snprintf(member, sizeof(member), "%s", lx->cur.text);
            advance(lx);
            if (lx->cur.kind == TK_LPAREN) {
                base = build_call_expr(lx, member, base);
            } else {
                char *r = fmtdup("nv_get_field(%s, \"%s\")", base, member);
                free(base); base = r;
            }
            continue;
        }
        break;
    }
    return base;
}

static char *parse_unary(Lexer *lx) {
    if (is_kw(lx, "not")) {
        advance(lx);
        char *a = parse_unary(lx);
        char *r = fmtdup("nv_not(%s)", a); free(a); return r;
    }
    if (lx->cur.kind == TK_MINUS) {
        advance(lx);
        char *a = parse_unary(lx);
        char *r = fmtdup("nv_neg(%s)", a); free(a); return r;
    }
    if (lx->cur.kind == TK_PLUS) {
        advance(lx);
        return parse_unary(lx);
    }
    return parse_postfix(lx);
}

static char *parse_mul(Lexer *lx) {
    char *a = parse_unary(lx);
    while (lx->cur.kind==TK_STAR || lx->cur.kind==TK_SLASH || lx->cur.kind==TK_PERCENT || lx->cur.kind==TK_DSTAR) {
        TokenKind op = lx->cur.kind; advance(lx);
        char *b = parse_unary(lx);
        a = join_binary(op==TK_STAR?"nv_mul":op==TK_SLASH?"nv_div":op==TK_PERCENT?"nv_mod":"nv_pow", a, b);
    }
    return a;
}

static char *parse_add(Lexer *lx) {
    char *a = parse_mul(lx);
    while (lx->cur.kind==TK_PLUS || lx->cur.kind==TK_MINUS) {
        TokenKind op = lx->cur.kind; advance(lx);
        char *b = parse_mul(lx);
        a = join_binary(op==TK_PLUS?"nv_add":"nv_sub", a, b);
    }
    return a;
}

static char *parse_range(Lexer *lx) {
    char *a = parse_add(lx);
    if (lx->cur.kind == TK_DDOT) {
        advance(lx);
        char *b = parse_add(lx);
        char *r = fmtdup("nv_range(%s, %s)", a, b);
        free(a); free(b);
        return r;
    }
    return a;
}

static char *parse_cmp(Lexer *lx) {
    char *a = parse_range(lx);
    while (lx->cur.kind==TK_EQEQ || lx->cur.kind==TK_NE || lx->cur.kind==TK_LT || lx->cur.kind==TK_LE || lx->cur.kind==TK_GT || lx->cur.kind==TK_GE || is_kw(lx,"in")) {
        int membership = is_kw(lx,"in");
        TokenKind op = lx->cur.kind; advance(lx);
        char *b = parse_range(lx);
        if (membership) {
            char *r = fmtdup("nv_contains(%s, %s)", b, a);
            free(a); free(b); a = r;
        } else {
            const char *fn = op==TK_EQEQ?"nv_eq":op==TK_NE?"nv_ne":op==TK_LT?"nv_lt":op==TK_LE?"nv_le":op==TK_GT?"nv_gt":"nv_ge";
            a = join_binary(fn, a, b);
        }
    }
    return a;
}

static char *parse_and(Lexer *lx) {
    char *a = parse_cmp(lx);
    while (is_kw(lx, "and")) {
        advance(lx);
        char *b = parse_cmp(lx);
        a = join_binary("nv_and", a, b);
    }
    return a;
}

static char *parse_expr(Lexer *lx) {
    char *a = parse_and(lx);
    while (is_kw(lx, "or")) {
        advance(lx);
        char *b = parse_and(lx);
        a = join_binary("nv_or", a, b);
    }
    return a;
}

static char *compile_expr(const char *src, int lineno) {
    Lexer lx; lexer_init(&lx, src, lineno);
    char *e = parse_expr(&lx);
    if (lx.cur.kind != TK_EOF) die("Line %d: unexpected element '%s'", lineno, lx.cur.text);
    return e;
}

/* ============================
   Runtime C Clariox séparé dans clariox_runtime.h
   ============================ */

static const char *RUNTIME_C =
"#include <stdio.h>\n"
"#include <stdlib.h>\n"
"#include <string.h>\n"
"#include <stdbool.h>\n"
"#include <math.h>\n"
"#include <setjmp.h>\n"
"#include <stdint.h>\n"
"#include <limits.h>\n"
"#include <ctype.h>\n"
"\n"
"typedef struct NvVal NvVal;\n"
"typedef struct NvList NvList;\n"
"typedef struct NvDict NvDict;\n"
"typedef struct NvObj NvObj;\n"
"typedef struct NvCall NvCall;\n"
"typedef struct NvTryFrame NvTryFrame;\n"
"typedef struct NvMemory NvMemory;\n"
"typedef struct NvMemoryScope NvMemoryScope;\n"
"\n"
"typedef enum { NV_NONE, NV_INT, NV_UINT, NV_FLOAT, NV_BOOL, NV_STR, NV_LIST, NV_DICT, NV_OBJ, NV_FILE, NV_MEMORY } NvKind;\n"
"struct NvVal { NvKind kind; union { long long i; unsigned long long u; double f; int b; char *s; NvList *list; NvDict *dict; NvObj *obj; FILE *file; NvMemory *memory; } as; };\n"
"struct NvList { NvVal *items; int len, cap; };\n"
"struct NvDict { char **keys; NvVal *vals; int len, cap; };\n"
"struct NvObj { char *type; NvDict *fields; };\n"
"struct NvCall { NvVal *args; int argc, cap; NvDict *kw; };\n"
"struct NvTryFrame { jmp_buf env; NvTryFrame *prev; NvMemoryScope *memory_scope; };\n"
"typedef enum {\n"
"    NV_MEM_BYTE,\n"
"    NV_MEM_INT8,\n"
"    NV_MEM_UINT8,\n"
"    NV_MEM_INT16,\n"
"    NV_MEM_UINT16,\n"
"    NV_MEM_INT32,\n"
"    NV_MEM_UINT32,\n"
"    NV_MEM_INT64,\n"
"    NV_MEM_UINT64,\n"
"    NV_MEM_FLOAT32,\n"
"    NV_MEM_FLOAT64\n"
"} NvMemoryType;\n"
"struct NvMemory {\n"
"    unsigned char *data;\n"
"    size_t size;\n"
"    size_t count;\n"
"    NvMemoryType type;\n"
"    int freed;\n"
"    NvMemory *next;\n"
"};\n"
"struct NvMemoryScope { NvMemory *memory; NvMemoryScope *prev; };\n"
"static NvMemory *nv_memory_head = NULL;\n"
"static NvMemoryScope *nv_memory_scope_top = NULL;\n"
"static int nv_memory_cleanup_registered = 0;\n"
"static NvTryFrame *nv_try_top = NULL;\n"
"static char nv_error_message[1024] = {0};\n"
"\n"
"static void *nv_xmalloc(size_t n){ void *p=malloc(n?n:1); if(!p){fprintf(stderr,\"Out of memory\\n\"); exit(2);} return p;}\n"
"static char *nv_strdup(const char *s){ size_t n=strlen(s)+1; char *p=nv_xmalloc(n); memcpy(p,s,n); return p;}\n"
"/* NV_STRING_INTERN_V2 */\n"
"typedef struct NvInternStr {\n"
"    struct NvInternStr *next;\n"
"    unsigned long long hash;\n"
"    size_t len;\n"
"    char data[];\n"
"} NvInternStr;\n"
"\n"
"#define NV_INTERN_BUCKETS 4096\n"
"static NvInternStr *nv_intern_table[NV_INTERN_BUCKETS] = {0};\n"
"\n"
"static unsigned long long nv_hash_text(const char *s,size_t n){\n"
"    unsigned long long h=1469598103934665603ULL;\n"
"    for(size_t i=0;i<n;i++){\n"
"        h^=(unsigned char)s[i];\n"
"        h*=1099511628211ULL;\n"
"    }\n"
"    return h;\n"
"}\n"
"\n"
"static char *nv_intern(const char *s){\n"
"    size_t n=strlen(s);\n"
"    unsigned long long h=nv_hash_text(s,n);\n"
"    size_t bucket=(size_t)(h%NV_INTERN_BUCKETS);\n"
"\n"
"    for(NvInternStr*p=nv_intern_table[bucket];p;p=p->next){\n"
"        if(p->hash==h && p->len==n &&\n"
"           memcmp(p->data,s,n+1)==0)\n"
"            return p->data;\n"
"    }\n"
"\n"
"    NvInternStr*p=(NvInternStr*)nv_xmalloc(sizeof(*p)+n+1);\n"
"    p->hash=h;\n"
"    p->len=n;\n"
"    memcpy(p->data,s,n+1);\n"
"    p->next=nv_intern_table[bucket];\n"
"    nv_intern_table[bucket]=p;\n"
"    return p->data;\n"
"}\n"
"static NvVal nv_none(void){ NvVal v; memset(&v,0,sizeof(v)); v.kind=NV_NONE; return v;}\n"
"static NvVal nv_int(long long x){ NvVal v=nv_none(); v.kind=NV_INT; v.as.i=x; return v;}\n"
"static NvVal nv_uint(unsigned long long x){ NvVal v=nv_none(); v.kind=NV_UINT; v.as.u=x; return v;}\n"
"static NvVal nv_float(double x){ NvVal v=nv_none(); v.kind=NV_FLOAT; v.as.f=x; return v;}\n"
"static NvVal nv_bool(int x){ NvVal v=nv_none(); v.kind=NV_BOOL; v.as.b=!!x; return v;}\n"
"static NvVal nv_str(const char *x){ NvVal v=nv_none(); v.kind=NV_STR; v.as.s=nv_intern(x); return v;}\n"
"static NvDict *nv_dict_new(void){ NvDict*d=nv_xmalloc(sizeof(*d)); d->keys=NULL; d->vals=NULL; d->len=0; d->cap=0; return d;}\n"
"static NvVal nv_dict_new_value(void){ NvVal v=nv_none(); v.kind=NV_DICT; v.as.dict=nv_dict_new(); return v;}\n"
"static NvVal nv_list_new(void){ NvVal v=nv_none(); v.kind=NV_LIST; v.as.list=nv_xmalloc(sizeof(NvList)); v.as.list->items=NULL; v.as.list->len=0; v.as.list->cap=0; return v;}\n"
"static NvVal nv_file_value(FILE *f){ NvVal v=nv_none(); v.kind=NV_FILE; v.as.file=f; return v;}\n"
"static NvVal nv_to_str(NvVal v){ char b[256]; switch(v.kind){case NV_STR:return nv_str(v.as.s);case NV_NONE:return nv_str(\"none\");case NV_INT:snprintf(b,sizeof(b),\"%lld\",v.as.i);return nv_str(b);case NV_UINT:snprintf(b,sizeof(b),\"%llu\",v.as.u);return nv_str(b);case NV_FLOAT:snprintf(b,sizeof(b),\"%g\",v.as.f);return nv_str(b);case NV_BOOL:return nv_str(v.as.b?\"true\":\"false\");case NV_LIST:return nv_str(\"<list>\");case NV_DICT:return nv_str(\"<dict>\");case NV_OBJ:snprintf(b,sizeof(b),\"<%s>\",v.as.obj->type);return nv_str(b);case NV_MEMORY:if(!v.as.memory||v.as.memory->freed)return nv_str(\"<memory freed>\");snprintf(b,sizeof(b),\"<memory %zu bytes>\",v.as.memory->size);return nv_str(b);case NV_FILE:return nv_str(\"<file>\");}return nv_str(\"\");}\n"
"static void nv_memory_scope_cleanup_to(NvMemoryScope *target);\n"
"static void nv_throw(const char *msg){ snprintf(nv_error_message,sizeof(nv_error_message),\"%s\",msg); if(nv_try_top){nv_memory_scope_cleanup_to(nv_try_top->memory_scope);longjmp(nv_try_top->env,1);} nv_memory_scope_cleanup_to(NULL); fprintf(stderr,\"Clariox error: %s\\n\",msg); exit(1);}\n"
"static void nv_throwf(const char *fmt,const char *a){ snprintf(nv_error_message,sizeof(nv_error_message),fmt,a); if(nv_try_top){nv_memory_scope_cleanup_to(nv_try_top->memory_scope);longjmp(nv_try_top->env,1);} nv_memory_scope_cleanup_to(NULL); fprintf(stderr,\"Clariox error: %s\\n\",nv_error_message); exit(1);}\n"
"static int nv_truth(NvVal v){\n"
"    switch(v.kind){\n"
"        case NV_NONE:return 0;\n"
"        case NV_BOOL:return v.as.b;\n"
"        case NV_INT:return v.as.i!=0;\n"
"        case NV_UINT:return v.as.u!=0;\n"
"        case NV_FLOAT:return v.as.f!=0.0;\n"
"        case NV_STR:return v.as.s&&v.as.s[0];\n"
"        case NV_LIST:return v.as.list&&v.as.list->len>0;\n"
"        case NV_DICT:return v.as.dict&&v.as.dict->len>0;\n"
"        case NV_OBJ:return 1;\n"
"        case NV_MEMORY:return v.as.memory&&!v.as.memory->freed;\n"
"        case NV_FILE:return v.as.file!=NULL;\n"
"    }\n"
"    return 0;\n"
"}\n"
"\n"
"static int nv_is_integer(NvVal v){\n"
"    return\n"
"        v.kind==NV_INT ||\n"
"        v.kind==NV_UINT ||\n"
"        v.kind==NV_BOOL;\n"
"}\n"
"\n"
"static int nv_is_numeric(NvVal v){\n"
"    return nv_is_integer(v) || v.kind==NV_FLOAT;\n"
"}\n"
"\n"
"static __int128 nv_integer_i128(NvVal v){\n"
"    if(v.kind==NV_INT)\n"
"        return (__int128)v.as.i;\n"
"\n"
"    if(v.kind==NV_UINT)\n"
"        return (__int128)v.as.u;\n"
"\n"
"    if(v.kind==NV_BOOL)\n"
"        return (__int128)v.as.b;\n"
"\n"
"    nv_throw(\"Expected an integer value\");\n"
"    return 0;\n"
"}\n"
"\n"
"static NvVal nv_integer_from_i128(__int128 x){\n"
"    if(x<(__int128)LLONG_MIN)\n"
"        nv_throw(\"Integer overflow\");\n"
"\n"
"    if(x<=(__int128)LLONG_MAX)\n"
"        return nv_int((long long)x);\n"
"\n"
"    if(\n"
"        (unsigned __int128)x <=\n"
"        (unsigned __int128)ULLONG_MAX\n"
"    ){\n"
"        return nv_uint((unsigned long long)x);\n"
"    }\n"
"\n"
"    nv_throw(\"Integer overflow\");\n"
"    return nv_none();\n"
"}\n"
"\n"
"static NvVal nv_integer_from_u128(unsigned __int128 x){\n"
"    if(\n"
"        x >\n"
"        (unsigned __int128)ULLONG_MAX\n"
"    ){\n"
"        nv_throw(\"Integer overflow\");\n"
"    }\n"
"\n"
"    if(\n"
"        x <=\n"
"        (unsigned __int128)LLONG_MAX\n"
"    ){\n"
"        return nv_int((long long)x);\n"
"    }\n"
"\n"
"    return nv_uint((unsigned long long)x);\n"
"}\n"
"\n"
"static double nv_num(NvVal v){\n"
"    if(v.kind==NV_INT)\n"
"        return (double)v.as.i;\n"
"\n"
"    if(v.kind==NV_UINT)\n"
"        return (double)v.as.u;\n"
"\n"
"    if(v.kind==NV_FLOAT)\n"
"        return v.as.f;\n"
"\n"
"    if(v.kind==NV_BOOL)\n"
"        return (double)v.as.b;\n"
"\n"
"    nv_throw(\"Expected a numeric value\");\n"
"    return 0;\n"
"}\n"
"\n"
"static long double nv_num_long_double(NvVal v){\n"
"    if(v.kind==NV_INT)\n"
"        return (long double)v.as.i;\n"
"\n"
"    if(v.kind==NV_UINT)\n"
"        return (long double)v.as.u;\n"
"\n"
"    if(v.kind==NV_FLOAT)\n"
"        return (long double)v.as.f;\n"
"\n"
"    if(v.kind==NV_BOOL)\n"
"        return (long double)v.as.b;\n"
"\n"
"    nv_throw(\"Expected a numeric value\");\n"
"    return 0;\n"
"}\n"
"\n"
"static NvVal nv_parse_integer_text(const char *text){\n"
"    const unsigned char *p=\n"
"        (const unsigned char*)text;\n"
"\n"
"    while(isspace(*p))\n"
"        p++;\n"
"\n"
"    int negative=0;\n"
"\n"
"    if(*p=='+' || *p=='-'){\n"
"        negative=(*p=='-');\n"
"        p++;\n"
"    }\n"
"\n"
"    if(!isdigit(*p))\n"
"        nv_throw(\"Expected an integer\");\n"
"\n"
"    unsigned long long value=0;\n"
"\n"
"    while(isdigit(*p)){\n"
"        unsigned digit=\n"
"            (unsigned)(*p-'0');\n"
"\n"
"        if(\n"
"            value >\n"
"            (ULLONG_MAX-digit)/10ULL\n"
"        ){\n"
"            nv_throw(\"Integer out of range\");\n"
"        }\n"
"\n"
"        value=value*10ULL+digit;\n"
"        p++;\n"
"    }\n"
"\n"
"    while(isspace(*p))\n"
"        p++;\n"
"\n"
"    if(*p!='\\0')\n"
"        nv_throw(\"Expected an integer\");\n"
"\n"
"    if(negative){\n"
"        const unsigned long long min_abs=\n"
"            9223372036854775808ULL;\n"
"\n"
"        if(value>min_abs)\n"
"            nv_throw(\"Integer out of range\");\n"
"\n"
"        if(value==min_abs)\n"
"            return nv_int(LLONG_MIN);\n"
"\n"
"        return nv_int(\n"
"            -(long long)value\n"
"        );\n"
"    }\n"
"\n"
"    if(\n"
"        value <=\n"
"        (unsigned long long)LLONG_MAX\n"
"    ){\n"
"        return nv_int((long long)value);\n"
"    }\n"
"\n"
"    return nv_uint(value);\n"
"}\n"
"\n"
"static NvVal nv_integer_from_double(double x){\n"
"    if(!isfinite(x))\n"
"        nv_throw(\n"
"            \"Cannot convert non-finite float to int\"\n"
"        );\n"
"\n"
"    if(x<0.0){\n"
"        if(x<(double)LLONG_MIN)\n"
"            nv_throw(\"Integer out of range\");\n"
"\n"
"        return nv_int((long long)x);\n"
"    }\n"
"\n"
"    if(x<=(double)LLONG_MAX)\n"
"        return nv_int((long long)x);\n"
"\n"
"    /*\n"
"     * La conversion depuis float reste limitée par\n"
"     * la précision intrinsèque du double.\n"
"     */\n"
"    if(x>=18446744073709551616.0)\n"
"        nv_throw(\"Integer out of range\");\n"
"\n"
"    return nv_uint(\n"
"        (unsigned long long)x\n"
"    );\n"
"}\n"
"\n"
"static void nv_memory_shutdown(void){ nv_memory_scope_cleanup_to(NULL); NvMemory*m=nv_memory_head; size_t leaks=0,bytes=0; while(m){ NvMemory*next=m->next; if(!m->freed){leaks++;bytes+=m->size;} free(m); m=next; } nv_memory_head=NULL; if(leaks)fprintf(stderr,\"Clariox memory warning: %zu manual allocation(s) not freed (%zu bytes)\\n\",leaks,bytes); }\n"
"static NvMemory *nv_memory_get(NvVal v){ if(v.kind!=NV_MEMORY||!v.as.memory)nv_throw(\"Expected a memory block\"); if(v.as.memory->freed)nv_throw(\"Memory block has already been freed\"); return v.as.memory; }\n"
"static const char *nv_memory_type_name(NvMemoryType type){\n"
"    switch(type){\n"
"        case NV_MEM_BYTE:return \"byte\";\n"
"        case NV_MEM_INT8:return \"int8\";\n"
"        case NV_MEM_UINT8:return \"uint8\";\n"
"        case NV_MEM_INT16:return \"int16\";\n"
"        case NV_MEM_UINT16:return \"uint16\";\n"
"        case NV_MEM_INT32:return \"int32\";\n"
"        case NV_MEM_UINT32:return \"uint32\";\n"
"        case NV_MEM_INT64:return \"int64\";\n"
"        case NV_MEM_UINT64:return \"uint64\";\n"
"        case NV_MEM_FLOAT32:return \"float32\";\n"
"        case NV_MEM_FLOAT64:return \"float64\";\n"
"    }\n"
"    return \"unknown\";\n"
"}\n"
"\n"
"static size_t nv_memory_type_size(NvMemoryType type){\n"
"    switch(type){\n"
"        case NV_MEM_BYTE:return 1;\n"
"        case NV_MEM_INT8:return sizeof(int8_t);\n"
"        case NV_MEM_UINT8:return sizeof(uint8_t);\n"
"        case NV_MEM_INT16:return sizeof(int16_t);\n"
"        case NV_MEM_UINT16:return sizeof(uint16_t);\n"
"        case NV_MEM_INT32:return sizeof(int32_t);\n"
"        case NV_MEM_UINT32:return sizeof(uint32_t);\n"
"        case NV_MEM_INT64:return sizeof(int64_t);\n"
"        case NV_MEM_UINT64:return sizeof(uint64_t);\n"
"        case NV_MEM_FLOAT32:return sizeof(float);\n"
"        case NV_MEM_FLOAT64:return sizeof(double);\n"
"    }\n"
"    nv_throw(\"Unknown memory element type\");\n"
"    return 0;\n"
"}\n"
"\n"
"static size_t nv_memory_nonnegative_integer(\n"
"    NvVal v,\n"
"    const char *message\n"
"){\n"
"    if(v.kind==NV_INT){\n"
"        if(v.as.i<0)\n"
"            nv_throw(message);\n"
"\n"
"        return (size_t)v.as.i;\n"
"    }\n"
"\n"
"    if(v.kind==NV_UINT){\n"
"        if(\n"
"            v.as.u >\n"
"            (unsigned long long)SIZE_MAX\n"
"        ){\n"
"            nv_throw(message);\n"
"        }\n"
"\n"
"        return (size_t)v.as.u;\n"
"    }\n"
"\n"
"    if(v.kind==NV_FLOAT){\n"
"        double x=v.as.f;\n"
"\n"
"        if(\n"
"            !isfinite(x) ||\n"
"            x<0.0 ||\n"
"            floor(x)!=x ||\n"
"            x>(double)SIZE_MAX\n"
"        ){\n"
"            nv_throw(message);\n"
"        }\n"
"\n"
"        return (size_t)x;\n"
"    }\n"
"\n"
"    nv_throw(message);\n"
"    return 0;\n"
"}\n"
"\n"
"static __int128 nv_memory_integer_value(\n"
"    NvVal value,\n"
"    const char *type_name\n"
"){\n"
"    if(value.kind==NV_INT)\n"
"        return (__int128)value.as.i;\n"
"\n"
"    if(value.kind==NV_UINT)\n"
"        return (__int128)value.as.u;\n"
"\n"
"    {\n"
"        char buf[160];\n"
"\n"
"        snprintf(\n"
"            buf,\n"
"            sizeof(buf),\n"
"            \"%s memory requires an integer value\",\n"
"            type_name\n"
"        );\n"
"\n"
"        nv_throw(buf);\n"
"    }\n"
"\n"
"    return 0;\n"
"}\n"
"\n"
"static void nv_memory_integer_range_error(\n"
"    const char *type_name\n"
"){\n"
"    char buf[160];\n"
"\n"
"    snprintf(\n"
"        buf,\n"
"        sizeof(buf),\n"
"        \"%s memory value out of range\",\n"
"        type_name\n"
"    );\n"
"\n"
"    nv_throw(buf);\n"
"}\n"
"\n"
"static NvVal nv_memory_alloc_kind(\n"
"    NvVal countv,\n"
"    NvMemoryType type\n"
"){\n"
"    size_t count=nv_memory_nonnegative_integer(\n"
"        countv,\n"
"        \"Memory allocation size must be a non-negative integer\"\n"
"    );\n"
"\n"
"    if(count==0)\n"
"        nv_throw(\"alloc() size must be greater than zero\");\n"
"\n"
"    size_t element_size=nv_memory_type_size(type);\n"
"\n"
"    if(count>SIZE_MAX/element_size)\n"
"        nv_throw(\"Memory allocation is too large\");\n"
"\n"
"    size_t bytes=count*element_size;\n"
"\n"
"    NvMemory*m=nv_xmalloc(sizeof(*m));\n"
"\n"
"    m->data=nv_xmalloc(bytes);\n"
"    memset(m->data,0,bytes);\n"
"\n"
"    m->size=bytes;\n"
"    m->count=count;\n"
"    m->type=type;\n"
"    m->freed=0;\n"
"\n"
"    m->next=nv_memory_head;\n"
"    nv_memory_head=m;\n"
"\n"
"    if(!nv_memory_cleanup_registered){\n"
"        atexit(nv_memory_shutdown);\n"
"        nv_memory_cleanup_registered=1;\n"
"    }\n"
"\n"
"    NvVal v=nv_none();\n"
"    v.kind=NV_MEMORY;\n"
"    v.as.memory=m;\n"
"\n"
"    return v;\n"
"}\n"
"\n"
"static NvVal nv_memory_alloc(NvVal sizev){\n"
"    return nv_memory_alloc_kind(\n"
"        sizev,\n"
"        NV_MEM_BYTE\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_memory_free(NvVal v){\n"
"    NvMemory*m=nv_memory_get(v);\n"
"\n"
"    free(m->data);\n"
"    m->data=NULL;\n"
"    m->freed=1;\n"
"\n"
"    return nv_none();\n"
"}\n"
"\n"
"static void nv_memory_free_scoped(NvVal v){\n"
"    if(v.kind!=NV_MEMORY||!v.as.memory)\n"
"        return;\n"
"\n"
"    NvMemory*m=v.as.memory;\n"
"\n"
"    if(m->freed)\n"
"        return;\n"
"\n"
"    free(m->data);\n"
"    m->data=NULL;\n"
"    m->freed=1;\n"
"}\n"
"\n"
"static void nv_memory_scope_enter(NvVal v){\n"
"    NvMemory*m=nv_memory_get(v);\n"
"    NvMemoryScope*s=nv_xmalloc(sizeof(*s));\n"
"\n"
"    s->memory=m;\n"
"    s->prev=nv_memory_scope_top;\n"
"\n"
"    nv_memory_scope_top=s;\n"
"}\n"
"\n"
"static void nv_memory_scope_leave(NvVal v){\n"
"    if(v.kind!=NV_MEMORY||!v.as.memory)\n"
"        return;\n"
"\n"
"    if(\n"
"        !nv_memory_scope_top ||\n"
"        nv_memory_scope_top->memory!=v.as.memory\n"
"    ){\n"
"        nv_throw(\"Internal scoped-memory stack mismatch\");\n"
"    }\n"
"\n"
"    NvMemoryScope*s=nv_memory_scope_top;\n"
"\n"
"    nv_memory_scope_top=s->prev;\n"
"\n"
"    nv_memory_free_scoped(v);\n"
"\n"
"    free(s);\n"
"}\n"
"\n"
"static void nv_memory_scope_cleanup_to(\n"
"    NvMemoryScope *target\n"
"){\n"
"    while(\n"
"        nv_memory_scope_top &&\n"
"        nv_memory_scope_top!=target\n"
"    ){\n"
"        NvMemoryScope*s=nv_memory_scope_top;\n"
"\n"
"        nv_memory_scope_top=s->prev;\n"
"\n"
"        if(\n"
"            s->memory &&\n"
"            !s->memory->freed\n"
"        ){\n"
"            free(s->memory->data);\n"
"            s->memory->data=NULL;\n"
"            s->memory->freed=1;\n"
"        }\n"
"\n"
"        free(s);\n"
"    }\n"
"}\n"
"\n"
"static NvVal nv_memory_size(NvVal v){\n"
"    NvMemory*m=nv_memory_get(v);\n"
"\n"
"    return nv_int(\n"
"        (long long)m->size\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_memory_length(NvVal v){\n"
"    NvMemory*m=nv_memory_get(v);\n"
"\n"
"    return nv_int(\n"
"        (long long)m->count\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_memory_type_value(NvVal v){\n"
"    NvMemory*m=nv_memory_get(v);\n"
"\n"
"    return nv_str(\n"
"        nv_memory_type_name(m->type)\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_memory_load_at(\n"
"    NvMemory *m,\n"
"    size_t i\n"
"){\n"
"    switch(m->type){\n"
"\n"
"        case NV_MEM_BYTE:\n"
"            return nv_int(\n"
"                (long long)m->data[i]\n"
"            );\n"
"\n"
"        case NV_MEM_INT8:{\n"
"            int8_t x;\n"
"            memcpy(&x,m->data+i*sizeof(x),sizeof(x));\n"
"            return nv_int((long long)x);\n"
"        }\n"
"\n"
"        case NV_MEM_UINT8:{\n"
"            uint8_t x;\n"
"            memcpy(&x,m->data+i*sizeof(x),sizeof(x));\n"
"            return nv_int((long long)x);\n"
"        }\n"
"\n"
"        case NV_MEM_INT16:{\n"
"            int16_t x;\n"
"            memcpy(&x,m->data+i*sizeof(x),sizeof(x));\n"
"            return nv_int((long long)x);\n"
"        }\n"
"\n"
"        case NV_MEM_UINT16:{\n"
"            uint16_t x;\n"
"            memcpy(&x,m->data+i*sizeof(x),sizeof(x));\n"
"            return nv_int((long long)x);\n"
"        }\n"
"\n"
"        case NV_MEM_INT32:{\n"
"            int32_t x;\n"
"            memcpy(&x,m->data+i*sizeof(x),sizeof(x));\n"
"            return nv_int((long long)x);\n"
"        }\n"
"\n"
"        case NV_MEM_UINT32:{\n"
"            uint32_t x;\n"
"            memcpy(&x,m->data+i*sizeof(x),sizeof(x));\n"
"            return nv_int((long long)x);\n"
"        }\n"
"\n"
"        case NV_MEM_INT64:{\n"
"            int64_t x;\n"
"            memcpy(&x,m->data+i*sizeof(x),sizeof(x));\n"
"            return nv_int((long long)x);\n"
"        }\n"
"\n"
"        case NV_MEM_UINT64:{\n"
"            uint64_t x;\n"
"            memcpy(&x,m->data+i*sizeof(x),sizeof(x));\n"
"            return nv_uint(\n"
"                (unsigned long long)x\n"
"            );\n"
"        }\n"
"\n"
"        case NV_MEM_FLOAT32:{\n"
"            float x;\n"
"            memcpy(&x,m->data+i*sizeof(x),sizeof(x));\n"
"            return nv_float((double)x);\n"
"        }\n"
"\n"
"        case NV_MEM_FLOAT64:{\n"
"            double x;\n"
"            memcpy(&x,m->data+i*sizeof(x),sizeof(x));\n"
"            return nv_float(x);\n"
"        }\n"
"    }\n"
"\n"
"    nv_throw(\"Unknown memory element type\");\n"
"    return nv_none();\n"
"}\n"
"\n"
"static void nv_memory_store_at(\n"
"    NvMemory *m,\n"
"    size_t i,\n"
"    NvVal value\n"
"){\n"
"    __int128 x;\n"
"\n"
"    switch(m->type){\n"
"\n"
"        case NV_MEM_BYTE:\n"
"            x=nv_memory_integer_value(\n"
"                value,\n"
"                \"byte\"\n"
"            );\n"
"\n"
"            if(x<0||x>255)\n"
"                nv_throw(\n"
"                    \"Memory byte must be between 0 and 255\"\n"
"                );\n"
"\n"
"            m->data[i]=(unsigned char)x;\n"
"            return;\n"
"\n"
"        case NV_MEM_INT8:{\n"
"            x=nv_memory_integer_value(value,\"int8\");\n"
"\n"
"            if(x<INT8_MIN||x>INT8_MAX)\n"
"                nv_memory_integer_range_error(\"int8\");\n"
"\n"
"            int8_t y=(int8_t)x;\n"
"            memcpy(m->data+i*sizeof(y),&y,sizeof(y));\n"
"            return;\n"
"        }\n"
"\n"
"        case NV_MEM_UINT8:{\n"
"            x=nv_memory_integer_value(value,\"uint8\");\n"
"\n"
"            if(x<0||x>UINT8_MAX)\n"
"                nv_memory_integer_range_error(\"uint8\");\n"
"\n"
"            uint8_t y=(uint8_t)x;\n"
"            memcpy(m->data+i*sizeof(y),&y,sizeof(y));\n"
"            return;\n"
"        }\n"
"\n"
"        case NV_MEM_INT16:{\n"
"            x=nv_memory_integer_value(value,\"int16\");\n"
"\n"
"            if(x<INT16_MIN||x>INT16_MAX)\n"
"                nv_memory_integer_range_error(\"int16\");\n"
"\n"
"            int16_t y=(int16_t)x;\n"
"            memcpy(m->data+i*sizeof(y),&y,sizeof(y));\n"
"            return;\n"
"        }\n"
"\n"
"        case NV_MEM_UINT16:{\n"
"            x=nv_memory_integer_value(value,\"uint16\");\n"
"\n"
"            if(x<0||x>UINT16_MAX)\n"
"                nv_memory_integer_range_error(\"uint16\");\n"
"\n"
"            uint16_t y=(uint16_t)x;\n"
"            memcpy(m->data+i*sizeof(y),&y,sizeof(y));\n"
"            return;\n"
"        }\n"
"\n"
"        case NV_MEM_INT32:{\n"
"            x=nv_memory_integer_value(value,\"int32\");\n"
"\n"
"            if(x<INT32_MIN||x>INT32_MAX)\n"
"                nv_memory_integer_range_error(\"int32\");\n"
"\n"
"            int32_t y=(int32_t)x;\n"
"            memcpy(m->data+i*sizeof(y),&y,sizeof(y));\n"
"            return;\n"
"        }\n"
"\n"
"        case NV_MEM_UINT32:{\n"
"            x=nv_memory_integer_value(value,\"uint32\");\n"
"\n"
"            if(\n"
"                x<0 ||\n"
"                x>(__int128)UINT32_MAX\n"
"            ){\n"
"                nv_memory_integer_range_error(\"uint32\");\n"
"            }\n"
"\n"
"            uint32_t y=(uint32_t)x;\n"
"            memcpy(m->data+i*sizeof(y),&y,sizeof(y));\n"
"            return;\n"
"        }\n"
"\n"
"        case NV_MEM_INT64:{\n"
"            x=nv_memory_integer_value(value,\"int64\");\n"
"\n"
"            if(\n"
"                x<(__int128)INT64_MIN ||\n"
"                x>(__int128)INT64_MAX\n"
"            ){\n"
"                nv_memory_integer_range_error(\"int64\");\n"
"            }\n"
"\n"
"            int64_t y=(int64_t)x;\n"
"            memcpy(m->data+i*sizeof(y),&y,sizeof(y));\n"
"            return;\n"
"        }\n"
"\n"
"        case NV_MEM_UINT64:{\n"
"            x=nv_memory_integer_value(value,\"uint64\");\n"
"\n"
"            if(\n"
"                x<0 ||\n"
"                (unsigned __int128)x >\n"
"                (unsigned __int128)UINT64_MAX\n"
"            ){\n"
"                nv_memory_integer_range_error(\"uint64\");\n"
"            }\n"
"\n"
"            uint64_t y=(uint64_t)x;\n"
"            memcpy(m->data+i*sizeof(y),&y,sizeof(y));\n"
"            return;\n"
"        }\n"
"\n"
"        case NV_MEM_FLOAT32:{\n"
"            double z=nv_num(value);\n"
"            float y=(float)z;\n"
"            memcpy(m->data+i*sizeof(y),&y,sizeof(y));\n"
"            return;\n"
"        }\n"
"\n"
"        case NV_MEM_FLOAT64:{\n"
"            double y=nv_num(value);\n"
"            memcpy(m->data+i*sizeof(y),&y,sizeof(y));\n"
"            return;\n"
"        }\n"
"    }\n"
"\n"
"    nv_throw(\"Unknown memory element type\");\n"
"}\n"
"\n"
"static NvVal nv_memory_read(\n"
"    NvVal v,\n"
"    NvVal index\n"
"){\n"
"    NvMemory*m=nv_memory_get(v);\n"
"\n"
"    size_t i=nv_memory_nonnegative_integer(\n"
"        index,\n"
"        \"Memory index must be a non-negative integer\"\n"
"    );\n"
"\n"
"    if(i>=m->count)\n"
"        nv_throw(\"Memory index out of range\");\n"
"\n"
"    return nv_memory_load_at(m,i);\n"
"}\n"
"\n"
"static NvVal nv_memory_write(\n"
"    NvVal v,\n"
"    NvVal index,\n"
"    NvVal value\n"
"){\n"
"    NvMemory*m=nv_memory_get(v);\n"
"\n"
"    size_t i=nv_memory_nonnegative_integer(\n"
"        index,\n"
"        \"Memory index must be a non-negative integer\"\n"
"    );\n"
"\n"
"    if(i>=m->count)\n"
"        nv_throw(\"Memory index out of range\");\n"
"\n"
"    nv_memory_store_at(\n"
"        m,\n"
"        i,\n"
"        value\n"
"    );\n"
"\n"
"    return nv_none();\n"
"}\n"
"\n"
"static void nv_memory_fill_native(\n"
"    NvMemory*m,\n"
"    NvVal value,\n"
"    size_t offset,\n"
"    size_t length\n"
"){\n"
"    if(\n"
"        offset>m->count ||\n"
"        length>m->count-offset\n"
"    ){\n"
"        nv_throw(\n"
"            \"Memory fill range out of bounds\"\n"
"        );\n"
"    }\n"
"\n"
"    /*\n"
"     * Fast path pour les blocs d'un octet.\n"
"     */\n"
"    if(\n"
"        m->type==NV_MEM_BYTE ||\n"
"        m->type==NV_MEM_UINT8\n"
"    ){\n"
"        const char *type_name=\n"
"            m->type==NV_MEM_BYTE\n"
"            ? \"byte\"\n"
"            : \"uint8\";\n"
"\n"
"        __int128 x=\n"
"            nv_memory_integer_value(\n"
"                value,\n"
"                type_name\n"
"            );\n"
"\n"
"        if(x<0||x>255){\n"
"            if(m->type==NV_MEM_BYTE)\n"
"                nv_throw(\n"
"                    \"Memory byte must be between 0 and 255\"\n"
"                );\n"
"\n"
"            nv_memory_integer_range_error(\"uint8\");\n"
"        }\n"
"\n"
"        memset(\n"
"            m->data+offset,\n"
"            (unsigned char)x,\n"
"            length\n"
"        );\n"
"\n"
"        return;\n"
"    }\n"
"\n"
"    for(\n"
"        size_t i=offset;\n"
"        i<offset+length;\n"
"        i++\n"
"    ){\n"
"        nv_memory_store_at(\n"
"            m,\n"
"            i,\n"
"            value\n"
"        );\n"
"    }\n"
"}\n"
"\n"
"static NvVal nv_memory_fill_all(\n"
"    NvVal v,\n"
"    NvVal value\n"
"){\n"
"    NvMemory*m=nv_memory_get(v);\n"
"\n"
"    nv_memory_fill_native(\n"
"        m,\n"
"        value,\n"
"        0,\n"
"        m->count\n"
"    );\n"
"\n"
"    return nv_none();\n"
"}\n"
"\n"
"static NvVal nv_memory_fill_range(\n"
"    NvVal v,\n"
"    NvVal value,\n"
"    NvVal offsetv,\n"
"    NvVal lengthv\n"
"){\n"
"    NvMemory*m=nv_memory_get(v);\n"
"\n"
"    size_t offset=nv_memory_nonnegative_integer(\n"
"        offsetv,\n"
"        \"Memory offset must not be negative\"\n"
"    );\n"
"\n"
"    size_t length=nv_memory_nonnegative_integer(\n"
"        lengthv,\n"
"        \"Memory length must not be negative\"\n"
"    );\n"
"\n"
"    nv_memory_fill_native(\n"
"        m,\n"
"        value,\n"
"        offset,\n"
"        length\n"
"    );\n"
"\n"
"    return nv_none();\n"
"}\n"
"\n"
"static void nv_memory_require_same_type(\n"
"    NvMemory*dst,\n"
"    NvMemory*src\n"
"){\n"
"    if(dst->type!=src->type)\n"
"        nv_throw(\n"
"            \"Memory copy requires matching element types\"\n"
"        );\n"
"}\n"
"\n"
"static NvVal nv_memory_copy_all(\n"
"    NvVal dstv,\n"
"    NvVal srcv\n"
"){\n"
"    NvMemory*dst=nv_memory_get(dstv);\n"
"    NvMemory*src=nv_memory_get(srcv);\n"
"\n"
"    nv_memory_require_same_type(\n"
"        dst,\n"
"        src\n"
"    );\n"
"\n"
"    if(src->count>dst->count)\n"
"        nv_throw(\n"
"            \"Source memory block does not fit in destination\"\n"
"        );\n"
"\n"
"    memmove(\n"
"        dst->data,\n"
"        src->data,\n"
"        src->size\n"
"    );\n"
"\n"
"    return nv_none();\n"
"}\n"
"\n"
"static NvVal nv_memory_copy_range(\n"
"    NvVal dstv,\n"
"    NvVal srcv,\n"
"    NvVal srcoffv,\n"
"    NvVal dstoffv,\n"
"    NvVal lengthv\n"
"){\n"
"    NvMemory*dst=nv_memory_get(dstv);\n"
"    NvMemory*src=nv_memory_get(srcv);\n"
"\n"
"    nv_memory_require_same_type(\n"
"        dst,\n"
"        src\n"
"    );\n"
"\n"
"    size_t srcoff=nv_memory_nonnegative_integer(\n"
"        srcoffv,\n"
"        \"Memory offset must not be negative\"\n"
"    );\n"
"\n"
"    size_t dstoff=nv_memory_nonnegative_integer(\n"
"        dstoffv,\n"
"        \"Memory offset must not be negative\"\n"
"    );\n"
"\n"
"    size_t length=nv_memory_nonnegative_integer(\n"
"        lengthv,\n"
"        \"Memory length must not be negative\"\n"
"    );\n"
"\n"
"    if(\n"
"        srcoff>src->count ||\n"
"        length>src->count-srcoff\n"
"    ){\n"
"        nv_throw(\n"
"            \"Source memory range out of bounds\"\n"
"        );\n"
"    }\n"
"\n"
"    if(\n"
"        dstoff>dst->count ||\n"
"        length>dst->count-dstoff\n"
"    ){\n"
"        nv_throw(\n"
"            \"Destination memory range out of bounds\"\n"
"        );\n"
"    }\n"
"\n"
"    size_t element_size=\n"
"        nv_memory_type_size(dst->type);\n"
"\n"
"    memmove(\n"
"        dst->data+dstoff*element_size,\n"
"        src->data+srcoff*element_size,\n"
"        length*element_size\n"
"    );\n"
"\n"
"    return nv_none();\n"
"}\n"
"static NvVal nv_add(NvVal a,NvVal b){\n"
"    if(a.kind==NV_STR&&b.kind==NV_STR){\n"
"        size_t n=\n"
"            strlen(a.as.s)+strlen(b.as.s)+1;\n"
"\n"
"        char*p=nv_xmalloc(n);\n"
"\n"
"        snprintf(\n"
"            p,\n"
"            n,\n"
"            \"%s%s\",\n"
"            a.as.s,\n"
"            b.as.s\n"
"        );\n"
"\n"
"        NvVal v=nv_str(p);\n"
"        free(p);\n"
"        return v;\n"
"    }\n"
"\n"
"    if(nv_is_integer(a)&&nv_is_integer(b)){\n"
"        return nv_integer_from_i128(\n"
"            nv_integer_i128(a)+\n"
"            nv_integer_i128(b)\n"
"        );\n"
"    }\n"
"\n"
"    return nv_float(\n"
"        nv_num(a)+nv_num(b)\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_sub(NvVal a,NvVal b){\n"
"    if(nv_is_integer(a)&&nv_is_integer(b)){\n"
"        return nv_integer_from_i128(\n"
"            nv_integer_i128(a)-\n"
"            nv_integer_i128(b)\n"
"        );\n"
"    }\n"
"\n"
"    return nv_float(\n"
"        nv_num(a)-nv_num(b)\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_mul(NvVal a,NvVal b){\n"
"    if(nv_is_integer(a)&&nv_is_integer(b)){\n"
"        __int128 x=nv_integer_i128(a);\n"
"        __int128 y=nv_integer_i128(b);\n"
"\n"
"        if(x>=0 && y>=0){\n"
"            unsigned __int128 p=\n"
"                (unsigned __int128)x *\n"
"                (unsigned __int128)y;\n"
"\n"
"            return nv_integer_from_u128(p);\n"
"        }\n"
"\n"
"        return nv_integer_from_i128(\n"
"            x*y\n"
"        );\n"
"    }\n"
"\n"
"    return nv_float(\n"
"        nv_num(a)*nv_num(b)\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_div(NvVal a,NvVal b){\n"
"    double d=nv_num(b);\n"
"\n"
"    if(d==0.0)\n"
"        nv_throw(\"Division by zero\");\n"
"\n"
"    return nv_float(\n"
"        nv_num(a)/d\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_mod(NvVal a,NvVal b){\n"
"    if(nv_is_integer(a)&&nv_is_integer(b)){\n"
"        __int128 x=nv_integer_i128(a);\n"
"        __int128 y=nv_integer_i128(b);\n"
"\n"
"        if(y==0)\n"
"            nv_throw(\"Modulo by zero\");\n"
"\n"
"        return nv_integer_from_i128(\n"
"            x%y\n"
"        );\n"
"    }\n"
"\n"
"    long long x=(long long)nv_num(a);\n"
"    long long y=(long long)nv_num(b);\n"
"\n"
"    if(!y)\n"
"        nv_throw(\"Modulo by zero\");\n"
"\n"
"    return nv_int(x%y);\n"
"}\n"
"\n"
"static NvVal nv_pow(NvVal a,NvVal b){\n"
"    return nv_float(\n"
"        pow(nv_num(a),nv_num(b))\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_neg(NvVal a){\n"
"    if(nv_is_integer(a)){\n"
"        return nv_integer_from_i128(\n"
"            -nv_integer_i128(a)\n"
"        );\n"
"    }\n"
"\n"
"    return nv_float(\n"
"        -nv_num(a)\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_not(NvVal a){\n"
"    return nv_bool(!nv_truth(a));\n"
"}\n"
"\n"
"/* and/or sont volontairement des macros : */\n"
"/* cela garantit le court-circuit du second opérande. */\n"
"#define nv_and(left,right) nv_bool(nv_truth((left)) && nv_truth((right)))\n"
"#define nv_or(left,right) nv_bool(nv_truth((left)) || nv_truth((right)))\n"
"\n"
"static int nv_same(NvVal a,NvVal b){\n"
"    if(a.kind!=b.kind){\n"
"        if(nv_is_numeric(a)&&nv_is_numeric(b)){\n"
"            if(nv_is_integer(a)&&nv_is_integer(b)){\n"
"                return\n"
"                    nv_integer_i128(a)==\n"
"                    nv_integer_i128(b);\n"
"            }\n"
"\n"
"            return\n"
"                nv_num_long_double(a)==\n"
"                nv_num_long_double(b);\n"
"        }\n"
"\n"
"        return 0;\n"
"    }\n"
"\n"
"    switch(a.kind){\n"
"        case NV_NONE:return 1;\n"
"        case NV_INT:return a.as.i==b.as.i;\n"
"        case NV_UINT:return a.as.u==b.as.u;\n"
"        case NV_FLOAT:return a.as.f==b.as.f;\n"
"        case NV_BOOL:return a.as.b==b.as.b;\n"
"        case NV_STR:return strcmp(a.as.s,b.as.s)==0;\n"
"        case NV_FILE:return a.as.file==b.as.file;\n"
"        case NV_MEMORY:return a.as.memory==b.as.memory;\n"
"        default:return a.as.obj==b.as.obj;\n"
"    }\n"
"}\n"
"\n"
"static NvVal nv_eq(NvVal a,NvVal b){\n"
"    return nv_bool(nv_same(a,b));\n"
"}\n"
"\n"
"static NvVal nv_ne(NvVal a,NvVal b){\n"
"    return nv_bool(!nv_same(a,b));\n"
"}\n"
"\n"
"static int nv_numeric_compare(\n"
"    NvVal a,\n"
"    NvVal b\n"
"){\n"
"    if(nv_is_integer(a)&&nv_is_integer(b)){\n"
"        __int128 x=nv_integer_i128(a);\n"
"        __int128 y=nv_integer_i128(b);\n"
"\n"
"        return x<y?-1:x>y?1:0;\n"
"    }\n"
"\n"
"    long double x=nv_num_long_double(a);\n"
"    long double y=nv_num_long_double(b);\n"
"\n"
"    return x<y?-1:x>y?1:0;\n"
"}\n"
"\n"
"static NvVal nv_lt(NvVal a,NvVal b){\n"
"    return nv_bool(\n"
"        nv_numeric_compare(a,b)<0\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_le(NvVal a,NvVal b){\n"
"    return nv_bool(\n"
"        nv_numeric_compare(a,b)<=0\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_gt(NvVal a,NvVal b){\n"
"    return nv_bool(\n"
"        nv_numeric_compare(a,b)>0\n"
"    );\n"
"}\n"
"\n"
"static NvVal nv_ge(NvVal a,NvVal b){\n"
"    return nv_bool(\n"
"        nv_numeric_compare(a,b)>=0\n"
"    );\n"
"}\n"
"\n"
"static void nv_print_one(NvVal v){\n"
"    switch(v.kind){\n"
"\n"
"        case NV_NONE:\n"
"            printf(\"none\");\n"
"            break;\n"
"\n"
"        case NV_INT:\n"
"            printf(\"%lld\",v.as.i);\n"
"            break;\n"
"\n"
"        case NV_UINT:\n"
"            printf(\"%llu\",v.as.u);\n"
"            break;\n"
"\n"
"        case NV_FLOAT:\n"
"            printf(\"%g\",v.as.f);\n"
"            break;\n"
"\n"
"        case NV_BOOL:\n"
"            printf(\n"
"                \"%s\",\n"
"                v.as.b?\"true\":\"false\"\n"
"            );\n"
"            break;\n"
"\n"
"        case NV_STR:\n"
"            printf(\"%s\",v.as.s);\n"
"            break;\n"
"\n"
"        case NV_LIST:\n"
"            printf(\"[\");\n"
"            for(int i=0;i<v.as.list->len;i++){\n"
"                if(i)printf(\", \");\n"
"                nv_print_one(\n"
"                    v.as.list->items[i]\n"
"                );\n"
"            }\n"
"            printf(\"]\");\n"
"            break;\n"
"\n"
"        case NV_DICT:\n"
"            printf(\"{\");\n"
"            for(int i=0;i<v.as.dict->len;i++){\n"
"                if(i)printf(\", \");\n"
"                printf(\n"
"                    \"\\\"%s\\\": \",\n"
"                    v.as.dict->keys[i]\n"
"                );\n"
"                nv_print_one(\n"
"                    v.as.dict->vals[i]\n"
"                );\n"
"            }\n"
"            printf(\"}\");\n"
"            break;\n"
"\n"
"        case NV_OBJ:\n"
"            printf(\n"
"                \"<%s>\",\n"
"                v.as.obj->type\n"
"            );\n"
"            break;\n"
"\n"
"        case NV_MEMORY:\n"
"            if(\n"
"                !v.as.memory ||\n"
"                v.as.memory->freed\n"
"            ){\n"
"                printf(\"<memory freed>\");\n"
"            }else{\n"
"                printf(\n"
"                    \"<memory %zu bytes>\",\n"
"                    v.as.memory->size\n"
"                );\n"
"            }\n"
"            break;\n"
"\n"
"        case NV_FILE:\n"
"            printf(\"<file>\");\n"
"            break;\n"
"    }\n"
"}\n"
"\n"
"static void nv_list_append(NvVal l,NvVal v){ if(l.kind!=NV_LIST)nv_throw(\"append() requires a list\"); NvList*p=l.as.list; if(p->len==p->cap){p->cap=p->cap?p->cap*2:8;p->items=realloc(p->items,sizeof(NvVal)*p->cap);} p->items[p->len++]=v;}\n"
"static NvVal nv_range(NvVal a,NvVal b){ long long x=(long long)nv_num(a), y=(long long)nv_num(b); NvVal l=nv_list_new(); if(x<=y){for(long long i=x;i<y;i++)nv_list_append(l,nv_int(i));}else{for(long long i=x;i>y;i--)nv_list_append(l,nv_int(i));} return l;}\n"
"static void nv_file_close(NvVal v){ if(v.kind==NV_FILE && v.as.file) fclose(v.as.file); }\n"
"static NvVal nv_file_read(NvVal v){ if(v.kind!=NV_FILE||!v.as.file)nv_throw(\"File is not open\"); if(fseek(v.as.file,0,SEEK_END)!=0)nv_throw(\"Unable to read file\"); long n=ftell(v.as.file); if(n<0)nv_throw(\"Unable to read file\"); rewind(v.as.file); char *buf=nv_xmalloc((size_t)n+1); size_t got=fread(buf,1,(size_t)n,v.as.file); buf[got]='\\0'; NvVal r=nv_str(buf); free(buf); return r;}\n"
"static NvVal nv_file_write(NvVal v,NvVal data){ if(v.kind!=NV_FILE||!v.as.file)nv_throw(\"File is not open\"); NvVal t=nv_to_str(data); fputs(t.as.s,v.as.file); fflush(v.as.file); return nv_none();}\n"
"static void nv_list_extend(NvVal l,NvVal other){ if(l.kind!=NV_LIST||other.kind!=NV_LIST)nv_throw(\"Unpacking * requires a list\"); for(int i=0;i<other.as.list->len;i++)nv_list_append(l,other.as.list->items[i]);}\n"
"static int nv_dict_find(NvDict*d,const char*k){for(int i=0;i<d->len;i++)if(strcmp(d->keys[i],k)==0)return i;return-1;}\n"
"static NvVal nv_contains(NvVal container,NvVal item){ if(container.kind==NV_LIST){for(int i=0;i<container.as.list->len;i++)if(nv_same(container.as.list->items[i],item))return nv_bool(1);return nv_bool(0);} if(container.kind==NV_DICT){if(item.kind!=NV_STR)return nv_bool(0);return nv_bool(nv_dict_find(container.as.dict,item.as.s)>=0);} if(container.kind==NV_STR){if(item.kind!=NV_STR)return nv_bool(0);return nv_bool(strstr(container.as.s,item.as.s)!=NULL);} nv_throw(\"'in' requires a list, dict, or string\");return nv_bool(0);}\n"
"static void nv_dict_set(NvDict*d,const char*k,NvVal v){int i=nv_dict_find(d,k);if(i>=0){d->vals[i]=v;return;}if(d->len==d->cap){d->cap=d->cap?d->cap*2:8;d->keys=realloc(d->keys,sizeof(char*)*d->cap);d->vals=realloc(d->vals,sizeof(NvVal)*d->cap);}d->keys[d->len]=nv_strdup(k);d->vals[d->len]=v;d->len++;}\n"
"static void nv_dict_set_value(NvVal d,const char*k,NvVal v){if(d.kind!=NV_DICT)nv_throw(\"Expected a dict\");nv_dict_set(d.as.dict,k,v);}\n"
"static void nv_dict_merge_value(NvVal d,NvVal src){if(d.kind!=NV_DICT||src.kind!=NV_DICT)nv_throw(\"Unpacking ** requires a dict\");for(int i=0;i<src.as.dict->len;i++)nv_dict_set(d.as.dict,src.as.dict->keys[i],src.as.dict->vals[i]);}\n"
"static NvVal nv_dict_get(NvDict*d,const char*k){int i=nv_dict_find(d,k);if(i<0){char buf[512];snprintf(buf,sizeof(buf),\"Key not found: %s\",k);nv_throw(buf);}return d->vals[i];}\n"
"static NvVal nv_get_index(NvVal a,NvVal i){ if(a.kind==NV_LIST){long long n=(long long)nv_num(i);if(n<0)n=a.as.list->len+n;if(n<0||n>=a.as.list->len)nv_throw(\"List index out of range\");return a.as.list->items[n];} if(a.kind==NV_DICT){if(i.kind!=NV_STR)nv_throw(\"Expected a string key\");return nv_dict_get(a.as.dict,i.as.s);} if(a.kind==NV_STR){long long n=(long long)nv_num(i);int len=(int)strlen(a.as.s);if(n<0)n=len+n;if(n<0||n>=len)nv_throw(\"String index out of range\");char tmp[2]={a.as.s[n],0};return nv_str(tmp);} nv_throw(\"This value is not indexable\");return nv_none();}\n"
"static void nv_set_index(NvVal a,NvVal i,NvVal v){ if(a.kind==NV_LIST){long long n=(long long)nv_num(i);if(n<0)n=a.as.list->len+n;if(n<0||n>=a.as.list->len)nv_throw(\"List index out of range\");a.as.list->items[n]=v;return;} if(a.kind==NV_DICT){if(i.kind!=NV_STR)nv_throw(\"Expected a string key\");nv_dict_set(a.as.dict,i.as.s,v);return;} nv_throw(\"This value does not support indexed assignment\");}\n"
"static NvVal nv_get_field(NvVal a,const char*name){if(a.kind!=NV_OBJ)nv_throw(\"Accès à un champ sur une valeur qui n'est pas un objet\");return nv_dict_get(a.as.obj->fields,name);}\n"
"static void nv_set_field(NvVal a,const char*name,NvVal v){if(a.kind!=NV_OBJ)nv_throw(\"Affectation de champ sur une valeur qui n'est pas un objet\");nv_dict_set(a.as.obj->fields,name,v);}\n"
"static NvVal nv_object_new(const char*type){NvVal v=nv_none();v.kind=NV_OBJ;v.as.obj=nv_xmalloc(sizeof(NvObj));v.as.obj->type=nv_strdup(type);v.as.obj->fields=nv_dict_new();return v;}\n"
"static int nv_len(NvVal v){if(v.kind==NV_LIST)return v.as.list->len;if(v.kind==NV_DICT)return v.as.dict->len;if(v.kind==NV_STR)return(int)strlen(v.as.s);nv_throw(\"len() requires a list, dict, or string\");return 0;}\n"
"static NvVal nv_iter_get(NvVal v,int i){if(v.kind==NV_LIST)return v.as.list->items[i];if(v.kind==NV_DICT)return nv_str(v.as.dict->keys[i]);if(v.kind==NV_STR){char t[2]={v.as.s[i],0};return nv_str(t);}nv_throw(\"This value is not iterable\");return nv_none();}\n"
"static NvCall nv_call_new(void){NvCall c;c.args=NULL;c.argc=0;c.cap=0;c.kw=nv_dict_new();return c;}\n"
"static void nv_call_add(NvCall*c,NvVal v){if(c->argc==c->cap){c->cap=c->cap?c->cap*2:8;c->args=realloc(c->args,sizeof(NvVal)*c->cap);}c->args[c->argc++]=v;}\n"
"static void nv_call_spread(NvCall*c,NvVal v){if(v.kind!=NV_LIST)nv_throw(\"Unpacking * requires a list\");for(int i=0;i<v.as.list->len;i++)nv_call_add(c,v.as.list->items[i]);}\n"
"static void nv_call_kw(NvCall*c,const char*k,NvVal v){nv_dict_set(c->kw,k,v);}\n"
"static void nv_call_kwspread(NvCall*c,NvVal v){if(v.kind!=NV_DICT)nv_throw(\"Unpacking ** requires a dict\");for(int i=0;i<v.as.dict->len;i++)nv_dict_set(c->kw,v.as.dict->keys[i],v.as.dict->vals[i]);}\n"
"static void nv_dict_free_shallow(NvDict*d){if(!d)return;for(int i=0;i<d->len;i++)free(d->keys[i]);free(d->keys);free(d->vals);free(d);}\n"
"static void nv_call_free(NvCall*c){if(!c)return;free(c->args);nv_dict_free_shallow(c->kw);c->args=NULL;c->kw=NULL;c->argc=0;c->cap=0;}\n"
"static NvVal nv_arg(NvVal*args,int argc,NvDict*kw,int pos,const char*name){if(pos<argc)return args[pos];int i=nv_dict_find(kw,name);if(i>=0)return kw->vals[i];char buf[512];snprintf(buf,sizeof(buf),\"Missing argument: %s\",name);nv_throw(buf);return nv_none();}\n"
"static void nv_expect_type(NvVal v,const char*t,const char*name){int ok=0;if(strcmp(t,\"int\")==0)ok=v.kind==NV_INT||v.kind==NV_UINT;else if(strcmp(t,\"float\")==0)ok=v.kind==NV_FLOAT||v.kind==NV_INT||v.kind==NV_UINT;else if(strcmp(t,\"str\")==0)ok=v.kind==NV_STR;else if(strcmp(t,\"bool\")==0)ok=v.kind==NV_BOOL;else if(strcmp(t,\"list\")==0)ok=v.kind==NV_LIST;else if(strcmp(t,\"dict\")==0)ok=v.kind==NV_DICT;else if(strcmp(t,\"object\")==0)ok=v.kind==NV_OBJ;else if(strcmp(t,\"file\")==0)ok=v.kind==NV_FILE;else if(strcmp(t,\"memory\")==0)ok=v.kind==NV_MEMORY;else ok=1;if(!ok){char buf[512];snprintf(buf,sizeof(buf),\"Invalid type for %s: expected %s\",name,t);nv_throw(buf);}}\n"
"static NvVal nv_dispatch_call(const char*,NvVal*,int,NvDict*);\n"
"static NvVal nv_dispatch_method(NvVal,const char*,NvVal*,int,NvDict*);\n"
;

/* ============================
   Blocs et contexte de compilation
   ============================ */

typedef enum {
    BLK_IF, BLK_WHILE, BLK_FOR,
    BLK_FUNC, BLK_OBJECT, BLK_STRUCTURE,
    BLK_TRY, BLK_CATCH, BLK_ALWAYS,
    BLK_MATCH, BLK_CASE, BLK_WITH, BLK_WITH_MEMORY
} BlockKind;

typedef enum { OUT_MAIN, OUT_FUNC, OUT_NONE } OutKind;

typedef struct {
    BlockKind kind;
    int indent;
    OutKind out_kind;
    int try_id;
    int case_count;
    char owner[MAX_NAME];
} Block;

static Block blocks[MAX_BLOCKS];
static int block_count=0;
static int try_counter=0;

static FILE *main_out=NULL;
static FILE *func_out=NULL;

static FILE *out_for_kind(OutKind k) {
    if (k==OUT_MAIN) return main_out;
    if (k==OUT_FUNC) return func_out;
    return NULL;
}

static OutKind current_output(void) {
    for (int i=block_count-1;i>=0;i--) {
        if (blocks[i].out_kind!=OUT_NONE) return blocks[i].out_kind;
    }
    return OUT_MAIN;
}

static const char *current_owner(void) {
    for (int i=block_count-1;i>=0;i--) {
        if (blocks[i].kind==BLK_OBJECT || blocks[i].kind==BLK_STRUCTURE) return blocks[i].owner;
    }
    return NULL;
}

static Block *top_block(void){return block_count?&blocks[block_count-1]:NULL;}

static int current_function_body_indent(void){
    for(int i=block_count-1;i>=0;i--){
        if(blocks[i].kind==BLK_FUNC)
            return blocks[i].indent + 4;
    }
    return -1;
}

static void push_block(BlockKind k,int indent,OutKind out,const char*owner,int try_id){
    if(block_count>=MAX_BLOCKS)die("Trop de blocs imbriqués");
    Block*b=&blocks[block_count++];memset(b,0,sizeof(*b));b->kind=k;b->indent=indent;b->out_kind=out;b->try_id=try_id;if(owner)snprintf(b->owner,sizeof(b->owner),"%s",owner);
}

static void close_one_block(void) {
    Block b=blocks[--block_count];
    FILE*out=out_for_kind(b.out_kind);
    switch(b.kind){
        case BLK_FUNC:
            emit_indent(out,b.indent); fprintf(out,"    return nv_none();\n");
            emit_indent(out,b.indent); fprintf(out,"}\n\n");
            break;
        case BLK_OBJECT: case BLK_STRUCTURE:
            break;
        case BLK_TRY:
            /* Un tente sans capture n'est pas utile, mais on ferme proprement. */
            if(out){emit_indent(out,b.indent);fprintf(out,"nv_try_top = __try%d.prev;\n",b.try_id);emit_indent(out,b.indent);fprintf(out,"}\n");}
            break;
        case BLK_FOR:
            if(out){emit_indent(out,b.indent);fprintf(out,"} }\n");}
            break;
        case BLK_WITH:
            if(out){emit_indent(out,b.indent+4);fprintf(out,"nv_file_close(%s);\n",b.owner);emit_indent(out,b.indent);fprintf(out,"}\n");}
            break;
        case BLK_WITH_MEMORY:
            if(out){emit_indent(out,b.indent+4);fprintf(out,"nv_memory_scope_leave(%s);\n",b.owner);emit_indent(out,b.indent);fprintf(out,"}\n");}
            break;
        case BLK_MATCH:
            if(out){emit_indent(out,b.indent);fprintf(out,"}\n");}
            break;
        default:
            if(out){emit_indent(out,b.indent);fprintf(out,"}\n");}
            break;
    }
}

static void close_blocks_above_indent(int indent) {
    while(block_count>0 && blocks[block_count-1].indent>indent) close_one_block();
}

static void emit_memory_cleanup_for_return(FILE *out,int indent){
    for(int bi=block_count-1;bi>=0;bi--){
        if(blocks[bi].kind==BLK_WITH_MEMORY){
            emit_indent(out,indent);
            fprintf(out,"nv_memory_scope_leave(%s);\n",blocks[bi].owner);
        }
        if(blocks[bi].kind==BLK_FUNC)break;
    }
}

static void emit_memory_cleanup_for_loop_jump(FILE *out,int indent){
    int loop_index=-1;

    for(int bi=block_count-1;bi>=0;bi--){
        if(blocks[bi].kind==BLK_FOR ||
           blocks[bi].kind==BLK_WHILE){
            loop_index=bi;
            break;
        }
    }

    if(loop_index<0)return;

    for(int bi=block_count-1;bi>loop_index;bi--){
        if(blocks[bi].kind==BLK_WITH_MEMORY){
            emit_indent(out,indent);
            fprintf(out,"nv_memory_scope_leave(%s);\n",blocks[bi].owner);
        }
    }
}



/* ==========================================================
   Remontée des variables locales de fonction.

   Clariox utilise une portée de fonction pour les variables
   ordinaires. En C, une déclaration réalisée dans un if/while
   serait limitée à ce bloc.

   Une première déclaration imbriquée marquée :

       [CLARIOX_HOIST_LOCAL] NvVal y = expr;

   devient :

       NvVal y = nv_none();

       ...
       y = expr;

   La transformation est volontairement limitée aux marqueurs
   émis par emit_set_lvalue().
   ========================================================== */

static int is_generated_function_signature(
    const char *line
){
    return
        strncmp(line,"static NvVal ",13)==0 &&
        strstr(line,"(NvVal *__args")!=NULL;
}

static int extract_hoisted_local_name(
    const char *line,
    char *name,
    size_t name_size
){
    const char *marker =
        strstr(line,"/*CLARIOX_HOIST_LOCAL*/");

    if(!marker)
        return 0;

    const char *p =
        strstr(marker,"NvVal ");

    if(!p)
        return 0;

    p += 6;

    size_t n = 0;

    while(
        (isalnum((unsigned char)p[n]) || p[n]=='_') &&
        n + 1 < name_size
    ){
        n++;
    }

    if(n==0)
        return 0;

    memcpy(name,p,n);
    name[n]='\0';

    return 1;
}

static int is_function_prologue_line(
    const char *line
){
    const char *p=line;

    while(*p==' ' || *p=='\t')
        p++;

    if(*p=='\0' || *p=='\n' || *p=='\r')
        return 1;

    if(
        strncmp(p,"NvVal ",6)==0 &&
        strstr(p," = nv_arg(")!=NULL
    ){
        return 1;
    }

    if(strncmp(p,"nv_expect_type(",15)==0)
        return 1;

    return 0;
}

static void emit_line_without_hoist_marker(
    FILE *dst,
    const char *line
){
    const char *marker =
        strstr(line,"/*CLARIOX_HOIST_LOCAL*/");

    if(!marker){
        fputs(line,dst);
        return;
    }

    fwrite(
        line,
        1,
        (size_t)(marker-line),
        dst
    );

    const char *p =
        marker + strlen("/*CLARIOX_HOIST_LOCAL*/");

    while(*p==' ' || *p=='\t')
        p++;

    if(strncmp(p,"NvVal ",6)==0)
        p += 6;

    fputs(p,dst);
}

static void flush_function_segment(
    FILE *segment,
    FILE *dst,
    VarScope *locals
){
    if(!segment)
        return;

    fflush(segment);
    rewind(segment);

    char line[MAX_LINE * 8];

    if(!fgets(line,sizeof(line),segment))
        return;

    /* Signature de fonction. */
    fputs(line,dst);

    int declarations_emitted = 0;

    while(fgets(line,sizeof(line),segment)){
        if(
            !declarations_emitted &&
            !is_function_prologue_line(line)
        ){
            for(int i=0;i<locals->count;i++){
                fprintf(
                    dst,
                    "    NvVal %s = nv_none();\n",
                    locals->vars[i]
                );
            }

            declarations_emitted = 1;
        }

        emit_line_without_hoist_marker(
            dst,
            line
        );
    }

    /*
     * Cas théorique d'une fonction ne contenant que son
     * prologue. Les marqueurs ne devraient alors pas exister,
     * mais garder le traitement complet.
     */
    if(!declarations_emitted){
        for(int i=0;i<locals->count;i++){
            fprintf(
                dst,
                "    NvVal %s = nv_none();\n",
                locals->vars[i]
            );
        }
    }
}

static void emit_functions_with_hoisted_locals(
    FILE *src,
    FILE *dst
){
    rewind(src);

    FILE *segment = NULL;
    VarScope locals;
    memset(&locals,0,sizeof(locals));

    char line[MAX_LINE * 8];

    while(fgets(line,sizeof(line),src)){
        if(is_generated_function_signature(line)){
            if(segment){
                flush_function_segment(
                    segment,
                    dst,
                    &locals
                );

                fclose(segment);
            }

            segment = tmpfile();

            if(!segment)
                die("Unable to create function hoist temporary file");

            memset(
                &locals,
                0,
                sizeof(locals)
            );
        }

        if(!segment){
            fputs(line,dst);
            continue;
        }

        char name[MAX_NAME];

        if(
            extract_hoisted_local_name(
                line,
                name,
                sizeof(name)
            )
        ){
            scope_add(
                &locals,
                name
            );
        }

        fputs(line,segment);
    }

    if(segment){
        flush_function_segment(
            segment,
            dst,
            &locals
        );

        fclose(segment);
    }
}


/* ============================
   Analyse des définitions
   ============================ */

static void parse_params(char *src, FuncMeta *fm) {
    char *p=trim(src);
    fm->param_count=0;
    if(!*p)return;
    char *save=NULL;
    for(char *tok=strtok_r(p,",",&save); tok; tok=strtok_r(NULL,",",&save)){
        if(fm->param_count>=MAX_PARAMS)die("Too many parameters in %s",fm->name);
        char *item=trim(tok); char *colon=strchr(item,':');
        ParamMeta *pm=&fm->params[fm->param_count++]; memset(pm,0,sizeof(*pm));
        if(colon){*colon='\0';snprintf(pm->name,sizeof(pm->name),"%s",trim(item));snprintf(pm->type,sizeof(pm->type),"%s",trim(colon+1));}
        else{snprintf(pm->name,sizeof(pm->name),"%s",item);pm->type[0]='\0';}
        if(!is_ident(pm->name))die("Invalid parameter: %s",pm->name);
    }
}

static FuncMeta *register_function(const char *name,const char *owner,char *params,const char *ret) {
    if(func_count>=MAX_FUNCS)die("Too many functions");
    FuncMeta *fm=&funcs[func_count++]; memset(fm,0,sizeof(*fm));
    snprintf(fm->name,sizeof(fm->name),"%s",name);
    if(owner&&*owner)snprintf(fm->owner,sizeof(fm->owner),"%s",owner);
    if(owner&&*owner)snprintf(fm->internal,sizeof(fm->internal),"clariox_%s_%s",owner,name); else snprintf(fm->internal,sizeof(fm->internal),"clariox_fn_%s",name);
    snprintf(fm->return_type,sizeof(fm->return_type),"%s",ret&&*ret?ret:"auto");
    parse_params(params,fm);
    return fm;
}

static void emit_function_header(FuncMeta *fm,int indent) {
    func_scope.count=0;
    func_consts.count=0;
    fprintf(func_out,"static NvVal %s(NvVal *__args, int __argc, NvDict *__kwargs) {\n",fm->internal);
    for(int i=0;i<fm->param_count;i++){
        ParamMeta *p=&fm->params[i];
        fprintf(func_out,"    NvVal %s = nv_arg(__args, __argc, __kwargs, %d, \"%s\");\n",p->name,i,p->name);
        if(p->type[0])fprintf(func_out,"    nv_expect_type(%s, \"%s\", \"%s\");\n",p->name,p->type,p->name);
        scope_add_typed(
            &func_scope,
            p->name,
            p->type[0] ? p->type : NULL
        );
    }
    (void)indent;
}

static TypeMeta *register_type(const char *name,UserTypeKind kind){
    if(find_type(name))die("Type déjà défini : %s",name);
    if(type_count>=MAX_TYPES)die("Trop de types");
    TypeMeta*t=&types[type_count++];memset(t,0,sizeof(*t));snprintf(t->name,sizeof(t->name),"%s",name);t->kind=kind;return t;
}

static TypeMeta *current_type_meta(void){
    const char*owner=current_owner();return owner?find_type(owner):NULL;
}

/* ============================
   Affectations et instructions
   ============================ */

static int find_top_level_assignment(const char *s, int *op_len) {
    int dp=0,db=0,dc=0,instr=0,esc=0;
    for(int i=0;s[i];i++){
        char c=s[i];
        if(esc){esc=0;continue;} if(instr&&c=='\\'){esc=1;continue;} if(c=='"'){instr=!instr;continue;} if(instr)continue;
        if(c=='(')dp++;else if(c==')')dp--;else if(c=='[')db++;else if(c==']')db--;else if(c=='{')dc++;else if(c=='}')dc--;
        if(dp||db||dc)continue;
        if((c=='+'||c=='-'||c=='*'||c=='/')&&s[i+1]=='='){*op_len=2;return i;}
        if(c=='=' && s[i+1]!='=' && (i==0||(s[i-1]!='!'&&s[i-1]!='<'&&s[i-1]!='>'))){*op_len=1;return i;}
    }
    return -1;
}


static char *compile_memory_alloc_expr(
    const char *src,
    int lineno
) {
    char tmp[MAX_LINE];
    snprintf(tmp,sizeof(tmp),"%s",src);
    char *s=trim(tmp);

    /*
     * Allocation brute historique :
     *     alloc(1024)
     */
    if(
        strncmp(s,"alloc",5)==0 &&
        (s[5]=='(' || isspace((unsigned char)s[5]))
    ){
        manual_alloc_context=1;
        char *e=compile_expr(s,lineno);
        manual_alloc_context=0;
        return e;
    }

    /*
     * Mémoire typée :
     *     alloc[int8](count)
     *     alloc[uint32](count)
     *     alloc[float32](count)
     *     ...
     */
    if(strncmp(s,"alloc[",6)!=0)
        die(
            "Line %d: memory declaration requires "
            "alloc(...) or alloc[type](count)",
            lineno
        );

    char *close=strchr(s+6,']');
    if(!close)
        die("Line %d: missing ']' in typed memory allocation",lineno);

    *close='\0';
    char *type=trim(s+6);
    char *after=trim(close+1);

    size_t n=strlen(after);
    if(
        n<3 ||
        after[0]!='(' ||
        after[n-1]!=')'
    ){
        die(
            "Line %d: typed allocation must use alloc[type](count)",
            lineno
        );
    }

    after[n-1]='\0';
    char *count_src=trim(after+1);

    if(!*count_src)
        die("Line %d: typed allocation requires an element count",lineno);

    char *count_expr=compile_expr(
        count_src,
        lineno
    );

    const char *kind=NULL;

    if(strcmp(type,"byte")==0)
        kind="NV_MEM_BYTE";
    else if(strcmp(type,"int8")==0)
        kind="NV_MEM_INT8";
    else if(strcmp(type,"uint8")==0)
        kind="NV_MEM_UINT8";
    else if(strcmp(type,"int16")==0)
        kind="NV_MEM_INT16";
    else if(strcmp(type,"uint16")==0)
        kind="NV_MEM_UINT16";
    else if(strcmp(type,"int32")==0)
        kind="NV_MEM_INT32";
    else if(strcmp(type,"uint32")==0)
        kind="NV_MEM_UINT32";
    else if(strcmp(type,"int64")==0)
        kind="NV_MEM_INT64";
    else if(strcmp(type,"uint64")==0)
        kind="NV_MEM_UINT64";
    else if(strcmp(type,"float32")==0)
        kind="NV_MEM_FLOAT32";
    else if(strcmp(type,"float64")==0)
        kind="NV_MEM_FLOAT64";
    else{
        free(count_expr);

        die(
            "Line %d: unsupported memory type '%s'",
            lineno,
            type
        );
    }

    char *result=fmtdup(
        "nv_memory_alloc_kind(%s,%s)",
        count_expr,
        kind
    );

    free(count_expr);

    return result;
}


/* ============================
   Vérification statique simple des types
   ============================ */

static int is_builtin_static_type(const char *type) {
    if (!type || !*type) return 0;

    return
        strcmp(type, "int") == 0 ||
        strcmp(type, "float") == 0 ||
        strcmp(type, "str") == 0 ||
        strcmp(type, "bool") == 0 ||
        strcmp(type, "none") == 0;
}

static const char *infer_simple_expr_type(
    const char *src,
    int lineno
) {
    Lexer lx;
    lexer_init(&lx, src, lineno);

    /* "Alice" */
    if (
        lx.cur.kind == TK_STRING &&
        lx.next.kind == TK_EOF
    ) {
        return "str";
    }

    /* 42 / 2.5 */
    if (
        lx.cur.kind == TK_NUMBER &&
        lx.next.kind == TK_EOF
    ) {
        if (
            strchr(lx.cur.text, '.') ||
            strchr(lx.cur.text, 'e') ||
            strchr(lx.cur.text, 'E')
        ) {
            return "float";
        }

        return "int";
    }

    /* -42 / +42 / -2.5 */
    if (
        (lx.cur.kind == TK_MINUS || lx.cur.kind == TK_PLUS) &&
        lx.next.kind == TK_NUMBER
    ) {
        advance(&lx);

        if (lx.next.kind != TK_EOF) {
            return NULL;
        }

        if (
            strchr(lx.cur.text, '.') ||
            strchr(lx.cur.text, 'e') ||
            strchr(lx.cur.text, 'E')
        ) {
            return "float";
        }

        return "int";
    }

    /* true / false / none */
    if (
        lx.cur.kind == TK_IDENT &&
        lx.next.kind == TK_EOF
    ) {
        if (
            strcmp(lx.cur.text, "true") == 0 ||
            strcmp(lx.cur.text, "false") == 0
        ) {
            return "bool";
        }

        if (strcmp(lx.cur.text, "none") == 0) {
            return "none";
        }
    }

    /*
     * Expression complexe :
     * aucune conclusion statique pour le moment.
     */
    return NULL;
}

static int static_type_compatible(
    const char *expected,
    const char *actual
) {
    /*
     * Ne pas bloquer les types utilisateur ou les types
     * que cette première passe ne connaît pas encore.
     */
    if (!is_builtin_static_type(expected)) {
        return 1;
    }

    if (!actual) {
        return 1;
    }

    if (strcmp(expected, actual) == 0) {
        return 1;
    }

    /*
     * Clariox autorise déjà un int là où un float
     * est demandé.
     */
    if (
        strcmp(expected, "float") == 0 &&
        strcmp(actual, "int") == 0
    ) {
        return 1;
    }

    return 0;
}

static void emit_set_lvalue(FILE*out,int indent,const char*lhs,const char*rhs,int lineno,VarScope*scope,const char*annot_type,const char*augop){
    char tmp[MAX_LINE];snprintf(tmp,sizeof(tmp),"%s",lhs);char*l=trim(tmp);
    /* champ objet : obj.nom */
    char *dot=strrchr(l,'.');
    if(dot){*dot='\0';char*obj=trim(l);char*field=trim(dot+1);if(!is_ident(field))die("Line %d: invalid field",lineno);char*objexpr=compile_expr(obj,lineno);char*value=NULL;if(augop){char*cur=fmtdup("nv_get_field(%s, \"%s\")",objexpr,field);char*rv=compile_expr(rhs,lineno);value=fmtdup("%s(%s,%s)",strcmp(augop,"+")==0?"nv_add":strcmp(augop,"-")==0?"nv_sub":strcmp(augop,"*")==0?"nv_mul":"nv_div",cur,rv);free(cur);free(rv);}else value=compile_expr(rhs,lineno);emit_indent(out,indent);fprintf(out,"nv_set_field(%s, \"%s\", %s);\n",objexpr,field,value);free(objexpr);free(value);return;}
    /* index : a[expr] */
    size_t n=strlen(l); if(n>2 && l[n-1]==']'){
        int depth=0;int open=-1;for(int i=(int)n-1;i>=0;i--){if(l[i]==']')depth++;else if(l[i]=='['){depth--;if(depth==0){open=i;break;}}}
        if(open>0){char base[MAX_LINE],idx[MAX_LINE];memcpy(base,l,(size_t)open);base[open]='\0';snprintf(idx,sizeof(idx),"%.*s",(int)n-open-2,l+open+1);char*be=compile_expr(trim(base),lineno);char*ie=compile_expr(trim(idx),lineno);char*val=NULL;if(augop){char*cur=fmtdup("nv_get_index(%s,%s)",be,ie);char*rv=compile_expr(rhs,lineno);val=fmtdup("%s(%s,%s)",strcmp(augop,"+")==0?"nv_add":strcmp(augop,"-")==0?"nv_sub":strcmp(augop,"*")==0?"nv_mul":"nv_div",cur,rv);free(cur);free(rv);}else val=compile_expr(rhs,lineno);emit_indent(out,indent);fprintf(out,"nv_set_index(%s, %s, %s);\n",be,ie,val);free(be);free(ie);free(val);return;}
    }
    /* variable simple, éventuellement typée */
    char name[MAX_NAME];snprintf(name,sizeof(name),"%s",l);char typebuf[MAX_NAME]={0};char*colon=strchr(name,':');if(colon){*colon='\0';snprintf(typebuf,sizeof(typebuf),"%s",trim(colon+1));}
    char*vn=trim(name);if(!is_ident(vn))die("Line %d: invalid variable '%s'",lineno,vn);
    const char*type =
        annot_type&&*annot_type
        ? annot_type
        : (typebuf[0] ? typebuf : NULL);

    const char *declared_type =
        scope_get_type(scope, vn);

    /*
     * Une variable déjà explicitement typée ne peut
     * pas être réannotée avec un autre type.
     */
    if (
        declared_type &&
        type &&
        strcmp(declared_type, type) != 0
    ) {
        die(
            "Line %d: conflicting type for '%s': declared %s, found %s",
            lineno,
            vn,
            declared_type,
            type
        );
    }

    /*
     * Pour une nouvelle variable, l'annotation courante
     * est le type attendu.
     *
     * Pour une variable existante explicitement typée,
     * son type enregistré continue de s'appliquer aux
     * affectations suivantes.
     */
    const char *expected_type =
        declared_type
        ? declared_type
        : type;

    int type_checked_statically = 0;

    if (expected_type && !augop) {
        const char *actual_type =
            infer_simple_expr_type(rhs, lineno);

        if (
            actual_type &&
            !static_type_compatible(
                expected_type,
                actual_type
            )
        ) {
            die(
                "Line %d: incompatible type for '%s': expected %s, found %s",
                lineno,
                vn,
                expected_type,
                actual_type
            );
        }

        /*
         * Le contrôle runtime n'est supprimé que pour
         * l'annotation présente sur cette instruction.
         */
        if (
            type &&
            actual_type &&
            is_builtin_static_type(type) &&
            static_type_compatible(
                type,
                actual_type
            )
        ) {
            type_checked_statically = 1;
        }
    }

    VarScope *consts = (scope == &func_scope) ? &func_consts : &main_consts;
    if (scope_has(consts, vn)) die("Line %d: '%s' is const and cannot be modified", lineno, vn);
    char*val=NULL;
    if(augop){if(!scope_has(scope,vn))die("Line %d: unknown variable '%s'",lineno,vn);char*rv=compile_expr(rhs,lineno);val=fmtdup("%s(%s,%s)",strcmp(augop,"+")==0?"nv_add":strcmp(augop,"-")==0?"nv_sub":strcmp(augop,"*")==0?"nv_mul":"nv_div",vn,rv);free(rv);}else val=compile_expr(rhs,lineno);
    emit_indent(out,indent);
    if(!scope_has(scope,vn)){
        int hoist_function_local = 0;

        if(scope == &func_scope){
            int function_body_indent =
                current_function_body_indent();

            if(
                function_body_indent >= 0 &&
                indent > function_body_indent
            ){
                hoist_function_local = 1;
            }
        }

        if(hoist_function_local){
            fprintf(
                out,
                "/*CLARIOX_HOIST_LOCAL*/ "
                "NvVal %s = %s;\n",
                vn,
                val
            );
        }else{
            fprintf(
                out,
                "NvVal %s = %s;\n",
                vn,
                val
            );
        }

        scope_add_typed(
            scope,
            vn,
            type
        );
    }else{
        fprintf(
            out,
            "%s = %s;\n",
            vn,
            val
        );
    }
    if(type && !type_checked_statically){
        emit_indent(out,indent);
        fprintf(
            out,
            "nv_expect_type(%s, \"%s\", \"%s\");\n",
            vn,
            type,
            vn
        );
    }
    free(val);
}

/* ============================
   Génération des dispatchers
   ============================ */

static void emit_dispatch(FILE*out){
    fprintf(out,"\nstatic NvVal nv_builtin_print(NvVal *args,int argc){for(int i=0;i<argc;i++){if(i)printf(\" \");nv_print_one(args[i]);}printf(\"\\n\");return nv_none();}\n");
    fprintf(out,"static NvVal nv_dispatch_call(const char *name,NvVal *args,int argc,NvDict *kw){\n");
    fprintf(out,"    if(strcmp(name,\"print\")==0) return nv_builtin_print(args,argc);\n");
    fprintf(out,"    if(strcmp(name,\"input\")==0){ if(argc>0){nv_print_one(args[0]);fflush(stdout);} char b[4096]; if(!fgets(b,sizeof(b),stdin))return nv_str(\"\"); b[strcspn(b,\"\\r\\n\")]=0; return nv_str(b); }\n");
    fprintf(out,"    if(strcmp(name,\"input_int\")==0){ if(argc>0){nv_print_one(args[0]);fflush(stdout);} char b[256]; if(!fgets(b,sizeof(b),stdin))return nv_int(0); b[strcspn(b,\"\\r\\n\")]=0; return nv_parse_integer_text(b); }\n");
    fprintf(out,"    if(strcmp(name,\"input_float\")==0){ if(argc>0){nv_print_one(args[0]);fflush(stdout);} char b[256]; if(!fgets(b,sizeof(b),stdin))return nv_float(0); char *e=NULL; double v=strtod(b,&e); if(e==b)nv_throw(\"Expected a floating-point number\"); return nv_float(v); }\n");
    fprintf(out,"    if(strcmp(name,\"int\")==0){ if(argc<1)nv_throw(\"int() expects a value\"); if(args[0].kind==NV_INT||args[0].kind==NV_UINT)return args[0]; if(args[0].kind==NV_STR)return nv_parse_integer_text(args[0].as.s); return nv_integer_from_double(nv_num(args[0])); }\n");
    fprintf(out,"    if(strcmp(name,\"float\")==0){ if(argc<1)nv_throw(\"float() expects a value\"); if(args[0].kind==NV_STR)return nv_float(strtod(args[0].as.s,NULL)); return nv_float(nv_num(args[0])); }\n");
    fprintf(out,"    if(strcmp(name,\"str\")==0){ if(argc<1)nv_throw(\"str() expects a value\"); return nv_to_str(args[0]); }\n");
    fprintf(out,"    if(strcmp(name,\"alloc\")==0){ if(argc!=1)nv_throw(\"alloc() expects exactly one size\"); return nv_memory_alloc(args[0]); }\n");
    fprintf(out,"    if(strcmp(name,\"free\")==0){ if(argc!=1)nv_throw(\"free() expects exactly one memory block\"); return nv_memory_free(args[0]); }\n");
    fprintf(out,"    if(strcmp(name,\"open\")==0){ if(argc<1||args[0].kind!=NV_STR)nv_throw(\"open() expects a string path\"); const char*m=\"r\"; if(argc>1&&args[1].kind==NV_STR){ if(strcmp(args[1].as.s,\"read\")==0)m=\"r\"; else if(strcmp(args[1].as.s,\"write\")==0)m=\"w\"; else if(strcmp(args[1].as.s,\"append\")==0)m=\"a\"; else m=args[1].as.s;} FILE*f=fopen(args[0].as.s,m); if(!f)nv_throwf(\"Unable to open file: %%s\",args[0].as.s); return nv_file_value(f); }\n");
    fprintf(out,"    if(strcmp(name,\"read_file\")==0){ if(argc<1||args[0].kind!=NV_STR)nv_throw(\"read_file() expects a string path\"); FILE*f=fopen(args[0].as.s,\"r\"); if(!f)nv_throwf(\"Unable to open file: %%s\",args[0].as.s); NvVal fv=nv_file_value(f); NvVal r=nv_file_read(fv); fclose(f); return r; }\n");
    fprintf(out,"    if(strcmp(name,\"write_file\")==0){ if(argc<2||args[0].kind!=NV_STR)nv_throw(\"write_file() expects a path and a value\"); FILE*f=fopen(args[0].as.s,\"w\"); if(!f)nv_throwf(\"Unable to open file: %%s\",args[0].as.s); NvVal fv=nv_file_value(f); nv_file_write(fv,args[1]); fclose(f); return nv_none(); }\n");
    fprintf(out,"    if(strcmp(name,\"len\")==0){ if(argc<1)nv_throw(\"len() expects a value\"); return nv_int(nv_len(args[0])); }\n");
    fprintf(out,"    if(strcmp(name,\"range\")==0){ long long a=0,b=0,p=1; if(argc==1){b=(long long)nv_num(args[0]);} else if(argc>=2){a=(long long)nv_num(args[0]);b=(long long)nv_num(args[1]);if(argc>=3)p=(long long)nv_num(args[2]);} else nv_throw(\"range() expects 1 to 3 arguments\"); if(p==0)nv_throw(\"range() step cannot be zero\"); NvVal l=nv_list_new(); if(p>0){for(long long i=a;i<b;i+=p)nv_list_append(l,nv_int(i));}else{for(long long i=a;i>b;i+=p)nv_list_append(l,nv_int(i));} return l;}\n");
    fprintf(out,"    if(strcmp(name,\"error\")==0){ if(argc<1||args[0].kind!=NV_STR)nv_throw(\"error() expects a string\"); nv_throw(args[0].as.s); }\n");
    for(int i=0;i<func_count;i++) if(funcs[i].owner[0]=='\0') fprintf(out,"    if(strcmp(name,\"%s\")==0) return %s(args,argc,kw);\n",funcs[i].name,funcs[i].internal);
    for(int i=0;i<type_count;i++){
        TypeMeta*t=&types[i];
        fprintf(out,"    if(strcmp(name,\"%s\")==0){ NvVal o=nv_object_new(\"%s\");\n",t->name,t->name);
        if(t->kind==TYPE_STRUCTURE){
            for(int f=0;f<t->field_count;f++){
                fprintf(out,"        { NvVal v=nv_arg(args,argc,kw,%d,\"%s\"); nv_set_field(o,\"%s\",v);",f,t->fields[f].name,t->fields[f].name);
                if(t->fields[f].type[0])fprintf(out," nv_expect_type(v,\"%s\",\"%s\");",t->fields[f].type,t->fields[f].name);
                fprintf(out," }\n");
            }
            fprintf(out,"        return o; }\n");
        }else{
            FuncMeta*init=find_method(t->name,"init");
            if(init){fprintf(out,"        NvVal *margs=nv_xmalloc(sizeof(NvVal)*(argc+1)); margs[0]=o; for(int i=0;i<argc;i++)margs[i+1]=args[i]; (void)%s(margs,argc+1,kw); free(margs); return o; }\n",init->internal);}else{
                for(int f=0;f<t->field_count;f++)fprintf(out,"        if(%d<argc) nv_set_field(o,\"%s\",args[%d]);\n",f,t->fields[f].name,f);
                fprintf(out,"        return o; }\n");
            }
        }
    }
    fprintf(out,"    nv_throwf(\"Fonction inconnue : %%s\",name); return nv_none();\n}\n");

    fprintf(out,"static NvVal nv_dispatch_method(NvVal self,const char *name,NvVal *args,int argc,NvDict *kw){\n");
    fprintf(out,"    if(self.kind==NV_LIST && strcmp(name,\"append\")==0){ if(argc<1)nv_throw(\"append() expects a value\"); nv_list_append(self,args[0]); return nv_none(); }\n");
    fprintf(out,"    if(self.kind==NV_LIST && strcmp(name,\"remove\")==0){ if(argc<1)nv_throw(\"remove() expects a value\"); for(int i=0;i<self.as.list->len;i++){if(nv_same(self.as.list->items[i],args[0])){for(int j=i;j<self.as.list->len-1;j++)self.as.list->items[j]=self.as.list->items[j+1];self.as.list->len--;return nv_none();}} return nv_none(); }\n");
    fprintf(out,"    if(self.kind==NV_DICT && strcmp(name,\"keys\")==0){ NvVal l=nv_list_new(); for(int i=0;i<self.as.dict->len;i++)nv_list_append(l,nv_str(self.as.dict->keys[i])); return l; }\n");
    fprintf(out,"    if(self.kind==NV_MEMORY && strcmp(name,\"size\")==0){ if(argc!=0)nv_throw(\"memory.size() expects no arguments\"); return nv_memory_size(self); }\n");
    fprintf(out,"    if(self.kind==NV_MEMORY && strcmp(name,\"length\")==0){ if(argc!=0)nv_throw(\"memory.length() expects no arguments\"); return nv_memory_length(self); }\n");
    fprintf(out,"    if(self.kind==NV_MEMORY && strcmp(name,\"type\")==0){ if(argc!=0)nv_throw(\"memory.type() expects no arguments\"); return nv_memory_type_value(self); }\n");
    fprintf(out,"    if(self.kind==NV_MEMORY && strcmp(name,\"read\")==0){ if(argc!=1)nv_throw(\"memory.read() expects an index\"); return nv_memory_read(self,args[0]); }\n");
    fprintf(out,"    if(self.kind==NV_MEMORY && strcmp(name,\"write\")==0){ if(argc!=2)nv_throw(\"memory.write() expects an index and a value\"); return nv_memory_write(self,args[0],args[1]); }\n");
    fprintf(out,"    if(self.kind==NV_MEMORY && strcmp(name,\"fill\")==0){ if(argc==1)return nv_memory_fill_all(self,args[0]); if(argc==3)return nv_memory_fill_range(self,args[0],args[1],args[2]); nv_throw(\"memory.fill() expects value or value, offset, length\"); }\n");
    fprintf(out,"    if(self.kind==NV_MEMORY && strcmp(name,\"copy_from\")==0){ if(argc==1)return nv_memory_copy_all(self,args[0]); if(argc==4)return nv_memory_copy_range(self,args[0],args[1],args[2],args[3]); nv_throw(\"memory.copy_from() expects source or source, source_offset, destination_offset, length\"); }\n");
    fprintf(out,"    if(self.kind==NV_FILE && strcmp(name,\"read\")==0) return nv_file_read(self);\n");
    fprintf(out,"    if(self.kind==NV_FILE && strcmp(name,\"write\")==0){ if(argc<1)nv_throw(\"file.write() expects a value\"); return nv_file_write(self,args[0]); }\n");
    fprintf(out,"    if(self.kind==NV_FILE && strcmp(name,\"close\")==0){ nv_file_close(self); return nv_none(); }\n");
    fprintf(out,"    if(self.kind==NV_OBJ){\n");
    for(int i=0;i<func_count;i++) if(funcs[i].owner[0]){
        fprintf(out,"        if(strcmp(self.as.obj->type,\"%s\")==0 && strcmp(name,\"%s\")==0){ NvVal *margs=nv_xmalloc(sizeof(NvVal)*(argc+1)); margs[0]=self; for(int j=0;j<argc;j++)margs[j+1]=args[j]; NvVal r=%s(margs,argc+1,kw); free(margs); return r; }\n",funcs[i].owner,funcs[i].name,funcs[i].internal);
    }
    fprintf(out,"    }\n    nv_throwf(\"Méthode inconnue : %%s\",name); return nv_none();\n}\n");
}

/* ============================
   Compilation du fichier source
   ============================ */

static void compile_source(FILE*in,const char*cfile){
    char main_tmp[512],func_tmp[512];snprintf(main_tmp,sizeof(main_tmp),"%s.main.tmp",cfile);snprintf(func_tmp,sizeof(func_tmp),"%s.func.tmp",cfile);
    main_out=fopen(main_tmp,"w+");func_out=fopen(func_tmp,"w+");if(!main_out||!func_out)die("Unable to create temporary files");
    main_scope.count=0;func_scope.count=0;main_consts.count=0;func_consts.count=0;block_count=0;

    char line[MAX_LINE];int lineno=0;
    while(fgets(line,sizeof(line),in)){
        lineno++;
        if(strchr(line,'\t'))die("Line %d: use spaces, not tabs",lineno);
        strip_comment(line);
        int indent=0;while(line[indent]==' ')indent++;
        if(indent%4!=0)die("Line %d: indentation must use groups of 4 spaces",lineno);
        char*s=trim(line+indent);if(!*s)continue;

        /* Les listes, tables et appels peuvent s'étendre sur plusieurs lignes. */
        char logical[MAX_LINE * 8];
        snprintf(logical, sizeof(logical), "%s", s);
        int balance = bracket_balance(logical);
        int start_lineno = lineno;
        while (balance > 0) {
            char extra[MAX_LINE];
            if (!fgets(extra, sizeof(extra), in))
                die("Line %d: unclosed parenthesis, bracket, or brace", start_lineno);
            lineno++;
            if (strchr(extra, '\t'))
                die("Line %d: use spaces, not tabs", lineno);
            strip_comment(extra);
            char *part = trim(extra);
            if (!*part) continue;
            size_t have = strlen(logical), need = strlen(part);
            if (have + need + 2 >= sizeof(logical))
                die("Line %d: multiline expression is too long", start_lineno);
            logical[have] = ' ';
            memcpy(logical + have + 1, part, need + 1);
            balance += bracket_balance(part);
        }
        s = logical;
        int statement_lineno = start_lineno;
        (void)statement_lineno;

        /* Fermer d'abord les blocs plus indentés ; garder celui du même niveau
           pour permettre sinon/capture/toujours. */
        close_blocks_above_indent(indent);

        /* Transitions de selon/cas. */
        if(strncmp(s,"case ",5)==0){
            if(top_block() && top_block()->kind==BLK_CASE && top_block()->indent==indent) close_one_block();
            Block *mb=NULL; for(int bi=block_count-1;bi>=0;bi--){if(blocks[bi].kind==BLK_MATCH && blocks[bi].indent==indent-4){mb=&blocks[bi];break;}}
            if(!mb)die("Line %d: 'case' must be inside a match block",lineno);
            size_t sn=strlen(s); if(s[sn-1]!=':')die("Line %d: expected ':' after case",lineno);
            char ce[MAX_LINE]; snprintf(ce,sizeof(ce),"%.*s",(int)sn-6,s+5); char *cv=compile_expr(trim(ce),lineno);
            FILE *mo=out_for_kind(mb->out_kind); emit_indent(mo,indent);
            fprintf(mo,mb->case_count?"else if (nv_truth(nv_eq(__match%d, %s))) {\n":"if (nv_truth(nv_eq(__match%d, %s))) {\n",mb->try_id,cv);
            free(cv); mb->case_count++; push_block(BLK_CASE,indent,mb->out_kind,NULL,0); continue;
        }
        if(strcmp(s,"else:")==0 && top_block() && top_block()->kind==BLK_CASE && top_block()->indent==indent){
            close_one_block(); Block *mb=NULL; for(int bi=block_count-1;bi>=0;bi--){if(blocks[bi].kind==BLK_MATCH && blocks[bi].indent==indent-4){mb=&blocks[bi];break;}}
            if(!mb)die("Line %d: match else without a match block",lineno);
            FILE *mo=out_for_kind(mb->out_kind); emit_indent(mo,indent); fprintf(mo,"else {\n"); mb->case_count++; push_block(BLK_CASE,indent,mb->out_kind,NULL,0); continue;
        }

        /* Transitions sinon/sinonsi/capture/toujours. */
        if((strncmp(s,"else:",5)==0 || strncmp(s,"elif ",5)==0) && top_block() && top_block()->indent==indent && top_block()->kind==BLK_IF){close_one_block();}
        if(strncmp(s,"catch ",6)==0 && top_block() && top_block()->indent==indent && top_block()->kind==BLK_TRY){
            Block tb=blocks[--block_count];FILE*out=out_for_kind(tb.out_kind);emit_indent(out,indent);fprintf(out,"nv_try_top = __try%d.prev;\n",tb.try_id);emit_indent(out,indent);fprintf(out,"} else {\n");emit_indent(out,indent+4);fprintf(out,"nv_try_top = __try%d.prev;\n",tb.try_id);
            char name[MAX_NAME];snprintf(name,sizeof(name),"%s",trim(s+6));size_t n=strlen(name);if(n&&name[n-1]==':')name[n-1]='\0';char*vn=trim(name);emit_indent(out,indent+4);fprintf(out,"NvVal %s = nv_str(nv_error_message);\n",vn);VarScope*sc=(current_output()==OUT_FUNC)?&func_scope:&main_scope;scope_add(sc,vn);push_block(BLK_CATCH,indent,tb.out_kind,NULL,tb.try_id);continue;
        }
        if(strcmp(s,"finally:")==0 && top_block() && top_block()->indent==indent && top_block()->kind==BLK_CATCH){OutKind ok=top_block()->out_kind;close_one_block();FILE*out=out_for_kind(ok);emit_indent(out,indent);fprintf(out,"{\n");push_block(BLK_ALWAYS,indent,ok,NULL,0);continue;}

        /* À même niveau, fermer le bloc précédent. Les conteneurs objet/structure
           restent ouverts pendant leurs membres indentés, mais se ferment dès
           qu'on revient à leur niveau. */
        while(top_block() && top_block()->indent==indent) close_one_block();

        /* Définition de structure / objet */
        if(indent==0 && strncmp(s,"struct ",7)==0){char name[MAX_NAME];snprintf(name,sizeof(name),"%s",trim(s+7));size_t n=strlen(name);if(n&&name[n-1]==':')name[n-1]='\0';if(!is_ident(trim(name)))die("Line %d: invalid struct name",lineno);register_type(trim(name),TYPE_STRUCTURE);push_block(BLK_STRUCTURE,0,OUT_NONE,trim(name),0);continue;}
        if(indent==0 && strncmp(s,"object ",7)==0){char name[MAX_NAME];snprintf(name,sizeof(name),"%s",trim(s+7));size_t n=strlen(name);if(n&&name[n-1]==':')name[n-1]='\0';if(!is_ident(trim(name)))die("Line %d: invalid object name",lineno);register_type(trim(name),TYPE_OBJECT);push_block(BLK_OBJECT,0,OUT_NONE,trim(name),0);continue;}

        /* Champ dans structure/objet */
        TypeMeta*ct=current_type_meta();
        if(ct && indent==4 && strncmp(s,"fn ",3)!=0){char buf[MAX_LINE];snprintf(buf,sizeof(buf),"%s",s);char*colon=strchr(buf,':');if(colon && !strchr(buf,'=')){*colon='\0';char*name=trim(buf);char*type=trim(colon+1);if(!is_ident(name))die("Line %d: invalid field",lineno);if(ct->field_count>=MAX_FIELDS)die("Too many fields");FieldMeta*f=&ct->fields[ct->field_count++];snprintf(f->name,sizeof(f->name),"%s",name);snprintf(f->type,sizeof(f->type),"%s",type);continue;}}

        /* Fonction globale ou méthode */
        if(strncmp(s,"fn ",3)==0){
            char hdr[MAX_LINE];snprintf(hdr,sizeof(hdr),"%s",s+3);char*lpar=strchr(hdr,'(');char*rpar=strrchr(hdr,')');if(!lpar||!rpar||rpar<lpar)die("Line %d: invalid function definition",lineno);*lpar='\0';char*name=trim(hdr);*rpar='\0';char*params=lpar+1;char ret[MAX_NAME]="auto";char*after=trim(rpar+1);if(strncmp(after,"->",2)==0){after=trim(after+2);char*col=strrchr(after,':');if(col)*col='\0';snprintf(ret,sizeof(ret),"%s",trim(after));}
            const char*owner=current_owner();if(owner&&find_type(owner)->kind==TYPE_STRUCTURE)die("Line %d: a struct cannot contain methods",lineno);
            FuncMeta*fm=register_function(name,owner,params,ret);emit_function_header(fm,indent);push_block(BLK_FUNC,indent,OUT_FUNC,owner,0);continue;
        }

        OutKind ok=current_output();FILE*out=out_for_kind(ok);if(!out)die("Line %d: invalid statement here",lineno);VarScope*scope=(ok==OUT_FUNC)?&func_scope:&main_scope;
        VarScope*consts=(ok==OUT_FUNC)?&func_consts:&main_consts;

        /* allocation mémoire manuelle */
        if(strncmp(s,"manual ",7)==0){
            char rest[MAX_LINE];
            snprintf(rest,sizeof(rest),"%s",trim(s+7));

            int ol=0;
            int ap=find_top_level_assignment(rest,&ol);

            if(ap<0||ol!=1)
                die("Line %d: use 'manual name = alloc(size)'",lineno);

            char lhs[MAX_NAME],rhs[MAX_LINE];

            snprintf(lhs,sizeof(lhs),"%.*s",ap,rest);
            snprintf(rhs,sizeof(rhs),"%s",rest+ap+1);

            char *vn=trim(lhs);
            char *rv=trim(rhs);

            if(!is_ident(vn))
                die("Line %d: invalid manual variable name",lineno);

            if(scope_has(scope,vn))
                die("Line %d: variable '%s' is already defined",lineno,vn);

            char *e=compile_memory_alloc_expr(rv,lineno);

            emit_indent(out,indent);
            fprintf(out,"NvVal %s = %s;\n",vn,e);

            emit_indent(out,indent);
            fprintf(out,"nv_expect_type(%s, \"memory\", \"%s\");\n",vn,vn);

            free(e);
            scope_add(scope,vn);
            continue;
        }

        /* valeur fixe */
        if(strncmp(s,"const ",6)==0){
            char rest[MAX_LINE]; snprintf(rest,sizeof(rest),"%s",trim(s+6)); int ol=0; int ap=find_top_level_assignment(rest,&ol);
            if(ap<0||ol!=1)die("Line %d: use 'const name = value'",lineno);
            char lhs[MAX_LINE],rhs[MAX_LINE]; snprintf(lhs,sizeof(lhs),"%.*s",ap,rest); snprintf(rhs,sizeof(rhs),"%s",rest+ap+1);
            char nbuf[MAX_NAME]; snprintf(nbuf,sizeof(nbuf),"%s",trim(lhs)); char *col=strchr(nbuf,':'); if(col)*col='\0'; char *vn=trim(nbuf);
            if(!is_ident(vn))die("Line %d: invalid const name",lineno);
            emit_set_lvalue(out,indent,trim(lhs),trim(rhs),lineno,scope,NULL,NULL); scope_add(consts,vn); continue;
        }

        /* selon / cas */
        if(strncmp(s,"match ",6)==0){
            size_t n=strlen(s); if(s[n-1]!=':')die("Line %d: expected ':' after match",lineno);
            char ex[MAX_LINE]; snprintf(ex,sizeof(ex),"%.*s",(int)n-7,s+6); char *e=compile_expr(trim(ex),lineno); int id=++try_counter;
            emit_indent(out,indent); fprintf(out,"{ NvVal __match%d = %s;\n",id,e); free(e); push_block(BLK_MATCH,indent,ok,NULL,id); continue;
        }

        /* mémoire allouée explicitement et libérée automatiquement */
        if(strncmp(s,"with memory ",12)==0){
            size_t n=strlen(s);

            if(n<14 || s[n-1]!=':')
                die("Line %d: expected ':' after with memory",lineno);

            char body[MAX_LINE];
            snprintf(body,sizeof(body),"%s",s+12);

            size_t bn=strlen(body);
            if(bn==0 || body[bn-1]!=':')
                die("Line %d: invalid with memory statement",lineno);

            body[bn-1]='\0';

            int ol=0;
            int ap=find_top_level_assignment(body,&ol);

            if(ap<0 || ol!=1)
                die("Line %d: use 'with memory name = alloc(size):'",lineno);

            char lhs[MAX_NAME];
            char rhs[MAX_LINE];

            snprintf(lhs,sizeof(lhs),"%.*s",ap,body);
            snprintf(rhs,sizeof(rhs),"%s",body+ap+1);

            char *vn=trim(lhs);
            char *rv=trim(rhs);

            if(!is_ident(vn))
                die("Line %d: invalid memory variable name",lineno);

            char *e=compile_memory_alloc_expr(rv,lineno);

            emit_indent(out,indent);
            fprintf(out,"{ NvVal %s = %s;\n",vn,e);

            emit_indent(out,indent+4);
            fprintf(out,
                    "nv_expect_type(%s, \"memory\", \"%s\");\n",
                    vn,vn);

            emit_indent(out,indent+4);
            fprintf(out,"nv_memory_scope_enter(%s);\n",vn);

            free(e);

            push_block(
                BLK_WITH_MEMORY,
                indent,
                ok,
                vn,
                0
            );

            continue;
        }

        /* avec ferme automatiquement un fichier à la fin normale du bloc */
        if(strncmp(s,"with ",5)==0){
            size_t n=strlen(s); if(s[n-1]!=':')die("Line %d: expected ':' after with",lineno);
            char body[MAX_LINE]; snprintf(body,sizeof(body),"%.*s",(int)n-6,s+5); int ol=0; int ap=find_top_level_assignment(body,&ol);
            if(ap<0||ol!=1)die("Line %d: use 'with file = open(...):'",lineno);
            char lhs[MAX_NAME],rhs[MAX_LINE]; snprintf(lhs,sizeof(lhs),"%.*s",ap,body); snprintf(rhs,sizeof(rhs),"%s",body+ap+1); char *vn=trim(lhs);
            if(!is_ident(vn))die("Line %d: invalid file variable name",lineno); char *e=compile_expr(trim(rhs),lineno);
            emit_indent(out,indent); fprintf(out,"{ NvVal %s = %s;\n",vn,e); free(e); push_block(BLK_WITH,indent,ok,vn,0); continue;
        }


        /* contrôle de boucle */
        if(strcmp(s,"break")==0 || strcmp(s,"continue")==0){
            int loop=0; for(int bi=block_count-1;bi>=0;bi--){if(blocks[bi].kind==BLK_FOR||blocks[bi].kind==BLK_WHILE){loop=1;break;}}
            if(!loop)die("Line %d: '%s' must be used inside a loop",lineno,s);
            emit_memory_cleanup_for_loop_jump(out,indent);
            emit_indent(out,indent);
            fprintf(out,strcmp(s,"break")==0?"break;\n":"continue;\n");
            continue;
        }

        /* retour */
        if(strncmp(s,"return",6)==0 && (s[6]=='\0'||isspace((unsigned char)s[6]))){
            char*rest=trim(s+7);

            if(*rest){
                char*e=compile_expr(rest,lineno);

                emit_indent(out,indent);
                fprintf(out,"NvVal __ret%d = %s;\n",lineno,e);

                free(e);

                emit_memory_cleanup_for_return(out,indent);

                emit_indent(out,indent);
                fprintf(out,"return __ret%d;\n",lineno);
            }else{
                emit_memory_cleanup_for_return(out,indent);

                emit_indent(out,indent);
                fprintf(out,"return nv_none();\n");
            }

            continue;
        }

        /* si / sinonsi / sinon */
        if(strncmp(s,"if ",3)==0){size_t n=strlen(s);if(s[n-1]!=':')die("Line %d: expected ':' after if",lineno);char cond[MAX_LINE];snprintf(cond,sizeof(cond),"%.*s",(int)n-4,s+3);char*e=compile_expr(trim(cond),lineno);emit_indent(out,indent);fprintf(out,"if (nv_truth(%s)) {\n",e);free(e);push_block(BLK_IF,indent,ok,NULL,0);continue;}
        if(strncmp(s,"elif ",5)==0){size_t n=strlen(s);if(s[n-1]!=':')die("Line %d: expected ':' after elif",lineno);char cond[MAX_LINE];snprintf(cond,sizeof(cond),"%.*s",(int)n-6,s+5);char*e=compile_expr(trim(cond),lineno);emit_indent(out,indent);fprintf(out,"else if (nv_truth(%s)) {\n",e);free(e);push_block(BLK_IF,indent,ok,NULL,0);continue;}
        if(strcmp(s,"else:")==0){emit_indent(out,indent);fprintf(out,"else {\n");push_block(BLK_IF,indent,ok,NULL,0);continue;}

        /* tantque */
        if(strncmp(s,"while ",6)==0){size_t n=strlen(s);if(s[n-1]!=':')die("Line %d: expected ':' after while",lineno);char cond[MAX_LINE];snprintf(cond,sizeof(cond),"%.*s",(int)n-7,s+6);char*e=compile_expr(trim(cond),lineno);emit_indent(out,indent);fprintf(out,"while (nv_truth(%s)) {\n",e);free(e);push_block(BLK_WHILE,indent,ok,NULL,0);continue;}

        /* pour x dans expr */
        if(strncmp(s,"for ",4)==0){size_t n=strlen(s);if(s[n-1]!=':')die("Line %d: expected ':' after for",lineno);char tmp[MAX_LINE];snprintf(tmp,sizeof(tmp),"%.*s",(int)n-5,s+4);char*din=strstr(tmp," in ");if(!din)die("Line %d: expected 'in'",lineno);*din='\0';char*vn=trim(tmp);char*iter=trim(din+4);if(!is_ident(vn))die("Line %d: invalid loop variable",lineno);char*ie=compile_expr(iter,lineno);int id=lineno;emit_indent(out,indent);fprintf(out,"{ NvVal __iter%d = %s; for (int __i%d=0; __i%d<nv_len(__iter%d); __i%d++) {\n",id,ie,id,id,id,id);free(ie);emit_indent(out,indent+4);if(!scope_has(scope,vn)){fprintf(out,"NvVal %s = nv_iter_get(__iter%d,__i%d);\n",vn,id,id);scope_add(scope,vn);}else fprintf(out,"%s = nv_iter_get(__iter%d,__i%d);\n",vn,id,id);push_block(BLK_FOR,indent,ok,NULL,0);continue;}

        /* tente */
        if(strcmp(s,"try:")==0){int id=++try_counter;emit_indent(out,indent);fprintf(out,"NvTryFrame __try%d; __try%d.prev=nv_try_top; __try%d.memory_scope=nv_memory_scope_top; nv_try_top=&__try%d; if (setjmp(__try%d.env)==0) {\n",id,id,id,id,id);push_block(BLK_TRY,indent,ok,NULL,id);continue;}

        /* Affectation */
        int oplen=0;int apos=find_top_level_assignment(s,&oplen);if(apos>=0){char lhs[MAX_LINE],rhs[MAX_LINE];snprintf(lhs,sizeof(lhs),"%.*s",apos,s);snprintf(rhs,sizeof(rhs),"%s",s+apos+oplen);char aug[2]={0};if(oplen==2){aug[0]=s[apos];aug[1]='\0';}emit_set_lvalue(out,indent,trim(lhs),trim(rhs),lineno,scope,NULL,aug[0]?aug:NULL);continue;}

        /* Expression seule, ex. ecris(...), liste.ajoute(...) */
        char*e=compile_expr(s,lineno);emit_indent(out,indent);fprintf(out,"(void)%s;\n",e);free(e);
    }

    while(block_count>0)close_one_block();
    fflush(main_out);fflush(func_out);rewind(main_out);rewind(func_out);

    /* Le runtime est séparé pour garder le C généré lisible. */
    char runtimefile[512]; snprintf(runtimefile,sizeof(runtimefile),"%s",cfile); char *slash=strrchr(runtimefile,'/');
    if(slash) snprintf(slash+1,(size_t)(runtimefile+sizeof(runtimefile)-(slash+1)),"clariox_runtime.h"); else snprintf(runtimefile,sizeof(runtimefile),"clariox_runtime.h");
    FILE*rt=fopen(runtimefile,"w"); if(!rt)die("Unable to create %s",runtimefile);
    fputs("#ifndef CLARIOX_RUNTIME_H\n#define CLARIOX_RUNTIME_H\n",rt); fputs(RUNTIME_C,rt); fputs("\n#endif\n",rt); fclose(rt);
    FILE*out=fopen(cfile,"w");if(!out)die("Unable to create %s",cfile);fputs("#include \"clariox_runtime.h\"\n",out);
    int ch;
    emit_functions_with_hoisted_locals(
        func_out,
        out
    );
    emit_dispatch(out);
    fprintf(out,"\nint main(void){\n");while((ch=fgetc(main_out))!=EOF)fputc(ch,out);fprintf(out,"    return 0;\n}\n");
    fclose(out);fclose(main_out);fclose(func_out);remove(main_tmp);remove(func_tmp);
}

int main(int argc,char**argv){
    if(argc!=3){fprintf(stderr,"Usage : %s programme.clx sortie\n",argv[0]);return 1;}
    if(!safe_filename(argv[1])||!safe_filename(argv[2])){fprintf(stderr,"Filename not allowed\n");return 1;}
    FILE*in=fopen(argv[1],"r");if(!in){perror("source");return 1;}
    char cfile[512];snprintf(cfile,sizeof(cfile),"%s.c",argv[2]);
    compile_source(in,cfile);fclose(in);
    char cmd[1400];snprintf(cmd,sizeof(cmd),"clang -std=gnu11 -O3 -Wall -Wextra -Wno-unused-function -Wno-unused-parameter '%s' -lm -o '%s'",cfile,argv[2]);
    printf("[Clariox] C généré : %s\n",cfile);printf("[Clariox] Runtime séparé : clariox_runtime.h\n");printf("[Clariox] Compilation native avec Clang -O3...\n");
    int rc=system(cmd);if(rc!=0){fprintf(stderr,"Clang compilation failed. Generated C file kept for diagnostics.\n");return 1;}
    printf("[Clariox] Executable created: %s\n",argv[2]);return 0;
}
