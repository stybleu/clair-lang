nombres = [10, 20, 30, 40, 50]

somme = 0

for i in range(100000000):
    somme = somme + nombres[i % 5]

print(somme)
