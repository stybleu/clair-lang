x = 1

for i in range(10000000):
    x = (x * 3 + i) % 1000000007

print(x)
