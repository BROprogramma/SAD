"""Zet de testconfiguratie klaar voor een nieuwe SIKB0101-versie (bijv. 15.1).

Voorwaarde: de geleverde versie-map staat naast 'SAD testsuite' en bevat 'Controle XSLT' en
'XSD en voorbeeld XML' (met de voorbeeldberichten van die versie). Die map wordt niet aangepast;
alles voor de tests komt in SAD testsuite/versies/<naam van de versie-map>/.

Gebruik:
    python nieuwe_versie.py "SAD Uitwisselberichten v15.1" --van "SAD Uitwisselberichten v15.0"

Wat het doet:
  1. kopieert de versie-instellingen (versie.json, overrides.json, bekende_afwijkingen.json,
     onbereikbaar.json, run_tests.bat) van versies/<--van>/ naar versies/<nieuwe versie>/;
     baseline, testberichten en rapport worden NIET gekopieerd (die horen bij de oude versie);
  2. toont welke XSLT's, lookups en XSD's verschillen met de --van-versie;
  3. haalt eventuele nieuwe externe schema's op en maakt de testberichten voor de nieuwe versie.
Daarna: python run_tests.py --versie "<nieuwe versie>" (de eerste run legt de baseline vast).
"""
import argparse
import difflib
import shutil
import sys
from pathlib import Path

import fetch_schemas
import maak_testberichten

SUITE_DIR = Path(__file__).resolve().parent
ROOT_DIR = SUITE_DIR.parent
VERSIONS_DIR = SUITE_DIR / "versies"
SETTINGS = ["versie.json", "overrides.json", "bekende_afwijkingen.json", "onbereikbaar.json", "run_tests.bat"]


def changed_lines(a, b):
    la = a.read_text(encoding="utf-8", errors="replace").splitlines()
    lb = b.read_text(encoding="utf-8", errors="replace").splitlines()
    return sum(1 for line in difflib.unified_diff([x.strip() for x in la], [x.strip() for x in lb], lineterm="")
               if line[:1] in "+-" and not line.startswith(("+++", "---")))


def compare(old, new):
    print(f"\nVerschillen t.o.v. {old.name}:")
    for sub in ("Controle XSLT", "XSD en voorbeeld XML"):
        old_files = {f.name: f for f in (old / sub).glob("*.*")}
        new_files = {f.name: f for f in (new / sub).glob("*.*")}
        for name in sorted(set(old_files) | set(new_files)):
            if name not in new_files:
                print(f"  {sub}/{name}: alleen in {old.name}")
            elif name not in old_files:
                print(f"  {sub}/{name}: nieuw")
            else:
                n = changed_lines(old_files[name], new_files[name])
                print(f"  {sub}/{name}: {'gelijk' if n == 0 else f'{n} regels anders'}")


def main():
    parser = argparse.ArgumentParser(description="Testconfiguratie klaarzetten voor een nieuwe versie")
    parser.add_argument("nieuw", help="naam van de nieuwe versie-map")
    parser.add_argument("--van", required=True, help="bestaande versie-map waarvan de instellingen worden overgenomen")
    parser.add_argument("--overschrijf", action="store_true", help="bestaande instellingen van de nieuwe versie overschrijven")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    new, old = ROOT_DIR / args.nieuw, ROOT_DIR / args.van
    for d in (new / "Controle XSLT", new / "XSD en voorbeeld XML" / "Voorbeeldberichten innameservice",
              VERSIONS_DIR / old.name):
        if not d.is_dir():
            parser.error(f"map ontbreekt: {d}")
    tests = VERSIONS_DIR / new.name
    existing = [f for f in SETTINGS if (tests / f).exists()]
    if existing and not args.overschrijf:
        parser.error(f"{tests} bevat al {', '.join(existing)}; gebruik --overschrijf om te vervangen")

    tests.mkdir(parents=True, exist_ok=True)
    for name in SETTINGS:
        if (VERSIONS_DIR / old.name / name).exists():
            shutil.copy(VERSIONS_DIR / old.name / name, tests / name)
    print(f"Instellingen gekopieerd van {old.name} naar {tests}")

    compare(old, new)

    print("\nExterne schema's ophalen (alleen nieuwe):")
    fetch_schemas.main()
    print()
    sys.argv = [sys.argv[0], new.name]
    maak_testberichten.main()

    print(f"""
Volgende stappen:
  1. Controleer {tests / 'versie.json'}: kloppen de waarden voor deze versie?
  2. Draai: python run_tests.py --versie "{new.name}"
     De eerste run legt baseline en controlelijst vast. Beoordeel elke FAIL:
     - verwacht verschil in deze versie → versie.json, bekende_afwijkingen.json,
       overrides.json of een case met "versies" aanpassen;
     - onverwacht → mogelijk een fout in de nieuwe XSLT.
  3. Oude versie laten vervallen? Zie README.md, 'Versie laten vervallen'.""")


if __name__ == "__main__":
    main()
