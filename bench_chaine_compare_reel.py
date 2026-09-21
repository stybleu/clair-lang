gauche1 = "Al"
droite1 = "ice"
nom = gauche1 + droite1

gauche2 = "A"
droite2 = "lice"
cible = gauche2 + droite2

compteur = 0

for i in range(50000000):
    if nom == cible:
        compteur += 1

print(compteur)
