#ifndef CLAIR_RUNTIME_H
#define CLAIR_RUNTIME_H
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <math.h>
#include <setjmp.h>

typedef struct NvVal NvVal;
typedef struct NvList NvList;
typedef struct NvDict NvDict;
typedef struct NvObj NvObj;
typedef struct NvCall NvCall;
typedef struct NvTryFrame NvTryFrame;

typedef enum { NV_NONE, NV_INT, NV_FLOAT, NV_BOOL, NV_STR, NV_LIST, NV_DICT, NV_OBJ, NV_FILE } NvKind;
struct NvVal { NvKind kind; union { long long i; double f; int b; char *s; NvList *list; NvDict *dict; NvObj *obj; FILE *file; } as; };
struct NvList { NvVal *items; int len, cap; };
struct NvDict { char **keys; NvVal *vals; int len, cap; };
struct NvObj { char *type; NvDict *fields; };
struct NvCall { NvVal *args; int argc, cap; NvDict *kw; };
struct NvTryFrame { jmp_buf env; NvTryFrame *prev; };
static NvTryFrame *nv_try_top = NULL;
static char nv_error_message[1024] = {0};

static void *nv_xmalloc(size_t n){ void *p=malloc(n?n:1); if(!p){fprintf(stderr,"Mémoire insuffisante\n"); exit(2);} return p;}
static char *nv_strdup(const char *s){ size_t n=strlen(s)+1; char *p=nv_xmalloc(n); memcpy(p,s,n); return p;}
static NvVal nv_none(void){ NvVal v; memset(&v,0,sizeof(v)); v.kind=NV_NONE; return v;}
static NvVal nv_int(long long x){ NvVal v=nv_none(); v.kind=NV_INT; v.as.i=x; return v;}
static NvVal nv_float(double x){ NvVal v=nv_none(); v.kind=NV_FLOAT; v.as.f=x; return v;}
static NvVal nv_bool(int x){ NvVal v=nv_none(); v.kind=NV_BOOL; v.as.b=!!x; return v;}
static NvVal nv_str(const char *x){ NvVal v=nv_none(); v.kind=NV_STR; v.as.s=nv_strdup(x); return v;}
static NvDict *nv_dict_new(void){ NvDict*d=nv_xmalloc(sizeof(*d)); d->keys=NULL; d->vals=NULL; d->len=0; d->cap=0; return d;}
static NvVal nv_dict_new_value(void){ NvVal v=nv_none(); v.kind=NV_DICT; v.as.dict=nv_dict_new(); return v;}
static NvVal nv_list_new(void){ NvVal v=nv_none(); v.kind=NV_LIST; v.as.list=nv_xmalloc(sizeof(NvList)); v.as.list->items=NULL; v.as.list->len=0; v.as.list->cap=0; return v;}
static NvVal nv_file_value(FILE *f){ NvVal v=nv_none(); v.kind=NV_FILE; v.as.file=f; return v;}
static NvVal nv_to_str(NvVal v){ char b[256]; switch(v.kind){case NV_STR:return nv_str(v.as.s);case NV_NONE:return nv_str("rien");case NV_INT:snprintf(b,sizeof(b),"%lld",v.as.i);return nv_str(b);case NV_FLOAT:snprintf(b,sizeof(b),"%g",v.as.f);return nv_str(b);case NV_BOOL:return nv_str(v.as.b?"vrai":"faux");case NV_LIST:return nv_str("<liste>");case NV_DICT:return nv_str("<table>");case NV_OBJ:snprintf(b,sizeof(b),"<%s>",v.as.obj->type);return nv_str(b);case NV_FILE:return nv_str("<fichier>");}return nv_str("");}
static void nv_throw(const char *msg){ snprintf(nv_error_message,sizeof(nv_error_message),"%s",msg); if(nv_try_top) longjmp(nv_try_top->env,1); fprintf(stderr,"Erreur Clair : %s\n",msg); exit(1);}
static void nv_throwf(const char *fmt,const char *a){ snprintf(nv_error_message,sizeof(nv_error_message),fmt,a); if(nv_try_top) longjmp(nv_try_top->env,1); fprintf(stderr,"Erreur Clair : %s\n",nv_error_message); exit(1);}
static int nv_truth(NvVal v){ switch(v.kind){case NV_NONE:return 0;case NV_BOOL:return v.as.b;case NV_INT:return v.as.i!=0;case NV_FLOAT:return v.as.f!=0.0;case NV_STR:return v.as.s&&v.as.s[0];case NV_LIST:return v.as.list&&v.as.list->len>0;case NV_DICT:return v.as.dict&&v.as.dict->len>0;case NV_OBJ:return 1;case NV_FILE:return v.as.file!=NULL;} return 0;}
static double nv_num(NvVal v){ if(v.kind==NV_INT)return(double)v.as.i; if(v.kind==NV_FLOAT)return v.as.f; if(v.kind==NV_BOOL)return(double)v.as.b; nv_throw("Une valeur numérique était attendue"); return 0;}
static NvVal nv_add(NvVal a,NvVal b){ if(a.kind==NV_STR&&b.kind==NV_STR){size_t n=strlen(a.as.s)+strlen(b.as.s)+1;char*p=nv_xmalloc(n);snprintf(p,n,"%s%s",a.as.s,b.as.s);NvVal v=nv_none();v.kind=NV_STR;v.as.s=p;return v;} if(a.kind==NV_INT&&b.kind==NV_INT)return nv_int(a.as.i+b.as.i); return nv_float(nv_num(a)+nv_num(b));}
static NvVal nv_sub(NvVal a,NvVal b){ if(a.kind==NV_INT&&b.kind==NV_INT)return nv_int(a.as.i-b.as.i); return nv_float(nv_num(a)-nv_num(b));}
static NvVal nv_mul(NvVal a,NvVal b){ if(a.kind==NV_INT&&b.kind==NV_INT)return nv_int(a.as.i*b.as.i); return nv_float(nv_num(a)*nv_num(b));}
static NvVal nv_div(NvVal a,NvVal b){ double d=nv_num(b); if(d==0.0)nv_throw("Division par zéro"); return nv_float(nv_num(a)/d);}
static NvVal nv_mod(NvVal a,NvVal b){ long long x=(long long)nv_num(a), y=(long long)nv_num(b); if(!y)nv_throw("Modulo par zéro"); return nv_int(x%y);}
static NvVal nv_pow(NvVal a,NvVal b){ return nv_float(pow(nv_num(a),nv_num(b)));}
static NvVal nv_neg(NvVal a){ if(a.kind==NV_INT)return nv_int(-a.as.i); return nv_float(-nv_num(a));}
static NvVal nv_not(NvVal a){return nv_bool(!nv_truth(a));}
static NvVal nv_and(NvVal a,NvVal b){return nv_bool(nv_truth(a)&&nv_truth(b));}
static NvVal nv_or(NvVal a,NvVal b){return nv_bool(nv_truth(a)||nv_truth(b));}
static int nv_same(NvVal a,NvVal b){ if(a.kind!=b.kind){if((a.kind==NV_INT||a.kind==NV_FLOAT||a.kind==NV_BOOL)&&(b.kind==NV_INT||b.kind==NV_FLOAT||b.kind==NV_BOOL))return nv_num(a)==nv_num(b);return 0;} switch(a.kind){case NV_NONE:return 1;case NV_INT:return a.as.i==b.as.i;case NV_FLOAT:return a.as.f==b.as.f;case NV_BOOL:return a.as.b==b.as.b;case NV_STR:return strcmp(a.as.s,b.as.s)==0;case NV_FILE:return a.as.file==b.as.file;default:return a.as.obj==b.as.obj;} }
static NvVal nv_eq(NvVal a,NvVal b){return nv_bool(nv_same(a,b));} static NvVal nv_ne(NvVal a,NvVal b){return nv_bool(!nv_same(a,b));}
static NvVal nv_lt(NvVal a,NvVal b){return nv_bool(nv_num(a)<nv_num(b));} static NvVal nv_le(NvVal a,NvVal b){return nv_bool(nv_num(a)<=nv_num(b));} static NvVal nv_gt(NvVal a,NvVal b){return nv_bool(nv_num(a)>nv_num(b));} static NvVal nv_ge(NvVal a,NvVal b){return nv_bool(nv_num(a)>=nv_num(b));}
static void nv_print_one(NvVal v){ switch(v.kind){case NV_NONE:printf("rien");break;case NV_INT:printf("%lld",v.as.i);break;case NV_FLOAT:printf("%g",v.as.f);break;case NV_BOOL:printf("%s",v.as.b?"vrai":"faux");break;case NV_STR:printf("%s",v.as.s);break;case NV_LIST:printf("[");for(int i=0;i<v.as.list->len;i++){if(i)printf(", ");nv_print_one(v.as.list->items[i]);}printf("]");break;case NV_DICT:printf("{");for(int i=0;i<v.as.dict->len;i++){if(i)printf(", ");printf("\"%s\": ",v.as.dict->keys[i]);nv_print_one(v.as.dict->vals[i]);}printf("}");break;case NV_OBJ:printf("<%s>",v.as.obj->type);break;case NV_FILE:printf("<fichier>");break;} }
static void nv_list_append(NvVal l,NvVal v){ if(l.kind!=NV_LIST)nv_throw("ajoute() nécessite une liste"); NvList*p=l.as.list; if(p->len==p->cap){p->cap=p->cap?p->cap*2:8;p->items=realloc(p->items,sizeof(NvVal)*p->cap);} p->items[p->len++]=v;}
static NvVal nv_range(NvVal a,NvVal b){ long long x=(long long)nv_num(a), y=(long long)nv_num(b); NvVal l=nv_list_new(); if(x<=y){for(long long i=x;i<y;i++)nv_list_append(l,nv_int(i));}else{for(long long i=x;i>y;i--)nv_list_append(l,nv_int(i));} return l;}
static void nv_file_close(NvVal v){ if(v.kind==NV_FILE && v.as.file) fclose(v.as.file); }
static NvVal nv_file_read(NvVal v){ if(v.kind!=NV_FILE||!v.as.file)nv_throw("Fichier non ouvert"); if(fseek(v.as.file,0,SEEK_END)!=0)nv_throw("Impossible de lire le fichier"); long n=ftell(v.as.file); if(n<0)nv_throw("Impossible de lire le fichier"); rewind(v.as.file); char *buf=nv_xmalloc((size_t)n+1); size_t got=fread(buf,1,(size_t)n,v.as.file); buf[got]='\0'; NvVal r=nv_str(buf); free(buf); return r;}
static NvVal nv_file_write(NvVal v,NvVal data){ if(v.kind!=NV_FILE||!v.as.file)nv_throw("Fichier non ouvert"); NvVal t=nv_to_str(data); fputs(t.as.s,v.as.file); fflush(v.as.file); return nv_none();}
static void nv_list_extend(NvVal l,NvVal other){ if(l.kind!=NV_LIST||other.kind!=NV_LIST)nv_throw("Le déballage * nécessite une liste"); for(int i=0;i<other.as.list->len;i++)nv_list_append(l,other.as.list->items[i]);}
static int nv_dict_find(NvDict*d,const char*k){for(int i=0;i<d->len;i++)if(strcmp(d->keys[i],k)==0)return i;return-1;}
static NvVal nv_contains(NvVal container,NvVal item){ if(container.kind==NV_LIST){for(int i=0;i<container.as.list->len;i++)if(nv_same(container.as.list->items[i],item))return nv_bool(1);return nv_bool(0);} if(container.kind==NV_DICT){if(item.kind!=NV_STR)return nv_bool(0);return nv_bool(nv_dict_find(container.as.dict,item.as.s)>=0);} if(container.kind==NV_STR){if(item.kind!=NV_STR)return nv_bool(0);return nv_bool(strstr(container.as.s,item.as.s)!=NULL);} nv_throw("'dans' nécessite une liste, une table ou un texte");return nv_bool(0);}
static void nv_dict_set(NvDict*d,const char*k,NvVal v){int i=nv_dict_find(d,k);if(i>=0){d->vals[i]=v;return;}if(d->len==d->cap){d->cap=d->cap?d->cap*2:8;d->keys=realloc(d->keys,sizeof(char*)*d->cap);d->vals=realloc(d->vals,sizeof(NvVal)*d->cap);}d->keys[d->len]=nv_strdup(k);d->vals[d->len]=v;d->len++;}
static void nv_dict_set_value(NvVal d,const char*k,NvVal v){if(d.kind!=NV_DICT)nv_throw("Une table était attendue");nv_dict_set(d.as.dict,k,v);}
static void nv_dict_merge_value(NvVal d,NvVal src){if(d.kind!=NV_DICT||src.kind!=NV_DICT)nv_throw("Le déballage ** nécessite une table");for(int i=0;i<src.as.dict->len;i++)nv_dict_set(d.as.dict,src.as.dict->keys[i],src.as.dict->vals[i]);}
static NvVal nv_dict_get(NvDict*d,const char*k){int i=nv_dict_find(d,k);if(i<0){char buf[512];snprintf(buf,sizeof(buf),"Clé introuvable : %s",k);nv_throw(buf);}return d->vals[i];}
static NvVal nv_get_index(NvVal a,NvVal i){ if(a.kind==NV_LIST){long long n=(long long)nv_num(i);if(n<0)n=a.as.list->len+n;if(n<0||n>=a.as.list->len)nv_throw("Indice de liste hors limites");return a.as.list->items[n];} if(a.kind==NV_DICT){if(i.kind!=NV_STR)nv_throw("Une clé texte était attendue");return nv_dict_get(a.as.dict,i.as.s);} if(a.kind==NV_STR){long long n=(long long)nv_num(i);int len=(int)strlen(a.as.s);if(n<0)n=len+n;if(n<0||n>=len)nv_throw("Indice de texte hors limites");char tmp[2]={a.as.s[n],0};return nv_str(tmp);} nv_throw("Cette valeur ne peut pas être indexée");return nv_none();}
static void nv_set_index(NvVal a,NvVal i,NvVal v){ if(a.kind==NV_LIST){long long n=(long long)nv_num(i);if(n<0)n=a.as.list->len+n;if(n<0||n>=a.as.list->len)nv_throw("Indice de liste hors limites");a.as.list->items[n]=v;return;} if(a.kind==NV_DICT){if(i.kind!=NV_STR)nv_throw("Une clé texte était attendue");nv_dict_set(a.as.dict,i.as.s,v);return;} nv_throw("Cette valeur ne peut pas recevoir un index");}
static NvVal nv_get_field(NvVal a,const char*name){if(a.kind!=NV_OBJ)nv_throw("Accès à un champ sur une valeur qui n'est pas un objet");return nv_dict_get(a.as.obj->fields,name);}
static void nv_set_field(NvVal a,const char*name,NvVal v){if(a.kind!=NV_OBJ)nv_throw("Affectation de champ sur une valeur qui n'est pas un objet");nv_dict_set(a.as.obj->fields,name,v);}
static NvVal nv_object_new(const char*type){NvVal v=nv_none();v.kind=NV_OBJ;v.as.obj=nv_xmalloc(sizeof(NvObj));v.as.obj->type=nv_strdup(type);v.as.obj->fields=nv_dict_new();return v;}
static int nv_len(NvVal v){if(v.kind==NV_LIST)return v.as.list->len;if(v.kind==NV_DICT)return v.as.dict->len;if(v.kind==NV_STR)return(int)strlen(v.as.s);nv_throw("longueur() nécessite une liste, une table ou un texte");return 0;}
static NvVal nv_iter_get(NvVal v,int i){if(v.kind==NV_LIST)return v.as.list->items[i];if(v.kind==NV_DICT)return nv_str(v.as.dict->keys[i]);if(v.kind==NV_STR){char t[2]={v.as.s[i],0};return nv_str(t);}nv_throw("Cette valeur n'est pas parcourable");return nv_none();}
static NvCall nv_call_new(void){NvCall c;c.args=NULL;c.argc=0;c.cap=0;c.kw=nv_dict_new();return c;}
static void nv_call_add(NvCall*c,NvVal v){if(c->argc==c->cap){c->cap=c->cap?c->cap*2:8;c->args=realloc(c->args,sizeof(NvVal)*c->cap);}c->args[c->argc++]=v;}
static void nv_call_spread(NvCall*c,NvVal v){if(v.kind!=NV_LIST)nv_throw("Le déballage * nécessite une liste");for(int i=0;i<v.as.list->len;i++)nv_call_add(c,v.as.list->items[i]);}
static void nv_call_kw(NvCall*c,const char*k,NvVal v){nv_dict_set(c->kw,k,v);}
static void nv_call_kwspread(NvCall*c,NvVal v){if(v.kind!=NV_DICT)nv_throw("Le déballage ** nécessite une table");for(int i=0;i<v.as.dict->len;i++)nv_dict_set(c->kw,v.as.dict->keys[i],v.as.dict->vals[i]);}
static void nv_call_free(NvCall*c){free(c->args);}
static NvVal nv_arg(NvVal*args,int argc,NvDict*kw,int pos,const char*name){if(pos<argc)return args[pos];int i=nv_dict_find(kw,name);if(i>=0)return kw->vals[i];char buf[512];snprintf(buf,sizeof(buf),"Argument manquant : %s",name);nv_throw(buf);return nv_none();}
static void nv_expect_type(NvVal v,const char*t,const char*name){int ok=0;if(strcmp(t,"entier")==0)ok=v.kind==NV_INT;else if(strcmp(t,"decimal")==0)ok=v.kind==NV_FLOAT||v.kind==NV_INT;else if(strcmp(t,"texte")==0)ok=v.kind==NV_STR;else if(strcmp(t,"booleen")==0)ok=v.kind==NV_BOOL;else if(strcmp(t,"liste")==0)ok=v.kind==NV_LIST;else if(strcmp(t,"table")==0)ok=v.kind==NV_DICT;else if(strcmp(t,"objet")==0)ok=v.kind==NV_OBJ;else if(strcmp(t,"fichier")==0)ok=v.kind==NV_FILE;else ok=1;if(!ok){char buf[512];snprintf(buf,sizeof(buf),"Type incorrect pour %s : %s attendu",name,t);nv_throw(buf);}}
static NvVal nv_dispatch_call(const char*,NvVal*,int,NvDict*);
static NvVal nv_dispatch_method(NvVal,const char*,NvVal*,int,NvDict*);


#endif
