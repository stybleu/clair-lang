#ifndef CLARIOX_RUNTIME_H
#define CLARIOX_RUNTIME_H
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <math.h>
#include <setjmp.h>
#include <stdint.h>
#include <limits.h>
#include <ctype.h>

typedef struct NvVal NvVal;
typedef struct NvList NvList;
typedef struct NvDict NvDict;
typedef struct NvObj NvObj;
typedef struct NvCall NvCall;
typedef struct NvTryFrame NvTryFrame;
typedef struct NvMemory NvMemory;
typedef struct NvMemoryScope NvMemoryScope;

typedef enum { NV_NONE, NV_INT, NV_UINT, NV_FLOAT, NV_BOOL, NV_STR, NV_LIST, NV_DICT, NV_OBJ, NV_FILE, NV_MEMORY } NvKind;
struct NvVal { NvKind kind; union { long long i; unsigned long long u; double f; int b; char *s; NvList *list; NvDict *dict; NvObj *obj; FILE *file; NvMemory *memory; } as; };
struct NvList { NvVal *items; int len, cap; };
struct NvDict { char **keys; NvVal *vals; int len, cap; };
struct NvObj { char *type; NvDict *fields; };
struct NvCall { NvVal *args; int argc, cap; NvDict *kw; };
struct NvTryFrame { jmp_buf env; NvTryFrame *prev; NvMemoryScope *memory_scope; };
typedef enum {
    NV_MEM_BYTE,
    NV_MEM_INT8,
    NV_MEM_UINT8,
    NV_MEM_INT16,
    NV_MEM_UINT16,
    NV_MEM_INT32,
    NV_MEM_UINT32,
    NV_MEM_INT64,
    NV_MEM_UINT64,
    NV_MEM_FLOAT32,
    NV_MEM_FLOAT64
} NvMemoryType;
struct NvMemory {
    unsigned char *data;
    size_t size;
    size_t count;
    NvMemoryType type;
    int freed;
    NvMemory *next;
};
struct NvMemoryScope { NvMemory *memory; NvMemoryScope *prev; };
static NvMemory *nv_memory_head = NULL;
static NvMemoryScope *nv_memory_scope_top = NULL;
static int nv_memory_cleanup_registered = 0;
static NvTryFrame *nv_try_top = NULL;
static char nv_error_message[1024] = {0};

static void *nv_xmalloc(size_t n){ void *p=malloc(n?n:1); if(!p){fprintf(stderr,"Out of memory\n"); exit(2);} return p;}
static char *nv_strdup(const char *s){ size_t n=strlen(s)+1; char *p=nv_xmalloc(n); memcpy(p,s,n); return p;}
/* NV_STRING_INTERN_V2 */
typedef struct NvInternStr {
    struct NvInternStr *next;
    unsigned long long hash;
    size_t len;
    char data[];
} NvInternStr;

#define NV_INTERN_BUCKETS 4096
static NvInternStr *nv_intern_table[NV_INTERN_BUCKETS] = {0};

static unsigned long long nv_hash_text(const char *s,size_t n){
    unsigned long long h=1469598103934665603ULL;
    for(size_t i=0;i<n;i++){
        h^=(unsigned char)s[i];
        h*=1099511628211ULL;
    }
    return h;
}

static char *nv_intern(const char *s){
    size_t n=strlen(s);
    unsigned long long h=nv_hash_text(s,n);
    size_t bucket=(size_t)(h%NV_INTERN_BUCKETS);

    for(NvInternStr*p=nv_intern_table[bucket];p;p=p->next){
        if(p->hash==h && p->len==n &&
           memcmp(p->data,s,n+1)==0)
            return p->data;
    }

    NvInternStr*p=(NvInternStr*)nv_xmalloc(sizeof(*p)+n+1);
    p->hash=h;
    p->len=n;
    memcpy(p->data,s,n+1);
    p->next=nv_intern_table[bucket];
    nv_intern_table[bucket]=p;
    return p->data;
}
static NvVal nv_none(void){ NvVal v; memset(&v,0,sizeof(v)); v.kind=NV_NONE; return v;}
static NvVal nv_int(long long x){ NvVal v=nv_none(); v.kind=NV_INT; v.as.i=x; return v;}
static NvVal nv_uint(unsigned long long x){ NvVal v=nv_none(); v.kind=NV_UINT; v.as.u=x; return v;}
static NvVal nv_float(double x){ NvVal v=nv_none(); v.kind=NV_FLOAT; v.as.f=x; return v;}
static NvVal nv_bool(int x){ NvVal v=nv_none(); v.kind=NV_BOOL; v.as.b=!!x; return v;}
static NvVal nv_str(const char *x){ NvVal v=nv_none(); v.kind=NV_STR; v.as.s=nv_intern(x); return v;}
static NvDict *nv_dict_new(void){ NvDict*d=nv_xmalloc(sizeof(*d)); d->keys=NULL; d->vals=NULL; d->len=0; d->cap=0; return d;}
static NvVal nv_dict_new_value(void){ NvVal v=nv_none(); v.kind=NV_DICT; v.as.dict=nv_dict_new(); return v;}
static NvVal nv_list_new(void){ NvVal v=nv_none(); v.kind=NV_LIST; v.as.list=nv_xmalloc(sizeof(NvList)); v.as.list->items=NULL; v.as.list->len=0; v.as.list->cap=0; return v;}
static NvVal nv_file_value(FILE *f){ NvVal v=nv_none(); v.kind=NV_FILE; v.as.file=f; return v;}
static NvVal nv_to_str(NvVal v){ char b[256]; switch(v.kind){case NV_STR:return nv_str(v.as.s);case NV_NONE:return nv_str("none");case NV_INT:snprintf(b,sizeof(b),"%lld",v.as.i);return nv_str(b);case NV_UINT:snprintf(b,sizeof(b),"%llu",v.as.u);return nv_str(b);case NV_FLOAT:snprintf(b,sizeof(b),"%g",v.as.f);return nv_str(b);case NV_BOOL:return nv_str(v.as.b?"true":"false");case NV_LIST:return nv_str("<list>");case NV_DICT:return nv_str("<dict>");case NV_OBJ:snprintf(b,sizeof(b),"<%s>",v.as.obj->type);return nv_str(b);case NV_MEMORY:if(!v.as.memory||v.as.memory->freed)return nv_str("<memory freed>");snprintf(b,sizeof(b),"<memory %zu bytes>",v.as.memory->size);return nv_str(b);case NV_FILE:return nv_str("<file>");}return nv_str("");}
static void nv_memory_scope_cleanup_to(NvMemoryScope *target);
static void nv_throw(const char *msg){ snprintf(nv_error_message,sizeof(nv_error_message),"%s",msg); if(nv_try_top){nv_memory_scope_cleanup_to(nv_try_top->memory_scope);longjmp(nv_try_top->env,1);} nv_memory_scope_cleanup_to(NULL); fprintf(stderr,"Clariox error: %s\n",msg); exit(1);}
static void nv_throwf(const char *fmt,const char *a){ snprintf(nv_error_message,sizeof(nv_error_message),fmt,a); if(nv_try_top){nv_memory_scope_cleanup_to(nv_try_top->memory_scope);longjmp(nv_try_top->env,1);} nv_memory_scope_cleanup_to(NULL); fprintf(stderr,"Clariox error: %s\n",nv_error_message); exit(1);}
static int nv_truth(NvVal v){
    switch(v.kind){
        case NV_NONE:return 0;
        case NV_BOOL:return v.as.b;
        case NV_INT:return v.as.i!=0;
        case NV_UINT:return v.as.u!=0;
        case NV_FLOAT:return v.as.f!=0.0;
        case NV_STR:return v.as.s&&v.as.s[0];
        case NV_LIST:return v.as.list&&v.as.list->len>0;
        case NV_DICT:return v.as.dict&&v.as.dict->len>0;
        case NV_OBJ:return 1;
        case NV_MEMORY:return v.as.memory&&!v.as.memory->freed;
        case NV_FILE:return v.as.file!=NULL;
    }
    return 0;
}

static int nv_is_integer(NvVal v){
    return
        v.kind==NV_INT ||
        v.kind==NV_UINT ||
        v.kind==NV_BOOL;
}

static int nv_is_numeric(NvVal v){
    return nv_is_integer(v) || v.kind==NV_FLOAT;
}

static __int128 nv_integer_i128(NvVal v){
    if(v.kind==NV_INT)
        return (__int128)v.as.i;

    if(v.kind==NV_UINT)
        return (__int128)v.as.u;

    if(v.kind==NV_BOOL)
        return (__int128)v.as.b;

    nv_throw("Expected an integer value");
    return 0;
}

static NvVal nv_integer_from_i128(__int128 x){
    if(x<(__int128)LLONG_MIN)
        nv_throw("Integer overflow");

    if(x<=(__int128)LLONG_MAX)
        return nv_int((long long)x);

    if(
        (unsigned __int128)x <=
        (unsigned __int128)ULLONG_MAX
    ){
        return nv_uint((unsigned long long)x);
    }

    nv_throw("Integer overflow");
    return nv_none();
}

static NvVal nv_integer_from_u128(unsigned __int128 x){
    if(
        x >
        (unsigned __int128)ULLONG_MAX
    ){
        nv_throw("Integer overflow");
    }

    if(
        x <=
        (unsigned __int128)LLONG_MAX
    ){
        return nv_int((long long)x);
    }

    return nv_uint((unsigned long long)x);
}

static double nv_num(NvVal v){
    if(v.kind==NV_INT)
        return (double)v.as.i;

    if(v.kind==NV_UINT)
        return (double)v.as.u;

    if(v.kind==NV_FLOAT)
        return v.as.f;

    if(v.kind==NV_BOOL)
        return (double)v.as.b;

    nv_throw("Expected a numeric value");
    return 0;
}

static long double nv_num_long_double(NvVal v){
    if(v.kind==NV_INT)
        return (long double)v.as.i;

    if(v.kind==NV_UINT)
        return (long double)v.as.u;

    if(v.kind==NV_FLOAT)
        return (long double)v.as.f;

    if(v.kind==NV_BOOL)
        return (long double)v.as.b;

    nv_throw("Expected a numeric value");
    return 0;
}

static NvVal nv_parse_integer_text(const char *text){
    const unsigned char *p=
        (const unsigned char*)text;

    while(isspace(*p))
        p++;

    int negative=0;

    if(*p=='+' || *p=='-'){
        negative=(*p=='-');
        p++;
    }

    if(!isdigit(*p))
        nv_throw("Expected an integer");

    unsigned long long value=0;

    while(isdigit(*p)){
        unsigned digit=
            (unsigned)(*p-'0');

        if(
            value >
            (ULLONG_MAX-digit)/10ULL
        ){
            nv_throw("Integer out of range");
        }

        value=value*10ULL+digit;
        p++;
    }

    while(isspace(*p))
        p++;

    if(*p!='\0')
        nv_throw("Expected an integer");

    if(negative){
        const unsigned long long min_abs=
            9223372036854775808ULL;

        if(value>min_abs)
            nv_throw("Integer out of range");

        if(value==min_abs)
            return nv_int(LLONG_MIN);

        return nv_int(
            -(long long)value
        );
    }

    if(
        value <=
        (unsigned long long)LLONG_MAX
    ){
        return nv_int((long long)value);
    }

    return nv_uint(value);
}

static NvVal nv_integer_from_double(double x){
    if(!isfinite(x))
        nv_throw(
            "Cannot convert non-finite float to int"
        );

    if(x<0.0){
        if(x<(double)LLONG_MIN)
            nv_throw("Integer out of range");

        return nv_int((long long)x);
    }

    if(x<=(double)LLONG_MAX)
        return nv_int((long long)x);

    /*
     * La conversion depuis float reste limitée par
     * la précision intrinsèque du double.
     */
    if(x>=18446744073709551616.0)
        nv_throw("Integer out of range");

    return nv_uint(
        (unsigned long long)x
    );
}

static void nv_memory_shutdown(void){ nv_memory_scope_cleanup_to(NULL); NvMemory*m=nv_memory_head; size_t leaks=0,bytes=0; while(m){ NvMemory*next=m->next; if(!m->freed){leaks++;bytes+=m->size;} free(m); m=next; } nv_memory_head=NULL; if(leaks)fprintf(stderr,"Clariox memory warning: %zu manual allocation(s) not freed (%zu bytes)\n",leaks,bytes); }
static NvMemory *nv_memory_get(NvVal v){ if(v.kind!=NV_MEMORY||!v.as.memory)nv_throw("Expected a memory block"); if(v.as.memory->freed)nv_throw("Memory block has already been freed"); return v.as.memory; }
static const char *nv_memory_type_name(NvMemoryType type){
    switch(type){
        case NV_MEM_BYTE:return "byte";
        case NV_MEM_INT8:return "int8";
        case NV_MEM_UINT8:return "uint8";
        case NV_MEM_INT16:return "int16";
        case NV_MEM_UINT16:return "uint16";
        case NV_MEM_INT32:return "int32";
        case NV_MEM_UINT32:return "uint32";
        case NV_MEM_INT64:return "int64";
        case NV_MEM_UINT64:return "uint64";
        case NV_MEM_FLOAT32:return "float32";
        case NV_MEM_FLOAT64:return "float64";
    }
    return "unknown";
}

static size_t nv_memory_type_size(NvMemoryType type){
    switch(type){
        case NV_MEM_BYTE:return 1;
        case NV_MEM_INT8:return sizeof(int8_t);
        case NV_MEM_UINT8:return sizeof(uint8_t);
        case NV_MEM_INT16:return sizeof(int16_t);
        case NV_MEM_UINT16:return sizeof(uint16_t);
        case NV_MEM_INT32:return sizeof(int32_t);
        case NV_MEM_UINT32:return sizeof(uint32_t);
        case NV_MEM_INT64:return sizeof(int64_t);
        case NV_MEM_UINT64:return sizeof(uint64_t);
        case NV_MEM_FLOAT32:return sizeof(float);
        case NV_MEM_FLOAT64:return sizeof(double);
    }
    nv_throw("Unknown memory element type");
    return 0;
}

static size_t nv_memory_nonnegative_integer(
    NvVal v,
    const char *message
){
    if(v.kind==NV_INT){
        if(v.as.i<0)
            nv_throw(message);

        return (size_t)v.as.i;
    }

    if(v.kind==NV_UINT){
        if(
            v.as.u >
            (unsigned long long)SIZE_MAX
        ){
            nv_throw(message);
        }

        return (size_t)v.as.u;
    }

    if(v.kind==NV_FLOAT){
        double x=v.as.f;

        if(
            !isfinite(x) ||
            x<0.0 ||
            floor(x)!=x ||
            x>(double)SIZE_MAX
        ){
            nv_throw(message);
        }

        return (size_t)x;
    }

    nv_throw(message);
    return 0;
}

static __int128 nv_memory_integer_value(
    NvVal value,
    const char *type_name
){
    if(value.kind==NV_INT)
        return (__int128)value.as.i;

    if(value.kind==NV_UINT)
        return (__int128)value.as.u;

    {
        char buf[160];

        snprintf(
            buf,
            sizeof(buf),
            "%s memory requires an integer value",
            type_name
        );

        nv_throw(buf);
    }

    return 0;
}

static void nv_memory_integer_range_error(
    const char *type_name
){
    char buf[160];

    snprintf(
        buf,
        sizeof(buf),
        "%s memory value out of range",
        type_name
    );

    nv_throw(buf);
}

static NvVal nv_memory_alloc_kind(
    NvVal countv,
    NvMemoryType type
){
    size_t count=nv_memory_nonnegative_integer(
        countv,
        "Memory allocation size must be a non-negative integer"
    );

    if(count==0)
        nv_throw("alloc() size must be greater than zero");

    size_t element_size=nv_memory_type_size(type);

    if(count>SIZE_MAX/element_size)
        nv_throw("Memory allocation is too large");

    size_t bytes=count*element_size;

    NvMemory*m=nv_xmalloc(sizeof(*m));

    m->data=nv_xmalloc(bytes);
    memset(m->data,0,bytes);

    m->size=bytes;
    m->count=count;
    m->type=type;
    m->freed=0;

    m->next=nv_memory_head;
    nv_memory_head=m;

    if(!nv_memory_cleanup_registered){
        atexit(nv_memory_shutdown);
        nv_memory_cleanup_registered=1;
    }

    NvVal v=nv_none();
    v.kind=NV_MEMORY;
    v.as.memory=m;

    return v;
}

static NvVal nv_memory_alloc(NvVal sizev){
    return nv_memory_alloc_kind(
        sizev,
        NV_MEM_BYTE
    );
}

static NvVal nv_memory_free(NvVal v){
    NvMemory*m=nv_memory_get(v);

    free(m->data);
    m->data=NULL;
    m->freed=1;

    return nv_none();
}

static void nv_memory_free_scoped(NvVal v){
    if(v.kind!=NV_MEMORY||!v.as.memory)
        return;

    NvMemory*m=v.as.memory;

    if(m->freed)
        return;

    free(m->data);
    m->data=NULL;
    m->freed=1;
}

static void nv_memory_scope_enter(NvVal v){
    NvMemory*m=nv_memory_get(v);
    NvMemoryScope*s=nv_xmalloc(sizeof(*s));

    s->memory=m;
    s->prev=nv_memory_scope_top;

    nv_memory_scope_top=s;
}

static void nv_memory_scope_leave(NvVal v){
    if(v.kind!=NV_MEMORY||!v.as.memory)
        return;

    if(
        !nv_memory_scope_top ||
        nv_memory_scope_top->memory!=v.as.memory
    ){
        nv_throw("Internal scoped-memory stack mismatch");
    }

    NvMemoryScope*s=nv_memory_scope_top;

    nv_memory_scope_top=s->prev;

    nv_memory_free_scoped(v);

    free(s);
}

static void nv_memory_scope_cleanup_to(
    NvMemoryScope *target
){
    while(
        nv_memory_scope_top &&
        nv_memory_scope_top!=target
    ){
        NvMemoryScope*s=nv_memory_scope_top;

        nv_memory_scope_top=s->prev;

        if(
            s->memory &&
            !s->memory->freed
        ){
            free(s->memory->data);
            s->memory->data=NULL;
            s->memory->freed=1;
        }

        free(s);
    }
}

static NvVal nv_memory_size(NvVal v){
    NvMemory*m=nv_memory_get(v);

    return nv_int(
        (long long)m->size
    );
}

static NvVal nv_memory_length(NvVal v){
    NvMemory*m=nv_memory_get(v);

    return nv_int(
        (long long)m->count
    );
}

static NvVal nv_memory_type_value(NvVal v){
    NvMemory*m=nv_memory_get(v);

    return nv_str(
        nv_memory_type_name(m->type)
    );
}

static NvVal nv_memory_load_at(
    NvMemory *m,
    size_t i
){
    switch(m->type){

        case NV_MEM_BYTE:
            return nv_int(
                (long long)m->data[i]
            );

        case NV_MEM_INT8:{
            int8_t x;
            memcpy(&x,m->data+i*sizeof(x),sizeof(x));
            return nv_int((long long)x);
        }

        case NV_MEM_UINT8:{
            uint8_t x;
            memcpy(&x,m->data+i*sizeof(x),sizeof(x));
            return nv_int((long long)x);
        }

        case NV_MEM_INT16:{
            int16_t x;
            memcpy(&x,m->data+i*sizeof(x),sizeof(x));
            return nv_int((long long)x);
        }

        case NV_MEM_UINT16:{
            uint16_t x;
            memcpy(&x,m->data+i*sizeof(x),sizeof(x));
            return nv_int((long long)x);
        }

        case NV_MEM_INT32:{
            int32_t x;
            memcpy(&x,m->data+i*sizeof(x),sizeof(x));
            return nv_int((long long)x);
        }

        case NV_MEM_UINT32:{
            uint32_t x;
            memcpy(&x,m->data+i*sizeof(x),sizeof(x));
            return nv_int((long long)x);
        }

        case NV_MEM_INT64:{
            int64_t x;
            memcpy(&x,m->data+i*sizeof(x),sizeof(x));
            return nv_int((long long)x);
        }

        case NV_MEM_UINT64:{
            uint64_t x;
            memcpy(&x,m->data+i*sizeof(x),sizeof(x));
            return nv_uint(
                (unsigned long long)x
            );
        }

        case NV_MEM_FLOAT32:{
            float x;
            memcpy(&x,m->data+i*sizeof(x),sizeof(x));
            return nv_float((double)x);
        }

        case NV_MEM_FLOAT64:{
            double x;
            memcpy(&x,m->data+i*sizeof(x),sizeof(x));
            return nv_float(x);
        }
    }

    nv_throw("Unknown memory element type");
    return nv_none();
}

static void nv_memory_store_at(
    NvMemory *m,
    size_t i,
    NvVal value
){
    __int128 x;

    switch(m->type){

        case NV_MEM_BYTE:
            x=nv_memory_integer_value(
                value,
                "byte"
            );

            if(x<0||x>255)
                nv_throw(
                    "Memory byte must be between 0 and 255"
                );

            m->data[i]=(unsigned char)x;
            return;

        case NV_MEM_INT8:{
            x=nv_memory_integer_value(value,"int8");

            if(x<INT8_MIN||x>INT8_MAX)
                nv_memory_integer_range_error("int8");

            int8_t y=(int8_t)x;
            memcpy(m->data+i*sizeof(y),&y,sizeof(y));
            return;
        }

        case NV_MEM_UINT8:{
            x=nv_memory_integer_value(value,"uint8");

            if(x<0||x>UINT8_MAX)
                nv_memory_integer_range_error("uint8");

            uint8_t y=(uint8_t)x;
            memcpy(m->data+i*sizeof(y),&y,sizeof(y));
            return;
        }

        case NV_MEM_INT16:{
            x=nv_memory_integer_value(value,"int16");

            if(x<INT16_MIN||x>INT16_MAX)
                nv_memory_integer_range_error("int16");

            int16_t y=(int16_t)x;
            memcpy(m->data+i*sizeof(y),&y,sizeof(y));
            return;
        }

        case NV_MEM_UINT16:{
            x=nv_memory_integer_value(value,"uint16");

            if(x<0||x>UINT16_MAX)
                nv_memory_integer_range_error("uint16");

            uint16_t y=(uint16_t)x;
            memcpy(m->data+i*sizeof(y),&y,sizeof(y));
            return;
        }

        case NV_MEM_INT32:{
            x=nv_memory_integer_value(value,"int32");

            if(x<INT32_MIN||x>INT32_MAX)
                nv_memory_integer_range_error("int32");

            int32_t y=(int32_t)x;
            memcpy(m->data+i*sizeof(y),&y,sizeof(y));
            return;
        }

        case NV_MEM_UINT32:{
            x=nv_memory_integer_value(value,"uint32");

            if(
                x<0 ||
                x>(__int128)UINT32_MAX
            ){
                nv_memory_integer_range_error("uint32");
            }

            uint32_t y=(uint32_t)x;
            memcpy(m->data+i*sizeof(y),&y,sizeof(y));
            return;
        }

        case NV_MEM_INT64:{
            x=nv_memory_integer_value(value,"int64");

            if(
                x<(__int128)INT64_MIN ||
                x>(__int128)INT64_MAX
            ){
                nv_memory_integer_range_error("int64");
            }

            int64_t y=(int64_t)x;
            memcpy(m->data+i*sizeof(y),&y,sizeof(y));
            return;
        }

        case NV_MEM_UINT64:{
            x=nv_memory_integer_value(value,"uint64");

            if(
                x<0 ||
                (unsigned __int128)x >
                (unsigned __int128)UINT64_MAX
            ){
                nv_memory_integer_range_error("uint64");
            }

            uint64_t y=(uint64_t)x;
            memcpy(m->data+i*sizeof(y),&y,sizeof(y));
            return;
        }

        case NV_MEM_FLOAT32:{
            double z=nv_num(value);
            float y=(float)z;
            memcpy(m->data+i*sizeof(y),&y,sizeof(y));
            return;
        }

        case NV_MEM_FLOAT64:{
            double y=nv_num(value);
            memcpy(m->data+i*sizeof(y),&y,sizeof(y));
            return;
        }
    }

    nv_throw("Unknown memory element type");
}

static NvVal nv_memory_read(
    NvVal v,
    NvVal index
){
    NvMemory*m=nv_memory_get(v);

    size_t i=nv_memory_nonnegative_integer(
        index,
        "Memory index must be a non-negative integer"
    );

    if(i>=m->count)
        nv_throw("Memory index out of range");

    return nv_memory_load_at(m,i);
}

static NvVal nv_memory_write(
    NvVal v,
    NvVal index,
    NvVal value
){
    NvMemory*m=nv_memory_get(v);

    size_t i=nv_memory_nonnegative_integer(
        index,
        "Memory index must be a non-negative integer"
    );

    if(i>=m->count)
        nv_throw("Memory index out of range");

    nv_memory_store_at(
        m,
        i,
        value
    );

    return nv_none();
}

static void nv_memory_fill_native(
    NvMemory*m,
    NvVal value,
    size_t offset,
    size_t length
){
    if(
        offset>m->count ||
        length>m->count-offset
    ){
        nv_throw(
            "Memory fill range out of bounds"
        );
    }

    /*
     * Fast path pour les blocs d'un octet.
     */
    if(
        m->type==NV_MEM_BYTE ||
        m->type==NV_MEM_UINT8
    ){
        const char *type_name=
            m->type==NV_MEM_BYTE
            ? "byte"
            : "uint8";

        __int128 x=
            nv_memory_integer_value(
                value,
                type_name
            );

        if(x<0||x>255){
            if(m->type==NV_MEM_BYTE)
                nv_throw(
                    "Memory byte must be between 0 and 255"
                );

            nv_memory_integer_range_error("uint8");
        }

        memset(
            m->data+offset,
            (unsigned char)x,
            length
        );

        return;
    }

    for(
        size_t i=offset;
        i<offset+length;
        i++
    ){
        nv_memory_store_at(
            m,
            i,
            value
        );
    }
}

static NvVal nv_memory_fill_all(
    NvVal v,
    NvVal value
){
    NvMemory*m=nv_memory_get(v);

    nv_memory_fill_native(
        m,
        value,
        0,
        m->count
    );

    return nv_none();
}

static NvVal nv_memory_fill_range(
    NvVal v,
    NvVal value,
    NvVal offsetv,
    NvVal lengthv
){
    NvMemory*m=nv_memory_get(v);

    size_t offset=nv_memory_nonnegative_integer(
        offsetv,
        "Memory offset must not be negative"
    );

    size_t length=nv_memory_nonnegative_integer(
        lengthv,
        "Memory length must not be negative"
    );

    nv_memory_fill_native(
        m,
        value,
        offset,
        length
    );

    return nv_none();
}

static void nv_memory_require_same_type(
    NvMemory*dst,
    NvMemory*src
){
    if(dst->type!=src->type)
        nv_throw(
            "Memory copy requires matching element types"
        );
}

static NvVal nv_memory_copy_all(
    NvVal dstv,
    NvVal srcv
){
    NvMemory*dst=nv_memory_get(dstv);
    NvMemory*src=nv_memory_get(srcv);

    nv_memory_require_same_type(
        dst,
        src
    );

    if(src->count>dst->count)
        nv_throw(
            "Source memory block does not fit in destination"
        );

    memmove(
        dst->data,
        src->data,
        src->size
    );

    return nv_none();
}

static NvVal nv_memory_copy_range(
    NvVal dstv,
    NvVal srcv,
    NvVal srcoffv,
    NvVal dstoffv,
    NvVal lengthv
){
    NvMemory*dst=nv_memory_get(dstv);
    NvMemory*src=nv_memory_get(srcv);

    nv_memory_require_same_type(
        dst,
        src
    );

    size_t srcoff=nv_memory_nonnegative_integer(
        srcoffv,
        "Memory offset must not be negative"
    );

    size_t dstoff=nv_memory_nonnegative_integer(
        dstoffv,
        "Memory offset must not be negative"
    );

    size_t length=nv_memory_nonnegative_integer(
        lengthv,
        "Memory length must not be negative"
    );

    if(
        srcoff>src->count ||
        length>src->count-srcoff
    ){
        nv_throw(
            "Source memory range out of bounds"
        );
    }

    if(
        dstoff>dst->count ||
        length>dst->count-dstoff
    ){
        nv_throw(
            "Destination memory range out of bounds"
        );
    }

    size_t element_size=
        nv_memory_type_size(dst->type);

    memmove(
        dst->data+dstoff*element_size,
        src->data+srcoff*element_size,
        length*element_size
    );

    return nv_none();
}
static NvVal nv_add(NvVal a,NvVal b){
    if(a.kind==NV_STR&&b.kind==NV_STR){
        size_t n=
            strlen(a.as.s)+strlen(b.as.s)+1;

        char*p=nv_xmalloc(n);

        snprintf(
            p,
            n,
            "%s%s",
            a.as.s,
            b.as.s
        );

        NvVal v=nv_str(p);
        free(p);
        return v;
    }

    if(nv_is_integer(a)&&nv_is_integer(b)){
        return nv_integer_from_i128(
            nv_integer_i128(a)+
            nv_integer_i128(b)
        );
    }

    return nv_float(
        nv_num(a)+nv_num(b)
    );
}

static NvVal nv_sub(NvVal a,NvVal b){
    if(nv_is_integer(a)&&nv_is_integer(b)){
        return nv_integer_from_i128(
            nv_integer_i128(a)-
            nv_integer_i128(b)
        );
    }

    return nv_float(
        nv_num(a)-nv_num(b)
    );
}

static NvVal nv_mul(NvVal a,NvVal b){
    if(nv_is_integer(a)&&nv_is_integer(b)){
        __int128 x=nv_integer_i128(a);
        __int128 y=nv_integer_i128(b);

        if(x>=0 && y>=0){
            unsigned __int128 p=
                (unsigned __int128)x *
                (unsigned __int128)y;

            return nv_integer_from_u128(p);
        }

        return nv_integer_from_i128(
            x*y
        );
    }

    return nv_float(
        nv_num(a)*nv_num(b)
    );
}

static NvVal nv_div(NvVal a,NvVal b){
    double d=nv_num(b);

    if(d==0.0)
        nv_throw("Division by zero");

    return nv_float(
        nv_num(a)/d
    );
}

static NvVal nv_mod(NvVal a,NvVal b){
    if(nv_is_integer(a)&&nv_is_integer(b)){
        __int128 x=nv_integer_i128(a);
        __int128 y=nv_integer_i128(b);

        if(y==0)
            nv_throw("Modulo by zero");

        return nv_integer_from_i128(
            x%y
        );
    }

    long long x=(long long)nv_num(a);
    long long y=(long long)nv_num(b);

    if(!y)
        nv_throw("Modulo by zero");

    return nv_int(x%y);
}

static NvVal nv_pow(NvVal a,NvVal b){
    return nv_float(
        pow(nv_num(a),nv_num(b))
    );
}

static NvVal nv_neg(NvVal a){
    if(nv_is_integer(a)){
        return nv_integer_from_i128(
            -nv_integer_i128(a)
        );
    }

    return nv_float(
        -nv_num(a)
    );
}

static NvVal nv_not(NvVal a){
    return nv_bool(!nv_truth(a));
}

/* and/or sont volontairement des macros : */
/* cela garantit le court-circuit du second opérande. */
#define nv_and(left,right) nv_bool(nv_truth((left)) && nv_truth((right)))
#define nv_or(left,right) nv_bool(nv_truth((left)) || nv_truth((right)))

static int nv_same(NvVal a,NvVal b){
    if(a.kind!=b.kind){
        if(nv_is_numeric(a)&&nv_is_numeric(b)){
            if(nv_is_integer(a)&&nv_is_integer(b)){
                return
                    nv_integer_i128(a)==
                    nv_integer_i128(b);
            }

            return
                nv_num_long_double(a)==
                nv_num_long_double(b);
        }

        return 0;
    }

    switch(a.kind){
        case NV_NONE:return 1;
        case NV_INT:return a.as.i==b.as.i;
        case NV_UINT:return a.as.u==b.as.u;
        case NV_FLOAT:return a.as.f==b.as.f;
        case NV_BOOL:return a.as.b==b.as.b;
        case NV_STR:return strcmp(a.as.s,b.as.s)==0;
        case NV_FILE:return a.as.file==b.as.file;
        case NV_MEMORY:return a.as.memory==b.as.memory;
        default:return a.as.obj==b.as.obj;
    }
}

static NvVal nv_eq(NvVal a,NvVal b){
    return nv_bool(nv_same(a,b));
}

static NvVal nv_ne(NvVal a,NvVal b){
    return nv_bool(!nv_same(a,b));
}

static int nv_numeric_compare(
    NvVal a,
    NvVal b
){
    if(nv_is_integer(a)&&nv_is_integer(b)){
        __int128 x=nv_integer_i128(a);
        __int128 y=nv_integer_i128(b);

        return x<y?-1:x>y?1:0;
    }

    long double x=nv_num_long_double(a);
    long double y=nv_num_long_double(b);

    return x<y?-1:x>y?1:0;
}

static NvVal nv_lt(NvVal a,NvVal b){
    return nv_bool(
        nv_numeric_compare(a,b)<0
    );
}

static NvVal nv_le(NvVal a,NvVal b){
    return nv_bool(
        nv_numeric_compare(a,b)<=0
    );
}

static NvVal nv_gt(NvVal a,NvVal b){
    return nv_bool(
        nv_numeric_compare(a,b)>0
    );
}

static NvVal nv_ge(NvVal a,NvVal b){
    return nv_bool(
        nv_numeric_compare(a,b)>=0
    );
}

static void nv_print_one(NvVal v){
    switch(v.kind){

        case NV_NONE:
            printf("none");
            break;

        case NV_INT:
            printf("%lld",v.as.i);
            break;

        case NV_UINT:
            printf("%llu",v.as.u);
            break;

        case NV_FLOAT:
            printf("%g",v.as.f);
            break;

        case NV_BOOL:
            printf(
                "%s",
                v.as.b?"true":"false"
            );
            break;

        case NV_STR:
            printf("%s",v.as.s);
            break;

        case NV_LIST:
            printf("[");
            for(int i=0;i<v.as.list->len;i++){
                if(i)printf(", ");
                nv_print_one(
                    v.as.list->items[i]
                );
            }
            printf("]");
            break;

        case NV_DICT:
            printf("{");
            for(int i=0;i<v.as.dict->len;i++){
                if(i)printf(", ");
                printf(
                    "\"%s\": ",
                    v.as.dict->keys[i]
                );
                nv_print_one(
                    v.as.dict->vals[i]
                );
            }
            printf("}");
            break;

        case NV_OBJ:
            printf(
                "<%s>",
                v.as.obj->type
            );
            break;

        case NV_MEMORY:
            if(
                !v.as.memory ||
                v.as.memory->freed
            ){
                printf("<memory freed>");
            }else{
                printf(
                    "<memory %zu bytes>",
                    v.as.memory->size
                );
            }
            break;

        case NV_FILE:
            printf("<file>");
            break;
    }
}

static void nv_list_append(NvVal l,NvVal v){ if(l.kind!=NV_LIST)nv_throw("append() requires a list"); NvList*p=l.as.list; if(p->len==p->cap){p->cap=p->cap?p->cap*2:8;p->items=realloc(p->items,sizeof(NvVal)*p->cap);} p->items[p->len++]=v;}
static NvVal nv_range(NvVal a,NvVal b){ long long x=(long long)nv_num(a), y=(long long)nv_num(b); NvVal l=nv_list_new(); if(x<=y){for(long long i=x;i<y;i++)nv_list_append(l,nv_int(i));}else{for(long long i=x;i>y;i--)nv_list_append(l,nv_int(i));} return l;}
static void nv_file_close(NvVal v){ if(v.kind==NV_FILE && v.as.file) fclose(v.as.file); }
static NvVal nv_file_read(NvVal v){ if(v.kind!=NV_FILE||!v.as.file)nv_throw("File is not open"); if(fseek(v.as.file,0,SEEK_END)!=0)nv_throw("Unable to read file"); long n=ftell(v.as.file); if(n<0)nv_throw("Unable to read file"); rewind(v.as.file); char *buf=nv_xmalloc((size_t)n+1); size_t got=fread(buf,1,(size_t)n,v.as.file); buf[got]='\0'; NvVal r=nv_str(buf); free(buf); return r;}
static NvVal nv_file_write(NvVal v,NvVal data){ if(v.kind!=NV_FILE||!v.as.file)nv_throw("File is not open"); NvVal t=nv_to_str(data); fputs(t.as.s,v.as.file); fflush(v.as.file); return nv_none();}
static void nv_list_extend(NvVal l,NvVal other){ if(l.kind!=NV_LIST||other.kind!=NV_LIST)nv_throw("Unpacking * requires a list"); for(int i=0;i<other.as.list->len;i++)nv_list_append(l,other.as.list->items[i]);}
static int nv_dict_find(NvDict*d,const char*k){for(int i=0;i<d->len;i++)if(strcmp(d->keys[i],k)==0)return i;return-1;}
static NvVal nv_contains(NvVal container,NvVal item){ if(container.kind==NV_LIST){for(int i=0;i<container.as.list->len;i++)if(nv_same(container.as.list->items[i],item))return nv_bool(1);return nv_bool(0);} if(container.kind==NV_DICT){if(item.kind!=NV_STR)return nv_bool(0);return nv_bool(nv_dict_find(container.as.dict,item.as.s)>=0);} if(container.kind==NV_STR){if(item.kind!=NV_STR)return nv_bool(0);return nv_bool(strstr(container.as.s,item.as.s)!=NULL);} nv_throw("'in' requires a list, dict, or string");return nv_bool(0);}
static void nv_dict_set(NvDict*d,const char*k,NvVal v){int i=nv_dict_find(d,k);if(i>=0){d->vals[i]=v;return;}if(d->len==d->cap){d->cap=d->cap?d->cap*2:8;d->keys=realloc(d->keys,sizeof(char*)*d->cap);d->vals=realloc(d->vals,sizeof(NvVal)*d->cap);}d->keys[d->len]=nv_strdup(k);d->vals[d->len]=v;d->len++;}
static void nv_dict_set_value(NvVal d,const char*k,NvVal v){if(d.kind!=NV_DICT)nv_throw("Expected a dict");nv_dict_set(d.as.dict,k,v);}
static void nv_dict_merge_value(NvVal d,NvVal src){if(d.kind!=NV_DICT||src.kind!=NV_DICT)nv_throw("Unpacking ** requires a dict");for(int i=0;i<src.as.dict->len;i++)nv_dict_set(d.as.dict,src.as.dict->keys[i],src.as.dict->vals[i]);}
static NvVal nv_dict_get(NvDict*d,const char*k){int i=nv_dict_find(d,k);if(i<0){char buf[512];snprintf(buf,sizeof(buf),"Key not found: %s",k);nv_throw(buf);}return d->vals[i];}
static NvVal nv_get_index(NvVal a,NvVal i){ if(a.kind==NV_LIST){long long n=(long long)nv_num(i);if(n<0)n=a.as.list->len+n;if(n<0||n>=a.as.list->len)nv_throw("List index out of range");return a.as.list->items[n];} if(a.kind==NV_DICT){if(i.kind!=NV_STR)nv_throw("Expected a string key");return nv_dict_get(a.as.dict,i.as.s);} if(a.kind==NV_STR){long long n=(long long)nv_num(i);int len=(int)strlen(a.as.s);if(n<0)n=len+n;if(n<0||n>=len)nv_throw("String index out of range");char tmp[2]={a.as.s[n],0};return nv_str(tmp);} nv_throw("This value is not indexable");return nv_none();}
static void nv_set_index(NvVal a,NvVal i,NvVal v){ if(a.kind==NV_LIST){long long n=(long long)nv_num(i);if(n<0)n=a.as.list->len+n;if(n<0||n>=a.as.list->len)nv_throw("List index out of range");a.as.list->items[n]=v;return;} if(a.kind==NV_DICT){if(i.kind!=NV_STR)nv_throw("Expected a string key");nv_dict_set(a.as.dict,i.as.s,v);return;} nv_throw("This value does not support indexed assignment");}
static NvVal nv_get_field(NvVal a,const char*name){if(a.kind!=NV_OBJ)nv_throw("Accès à un champ sur une valeur qui n'est pas un objet");return nv_dict_get(a.as.obj->fields,name);}
static void nv_set_field(NvVal a,const char*name,NvVal v){if(a.kind!=NV_OBJ)nv_throw("Affectation de champ sur une valeur qui n'est pas un objet");nv_dict_set(a.as.obj->fields,name,v);}
static NvVal nv_object_new(const char*type){NvVal v=nv_none();v.kind=NV_OBJ;v.as.obj=nv_xmalloc(sizeof(NvObj));v.as.obj->type=nv_strdup(type);v.as.obj->fields=nv_dict_new();return v;}
static int nv_len(NvVal v){if(v.kind==NV_LIST)return v.as.list->len;if(v.kind==NV_DICT)return v.as.dict->len;if(v.kind==NV_STR)return(int)strlen(v.as.s);nv_throw("len() requires a list, dict, or string");return 0;}
static NvVal nv_iter_get(NvVal v,int i){if(v.kind==NV_LIST)return v.as.list->items[i];if(v.kind==NV_DICT)return nv_str(v.as.dict->keys[i]);if(v.kind==NV_STR){char t[2]={v.as.s[i],0};return nv_str(t);}nv_throw("This value is not iterable");return nv_none();}
static NvCall nv_call_new(void){NvCall c;c.args=NULL;c.argc=0;c.cap=0;c.kw=nv_dict_new();return c;}
static void nv_call_add(NvCall*c,NvVal v){if(c->argc==c->cap){c->cap=c->cap?c->cap*2:8;c->args=realloc(c->args,sizeof(NvVal)*c->cap);}c->args[c->argc++]=v;}
static void nv_call_spread(NvCall*c,NvVal v){if(v.kind!=NV_LIST)nv_throw("Unpacking * requires a list");for(int i=0;i<v.as.list->len;i++)nv_call_add(c,v.as.list->items[i]);}
static void nv_call_kw(NvCall*c,const char*k,NvVal v){nv_dict_set(c->kw,k,v);}
static void nv_call_kwspread(NvCall*c,NvVal v){if(v.kind!=NV_DICT)nv_throw("Unpacking ** requires a dict");for(int i=0;i<v.as.dict->len;i++)nv_dict_set(c->kw,v.as.dict->keys[i],v.as.dict->vals[i]);}
static void nv_dict_free_shallow(NvDict*d){if(!d)return;for(int i=0;i<d->len;i++)free(d->keys[i]);free(d->keys);free(d->vals);free(d);}
static void nv_call_free(NvCall*c){if(!c)return;free(c->args);nv_dict_free_shallow(c->kw);c->args=NULL;c->kw=NULL;c->argc=0;c->cap=0;}
static NvVal nv_arg(NvVal*args,int argc,NvDict*kw,int pos,const char*name){if(pos<argc)return args[pos];int i=nv_dict_find(kw,name);if(i>=0)return kw->vals[i];char buf[512];snprintf(buf,sizeof(buf),"Missing argument: %s",name);nv_throw(buf);return nv_none();}
static void nv_expect_type(NvVal v,const char*t,const char*name){int ok=0;if(strcmp(t,"int")==0)ok=v.kind==NV_INT||v.kind==NV_UINT;else if(strcmp(t,"float")==0)ok=v.kind==NV_FLOAT||v.kind==NV_INT||v.kind==NV_UINT;else if(strcmp(t,"str")==0)ok=v.kind==NV_STR;else if(strcmp(t,"bool")==0)ok=v.kind==NV_BOOL;else if(strcmp(t,"list")==0)ok=v.kind==NV_LIST;else if(strcmp(t,"dict")==0)ok=v.kind==NV_DICT;else if(strcmp(t,"object")==0)ok=v.kind==NV_OBJ;else if(strcmp(t,"file")==0)ok=v.kind==NV_FILE;else if(strcmp(t,"memory")==0)ok=v.kind==NV_MEMORY;else ok=1;if(!ok){char buf[512];snprintf(buf,sizeof(buf),"Invalid type for %s: expected %s",name,t);nv_throw(buf);}}
static NvVal nv_dispatch_call(const char*,NvVal*,int,NvDict*);
static NvVal nv_dispatch_method(NvVal,const char*,NvVal*,int,NvDict*);

#endif
