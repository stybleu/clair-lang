# Clariox

**Clariox** is an experimental compiled programming language focused on readable syntax, native execution, and safe compiler optimizations.

> Status: active development — not production-ready yet.

## Compilation pipeline

```text
Clariox source (.clx)
        ↓
Generated C
        ↓
Clang -O3
        ↓
Native executable
```

Clariox currently uses the following architecture:

```text
Clariox → C → Clang → machine code
```

## Current features

- integers and floating-point numbers
- strings, lists and dictionaries
- functions
- if / elif / else
- while loops
- optimized range() loops
- objects and structures
- file operations
- manual memory blocks
- flow-sensitive numeric specialization
- native integer and float optimization
- native if / elif / while numeric conditions
- short-circuit and / or semantics
- loop-local float unboxing
- native executable generation with Clang

## Example

```clariox
a = 0.0
b = 10.0

while a < 5.0 and b > 5.0:
    a = a + 1.0
    b = b - 1.0

print(a + b)
```

Compile:

```bash
./clariox program.clx
```

Run:

```bash
./program
```

## Optimization philosophy

> Optimize proven cases. Preserve dynamic semantics otherwise.

Clariox keeps values dynamic when their type cannot be proven safely, while proven numeric values can be lowered to native C types such as `long long` and `double`.

## Platform

Development currently happens primarily on Android / Termux.

The C + Clang backend is intended to make Clariox portable to Linux, Windows, macOS and Android.

## Project status

Clariox is experimental and under active development.

## Author

Developed by **Stybleu**.
