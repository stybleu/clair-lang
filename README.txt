# CLARIOX

Clariox is a compiled programming language designed around a simple,
readable syntax while targeting native performance.

Source files use the .clx extension.

Compilation pipeline
--------------------

    program.clx
        -> Clariox compiler
        -> generated C
        -> Clang -O3
        -> native executable

The runtime is separated into:

    clariox_runtime.h

The compiler itself is:

    clarioxc.c

The main command-line launcher is:

    ./clariox


Termux installation
-------------------

From the extracted project directory:

    bash installer_termux.sh

The project is normally installed in:

    ~/clariox


Basic compilation
-----------------

Compile a Clariox program:

    ./clariox program.clx

Then run the generated executable:

    ./program

Example:

    ./clariox demo.clx
    ./demo


Variables
---------

Variables do not require explicit type declarations:

    name = "Alice"
    age = 25
    temperature = 18.5

Optional type annotations are supported:

    age: int = 25
    temperature: float = 18.5
    name: str = "Alice"


Constants
---------

Use const:

    const PI = 3.14159

A const value cannot be reassigned.


Built-in values
---------------

    true
    false
    none


Output
------

    print("Hello")
    print("Age:", 25)


String interpolation
--------------------

    name = "Alice"
    age = 25

    print("Hello {name}, you are {age} years old")


Conditions
----------

    if age >= 18:
        print("Adult")
    elif age == 17:
        print("Almost adult")
    else:
        print("Minor")


Logical operators
-----------------

    and
    or
    not

Example:

    if active and not blocked:
        print("Access granted")

    if admin or owner:
        print("Authorized")


Loops
-----

For loop:

    for i in range(10):
        print(i)

Range with start and end:

    for i in range(5, 10):
        print(i)

Range with step:

    for i in range(0, 20, 2):
        print(i)

While loop:

    counter = 5

    while counter > 0:
        print(counter)
        counter -= 1


Loop control
------------

    break
    continue


Membership
----------

    numbers = [10, 20, 30]

    if 20 in numbers:
        print("Found")


Functions
---------

Functions use fn:

    fn add(a: int, b: int) -> int:
        return a + b

    result = add(10, 20)
    print(result)


Lists
-----

    numbers = [10, 20, 30]

    numbers.append(40)
    numbers.remove(20)

    print(numbers)
    print(numbers[0])
    print(len(numbers))


Dictionaries
------------

    person = {
        "name": "Alice",
        "age": 25
    }

    print(person["name"])
    print(person.keys())


Argument unpacking
------------------

List unpacking:

    result = add(*[10, 20])

Dictionary unpacking is also supported with:

    **value


Structures
----------

Structures contain fields but no methods:

    struct Position:
        x: float
        y: float

    position = Position(1.5, 2.5)


Objects
-------

Objects can contain fields and methods:

    object Player:
        fn init(self, name: str, points: int):
            self.name = name
            self.points = points

        fn add_points(self, points: int):
            self.points += points

    player = Player("Alice", 100)


Match / case
------------

    color = "green"

    match color:
        case "red":
            print("Stop")
        case "green":
            print("Go")
        else:
            print("Unknown")


Input
-----

Text input:

    name = input("Name: ")

Integer input:

    age = input_int("Age: ")

Floating-point input:

    height = input_float("Height: ")


Conversions
-----------

    int("25")
    float("18.5")
    str(25)


Files
-----

Write a complete file:

    write_file("note.txt", "Hello")

Read a complete file:

    content = read_file("note.txt")
    print(content)


File objects
------------

Open a file:

    file = open("note.txt", "read")

Available modes:

    "read"
    "write"
    "append"

File methods:

    file.read()
    file.write("Hello")
    file.close()


Automatic file closing
----------------------

Use with:

    with file = open("note.txt", "write"):
        file.write("Hello from Clariox")


Error handling
--------------

    try:
        error("Example error")
    catch problem:
        print("Caught:", problem)
    finally:
        print("Finished")


Supported type annotations
--------------------------

    int
    float
    str
    bool
    list
    dict
    object
    file

Type annotations are optional.


Native optimization
-------------------

Clariox generates C and uses Clang with optimization enabled.

The optimization pipeline currently includes specialization for:

    numeric values
    numeric functions
    homogeneous numeric lists
    strings
    string literals
    range loops

When possible, dynamic NvVal values are replaced by native C values such as:

    long long
    double

This reduces dynamic runtime overhead in optimized sections.


Development tests
-----------------

Language tests are located in:

    tests_language/

String regression tests:

    tests_chain/

Structure regression tests:

    tests_structures/

Current validated language features include:

    English control-flow syntax
    English built-in API
    English type annotations
    list.append()
    list.remove()
    dict.keys()
    file.read()
    file.write()
    file.close()
    match / case
    try / catch / finally
    with
    const
    and / or / not


Project
-------

Language: Clariox
Source extension: .clx
Compiler: clarioxc
Backend: Clang
Generated language: C
