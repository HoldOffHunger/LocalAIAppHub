import re
from urllib.parse import unquote, urlsplit

URL = re.compile(r"https?://[^\s\"'<>\]\[|{}]+", re.I)
TRAILING = ".,;:!?)'\""
INDEX_PAGES = re.compile(r"/(?:index|default)\.(?:html?|php|asp)$", re.I)


def urls_in(text: str) -> list[str]:
    return [url.rstrip(TRAILING) for url in URL.findall(text or "")]


def original(url: str) -> str:
    # A source we took from the Wayback Machine stands for the page it captured
    found = re.match(r"https?://(?:web\.)?archive\.org/web/[^/]+/(https?://.+)", url, re.I)
    return original(found.group(1)) if found else url


def host(url: str) -> str:
    try:
        name = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return name[4:] if name.startswith("www.") else name


def same_page(url: str) -> str:
    # One key for every spelling of a page: scheme, www, case of the host, a trailing slash, index.html and escapes don't matter
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    path = INDEX_PAGES.sub("/", unquote(parts.path or "/")).rstrip("/") or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"{host(url)}{path}{query}"


def wiki_url(domain_index: bytes, path: bytes) -> str:
    # Wikipedia's externallinks keeps the host backwards ("http://com.example.www.") and the path apart
    scheme, _, reversed_host = domain_index.decode("utf-8", "replace").partition("://")
    name = ".".join(reversed(reversed_host.rstrip(".").split(".")))
    return f"{scheme}://{name}{path.decode('utf-8', 'replace')}"


def domain_keys(domain_index: bytes) -> list[bytes]:
    # The backwards host's leading labels, longest last: b"com.example." then b"com.example.www." and so on
    _, _, reversed_host = domain_index.partition(b"://")
    labels = reversed_host.rstrip(b".").split(b".")
    return [b".".join(labels[:count]) + b"." for count in range(2, min(len(labels), 6) + 1)]


def domain_key(domain: str) -> bytes:
    return ".".join(reversed(domain.lower().split("."))).encode() + b"."
