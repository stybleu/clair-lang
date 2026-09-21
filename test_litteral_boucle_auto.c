#include "clair_runtime.h"

static NvVal clair_literal_1;

#include <string.h>

typedef struct {
    const char *data;
    long long len;
} ClairString;


static ClairString clair_string_literal(const char *s)
{
    ClairString r;
    r.data = s;
    r.len = (long long)strlen(s);
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

    char *buffer = nv_xmalloc((size_t)total + 1);

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

    return r;
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


static NvVal nv_builtin_print(NvVal *args,int argc){for(int i=0;i<argc;i++){if(i)printf(" ");nv_print_one(args[i]);}printf("\n");return nv_none();}
static NvVal nv_dispatch_call(const char *name,NvVal *args,int argc,NvDict *kw){
    if(strcmp(name,"ecris")==0) return nv_builtin_print(args,argc);
    if(strcmp(name,"demande")==0){ if(argc>0){nv_print_one(args[0]);fflush(stdout);} char b[4096]; if(!fgets(b,sizeof(b),stdin))return clair_literal_1; b[strcspn(b,"\r\n")]=0; return nv_str(b); }
    if(strcmp(name,"demande_entier")==0){ if(argc>0){nv_print_one(args[0]);fflush(stdout);} char b[256]; if(!fgets(b,sizeof(b),stdin))return nv_int(0); char *e=NULL; long long v=strtoll(b,&e,10); if(e==b)nv_throw("Un entier était attendu"); return nv_int(v); }
    if(strcmp(name,"demande_decimal")==0){ if(argc>0){nv_print_one(args[0]);fflush(stdout);} char b[256]; if(!fgets(b,sizeof(b),stdin))return nv_float(0); char *e=NULL; double v=strtod(b,&e); if(e==b)nv_throw("Un nombre décimal était attendu"); return nv_float(v); }
    if(strcmp(name,"entier")==0){ if(argc<1)nv_throw("entier() attend une valeur"); if(args[0].kind==NV_INT)return args[0]; if(args[0].kind==NV_STR)return nv_int(strtoll(args[0].as.s,NULL,10)); return nv_int((long long)nv_num(args[0])); }
    if(strcmp(name,"decimal")==0){ if(argc<1)nv_throw("decimal() attend une valeur"); if(args[0].kind==NV_STR)return nv_float(strtod(args[0].as.s,NULL)); return nv_float(nv_num(args[0])); }
    if(strcmp(name,"texte")==0){ if(argc<1)nv_throw("texte() attend une valeur"); return nv_to_str(args[0]); }
    if(strcmp(name,"ouvre")==0){ if(argc<1||args[0].kind!=NV_STR)nv_throw("ouvre() attend un chemin texte"); const char*m="r"; if(argc>1&&args[1].kind==NV_STR){ if(strcmp(args[1].as.s,"lecture")==0)m="r"; else if(strcmp(args[1].as.s,"ecriture")==0)m="w"; else if(strcmp(args[1].as.s,"ajout")==0)m="a"; else m=args[1].as.s;} FILE*f=fopen(args[0].as.s,m); if(!f)nv_throwf("Impossible d'ouvrir le fichier : %s",args[0].as.s); return nv_file_value(f); }
    if(strcmp(name,"lis_fichier")==0){ if(argc<1||args[0].kind!=NV_STR)nv_throw("lis_fichier() attend un chemin texte"); FILE*f=fopen(args[0].as.s,"r"); if(!f)nv_throwf("Impossible d'ouvrir le fichier : %s",args[0].as.s); NvVal fv=nv_file_value(f); NvVal r=nv_file_read(fv); fclose(f); return r; }
    if(strcmp(name,"ecris_fichier")==0){ if(argc<2||args[0].kind!=NV_STR)nv_throw("ecris_fichier() attend un chemin et une valeur"); FILE*f=fopen(args[0].as.s,"w"); if(!f)nv_throwf("Impossible d'ouvrir le fichier : %s",args[0].as.s); NvVal fv=nv_file_value(f); nv_file_write(fv,args[1]); fclose(f); return nv_none(); }
    if(strcmp(name,"longueur")==0){ if(argc<1)nv_throw("longueur() attend une valeur"); return nv_int(nv_len(args[0])); }
    if(strcmp(name,"plage")==0){ long long a=0,b=0,p=1; if(argc==1){b=(long long)nv_num(args[0]);} else if(argc>=2){a=(long long)nv_num(args[0]);b=(long long)nv_num(args[1]);if(argc>=3)p=(long long)nv_num(args[2]);} else nv_throw("plage() attend 1 à 3 arguments"); if(p==0)nv_throw("Le pas de plage ne peut pas être zéro"); NvVal l=nv_list_new(); if(p>0){for(long long i=a;i<b;i+=p)nv_list_append(l,nv_int(i));}else{for(long long i=a;i>b;i+=p)nv_list_append(l,nv_int(i));} return l;}
    if(strcmp(name,"erreur")==0){ if(argc<1||args[0].kind!=NV_STR)nv_throw("erreur() attend un texte"); nv_throw(args[0].as.s); }
    nv_throwf("Fonction inconnue : %s",name); return nv_none();
}
static NvVal nv_dispatch_method(NvVal self,const char *name,NvVal *args,int argc,NvDict *kw){
    if(self.kind==NV_LIST && strcmp(name,"ajoute")==0){ if(argc<1)nv_throw("ajoute() attend une valeur"); nv_list_append(self,args[0]); return nv_none(); }
    if(self.kind==NV_LIST && strcmp(name,"retire")==0){ if(argc<1)nv_throw("retire() attend une valeur"); for(int i=0;i<self.as.list->len;i++){if(nv_same(self.as.list->items[i],args[0])){for(int j=i;j<self.as.list->len-1;j++)self.as.list->items[j]=self.as.list->items[j+1];self.as.list->len--;return nv_none();}} return nv_none(); }
    if(self.kind==NV_DICT && strcmp(name,"cles")==0){ NvVal l=nv_list_new(); for(int i=0;i<self.as.dict->len;i++)nv_list_append(l,nv_str(self.as.dict->keys[i])); return l; }
    if(self.kind==NV_FILE && strcmp(name,"lis")==0) return nv_file_read(self);
    if(self.kind==NV_FILE && strcmp(name,"ecris")==0){ if(argc<1)nv_throw("fichier.ecris() attend une valeur"); return nv_file_write(self,args[0]); }
    if(self.kind==NV_FILE && strcmp(name,"ferme")==0){ nv_file_close(self); return nv_none(); }
    if(self.kind==NV_OBJ){
    }
    nv_throwf("Méthode inconnue : %s",name); return nv_none();
}

int main(void){
    clair_literal_1 = nv_str("");
ClairString nom = clair_string_literal("Alice");
long long compteur = 0LL;
long long clair_range_index_1 = 0LL;
long long clair_range_fin_1 = 100000000LL;
long long clair_range_pas_1 = 1LL;
while (((clair_range_index_1 < clair_range_fin_1))) {
    long long i = clair_range_index_1;
    if (nv_truth(nv_bool(clair_string_eq(nom, clair_string_literal("Alice"))))) {
        compteur = (compteur + 1LL);
    }
    clair_range_index_1 = (clair_range_index_1 + clair_range_pas_1);
}
(void)({ NvCall __c = nv_call_new(); nv_call_add(&__c, nv_int(compteur)); NvVal __r = nv_dispatch_call("ecris", __c.args, __c.argc, __c.kw); nv_call_free(&__c); __r; });
    return 0;
}
