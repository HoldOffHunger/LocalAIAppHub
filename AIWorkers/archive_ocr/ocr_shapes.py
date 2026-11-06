from dataclasses import dataclass

# What a scanner prints for what the page meant: (seen, meant, family). Strong shapes are ones a typist almost never makes;
# weak ones are single look-alike letters, which a slip of the keys can make too. None of these letters are neighbours on a
# keyboard (m/n, e/r and i/o are, and are left out on purpose), and no vowel stands in for another, since
# that is how people misspell: "tegether" and "operater" were the hunter's, not a scanner's.
SHAPES = [
    ("rn", "m", "rn/m"), ("m", "rn", "rn/m"), ("in", "m", "rn/m"), ("ni", "m", "rn/m"), ("iii", "m", "rn/m"),
    ("ri", "n", "rn/m"), ("n", "ri", "rn/m"),
    ("cl", "d", "cl/d"), ("d", "cl", "cl/d"),
    ("li", "h", "li/h"), ("h", "li", "li/h"), ("lı", "h", "li/h"),
    ("vv", "w", "vv/w"), ("w", "vv", "vv/w"), ("iv", "w", "vv/w"),  # "ivith"
    ("ii", "u", "ii/u"), ("ii", "n", "ii/u"), ("u", "ii", "ii/u"),
    ("f", "s", "long s"),  # an old book's long s (ſ) read as f: "fuch", "himfelf"
    ("ft", "ffi", "ligature"), ("ft", "ffic", "ligature"), ("f", "fi", "ligature"), ("f", "fl", "ligature"),
    ("fl", "ffl", "ligature"),  # not fi→ffi: "oficial" and "dificulty" are people forgetting the double f
    ("b", "h", "b/h"), ("h", "b", "b/h"),
    ("c", "e", "c/e"), ("e", "c", "c/e"), ("c", "o", "c/o"), ("o", "c", "c/o"),
    ("n", "u", "n/u"), ("u", "n", "n/u"),
    ("l", "i", "l/i"), ("i", "l", "l/i"), ("l", "t", "l/t"), ("t", "l", "l/t"), ("t", "c", "c/t"), ("c", "t", "c/t"),
    ("v", "y", "v/y"), ("y", "v", "v/y"),
]
STRONG = {"rn/m", "cl/d", "li/h", "vv/w", "ii/u", "long s", "ligature"}


@dataclass(frozen=True)
class Reading:
    word: str  # what the page meant
    steps: tuple[tuple[str, str, str], ...]  # each (seen, meant, family), left to right

    @property
    def families(self) -> list[str]:
        return [family for _, _, family in self.steps]

    @property
    def strong(self) -> bool:
        return any(family in STRONG for family in self.families)

    @property
    def only_strong(self) -> bool:
        return all(family in STRONG for family in self.families)

    def describe(self) -> str:
        return ", ".join(f"{seen}→{meant} ({family})" for seen, meant, family in self.steps)


def readings(seen: str, steps: int = 2) -> list[Reading]:
    """Every word this OCR output could have been, with at most `steps` look-alike swaps, fewest swaps first.

    Swaps never overlap: each letter the scanner printed is read again at most once."""
    found: dict[str, Reading] = {}

    def walk(at: int, done: str, taken: tuple) -> None:
        if at == len(seen):
            if taken and (done not in found or len(taken) < len(found[done].steps)):
                found[done] = Reading(done, taken)
            return
        walk(at + 1, done + seen[at], taken)
        if len(taken) < steps:
            for shape in SHAPES:
                if seen.startswith(shape[0], at):
                    walk(at + len(shape[0]), done + shape[1], taken + (shape,))

    walk(0, "", ())
    found.pop(seen, None)
    return sorted(found.values(), key=lambda reading: (len(reading.steps), reading.word))


def ocr_shaped(wrong: str, right: str, steps: int = 2) -> Reading | None:
    """How a scanner turns `right` into `wrong`, if only look-alike swaps do it; None for a typing slip."""
    wrong, right = wrong.lower(), right.lower()
    if wrong == right or " " in wrong or " " in right:
        return None
    return next((reading for reading in readings(wrong, steps) if reading.word == right), None)
