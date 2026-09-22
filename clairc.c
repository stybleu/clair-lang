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
    if (!p) die("Mémoire insuffisante");
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
    if (n < 0) die("Erreur de formatage");
    char *buf = (char*)malloc((size_t)n + 1);
    if (!buf) die("Mémoire insuffisante");
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
    int count;
} VarScope;

static VarScope main_scope;
static VarScope func_scope;
static VarScope main_consts;
static VarScope func_consts;

static int scope_has(VarScope *s, const char *name) {
    for (int i = 0; i < s->count; i++) {
        if (strcmp(s->vars[i], name) == 0) return 1;
    }
    return 0;
}

static void scope_add(VarScope *s, const char *name) {
    if (scope_has(s, name)) return;
    if (s->count >= MAX_VARS) die("Trop de variables");
    snprintf(s->vars[s->count++], MAX_NAME, "%s", name);
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
        if (s[i-1] != '"') die("Erreur ligne %d : texte non fermé", lx->lineno);
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
    die("Erreur ligne %d : caractère inattendu '%c'", lx->lineno, c);
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
    if (lx->cur.kind != k) die("Erreur ligne %d : %s attendu", lx->lineno, what);
}

/* ============================
   Génération d'expressions C
   Les valeurs dynamiques du prototype passent par NvVal.
   ============================ */

static char *parse_expr(Lexer *lx);

static char *compile_expr(const char *src, int lineno);

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
            if (li + 2 >= sizeof(lit)) die("Erreur ligne %d : texte interpolé trop long", lineno);
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
            if (j >= n - 1) die("Erreur ligne %d : '}' manquant dans le texte interpolé", lineno);
            size_t en = j - i - 1;
            if (!en || en >= 2048) die("Erreur ligne %d : interpolation invalide", lineno);
            char expr[2048]; memcpy(expr, token+i+1, en); expr[en] = '\0';
            char *e = compile_expr(trim(expr), lineno);
            char *part = fmtdup("nv_to_str(%s)", e);
            char *tmp = fmtdup("nv_add(%s, %s)", acc, part);
            free(e); free(part); free(acc); acc = tmp;
            i = j + 1; continue;
        }
        if (li + 1 >= sizeof(lit)) die("Erreur ligne %d : texte interpolé trop long", lineno);
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

static char *parse_primary(Lexer *lx) {
    if (lx->cur.kind == TK_NUMBER) {
        char tmp[1024]; snprintf(tmp, sizeof(tmp), "%s", lx->cur.text);
        int is_float = strchr(tmp, '.') || strchr(tmp,'e') || strchr(tmp,'E');
        advance(lx);
        return is_float ? fmtdup("nv_float(%s)", tmp) : fmtdup("nv_int(%sLL)", tmp);
    }

    if (lx->cur.kind == TK_STRING) {
        char tmp[1024]; snprintf(tmp, sizeof(tmp), "%s", lx->cur.text);
        advance(lx);
        return compile_interpolated_string(tmp, lx->lineno);
    }

    if (is_kw(lx, "vrai")) { advance(lx); return xstrdup("nv_bool(1)"); }
    if (is_kw(lx, "faux")) { advance(lx); return xstrdup("nv_bool(0)"); }
    if (is_kw(lx, "rien")) { advance(lx); return xstrdup("nv_none()"); }

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
                    die("Erreur ligne %d : clé de table invalide", lx->lineno);
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

    die("Erreur ligne %d : expression invalide", lx->lineno);
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
    if (is_kw(lx, "non")) {
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
    while (lx->cur.kind==TK_EQEQ || lx->cur.kind==TK_NE || lx->cur.kind==TK_LT || lx->cur.kind==TK_LE || lx->cur.kind==TK_GT || lx->cur.kind==TK_GE || is_kw(lx,"dans")) {
        int membership = is_kw(lx,"dans");
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
    while (is_kw(lx, "et")) {
        advance(lx);
        char *b = parse_cmp(lx);
        a = join_binary("nv_and", a, b);
    }
    return a;
}

static char *parse_expr(Lexer *lx) {
    char *a = parse_and(lx);
    while (is_kw(lx, "ou")) {
        advance(lx);
        char *b = parse_and(lx);
        a = join_binary("nv_or", a, b);
    }
    return a;
}

static char *compile_expr(const char *src, int lineno) {
    Lexer lx; lexer_init(&lx, src, lineno);
    char *e = parse_expr(&lx);
    if (lx.cur.kind != TK_EOF) die("Erreur ligne %d : élément inattendu '%s'", lineno, lx.cur.text);
    return e;
}

/* ============================
   Runtime C Clair séparé dans clair_runtime.h
   ============================ */

static const char *RUNTIME_C =
"#include <stdio.h>\n"
"#include <stdlib.h>\n"
"#include <string.h>\n"
"#include <stdbool.h>\n"
"#include <math.h>\n"
"#include <setjmp.h>\n"
"\n"
"typedef struct NvVal NvVal;\n"
"typedef struct NvList NvList;\n"
"typedef struct NvDict NvDict;\n"
"typedef struct NvObj NvObj;\n"
"typedef struct NvCall NvCall;\n"
"typedef struct NvTryFrame NvTryFrame;\n"
"\n"
"typedef enum { NV_NONE, NV_INT, NV_FLOAT, NV_BOOL, NV_STR, NV_LIST, NV_DICT, NV_OBJ, NV_FILE } NvKind;\n"
"struct NvVal { NvKind kind; union { long long i; double f; int b; char *s; NvList *list; NvDict *dict; NvObj *obj; FILE *file; } as; };\n"
"struct NvList { NvVal *items; int len, cap; };\n"
"struct NvDict { char **keys; NvVal *vals; int len, cap; };\n"
"struct NvObj { char *type; NvDict *fields; };\n"
"struct NvCall { NvVal *args; int argc, cap; NvDict *kw; };\n"
"struct NvTryFrame { jmp_buf env; NvTryFrame *prev; };\n"
"static NvTryFrame *nv_try_top = NULL;\n"
"static char nv_error_message[1024] = {0};\n"
"\n"
"static void *nv_xmalloc(size_t n){ void *p=malloc(n?n:1); if(!p){fprintf(stderr,\"Mémoire insuffisante\\n\"); exit(2);} return p;}\n"
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
"static NvVal nv_float(double x){ NvVal v=nv_none(); v.kind=NV_FLOAT; v.as.f=x; return v;}\n"
"static NvVal nv_bool(int x){ NvVal v=nv_none(); v.kind=NV_BOOL; v.as.b=!!x; return v;}\n"
"static NvVal nv_str(const char *x){ NvVal v=nv_none(); v.kind=NV_STR; v.as.s=nv_intern(x); return v;}\n"
"static NvDict *nv_dict_new(void){ NvDict*d=nv_xmalloc(sizeof(*d)); d->keys=NULL; d->vals=NULL; d->len=0; d->cap=0; return d;}\n"
"static NvVal nv_dict_new_value(void){ NvVal v=nv_none(); v.kind=NV_DICT; v.as.dict=nv_dict_new(); return v;}\n"
"static NvVal nv_list_new(void){ NvVal v=nv_none(); v.kind=NV_LIST; v.as.list=nv_xmalloc(sizeof(NvList)); v.as.list->items=NULL; v.as.list->len=0; v.as.list->cap=0; return v;}\n"
"static NvVal nv_file_value(FILE *f){ NvVal v=nv_none(); v.kind=NV_FILE; v.as.file=f; return v;}\n"
"static NvVal nv_to_str(NvVal v){ char b[256]; switch(v.kind){case NV_STR:return nv_str(v.as.s);case NV_NONE:return nv_str(\"rien\");case NV_INT:snprintf(b,sizeof(b),\"%lld\",v.as.i);return nv_str(b);case NV_FLOAT:snprintf(b,sizeof(b),\"%g\",v.as.f);return nv_str(b);case NV_BOOL:return nv_str(v.as.b?\"vrai\":\"faux\");case NV_LIST:return nv_str(\"<liste>\");case NV_DICT:return nv_str(\"<table>\");case NV_OBJ:snprintf(b,sizeof(b),\"<%s>\",v.as.obj->type);return nv_str(b);case NV_FILE:return nv_str(\"<fichier>\");}return nv_str(\"\");}\n"
"static void nv_throw(const char *msg){ snprintf(nv_error_message,sizeof(nv_error_message),\"%s\",msg); if(nv_try_top) longjmp(nv_try_top->env,1); fprintf(stderr,\"Erreur Clair : %s\\n\",msg); exit(1);}\n"
"static void nv_throwf(const char *fmt,const char *a){ snprintf(nv_error_message,sizeof(nv_error_message),fmt,a); if(nv_try_top) longjmp(nv_try_top->env,1); fprintf(stderr,\"Erreur Clair : %s\\n\",nv_error_message); exit(1);}\n"
"static int nv_truth(NvVal v){ switch(v.kind){case NV_NONE:return 0;case NV_BOOL:return v.as.b;case NV_INT:return v.as.i!=0;case NV_FLOAT:return v.as.f!=0.0;case NV_STR:return v.as.s&&v.as.s[0];case NV_LIST:return v.as.list&&v.as.list->len>0;case NV_DICT:return v.as.dict&&v.as.dict->len>0;case NV_OBJ:return 1;case NV_FILE:return v.as.file!=NULL;} return 0;}\n"
"static double nv_num(NvVal v){ if(v.kind==NV_INT)return(double)v.as.i; if(v.kind==NV_FLOAT)return v.as.f; if(v.kind==NV_BOOL)return(double)v.as.b; nv_throw(\"Une valeur numérique était attendue\"); return 0;}\n"
"static NvVal nv_add(NvVal a,NvVal b){ if(a.kind==NV_STR&&b.kind==NV_STR){size_t n=strlen(a.as.s)+strlen(b.as.s)+1;char*p=nv_xmalloc(n);snprintf(p,n,\"%s%s\",a.as.s,b.as.s);NvVal v=nv_str(p);free(p);return v;} if(a.kind==NV_INT&&b.kind==NV_INT)return nv_int(a.as.i+b.as.i); return nv_float(nv_num(a)+nv_num(b));}\n"
"static NvVal nv_sub(NvVal a,NvVal b){ if(a.kind==NV_INT&&b.kind==NV_INT)return nv_int(a.as.i-b.as.i); return nv_float(nv_num(a)-nv_num(b));}\n"
"static NvVal nv_mul(NvVal a,NvVal b){ if(a.kind==NV_INT&&b.kind==NV_INT)return nv_int(a.as.i*b.as.i); return nv_float(nv_num(a)*nv_num(b));}\n"
"static NvVal nv_div(NvVal a,NvVal b){ double d=nv_num(b); if(d==0.0)nv_throw(\"Division par zéro\"); return nv_float(nv_num(a)/d);}\n"
"static NvVal nv_mod(NvVal a,NvVal b){ long long x=(long long)nv_num(a), y=(long long)nv_num(b); if(!y)nv_throw(\"Modulo par zéro\"); return nv_int(x%y);}\n"
"static NvVal nv_pow(NvVal a,NvVal b){ return nv_float(pow(nv_num(a),nv_num(b)));}\n"
"static NvVal nv_neg(NvVal a){ if(a.kind==NV_INT)return nv_int(-a.as.i); return nv_float(-nv_num(a));}\n"
"static NvVal nv_not(NvVal a){return nv_bool(!nv_truth(a));}\n"
"static NvVal nv_and(NvVal a,NvVal b){return nv_bool(nv_truth(a)&&nv_truth(b));}\n"
"static NvVal nv_or(NvVal a,NvVal b){return nv_bool(nv_truth(a)||nv_truth(b));}\n"
"static int nv_same(NvVal a,NvVal b){ if(a.kind!=b.kind){if((a.kind==NV_INT||a.kind==NV_FLOAT||a.kind==NV_BOOL)&&(b.kind==NV_INT||b.kind==NV_FLOAT||b.kind==NV_BOOL))return nv_num(a)==nv_num(b);return 0;} switch(a.kind){case NV_NONE:return 1;case NV_INT:return a.as.i==b.as.i;case NV_FLOAT:return a.as.f==b.as.f;case NV_BOOL:return a.as.b==b.as.b;case NV_STR:return strcmp(a.as.s,b.as.s)==0;case NV_FILE:return a.as.file==b.as.file;default:return a.as.obj==b.as.obj;} }\n"
"static NvVal nv_eq(NvVal a,NvVal b){return nv_bool(nv_same(a,b));} static NvVal nv_ne(NvVal a,NvVal b){return nv_bool(!nv_same(a,b));}\n"
"static NvVal nv_lt(NvVal a,NvVal b){return nv_bool(nv_num(a)<nv_num(b));} static NvVal nv_le(NvVal a,NvVal b){return nv_bool(nv_num(a)<=nv_num(b));} static NvVal nv_gt(NvVal a,NvVal b){return nv_bool(nv_num(a)>nv_num(b));} static NvVal nv_ge(NvVal a,NvVal b){return nv_bool(nv_num(a)>=nv_num(b));}\n"
"static void nv_print_one(NvVal v){ switch(v.kind){case NV_NONE:printf(\"rien\");break;case NV_INT:printf(\"%lld\",v.as.i);break;case NV_FLOAT:printf(\"%g\",v.as.f);break;case NV_BOOL:printf(\"%s\",v.as.b?\"vrai\":\"faux\");break;case NV_STR:printf(\"%s\",v.as.s);break;case NV_LIST:printf(\"[\");for(int i=0;i<v.as.list->len;i++){if(i)printf(\", \");nv_print_one(v.as.list->items[i]);}printf(\"]\");break;case NV_DICT:printf(\"{\");for(int i=0;i<v.as.dict->len;i++){if(i)printf(\", \");printf(\"\\\"%s\\\": \",v.as.dict->keys[i]);nv_print_one(v.as.dict->vals[i]);}printf(\"}\");break;case NV_OBJ:printf(\"<%s>\",v.as.obj->type);break;case NV_FILE:printf(\"<fichier>\");break;} }\n"
"static void nv_list_append(NvVal l,NvVal v){ if(l.kind!=NV_LIST)nv_throw(\"ajoute() nécessite une liste\"); NvList*p=l.as.list; if(p->len==p->cap){p->cap=p->cap?p->cap*2:8;p->items=realloc(p->items,sizeof(NvVal)*p->cap);} p->items[p->len++]=v;}\n"
"static NvVal nv_range(NvVal a,NvVal b){ long long x=(long long)nv_num(a), y=(long long)nv_num(b); NvVal l=nv_list_new(); if(x<=y){for(long long i=x;i<y;i++)nv_list_append(l,nv_int(i));}else{for(long long i=x;i>y;i--)nv_list_append(l,nv_int(i));} return l;}\n"
"static void nv_file_close(NvVal v){ if(v.kind==NV_FILE && v.as.file) fclose(v.as.file); }\n"
"static NvVal nv_file_read(NvVal v){ if(v.kind!=NV_FILE||!v.as.file)nv_throw(\"Fichier non ouvert\"); if(fseek(v.as.file,0,SEEK_END)!=0)nv_throw(\"Impossible de lire le fichier\"); long n=ftell(v.as.file); if(n<0)nv_throw(\"Impossible de lire le fichier\"); rewind(v.as.file); char *buf=nv_xmalloc((size_t)n+1); size_t got=fread(buf,1,(size_t)n,v.as.file); buf[got]='\\0'; NvVal r=nv_str(buf); free(buf); return r;}\n"
"static NvVal nv_file_write(NvVal v,NvVal data){ if(v.kind!=NV_FILE||!v.as.file)nv_throw(\"Fichier non ouvert\"); NvVal t=nv_to_str(data); fputs(t.as.s,v.as.file); fflush(v.as.file); return nv_none();}\n"
"static void nv_list_extend(NvVal l,NvVal other){ if(l.kind!=NV_LIST||other.kind!=NV_LIST)nv_throw(\"Le déballage * nécessite une liste\"); for(int i=0;i<other.as.list->len;i++)nv_list_append(l,other.as.list->items[i]);}\n"
"static int nv_dict_find(NvDict*d,const char*k){for(int i=0;i<d->len;i++)if(strcmp(d->keys[i],k)==0)return i;return-1;}\n"
"static NvVal nv_contains(NvVal container,NvVal item){ if(container.kind==NV_LIST){for(int i=0;i<container.as.list->len;i++)if(nv_same(container.as.list->items[i],item))return nv_bool(1);return nv_bool(0);} if(container.kind==NV_DICT){if(item.kind!=NV_STR)return nv_bool(0);return nv_bool(nv_dict_find(container.as.dict,item.as.s)>=0);} if(container.kind==NV_STR){if(item.kind!=NV_STR)return nv_bool(0);return nv_bool(strstr(container.as.s,item.as.s)!=NULL);} nv_throw(\"'dans' nécessite une liste, une table ou un texte\");return nv_bool(0);}\n"
"static void nv_dict_set(NvDict*d,const char*k,NvVal v){int i=nv_dict_find(d,k);if(i>=0){d->vals[i]=v;return;}if(d->len==d->cap){d->cap=d->cap?d->cap*2:8;d->keys=realloc(d->keys,sizeof(char*)*d->cap);d->vals=realloc(d->vals,sizeof(NvVal)*d->cap);}d->keys[d->len]=nv_strdup(k);d->vals[d->len]=v;d->len++;}\n"
"static void nv_dict_set_value(NvVal d,const char*k,NvVal v){if(d.kind!=NV_DICT)nv_throw(\"Une table était attendue\");nv_dict_set(d.as.dict,k,v);}\n"
"static void nv_dict_merge_value(NvVal d,NvVal src){if(d.kind!=NV_DICT||src.kind!=NV_DICT)nv_throw(\"Le déballage ** nécessite une table\");for(int i=0;i<src.as.dict->len;i++)nv_dict_set(d.as.dict,src.as.dict->keys[i],src.as.dict->vals[i]);}\n"
"static NvVal nv_dict_get(NvDict*d,const char*k){int i=nv_dict_find(d,k);if(i<0){char buf[512];snprintf(buf,sizeof(buf),\"Clé introuvable : %s\",k);nv_throw(buf);}return d->vals[i];}\n"
"static NvVal nv_get_index(NvVal a,NvVal i){ if(a.kind==NV_LIST){long long n=(long long)nv_num(i);if(n<0)n=a.as.list->len+n;if(n<0||n>=a.as.list->len)nv_throw(\"Indice de liste hors limites\");return a.as.list->items[n];} if(a.kind==NV_DICT){if(i.kind!=NV_STR)nv_throw(\"Une clé texte était attendue\");return nv_dict_get(a.as.dict,i.as.s);} if(a.kind==NV_STR){long long n=(long long)nv_num(i);int len=(int)strlen(a.as.s);if(n<0)n=len+n;if(n<0||n>=len)nv_throw(\"Indice de texte hors limites\");char tmp[2]={a.as.s[n],0};return nv_str(tmp);} nv_throw(\"Cette valeur ne peut pas être indexée\");return nv_none();}\n"
"static void nv_set_index(NvVal a,NvVal i,NvVal v){ if(a.kind==NV_LIST){long long n=(long long)nv_num(i);if(n<0)n=a.as.list->len+n;if(n<0||n>=a.as.list->len)nv_throw(\"Indice de liste hors limites\");a.as.list->items[n]=v;return;} if(a.kind==NV_DICT){if(i.kind!=NV_STR)nv_throw(\"Une clé texte était attendue\");nv_dict_set(a.as.dict,i.as.s,v);return;} nv_throw(\"Cette valeur ne peut pas recevoir un index\");}\n"
"static NvVal nv_get_field(NvVal a,const char*name){if(a.kind!=NV_OBJ)nv_throw(\"Accès à un champ sur une valeur qui n'est pas un objet\");return nv_dict_get(a.as.obj->fields,name);}\n"
"static void nv_set_field(NvVal a,const char*name,NvVal v){if(a.kind!=NV_OBJ)nv_throw(\"Affectation de champ sur une valeur qui n'est pas un objet\");nv_dict_set(a.as.obj->fields,name,v);}\n"
"static NvVal nv_object_new(const char*type){NvVal v=nv_none();v.kind=NV_OBJ;v.as.obj=nv_xmalloc(sizeof(NvObj));v.as.obj->type=nv_strdup(type);v.as.obj->fields=nv_dict_new();return v;}\n"
"static int nv_len(NvVal v){if(v.kind==NV_LIST)return v.as.list->len;if(v.kind==NV_DICT)return v.as.dict->len;if(v.kind==NV_STR)return(int)strlen(v.as.s);nv_throw(\"longueur() nécessite une liste, une table ou un texte\");return 0;}\n"
"static NvVal nv_iter_get(NvVal v,int i){if(v.kind==NV_LIST)return v.as.list->items[i];if(v.kind==NV_DICT)return nv_str(v.as.dict->keys[i]);if(v.kind==NV_STR){char t[2]={v.as.s[i],0};return nv_str(t);}nv_throw(\"Cette valeur n'est pas parcourable\");return nv_none();}\n"
"static NvCall nv_call_new(void){NvCall c;c.args=NULL;c.argc=0;c.cap=0;c.kw=nv_dict_new();return c;}\n"
"static void nv_call_add(NvCall*c,NvVal v){if(c->argc==c->cap){c->cap=c->cap?c->cap*2:8;c->args=realloc(c->args,sizeof(NvVal)*c->cap);}c->args[c->argc++]=v;}\n"
"static void nv_call_spread(NvCall*c,NvVal v){if(v.kind!=NV_LIST)nv_throw(\"Le déballage * nécessite une liste\");for(int i=0;i<v.as.list->len;i++)nv_call_add(c,v.as.list->items[i]);}\n"
"static void nv_call_kw(NvCall*c,const char*k,NvVal v){nv_dict_set(c->kw,k,v);}\n"
"static void nv_call_kwspread(NvCall*c,NvVal v){if(v.kind!=NV_DICT)nv_throw(\"Le déballage ** nécessite une table\");for(int i=0;i<v.as.dict->len;i++)nv_dict_set(c->kw,v.as.dict->keys[i],v.as.dict->vals[i]);}\n"
"static void nv_dict_free_shallow(NvDict*d){if(!d)return;for(int i=0;i<d->len;i++)free(d->keys[i]);free(d->keys);free(d->vals);free(d);}\n"
"static void nv_call_free(NvCall*c){if(!c)return;free(c->args);nv_dict_free_shallow(c->kw);c->args=NULL;c->kw=NULL;c->argc=0;c->cap=0;}\n"
"static NvVal nv_arg(NvVal*args,int argc,NvDict*kw,int pos,const char*name){if(pos<argc)return args[pos];int i=nv_dict_find(kw,name);if(i>=0)return kw->vals[i];char buf[512];snprintf(buf,sizeof(buf),\"Argument manquant : %s\",name);nv_throw(buf);return nv_none();}\n"
"static void nv_expect_type(NvVal v,const char*t,const char*name){int ok=0;if(strcmp(t,\"entier\")==0)ok=v.kind==NV_INT;else if(strcmp(t,\"decimal\")==0)ok=v.kind==NV_FLOAT||v.kind==NV_INT;else if(strcmp(t,\"texte\")==0)ok=v.kind==NV_STR;else if(strcmp(t,\"booleen\")==0)ok=v.kind==NV_BOOL;else if(strcmp(t,\"liste\")==0)ok=v.kind==NV_LIST;else if(strcmp(t,\"table\")==0)ok=v.kind==NV_DICT;else if(strcmp(t,\"objet\")==0)ok=v.kind==NV_OBJ;else if(strcmp(t,\"fichier\")==0)ok=v.kind==NV_FILE;else ok=1;if(!ok){char buf[512];snprintf(buf,sizeof(buf),\"Type incorrect pour %s : %s attendu\",name,t);nv_throw(buf);}}\n"
"static NvVal nv_dispatch_call(const char*,NvVal*,int,NvDict*);\n"
"static NvVal nv_dispatch_method(NvVal,const char*,NvVal*,int,NvDict*);\n"
"\n";

/* ============================
   Blocs et contexte de compilation
   ============================ */

typedef enum {
    BLK_IF, BLK_WHILE, BLK_FOR,
    BLK_FUNC, BLK_OBJECT, BLK_STRUCTURE,
    BLK_TRY, BLK_CATCH, BLK_ALWAYS,
    BLK_MATCH, BLK_CASE, BLK_WITH
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


/* ============================
   Analyse des définitions
   ============================ */

static void parse_params(char *src, FuncMeta *fm) {
    char *p=trim(src);
    fm->param_count=0;
    if(!*p)return;
    char *save=NULL;
    for(char *tok=strtok_r(p,",",&save); tok; tok=strtok_r(NULL,",",&save)){
        if(fm->param_count>=MAX_PARAMS)die("Trop de paramètres dans %s",fm->name);
        char *item=trim(tok); char *colon=strchr(item,':');
        ParamMeta *pm=&fm->params[fm->param_count++]; memset(pm,0,sizeof(*pm));
        if(colon){*colon='\0';snprintf(pm->name,sizeof(pm->name),"%s",trim(item));snprintf(pm->type,sizeof(pm->type),"%s",trim(colon+1));}
        else{snprintf(pm->name,sizeof(pm->name),"%s",item);pm->type[0]='\0';}
        if(!is_ident(pm->name))die("Paramètre invalide : %s",pm->name);
    }
}

static FuncMeta *register_function(const char *name,const char *owner,char *params,const char *ret) {
    if(func_count>=MAX_FUNCS)die("Trop de fonctions");
    FuncMeta *fm=&funcs[func_count++]; memset(fm,0,sizeof(*fm));
    snprintf(fm->name,sizeof(fm->name),"%s",name);
    if(owner&&*owner)snprintf(fm->owner,sizeof(fm->owner),"%s",owner);
    if(owner&&*owner)snprintf(fm->internal,sizeof(fm->internal),"clair_%s_%s",owner,name); else snprintf(fm->internal,sizeof(fm->internal),"clair_fn_%s",name);
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
        scope_add(&func_scope,p->name);
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

static void emit_set_lvalue(FILE*out,int indent,const char*lhs,const char*rhs,int lineno,VarScope*scope,const char*annot_type,const char*augop){
    char tmp[MAX_LINE];snprintf(tmp,sizeof(tmp),"%s",lhs);char*l=trim(tmp);
    /* champ objet : obj.nom */
    char *dot=strrchr(l,'.');
    if(dot){*dot='\0';char*obj=trim(l);char*field=trim(dot+1);if(!is_ident(field))die("Erreur ligne %d : champ invalide",lineno);char*objexpr=compile_expr(obj,lineno);char*value=NULL;if(augop){char*cur=fmtdup("nv_get_field(%s, \"%s\")",objexpr,field);char*rv=compile_expr(rhs,lineno);value=fmtdup("%s(%s,%s)",strcmp(augop,"+")==0?"nv_add":strcmp(augop,"-")==0?"nv_sub":strcmp(augop,"*")==0?"nv_mul":"nv_div",cur,rv);free(cur);free(rv);}else value=compile_expr(rhs,lineno);emit_indent(out,indent);fprintf(out,"nv_set_field(%s, \"%s\", %s);\n",objexpr,field,value);free(objexpr);free(value);return;}
    /* index : a[expr] */
    size_t n=strlen(l); if(n>2 && l[n-1]==']'){
        int depth=0;int open=-1;for(int i=(int)n-1;i>=0;i--){if(l[i]==']')depth++;else if(l[i]=='['){depth--;if(depth==0){open=i;break;}}}
        if(open>0){char base[MAX_LINE],idx[MAX_LINE];memcpy(base,l,(size_t)open);base[open]='\0';snprintf(idx,sizeof(idx),"%.*s",(int)n-open-2,l+open+1);char*be=compile_expr(trim(base),lineno);char*ie=compile_expr(trim(idx),lineno);char*val=NULL;if(augop){char*cur=fmtdup("nv_get_index(%s,%s)",be,ie);char*rv=compile_expr(rhs,lineno);val=fmtdup("%s(%s,%s)",strcmp(augop,"+")==0?"nv_add":strcmp(augop,"-")==0?"nv_sub":strcmp(augop,"*")==0?"nv_mul":"nv_div",cur,rv);free(cur);free(rv);}else val=compile_expr(rhs,lineno);emit_indent(out,indent);fprintf(out,"nv_set_index(%s, %s, %s);\n",be,ie,val);free(be);free(ie);free(val);return;}
    }
    /* variable simple, éventuellement typée */
    char name[MAX_NAME];snprintf(name,sizeof(name),"%s",l);char typebuf[MAX_NAME]={0};char*colon=strchr(name,':');if(colon){*colon='\0';snprintf(typebuf,sizeof(typebuf),"%s",trim(colon+1));}
    char*vn=trim(name);if(!is_ident(vn))die("Erreur ligne %d : variable invalide '%s'",lineno,vn);
    const char*type = annot_type&&*annot_type?annot_type:(typebuf[0]?typebuf:NULL);
    VarScope *consts = (scope == &func_scope) ? &func_consts : &main_consts;
    if (scope_has(consts, vn)) die("Erreur ligne %d : '%s' est fixe et ne peut pas être modifié", lineno, vn);
    char*val=NULL;
    if(augop){if(!scope_has(scope,vn))die("Erreur ligne %d : variable inconnue '%s'",lineno,vn);char*rv=compile_expr(rhs,lineno);val=fmtdup("%s(%s,%s)",strcmp(augop,"+")==0?"nv_add":strcmp(augop,"-")==0?"nv_sub":strcmp(augop,"*")==0?"nv_mul":"nv_div",vn,rv);free(rv);}else val=compile_expr(rhs,lineno);
    emit_indent(out,indent);
    if(!scope_has(scope,vn)){fprintf(out,"NvVal %s = %s;\n",vn,val);scope_add(scope,vn);}else fprintf(out,"%s = %s;\n",vn,val);
    if(type){emit_indent(out,indent);fprintf(out,"nv_expect_type(%s, \"%s\", \"%s\");\n",vn,type,vn);}free(val);
}

/* ============================
   Génération des dispatchers
   ============================ */

static void emit_dispatch(FILE*out){
    fprintf(out,"\nstatic NvVal nv_builtin_print(NvVal *args,int argc){for(int i=0;i<argc;i++){if(i)printf(\" \");nv_print_one(args[i]);}printf(\"\\n\");return nv_none();}\n");
    fprintf(out,"static NvVal nv_dispatch_call(const char *name,NvVal *args,int argc,NvDict *kw){\n");
    fprintf(out,"    if(strcmp(name,\"ecris\")==0) return nv_builtin_print(args,argc);\n");
    fprintf(out,"    if(strcmp(name,\"demande\")==0){ if(argc>0){nv_print_one(args[0]);fflush(stdout);} char b[4096]; if(!fgets(b,sizeof(b),stdin))return nv_str(\"\"); b[strcspn(b,\"\\r\\n\")]=0; return nv_str(b); }\n");
    fprintf(out,"    if(strcmp(name,\"demande_entier\")==0){ if(argc>0){nv_print_one(args[0]);fflush(stdout);} char b[256]; if(!fgets(b,sizeof(b),stdin))return nv_int(0); char *e=NULL; long long v=strtoll(b,&e,10); if(e==b)nv_throw(\"Un entier était attendu\"); return nv_int(v); }\n");
    fprintf(out,"    if(strcmp(name,\"demande_decimal\")==0){ if(argc>0){nv_print_one(args[0]);fflush(stdout);} char b[256]; if(!fgets(b,sizeof(b),stdin))return nv_float(0); char *e=NULL; double v=strtod(b,&e); if(e==b)nv_throw(\"Un nombre décimal était attendu\"); return nv_float(v); }\n");
    fprintf(out,"    if(strcmp(name,\"entier\")==0){ if(argc<1)nv_throw(\"entier() attend une valeur\"); if(args[0].kind==NV_INT)return args[0]; if(args[0].kind==NV_STR)return nv_int(strtoll(args[0].as.s,NULL,10)); return nv_int((long long)nv_num(args[0])); }\n");
    fprintf(out,"    if(strcmp(name,\"decimal\")==0){ if(argc<1)nv_throw(\"decimal() attend une valeur\"); if(args[0].kind==NV_STR)return nv_float(strtod(args[0].as.s,NULL)); return nv_float(nv_num(args[0])); }\n");
    fprintf(out,"    if(strcmp(name,\"texte\")==0){ if(argc<1)nv_throw(\"texte() attend une valeur\"); return nv_to_str(args[0]); }\n");
    fprintf(out,"    if(strcmp(name,\"ouvre\")==0){ if(argc<1||args[0].kind!=NV_STR)nv_throw(\"ouvre() attend un chemin texte\"); const char*m=\"r\"; if(argc>1&&args[1].kind==NV_STR){ if(strcmp(args[1].as.s,\"lecture\")==0)m=\"r\"; else if(strcmp(args[1].as.s,\"ecriture\")==0)m=\"w\"; else if(strcmp(args[1].as.s,\"ajout\")==0)m=\"a\"; else m=args[1].as.s;} FILE*f=fopen(args[0].as.s,m); if(!f)nv_throwf(\"Impossible d'ouvrir le fichier : %%s\",args[0].as.s); return nv_file_value(f); }\n");
    fprintf(out,"    if(strcmp(name,\"lis_fichier\")==0){ if(argc<1||args[0].kind!=NV_STR)nv_throw(\"lis_fichier() attend un chemin texte\"); FILE*f=fopen(args[0].as.s,\"r\"); if(!f)nv_throwf(\"Impossible d'ouvrir le fichier : %%s\",args[0].as.s); NvVal fv=nv_file_value(f); NvVal r=nv_file_read(fv); fclose(f); return r; }\n");
    fprintf(out,"    if(strcmp(name,\"ecris_fichier\")==0){ if(argc<2||args[0].kind!=NV_STR)nv_throw(\"ecris_fichier() attend un chemin et une valeur\"); FILE*f=fopen(args[0].as.s,\"w\"); if(!f)nv_throwf(\"Impossible d'ouvrir le fichier : %%s\",args[0].as.s); NvVal fv=nv_file_value(f); nv_file_write(fv,args[1]); fclose(f); return nv_none(); }\n");
    fprintf(out,"    if(strcmp(name,\"longueur\")==0){ if(argc<1)nv_throw(\"longueur() attend une valeur\"); return nv_int(nv_len(args[0])); }\n");
    fprintf(out,"    if(strcmp(name,\"plage\")==0){ long long a=0,b=0,p=1; if(argc==1){b=(long long)nv_num(args[0]);} else if(argc>=2){a=(long long)nv_num(args[0]);b=(long long)nv_num(args[1]);if(argc>=3)p=(long long)nv_num(args[2]);} else nv_throw(\"plage() attend 1 à 3 arguments\"); if(p==0)nv_throw(\"Le pas de plage ne peut pas être zéro\"); NvVal l=nv_list_new(); if(p>0){for(long long i=a;i<b;i+=p)nv_list_append(l,nv_int(i));}else{for(long long i=a;i>b;i+=p)nv_list_append(l,nv_int(i));} return l;}\n");
    fprintf(out,"    if(strcmp(name,\"erreur\")==0){ if(argc<1||args[0].kind!=NV_STR)nv_throw(\"erreur() attend un texte\"); nv_throw(args[0].as.s); }\n");
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
    fprintf(out,"    if(self.kind==NV_LIST && strcmp(name,\"ajoute\")==0){ if(argc<1)nv_throw(\"ajoute() attend une valeur\"); nv_list_append(self,args[0]); return nv_none(); }\n");
    fprintf(out,"    if(self.kind==NV_LIST && strcmp(name,\"retire\")==0){ if(argc<1)nv_throw(\"retire() attend une valeur\"); for(int i=0;i<self.as.list->len;i++){if(nv_same(self.as.list->items[i],args[0])){for(int j=i;j<self.as.list->len-1;j++)self.as.list->items[j]=self.as.list->items[j+1];self.as.list->len--;return nv_none();}} return nv_none(); }\n");
    fprintf(out,"    if(self.kind==NV_DICT && strcmp(name,\"cles\")==0){ NvVal l=nv_list_new(); for(int i=0;i<self.as.dict->len;i++)nv_list_append(l,nv_str(self.as.dict->keys[i])); return l; }\n");
    fprintf(out,"    if(self.kind==NV_FILE && strcmp(name,\"lis\")==0) return nv_file_read(self);\n");
    fprintf(out,"    if(self.kind==NV_FILE && strcmp(name,\"ecris\")==0){ if(argc<1)nv_throw(\"fichier.ecris() attend une valeur\"); return nv_file_write(self,args[0]); }\n");
    fprintf(out,"    if(self.kind==NV_FILE && strcmp(name,\"ferme\")==0){ nv_file_close(self); return nv_none(); }\n");
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
    main_out=fopen(main_tmp,"w+");func_out=fopen(func_tmp,"w+");if(!main_out||!func_out)die("Impossible de créer les fichiers temporaires");
    main_scope.count=0;func_scope.count=0;main_consts.count=0;func_consts.count=0;block_count=0;

    char line[MAX_LINE];int lineno=0;
    while(fgets(line,sizeof(line),in)){
        lineno++;
        if(strchr(line,'\t'))die("Erreur ligne %d : utilise des espaces, pas des tabulations",lineno);
        strip_comment(line);
        int indent=0;while(line[indent]==' ')indent++;
        if(indent%4!=0)die("Erreur ligne %d : l'indentation doit utiliser des groupes de 4 espaces",lineno);
        char*s=trim(line+indent);if(!*s)continue;

        /* Les listes, tables et appels peuvent s'étendre sur plusieurs lignes. */
        char logical[MAX_LINE * 8];
        snprintf(logical, sizeof(logical), "%s", s);
        int balance = bracket_balance(logical);
        int start_lineno = lineno;
        while (balance > 0) {
            char extra[MAX_LINE];
            if (!fgets(extra, sizeof(extra), in))
                die("Erreur ligne %d : parenthèse, crochet ou accolade non fermé", start_lineno);
            lineno++;
            if (strchr(extra, '\t'))
                die("Erreur ligne %d : utilise des espaces, pas des tabulations", lineno);
            strip_comment(extra);
            char *part = trim(extra);
            if (!*part) continue;
            size_t have = strlen(logical), need = strlen(part);
            if (have + need + 2 >= sizeof(logical))
                die("Erreur ligne %d : expression multiligne trop longue", start_lineno);
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
        if(strncmp(s,"cas ",4)==0){
            if(top_block() && top_block()->kind==BLK_CASE && top_block()->indent==indent) close_one_block();
            Block *mb=NULL; for(int bi=block_count-1;bi>=0;bi--){if(blocks[bi].kind==BLK_MATCH && blocks[bi].indent==indent-4){mb=&blocks[bi];break;}}
            if(!mb)die("Erreur ligne %d : 'cas' doit être placé dans un bloc selon",lineno);
            size_t sn=strlen(s); if(s[sn-1]!=':')die("Erreur ligne %d : ':' attendu après cas",lineno);
            char ce[MAX_LINE]; snprintf(ce,sizeof(ce),"%.*s",(int)sn-5,s+4); char *cv=compile_expr(trim(ce),lineno);
            FILE *mo=out_for_kind(mb->out_kind); emit_indent(mo,indent);
            fprintf(mo,mb->case_count?"else if (nv_truth(nv_eq(__selon%d, %s))) {\n":"if (nv_truth(nv_eq(__selon%d, %s))) {\n",mb->try_id,cv);
            free(cv); mb->case_count++; push_block(BLK_CASE,indent,mb->out_kind,NULL,0); continue;
        }
        if(strcmp(s,"sinon:")==0 && top_block() && top_block()->kind==BLK_CASE && top_block()->indent==indent){
            close_one_block(); Block *mb=NULL; for(int bi=block_count-1;bi>=0;bi--){if(blocks[bi].kind==BLK_MATCH && blocks[bi].indent==indent-4){mb=&blocks[bi];break;}}
            if(!mb)die("Erreur ligne %d : sinon de selon sans bloc selon",lineno);
            FILE *mo=out_for_kind(mb->out_kind); emit_indent(mo,indent); fprintf(mo,"else {\n"); mb->case_count++; push_block(BLK_CASE,indent,mb->out_kind,NULL,0); continue;
        }

        /* Transitions sinon/sinonsi/capture/toujours. */
        if((strncmp(s,"sinon:",6)==0 || strncmp(s,"sinonsi ",8)==0) && top_block() && top_block()->indent==indent && top_block()->kind==BLK_IF){close_one_block();}
        if(strncmp(s,"capture ",8)==0 && top_block() && top_block()->indent==indent && top_block()->kind==BLK_TRY){
            Block tb=blocks[--block_count];FILE*out=out_for_kind(tb.out_kind);emit_indent(out,indent);fprintf(out,"nv_try_top = __try%d.prev;\n",tb.try_id);emit_indent(out,indent);fprintf(out,"} else {\n");emit_indent(out,indent+4);fprintf(out,"nv_try_top = __try%d.prev;\n",tb.try_id);
            char name[MAX_NAME];snprintf(name,sizeof(name),"%s",trim(s+8));size_t n=strlen(name);if(n&&name[n-1]==':')name[n-1]='\0';char*vn=trim(name);emit_indent(out,indent+4);fprintf(out,"NvVal %s = nv_str(nv_error_message);\n",vn);VarScope*sc=(current_output()==OUT_FUNC)?&func_scope:&main_scope;scope_add(sc,vn);push_block(BLK_CATCH,indent,tb.out_kind,NULL,tb.try_id);continue;
        }
        if(strcmp(s,"toujours:")==0 && top_block() && top_block()->indent==indent && top_block()->kind==BLK_CATCH){OutKind ok=top_block()->out_kind;close_one_block();FILE*out=out_for_kind(ok);emit_indent(out,indent);fprintf(out,"{\n");push_block(BLK_ALWAYS,indent,ok,NULL,0);continue;}

        /* À même niveau, fermer le bloc précédent. Les conteneurs objet/structure
           restent ouverts pendant leurs membres indentés, mais se ferment dès
           qu'on revient à leur niveau. */
        while(top_block() && top_block()->indent==indent) close_one_block();

        /* Définition de structure / objet */
        if(indent==0 && strncmp(s,"structure ",10)==0){char name[MAX_NAME];snprintf(name,sizeof(name),"%s",trim(s+10));size_t n=strlen(name);if(n&&name[n-1]==':')name[n-1]='\0';if(!is_ident(trim(name)))die("Erreur ligne %d : nom de structure invalide",lineno);register_type(trim(name),TYPE_STRUCTURE);push_block(BLK_STRUCTURE,0,OUT_NONE,trim(name),0);continue;}
        if(indent==0 && strncmp(s,"objet ",6)==0){char name[MAX_NAME];snprintf(name,sizeof(name),"%s",trim(s+6));size_t n=strlen(name);if(n&&name[n-1]==':')name[n-1]='\0';if(!is_ident(trim(name)))die("Erreur ligne %d : nom d'objet invalide",lineno);register_type(trim(name),TYPE_OBJECT);push_block(BLK_OBJECT,0,OUT_NONE,trim(name),0);continue;}

        /* Champ dans structure/objet */
        TypeMeta*ct=current_type_meta();
        if(ct && indent==4 && strncmp(s,"fn ",3)!=0){char buf[MAX_LINE];snprintf(buf,sizeof(buf),"%s",s);char*colon=strchr(buf,':');if(colon && !strchr(buf,'=')){*colon='\0';char*name=trim(buf);char*type=trim(colon+1);if(!is_ident(name))die("Erreur ligne %d : champ invalide",lineno);if(ct->field_count>=MAX_FIELDS)die("Trop de champs");FieldMeta*f=&ct->fields[ct->field_count++];snprintf(f->name,sizeof(f->name),"%s",name);snprintf(f->type,sizeof(f->type),"%s",type);continue;}}

        /* Fonction globale ou méthode */
        if(strncmp(s,"fn ",3)==0){
            char hdr[MAX_LINE];snprintf(hdr,sizeof(hdr),"%s",s+3);char*lpar=strchr(hdr,'(');char*rpar=strrchr(hdr,')');if(!lpar||!rpar||rpar<lpar)die("Erreur ligne %d : définition de fonction invalide",lineno);*lpar='\0';char*name=trim(hdr);*rpar='\0';char*params=lpar+1;char ret[MAX_NAME]="auto";char*after=trim(rpar+1);if(strncmp(after,"->",2)==0){after=trim(after+2);char*col=strrchr(after,':');if(col)*col='\0';snprintf(ret,sizeof(ret),"%s",trim(after));}
            const char*owner=current_owner();if(owner&&find_type(owner)->kind==TYPE_STRUCTURE)die("Erreur ligne %d : une structure ne contient pas de méthode",lineno);
            FuncMeta*fm=register_function(name,owner,params,ret);emit_function_header(fm,indent);push_block(BLK_FUNC,indent,OUT_FUNC,owner,0);continue;
        }

        OutKind ok=current_output();FILE*out=out_for_kind(ok);if(!out)die("Erreur ligne %d : instruction invalide ici",lineno);VarScope*scope=(ok==OUT_FUNC)?&func_scope:&main_scope;
        VarScope*consts=(ok==OUT_FUNC)?&func_consts:&main_consts;

        /* valeur fixe */
        if(strncmp(s,"fixe ",5)==0){
            char rest[MAX_LINE]; snprintf(rest,sizeof(rest),"%s",trim(s+5)); int ol=0; int ap=find_top_level_assignment(rest,&ol);
            if(ap<0||ol!=1)die("Erreur ligne %d : utilise 'fixe nom = valeur'",lineno);
            char lhs[MAX_LINE],rhs[MAX_LINE]; snprintf(lhs,sizeof(lhs),"%.*s",ap,rest); snprintf(rhs,sizeof(rhs),"%s",rest+ap+1);
            char nbuf[MAX_NAME]; snprintf(nbuf,sizeof(nbuf),"%s",trim(lhs)); char *col=strchr(nbuf,':'); if(col)*col='\0'; char *vn=trim(nbuf);
            if(!is_ident(vn))die("Erreur ligne %d : nom fixe invalide",lineno);
            emit_set_lvalue(out,indent,trim(lhs),trim(rhs),lineno,scope,NULL,NULL); scope_add(consts,vn); continue;
        }

        /* selon / cas */
        if(strncmp(s,"selon ",6)==0){
            size_t n=strlen(s); if(s[n-1]!=':')die("Erreur ligne %d : ':' attendu après selon",lineno);
            char ex[MAX_LINE]; snprintf(ex,sizeof(ex),"%.*s",(int)n-7,s+6); char *e=compile_expr(trim(ex),lineno); int id=++try_counter;
            emit_indent(out,indent); fprintf(out,"{ NvVal __selon%d = %s;\n",id,e); free(e); push_block(BLK_MATCH,indent,ok,NULL,id); continue;
        }

        /* avec ferme automatiquement un fichier à la fin normale du bloc */
        if(strncmp(s,"avec ",5)==0){
            size_t n=strlen(s); if(s[n-1]!=':')die("Erreur ligne %d : ':' attendu après avec",lineno);
            char body[MAX_LINE]; snprintf(body,sizeof(body),"%.*s",(int)n-6,s+5); int ol=0; int ap=find_top_level_assignment(body,&ol);
            if(ap<0||ol!=1)die("Erreur ligne %d : utilise 'avec fichier = ouvre(...):'",lineno);
            char lhs[MAX_NAME],rhs[MAX_LINE]; snprintf(lhs,sizeof(lhs),"%.*s",ap,body); snprintf(rhs,sizeof(rhs),"%s",body+ap+1); char *vn=trim(lhs);
            if(!is_ident(vn))die("Erreur ligne %d : nom de fichier invalide",lineno); char *e=compile_expr(trim(rhs),lineno);
            emit_indent(out,indent); fprintf(out,"{ NvVal %s = %s;\n",vn,e); free(e); scope_add(scope,vn); push_block(BLK_WITH,indent,ok,vn,0); continue;
        }


        /* contrôle de boucle */
        if(strcmp(s,"arrete")==0 || strcmp(s,"suivant")==0){
            int loop=0; for(int bi=block_count-1;bi>=0;bi--){if(blocks[bi].kind==BLK_FOR||blocks[bi].kind==BLK_WHILE){loop=1;break;}}
            if(!loop)die("Erreur ligne %d : '%s' doit être utilisé dans une boucle",lineno,s);
            emit_indent(out,indent); fprintf(out,strcmp(s,"arrete")==0?"break;\n":"continue;\n"); continue;
        }

        /* retour */
        if(strncmp(s,"retourne",8)==0 && (s[8]=='\0'||isspace((unsigned char)s[8]))){char*rest=trim(s+8);emit_indent(out,indent);if(*rest){char*e=compile_expr(rest,lineno);fprintf(out,"return %s;\n",e);free(e);}else fprintf(out,"return nv_none();\n");continue;}

        /* si / sinonsi / sinon */
        if(strncmp(s,"si ",3)==0){size_t n=strlen(s);if(s[n-1]!=':')die("Erreur ligne %d : ':' attendu après si",lineno);char cond[MAX_LINE];snprintf(cond,sizeof(cond),"%.*s",(int)n-4,s+3);char*e=compile_expr(trim(cond),lineno);emit_indent(out,indent);fprintf(out,"if (nv_truth(%s)) {\n",e);free(e);push_block(BLK_IF,indent,ok,NULL,0);continue;}
        if(strncmp(s,"sinonsi ",8)==0){size_t n=strlen(s);if(s[n-1]!=':')die("Erreur ligne %d : ':' attendu après sinonsi",lineno);char cond[MAX_LINE];snprintf(cond,sizeof(cond),"%.*s",(int)n-9,s+8);char*e=compile_expr(trim(cond),lineno);emit_indent(out,indent);fprintf(out,"else if (nv_truth(%s)) {\n",e);free(e);push_block(BLK_IF,indent,ok,NULL,0);continue;}
        if(strcmp(s,"sinon:")==0){emit_indent(out,indent);fprintf(out,"else {\n");push_block(BLK_IF,indent,ok,NULL,0);continue;}

        /* tantque */
        if(strncmp(s,"tantque ",8)==0){size_t n=strlen(s);if(s[n-1]!=':')die("Erreur ligne %d : ':' attendu après tantque",lineno);char cond[MAX_LINE];snprintf(cond,sizeof(cond),"%.*s",(int)n-9,s+8);char*e=compile_expr(trim(cond),lineno);emit_indent(out,indent);fprintf(out,"while (nv_truth(%s)) {\n",e);free(e);push_block(BLK_WHILE,indent,ok,NULL,0);continue;}

        /* pour x dans expr */
        if(strncmp(s,"pour ",5)==0){size_t n=strlen(s);if(s[n-1]!=':')die("Erreur ligne %d : ':' attendu après pour",lineno);char tmp[MAX_LINE];snprintf(tmp,sizeof(tmp),"%.*s",(int)n-6,s+5);char*din=strstr(tmp," dans ");if(!din)die("Erreur ligne %d : 'dans' attendu",lineno);*din='\0';char*vn=trim(tmp);char*iter=trim(din+6);if(!is_ident(vn))die("Erreur ligne %d : variable de boucle invalide",lineno);char*ie=compile_expr(iter,lineno);int id=lineno;emit_indent(out,indent);fprintf(out,"{ NvVal __iter%d = %s; for (int __i%d=0; __i%d<nv_len(__iter%d); __i%d++) {\n",id,ie,id,id,id,id);free(ie);emit_indent(out,indent+4);if(!scope_has(scope,vn)){fprintf(out,"NvVal %s = nv_iter_get(__iter%d,__i%d);\n",vn,id,id);scope_add(scope,vn);}else fprintf(out,"%s = nv_iter_get(__iter%d,__i%d);\n",vn,id,id);push_block(BLK_FOR,indent,ok,NULL,0);continue;}

        /* tente */
        if(strcmp(s,"tente:")==0){int id=++try_counter;emit_indent(out,indent);fprintf(out,"NvTryFrame __try%d; __try%d.prev=nv_try_top; nv_try_top=&__try%d; if (setjmp(__try%d.env)==0) {\n",id,id,id,id);push_block(BLK_TRY,indent,ok,NULL,id);continue;}

        /* Affectation */
        int oplen=0;int apos=find_top_level_assignment(s,&oplen);if(apos>=0){char lhs[MAX_LINE],rhs[MAX_LINE];snprintf(lhs,sizeof(lhs),"%.*s",apos,s);snprintf(rhs,sizeof(rhs),"%s",s+apos+oplen);char aug[2]={0};if(oplen==2){aug[0]=s[apos];aug[1]='\0';}emit_set_lvalue(out,indent,trim(lhs),trim(rhs),lineno,scope,NULL,aug[0]?aug:NULL);continue;}

        /* Expression seule, ex. ecris(...), liste.ajoute(...) */
        char*e=compile_expr(s,lineno);emit_indent(out,indent);fprintf(out,"(void)%s;\n",e);free(e);
    }

    while(block_count>0)close_one_block();
    fflush(main_out);fflush(func_out);rewind(main_out);rewind(func_out);

    /* Le runtime est séparé pour garder le C généré lisible. */
    char runtimefile[512]; snprintf(runtimefile,sizeof(runtimefile),"%s",cfile); char *slash=strrchr(runtimefile,'/');
    if(slash) snprintf(slash+1,(size_t)(runtimefile+sizeof(runtimefile)-(slash+1)),"clair_runtime.h"); else snprintf(runtimefile,sizeof(runtimefile),"clair_runtime.h");
    FILE*rt=fopen(runtimefile,"w"); if(!rt)die("Impossible de créer %s",runtimefile);
    fputs("#ifndef CLAIR_RUNTIME_H\n#define CLAIR_RUNTIME_H\n",rt); fputs(RUNTIME_C,rt); fputs("\n#endif\n",rt); fclose(rt);
    FILE*out=fopen(cfile,"w");if(!out)die("Impossible de créer %s",cfile);fputs("#include \"clair_runtime.h\"\n",out);
    int ch;while((ch=fgetc(func_out))!=EOF)fputc(ch,out);
    emit_dispatch(out);
    fprintf(out,"\nint main(void){\n");while((ch=fgetc(main_out))!=EOF)fputc(ch,out);fprintf(out,"    return 0;\n}\n");
    fclose(out);fclose(main_out);fclose(func_out);remove(main_tmp);remove(func_tmp);
}

int main(int argc,char**argv){
    if(argc!=3){fprintf(stderr,"Usage : %s programme.clair sortie\n",argv[0]);return 1;}
    if(!safe_filename(argv[1])||!safe_filename(argv[2])){fprintf(stderr,"Nom de fichier non autorisé\n");return 1;}
    FILE*in=fopen(argv[1],"r");if(!in){perror("source");return 1;}
    char cfile[512];snprintf(cfile,sizeof(cfile),"%s.c",argv[2]);
    compile_source(in,cfile);fclose(in);
    char cmd[1400];snprintf(cmd,sizeof(cmd),"clang -std=gnu11 -O3 -Wall -Wextra -Wno-unused-function -Wno-unused-parameter '%s' -lm -o '%s'",cfile,argv[2]);
    printf("[Clair] C généré : %s\n",cfile);printf("[Clair] Runtime séparé : clair_runtime.h\n");printf("[Clair] Compilation native avec Clang -O3...\n");
    int rc=system(cmd);if(rc!=0){fprintf(stderr,"Échec de Clang. Le fichier C généré a été conservé pour diagnostic.\n");return 1;}
    printf("[Clair] Exécutable créé : %s\n",argv[2]);return 0;
}
