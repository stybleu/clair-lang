CLARIOX v5 — prototype de langage francophone compilé vers C
============================================================

Objectif
--------
Clariox vise une syntaxe facile à lire pour un francophone, tout en produisant
un programme C compilé nativement avec Clang.

Chaîne actuelle :

    programme.clx
        -> clarioxc
        -> programme.c
        -> Clang -O3
        -> exécutable natif

Le runtime est désormais séparé dans clariox_runtime.h afin que le fichier C
généré reste beaucoup plus lisible.

Installation Termux
-------------------
Depuis le dossier où l'archive a été extraite :

    bash installer_termux.sh

L'installateur copie Clariox dans ~/clariox pour éviter le problème noexec du
dossier Android Download.

Compilation manuelle
--------------------

    cd ~/clariox
    clang clarioxc.c -std=gnu11 -O2 -Wall -Wextra -o clarioxc
    ./clarioxc demo.clx demo
    ./demo

Voir le C généré :

    cat demo.c

Voir le runtime séparé :

    less clariox_runtime.h

Syntaxe prise en charge
-----------------------

Variables :

    nom = "Alice"
    age = 25
    temperature: decimal = 18.5

Valeurs fixes :

    fixe PI = 3.14159

Une valeur fixe ne peut plus être réaffectée.

Texte interpolé :

    ecris("Bonjour {nom}, tu as {age} ans")

Conditions :

    si age >= 18 et actif:
        ecris("Autorisé")
    sinonsi age == 17 ou invitation:
        ecris("À vérifier")
    sinon:
        ecris("Refusé")

Opérateurs logiques :

    et
    ou
    non

Boucles :

    pour i dans 0..10:
        ecris(i)

    tantque compteur > 0:
        compteur -= 1

Contrôle des boucles :

    arrete
    suivant

Appartenance :

    si 20 dans nombres:
        ecris("Trouvé")

Fonctions :

    fn addition(a: entier, b: entier) -> entier:
        retourne a + b

Listes :

    nombres = [10, 20, 30]
    nombres.ajoute(40)
    nombres.retire(20)
    ecris(nombres[0])

Tables :

    personne = {
        "nom": "Alice",
        "age": 25
    }

    ecris(personne["nom"])
    ecris(personne.cles())

Déballage :

    resultat = addition(*[10, 20])
    presente(**personne)

Structure :

    structure Position:
        x: decimal
        y: decimal

    pos = Position(1.5, 2.5)

Objet :

    objet Joueur:
        fn init(self, nom: texte, points: entier):
            self.nom = nom
            self.points = points

        fn gagne(self, points: entier):
            self.points += points

Selon / cas :

    selon couleur:
        cas "rouge":
            ecris("Stop")
        cas "vert":
            ecris("Passe")
        sinon:
            ecris("Inconnu")

Entrée clavier :

    nom = demande("Ton nom ? ")
    age = demande_entier("Ton âge ? ")
    taille = demande_decimal("Ta taille ? ")

Conversions :

    entier("25")
    decimal("18.5")
    texte(25)

Fichiers :

    ecris_fichier("note.txt", "Bonjour")
    contenu = lis_fichier("note.txt")

Ou avec fermeture automatique :

    avec fichier = ouvre("note.txt", "ecriture"):
        fichier.ecris("Bonjour")

Modes disponibles pour ouvre() :

    "lecture"
    "ecriture"
    "ajout"

Gestion des erreurs :

    tente:
        erreur("Problème")
    capture probleme:
        ecris("Erreur : {probleme}")
    toujours:
        ecris("Fin")

Types actuellement reconnus
----------------------------

    entier
    decimal
    texte
    booleen
    liste
    table
    objet
    fichier

Le typage reste facultatif dans le code Clariox.

Important sur les performances
------------------------------
Cette v5 compile bien en C natif avec Clang -O3, mais les valeurs utilisent
encore un runtime dynamique NvVal pour rendre listes, tables et objets simples
à implémenter. Elle n'a donc pas encore les performances maximales visées.

La prochaine étape d'optimisation consistera à spécialiser automatiquement les
variables connues :

    age = 25

pour produire directement quelque chose de proche de :

    long long age = 25;

sans NvVal lorsque le type est déterminé à la compilation.
