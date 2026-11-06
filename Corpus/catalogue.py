# Reading Ben's book catalogues: his .rtf lists, one book a block, as WordPad saves them.
#
#     Angier, Natalie - Canon
#     "The Canon: A Whirligig Tour of the Beautiful Basics of Science," by Natalie Angier, published by Houghton Mifflin Company, 2007.
#     ISBN:  978-0-618-24295-5
#     Cover:  Hardcover
#     ...
#
# Standard library only.

import re

FIELDS = ("ISBN", "Cover", "Condition", "Pages", "Weight")


def rtf_text(rtf):
    # Just enough RTF for WordPad's lists: paragraphs, escaped characters and code-page bytes; formatting is dropped
    out, depth, skip_at = [], 0, None
    i = 0
    while i < len(rtf):
        c = rtf[i]
        if c == "{":
            depth += 1
            if rtf.startswith("{\\*", i) or rtf.startswith("{\\fonttbl", i) or rtf.startswith("{\\colortbl", i):
                skip_at = skip_at or depth  # a destination nobody reads: font tables, generator notes
            i += 1
        elif c == "}":
            if skip_at == depth:
                skip_at = None
            depth -= 1
            i += 1
        elif c == "\\":
            word = re.match(r"\\([a-z]+)(-?\d+)? ?|\\'([0-9a-f]{2})|\\(.)", rtf[i:], re.I | re.S)
            if not word:  # a lone backslash at the very end, as when a long file is read only in part
                break
            i += word.end()
            if skip_at:
                continue
            if word.group(3):
                out.append(bytes([int(word.group(3), 16)]).decode("cp1252", "replace"))
            elif word.group(4):
                out.append(word.group(4) if word.group(4) in "\\{}" else "")
            elif word.group(1) in ("par", "line"):
                out.append("\n")
            elif word.group(1) == "tab":
                out.append("\t")
            elif word.group(1) == "u" and word.group(2):
                out.append(chr(int(word.group(2)) % 65536))
                if i < len(rtf) and rtf[i] == "?":
                    i += 1  # the \u's stand-in character
        elif c in "\r\n":
            i += 1
        else:
            if not skip_at:
                out.append(c)
            i += 1
    return "".join(out)


def display_name(sort_name):
    # "Angier, Natalie" → "Natalie Angier"; "Alkaloidal Clinic" stays as it is
    if sort_name.count(",") == 1:
        last, first = (part.strip() for part in sort_name.split(","))
        return f"{first} {last}" if first else last
    return sort_name.strip()


def books(rtf):
    """Each book in a catalogue: its author, title, year, the full citation and the fields under it."""
    found = []
    for block in re.split(r"\n\s*\n", rtf_text(rtf)):
        lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
        if not lines or " - " not in lines[0]:
            continue
        author_sort, short = (part.strip() for part in lines[0].split(" - ", 1))
        citation = next((line for line in lines[1:] if line.startswith(('"', "“"))), "")
        quoted = re.match(r'["“](.+?),?["”]', citation)
        title = quoted.group(1).rstrip(",") if quoted else short
        year = re.findall(r"\b(1[5-9]\d\d|20\d\d)\b", citation)
        fields = {}
        for line in lines[1:]:
            key, _, value = line.partition(":")
            if key in FIELDS and value.strip() and value.strip() not in ("X", "N/A"):
                fields[key.lower()] = value.strip()
        todo = [line for line in lines[1:] if line.upper().startswith("TODO")]
        found.append({"author": display_name(author_sort), "author_sort": author_sort, "title": title, "short": short,
                      "year": int(year[-1]) if year else None, "citation": citation, "fields": fields, "todo": todo})
    return found


HEADER = re.compile(r'^\t*\*{0,3}\t*["“](.+?),?["”]\s*,?\s*(.*)$')


def read_titles(rtf):
    """Titles.rtf, the books Ben has read: '***\t"Short," Author' and the full citation on the next line."""
    found, lines = [], [line for line in rtf_text(rtf).split("\n")]
    for at, line in enumerate(lines):
        if not line.startswith("***"):
            continue
        header = HEADER.match(line)
        if not header:
            continue
        short, author = header.group(1).rstrip(","), header.group(2).strip()
        citation = next((nxt.strip() for nxt in lines[at + 1:at + 3] if nxt.strip().startswith(('"', "“"))), "")
        quoted = re.match(r'["“](.+?),?["”]', citation)
        year = re.findall(r"\b(1[5-9]\d\d|20\d\d)\b", citation)
        found.append({"header": f'"{short}," {author}', "short": short, "author": author,
                      "title": quoted.group(1).rstrip(",") if quoted else short, "year": int(year[0]) if year else None,
                      "citation": citation})
    return found


def evidence_lists(rtf):
    """Lists-Per-Title.rtf: under each book's '\t"Short," Author' line, the evidence Ben found in it, one kind a line."""
    found, current = {}, None
    for line in rtf_text(rtf).split("\n"):
        header = HEADER.match(line) if line.startswith("\t") else None
        if header:
            current = f'"{header.group(1).rstrip(",")}," {header.group(2).strip()}'
            found.setdefault(current, [])
        elif current and line.strip():
            found[current].append(line.strip())
    return found


def web_note(name, rtf):
    """One of Ben's web-reading notes, 'Notes, A Hanging, Orwell.rtf', which opens with 'READ:  YES'; None if not one."""
    found = re.match(r"Notes,\s*(.+),\s*([^,]+?)\.rtf$", name, re.I)
    if not found:
        return None
    read = re.search(r"READ:\s*(\w+)", rtf_text(rtf[:4000]))
    return {"title": found.group(1).strip(), "author": found.group(2).strip(), "read": bool(read and read.group(1).upper() == "YES")}


def work_key(title, author):
    # Two copies are one work when their main titles (before any subtitle) and authors' surnames agree, however spelt
    main = re.split(r"[:;]", title)[0].lower()
    main = re.sub(r"^(the|a|an)\s+", "", re.sub(r"[^\w\s]", "", main)).strip()
    surname = re.sub(r"[^\w\s]", "", author.lower()).split()
    return f"{' '.join(main.split())}|{surname[-1] if surname else ''}"
