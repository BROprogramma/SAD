"""Haalt eenmalig de externe schema's (GML, O&M, Sampling, ...) op waar de SAD-XSD's (alle versies) naar verwijzen.

Ze worden bewaard in schema-cache/<host>/<pad>, zodat run_tests.py daarna offline kan valideren.
Gebruik: python fetch_schemas.py
"""
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

SUITE_DIR = Path(__file__).resolve().parent
CACHE_DIR = SUITE_DIR / "schema-cache"
# De XSD's van alle versie-mappen naast de testsuite
XSD_DIRS = sorted(d / "XSD en voorbeeld XML" for d in SUITE_DIR.parent.iterdir()
                  if (d / "XSD en voorbeeld XML").is_dir())
LOCATION = re.compile(r'<(?:\w+:)?(?:import|include|redefine)\b[^>]*?schemaLocation="([^"]+)"', re.S)


def cache_path(url):
    u = urlparse(url)
    return CACHE_DIR / u.netloc / u.path.lstrip("/")


def fetch(url):
    target = cache_path(url)
    if target.exists():
        return target.read_text(encoding="utf-8")
    request = urllib.request.Request(url, headers={"User-Agent": "sad-xslt-tests"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data.decode("utf-8")


def main():
    queue = []
    for xsd in (x for d in XSD_DIRS for x in d.glob("*.xsd")):
        queue += [loc for loc in LOCATION.findall(xsd.read_text(encoding="utf-8")) if loc.startswith("http")]
    seen = set()
    while queue:
        url = queue.pop()
        if url in seen:
            continue
        seen.add(url)
        try:
            text = fetch(url)
        except Exception as e:
            print(f"FOUT bij ophalen {url}: {e}")
            return 1
        queue += [urljoin(url, loc) for loc in LOCATION.findall(text)]
    size = sum(f.stat().st_size for f in CACHE_DIR.rglob("*") if f.is_file())
    print(f"{len(seen)} schema's in {CACHE_DIR} ({size / 1024:.0f} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
