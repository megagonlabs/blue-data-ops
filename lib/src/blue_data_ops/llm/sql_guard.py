from __future__ import annotations


def is_read_query(query: object) -> bool:
    """Admit one SELECT, rejecting syntax with ambiguous dialect interpretations."""
    if type(query) is not str or any(char in query for char in ("\0", "\v", "\f")):
        return False
    size = len(query)
    i = 0
    first = True
    ended = False
    while i < size:
        char = query[i]
        if char in " \t\r\n":
            i += 1
            continue
        if query.startswith("--", i):
            if first or (i + 2 < size and query[i + 2] not in " \t\r\n"):
                return False
            i += 2
            while i < size and query[i] not in "\r\n":
                i += 1
            # Dialects disagree on whether a bare CR ends a line comment.
            if i < size and query[i] == "\r" and (i + 1 == size or query[i + 1] != "\n"):
                return False
            continue
        if query.startswith("/*", i):
            if first:
                return False
            i += 2
            # MySQL and MariaDB execute these comment bodies as SQL.
            if query.startswith("!", i) or query[i : i + 2].upper() == "M!":
                return False
            while i < size and not query.startswith("*/", i):
                if query.startswith("/*", i):
                    return False
                i += 1
            if i == size:
                return False
            i += 2
            continue
        # Comment, quoting and escape rules for these forms differ by dialect.
        if ended or char in "#$\\[]" or ord(char) < 32:
            return False
        if char == ";":
            if first:
                return False
            ended = True
            i += 1
            continue
        if char in "'\"`":
            if first:
                return False
            quote = char
            i += 1
            while i < size:
                if query[i] == "\\":
                    return False
                if query[i] == quote:
                    i += 1
                    if i < size and query[i] == quote:
                        i += 1
                        continue
                    break
                i += 1
            else:
                return False
            continue
        if char.isalnum() or char == "_":
            start = i
            while i < size and (query[i].isalnum() or query[i] == "_"):
                i += 1
            token = query[start:i].upper()
            if first:
                if not query[start:i].isascii() or token != "SELECT":
                    return False
                first = False
            # MySQL ends floating literals before keywords; 1.e0 leaves E0 here.
            elif token == "INTO" or (
                "INTO" in token
                and (
                    token[0].isdigit()
                    or (token.startswith("E") and len(token) > 1 and token[1].isdigit())
                )
            ):
                return False
            continue
        if first:
            return False
        i += 1
    return not first
