#!/usr/bin/env python3

import re
import sys


FOR_RANGE_RE = re.compile(
    r'^(\s*)for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+range\((.*)\)\s*:\s*$'
)


def indentation(line):
    return len(line) - len(line.lstrip(" "))


def split_args(text):
    args = []
    current = []
    depth = 0
    quote = None
    escape = False

    for ch in text:
        if escape:
            current.append(ch)
            escape = False
            continue

        if ch == "\\":
            current.append(ch)
            escape = True
            continue

        if quote:
            current.append(ch)
            if ch == quote:
                quote = None
            continue

        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            continue

        if ch in "([{":
            depth += 1
            current.append(ch)
            continue

        if ch in ")]}":
            depth -= 1
            current.append(ch)
            continue

        if ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            continue

        current.append(ch)

    if current:
        args.append("".join(current).strip())

    return args


def step_direction(step):
    s = step.strip()

    if re.fullmatch(r'\+?\d+', s):
        n = int(s)
        if n > 0:
            return 1
        if n < 0:
            return -1
        return 0

    if re.fullmatch(r'-\d+', s):
        return -1

    return None


counter = 0


def transform(lines):
    global counter

    output = []
    i = 0

    while i < len(lines):
        line = lines[i]
        match = FOR_RANGE_RE.match(line.rstrip("\n"))

        if not match:
            output.append(line)
            i += 1
            continue

        spaces, variable, args_text = match.groups()
        base_indent = len(spaces)

        j = i + 1

        while j < len(lines):
            candidate = lines[j]

            if candidate.strip() == "":
                j += 1
                continue

            if indentation(candidate) <= base_indent:
                break

            j += 1

        body = lines[i + 1:j]
        args = split_args(args_text)

        # Reste sur l'ancien système si la forme n'est pas sûre.
        if len(args) not in (1, 2, 3):
            output.append(line)
            output.extend(transform(body))
            i = j
            continue

        # Pour l'instant on ne réécrit pas une boucle contenant continue.
        if any(
            re.match(r'^\s*(continue|continue)\b', x)
            for x in body
        ):
            output.append(line)
            output.extend(transform(body))
            i = j
            continue

        if len(args) == 1:
            start = "0"
            stop = args[0]
            step = "1"
            direction = 1

        elif len(args) == 2:
            start = args[0]
            stop = args[1]
            step = "1"
            direction = 1

        else:
            start, stop, step = args
            direction = step_direction(step)

            # Pas dynamique ou nul : garde range() classique.
            if direction is None or direction == 0:
                output.append(line)
                output.extend(transform(body))
                i = j
                continue

        counter += 1
        n = counter

        index_name = f"clariox_range_index_{n}"
        stop_name = f"clariox_range_fin_{n}"
        step_name = f"clariox_range_pas_{n}"

        body_indent = spaces + "    "

        output.append(f"{spaces}{index_name} = {start}\n")
        output.append(f"{spaces}{stop_name} = {stop}\n")
        output.append(f"{spaces}{step_name} = {step}\n")

        if direction > 0:
            condition = f"{index_name} < {stop_name}"
        else:
            condition = f"{index_name} > {stop_name}"

        output.append(f"{spaces}while {condition}:\n")
        output.append(f"{body_indent}{variable} = {index_name}\n")

        transformed_body = transform(body)
        output.extend(transformed_body)

        output.append(
            f"{body_indent}{index_name} = "
            f"{index_name} + {step_name}\n"
        )

        i = j

    return output


def main():
    if len(sys.argv) != 3:
        print("Usage : optimise_plage.py entree.clx sortie.clx")
        sys.exit(2)

    source, destination = sys.argv[1], sys.argv[2]

    with open(source, "r", encoding="utf-8") as f:
        lines = f.readlines()

    result = transform(lines)

    with open(destination, "w", encoding="utf-8") as f:
        f.writelines(result)


if __name__ == "__main__":
    main()
