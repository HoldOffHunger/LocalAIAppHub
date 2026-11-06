"""A looser title key, the same on both sides, so names that mean one thing meet (Ben, 4 Nov 2026).

"Communism in America", "American Communism" and "American communists" all become "america communis": ideology words lose
-ism/-ist to one stem, a country's adjective and other names become the country, small words drop out, and the rest is
sorted, so word order doesn't matter. Wikipedia's titles are read once with this key into an index of their own.

Also two more kinds of name for a collection: a short folder name read as an acronym ("kpd", "cpgb", which Wikipedia
redirects), and "Communist Party of <Country>" for the Comintern's country sections.
"""

import re
from datetime import datetime
from functools import lru_cache

from wiki_dumps import WikiDumps, row_values, table_rows
from wiki_index import CHECKPOINT, WikiIndex, title_key

# Every form a country goes by, to one token. Russia and the Soviet Union stay apart: they're different subjects
COUNTRIES = {
    "afghanistan": "afghan afghans", "albania": "albanian albanians", "algeria": "algerian algerians",
    "argentina": "argentine argentinian argentinians", "australia": "australian australians", "austria": "austrian austrians",
    "bangladesh": "bangladeshi bangladeshis", "belgium": "belgian belgians", "bolivia": "bolivian bolivians",
    "brazil": "brazilian brazilians", "britain": "british briton britons uk",
    "bulgaria": "bulgarian bulgarians", "canada": "canadian canadians", "ceylon": "ceylonese",
    "chile": "chilean chileans", "china": "chinese prc", "cuba": "cuban cubans", "czechoslovakia": "czechoslovak czechoslovakian",
    "czech": "czechs czechia", "denmark": "danish dane danes", "dominican": "dominicans", "egypt": "egyptian egyptians",
    "england": "english", "finland": "finnish finn finns", "france": "french", "germany": "german germans",
    "greece": "greek greeks", "grenada": "grenadian grenadians", "guatemala": "guatemalan guatemalans", "haiti": "haitian haitians",
    "hungary": "hungarian hungarians", "india": "indian indians", "indonesia": "indonesian indonesians", "iran": "iranian iranians persia persian",
    "iraq": "iraqi iraqis", "ireland": "irish", "israel": "israeli israelis", "italy": "italian italians", "japan": "japanese",
    "korea": "korean koreans", "kurdistan": "kurdish kurd kurds", "mexico": "mexican mexicans", "netherlands": "dutch holland",
    "nicaragua": "nicaraguan nicaraguans", "norway": "norwegian norwegians", "pakistan": "pakistani pakistanis",
    "palestine": "palestinian palestinians", "peru": "peruvian peruvians", "philippines": "philippine filipino filipinos",
    "poland": "polish pole poles", "portugal": "portuguese", "romania": "romanian romanians", "russia": "russian russians",
    "scotland": "scottish scots scot", "serbia": "serbian serbs serb", "southafrica": "south-african", "spain": "spanish spaniard spaniards",
    "srilanka": "sri-lankan", "sweden": "swedish swede swedes", "switzerland": "swiss", "turkey": "turkish turk turks",
    "usa": "us america american americans", "ussr": "soviet soviets", "vietnam": "vietnamese", "wales": "welsh",
    "yugoslavia": "yugoslav yugoslavs yugoslavian",
}
PHRASES = [(re.compile(rf"\b{before}\b"), after) for before, after in (
    ("united states of america", "usa"), ("united states", "usa"), ("united kingdom", "britain"), ("great britain", "britain"),
    ("soviet union", "ussr"), ("south africa", "southafrica"), ("south african", "southafrica"), ("sri lanka", "srilanka"),
    ("sri lankan", "srilanka"), ("czech republic", "czech"), ("dominican republic", "dominican"))]
TOKEN = {form: country for country, forms in COUNTRIES.items() for form in [country, *forms.split()]}
SMALL = {"of", "in", "the", "and", "a", "an", "for", "on", "to", "at", "by", "de", "du", "des", "la", "le", "el", "del", "di", "y"}
ISM = re.compile(r"(?:isms|ists|ism|ist)$")


@lru_cache(maxsize=1_000_000)  # 66 million titles, but far fewer different words
def stem(word: str) -> str:
    if word in TOKEN:
        return TOKEN[word]
    if len(word) >= 7 and ISM.search(word):
        return ISM.sub("is", word)  # communism, communist, communists -> communis; but list, mist, twist are left alone
    if len(word) >= 5 and word.endswith("ies"):
        return word[:-3] + "y"  # parties -> party
    if len(word) >= 5 and word.endswith("s") and not word.endswith(("ss", "is", "us")):
        return word[:-1]  # workers -> worker
    return word


PHRASE_WORDS = ("united", "great", "soviet", "south", "sri", "czech", "dominican")


def loose_key(name: str) -> str:
    text = title_key(name)[0]
    if any(word in text for word in PHRASE_WORDS):  # most titles have none, and the phrase pass is the slow part
        for phrase, token in PHRASES:
            text = phrase.sub(token, text)
    words = sorted({stem(word) for word in text.split() if word not in SMALL})
    return " ".join(words)


SHORT = re.compile(r"^[a-z]{2,6}$")


def aside_fits(aside: str, name: str) -> bool:
    # A Wikipedia aside belongs to the collection when its loose words are all in the collection's name and filing:
    # "(UK)" fits "history / erol / periodicals / britain / red front"; "(Carlyle)" and "(Serbia)" don't
    return set(loose_key(aside).split()) <= set(loose_key(name).split())


def acronym(slug: str) -> str:
    # A short folder name that isn't a word we know as a country: "kpd", "cpgb", "ysa", "iwma"
    return slug if SHORT.match(slug) and slug not in TOKEN else ""


def comintern_party(folder: str) -> list[str]:
    # history/international/comintern/sections/<country>: the party Wikipedia files under that country's name
    parts = folder.split("/")
    if len(parts) == 5 and parts[:4] == ["history", "international", "comintern", "sections"] and parts[4] in TOKEN:
        country = TOKEN[parts[4]]
        return [f"Communist Party of {country}", f"{country} Communist Party"]
    return []


def scan_loose(index: WikiIndex, dumps: WikiDumps, keys: set[str], ends: datetime | None) -> bool:
    # WikiIndex.scan_pages with the loose key: every article title, kept when its loose key is one of ours. Resumable
    if index.meta("pages_done"):
        return True
    start, kept, number = int(index.meta("pages_line") or 0), [], 0
    print(f"reading Wikipedia's article titles for {len(keys):,} loose names" + (f", from line {start:,}" if start else ""), flush=True)
    number = start
    for number, line in table_rows(dumps.path("page"), start):
        page, namespace, title, redirect = row_values(line, 4)
        if namespace == b"0":
            text = title.decode("utf-8", "replace").replace("_", " ")
            key = loose_key(text)
            if key in keys:
                kept.append((int(page), text, int(redirect), key, title_key(text)[1]))
        if number % CHECKPOINT == 0 and number > start:
            index._save_pages(kept, number)
            kept = []
            if ends and datetime.now() >= ends:
                print(f"  stopped at line {number:,}; the read resumes there next turn", flush=True)
                return False
    index._save_pages(kept, number)
    with index.connection:
        index.set_meta("pages_done", 1)
    return True
