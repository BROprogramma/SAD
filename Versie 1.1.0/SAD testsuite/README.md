# Tests voor de SAD controle-XSLT's

Controleert na een aanpassing aan `SIKB_SAD IMBRO.xslt` of `SIKB_SAD IMBROA.xslt` of er niets is omgevallen, voor **elke SIKB0101-versie** (nu 14.9.0 en 15.0).

## Opzet

```
BRO XSLTs/
├── SAD Uitwisselberichten/           ← geleverde versie 14.9.0 (ongewijzigd, niets van de tests erin)
│   └── Controle XSLT/ , XSD en voorbeeld XML/
├── SAD Uitwisselberichten v15.0/     ← geleverde versie 15.0 (idem)
└── SAD testsuite/                    ← ALLES voor de tests
    ├── run_tests.py                  ← de testrunner
    ├── run_alle_versies.bat          ← dubbelklik: test alle versies
    ├── cases.json                    ← handgeschreven testcases (voor alle versies)
    ├── nieuwe_versie.py, maak_testberichten.py, fetch_schemas.py, xslt_sites.py, schema-cache/
    └── versies/
        ├── SAD Uitwisselberichten/           ← zelfde naam als de geleverde map
        │   ├── run_tests.bat                 ← dubbelklik: test alleen deze versie
        │   ├── versie.json                   ← versie-afhankelijke waarden voor cases.json
        │   ├── bekende_afwijkingen.json, overrides.json, onbereikbaar.json
        │   ├── baseline/ , testberichten/
        │   └── report/report.html            ← rapport van de laatste run
        └── SAD Uitwisselberichten v15.0/     ← (zelfde opbouw)
```

De geleverde mappen blijven precies zoals ze geleverd zijn. De runner koppelt ze **op mapnaam**: een map naast `SAD testsuite` met een `Controle XSLT`-map wordt getest als er een gelijknamige map in `SAD testsuite/versies/` staat. Elke versie gebruikt **zijn eigen** XSLT's, voorbeeldberichten en XSD's. Een geleverde map zonder testconfiguratie (of een configuratie zonder geleverde map) wordt overgeslagen met een melding.

## Installeren (eenmalig)

Nodig: Python 3 (met *Add python.exe to PATH*). De `.bat`-bestanden controleren zelf of de pakketten `saxonche` en `lxml` aanwezig zijn en installeren ze anders eenmalig (`requirements.txt`). Handmatig kan ook:

```
python -m pip install --user -r requirements.txt
python fetch_schemas.py
```

`saxonche` is Saxon-HE (XSLT 2.0-processor, van Saxonica, open source onder MPL 2.0), `lxml` (BSD-licentie) wordt gebruikt voor XSD-validatie en om berichten in het geheugen aan te passen. Beide zijn gratis en komen van PyPI. `fetch_schemas.py` haalt eenmalig de externe schema's (GML, O&M, ...) van alle versies op naar `schema-cache/`; die staat er al, dus dit is alleen nodig als een nieuwe versie andere externe schema's gebruikt.

## Draaien

Dubbelklik `run_alle_versies.bat` (alle versies) of `versies/<versie>/run_tests.bat` (één versie), of vanuit `SAD testsuite`:

```
python run_tests.py                                     alle versies (~25 s per versie, parallel)
python run_tests.py --versie "SAD Uitwisselberichten"   alleen deze versie (mag vaker)
python run_tests.py --snel                              zonder automatische controles
python run_tests.py -k asbestos                         alleen tests met 'asbestos' in de naam
python run_tests.py --versie V --xslt-dir MAP           XSLT's uit MAP testen (bijv. een aangepaste kopie)
python run_tests.py --update-baseline                   huidige uitvoer + controlelijst vastleggen als nieuwe baseline
python run_tests.py --workers 4                         aantal parallelle processen (standaard: cores - 1, max 16)
```

De opties van `run_tests.bat` worden doorgegeven, bijv. `run_tests.bat -k Layer`. Na elke run staat er per versie een rapport in `versies/<versie>/report/report.html` (met filter "alleen gefaalde tests"); bij meerdere versies volgt in de terminal een overzicht. Exitcode 0 = niets gefaald, 1 = iets gefaald.

**Tip bij het aanpassen van een XSLT:** werk in een kopie en test die eerst met `--versie ... --xslt-dir`, of draai de tests direct na je wijziging en kijk in het rapport.

## Wat wordt er getest (per versie)

| Groep | Wat |
|---|---|
| XSLT's | Beide XSLT's compileren, lookupbestanden zijn well-formed, en de meetversie (zie onder) geeft exact dezelfde meldingen als het origineel. |
| XSD-validatie | Alle inname- en uitgifte-voorbeelden valideren tegen de eigen `issad-messages.xsd` / `dssad-messages.xsd`. |
| Voorbeeldberichten | Elk officieel voorbeeldbericht gaat door de XSLT van zijn regime (uit `qualityRegime`: `IMBRO` → IMBRO-XSLT, `IMBRO/A` → IMBROA-XSLT) en moet 0 ERRORs geven. |
| Testberichten | Afgeleide berichten in `versies/<versie>/testberichten/` (zie onder), ook 0 ERRORs (of bekende afwijking). |
| Baseline | De volledige uitvoer per bericht moet exact gelijk zijn aan `versies/<versie>/baseline/` (volgorde maakt niet uit). Bij verschil zie je welke meldingen erbij kwamen of verdwenen. |
| Controlelijst | Alle controle-aanroepen in elke XSLT (met parameters, zoals ERROR/WARNING) moeten gelijk zijn aan `versies/<versie>/baseline/controlelijst *.json`. Vangt een weggehaalde of gewijzigde controle. |
| Automatische controles | Voor elke standaard-controle (checkExistence, checkFilled, checkLookupId, checkLength, checkExactLength, datums, geometrie, coördinaten, rol-relaties) wordt een element in een bericht bewust fout gemaakt; de test slaagt alleen als precies díe controle een melding geeft. Nieuwe controles gaan automatisch mee. |
| Testcases | Handgeschreven cases uit de gedeelde `cases.json` voor de overige controles (losse meldingen, lagen, filters, Analysis, ...). |

**Dekking**: onderaan het rapport staat per XSLT hoeveel controles in minstens één test een melding gaven, de lijst die nog nooit geraakt is, en de controles die als onbereikbaar zijn uitgesloten. Alleen een volledige run (zonder `-k`/`--snel`) geeft een representatieve dekking.

### Hoe weet de test welke controle een melding gaf?
De runner maakt in het geheugen een *meetversie* van elke XSLT waarin elke controle-aanroep zijn regelnummer aan de melding meegeeft, en een *verkenningsversie* die registreert welke elementen welke controle bereiken. De originele XSLT wordt niet aangepast; een aparte test bewaakt dat de meetversie exact dezelfde meldingen geeft.

## Bestanden

**Gedeeld (`SAD testsuite/`)**

| Bestand | Doel |
|---|---|
| `run_tests.py`, `run_alle_versies.bat` | De testrunner. |
| `xslt_sites.py` | Vindt de controle-aanroepen in de XSLT en maakt de meet- en verkenningsversie. |
| `cases.json` | Handgeschreven testcases voor alle versies. |
| `nieuwe_versie.py` | Zet `versies/<nieuwe versie>/` klaar voor een nieuwe versie (zie *Versies wisselen*). |
| `maak_testberichten.py` | Maakt `versies/<versie>/testberichten/` opnieuw aan uit de officiële voorbeelden (alle versies, of één: `python maak_testberichten.py "SAD Uitwisselberichten"`). |
| `fetch_schemas.py`, `schema-cache/` | Externe schema's voor de XSD-validatie. |

**Per versie (`versies/<naam van de geleverde map>/`)**

| Bestand | Doel |
|---|---|
| `run_tests.bat` | Test alleen deze versie. |
| `versie.json` | Waarden die per versie verschillen, gebruikt als `${NAAM}` in `cases.json`. |
| `overrides.json` | Aanpassingen op automatische controles (overslaan, andere mutatie), altijd met reden. |
| `bekende_afwijkingen.json` | Bewust geaccepteerde afwijkingen (status BEKEND i.p.v. FAIL). |
| `onbereikbaar.json` | Controles die nooit kunnen afgaan (dode code), met reden; tellen niet mee in de dekking. |
| `baseline/` | Vastgelegde uitvoer per bericht + controlelijst per XSLT. |
| `testberichten/`, `report/` | Afgeleide testberichten en het rapport. |

## Een testcase toevoegen

Voeg een blok toe aan `SAD testsuite/cases.json`; de case draait dan in alle versies:

```json
{
  "name": "Project - twee investigationReasons",
  "sources": ["3. SAD_registrationRequest IMBRO.xml", "1. SAD_registrationRequest IMBROA.xml"],
  "mutations": [
    { "xpath": "//imsikb0101:Project/imsikb0101:investigationReason", "action": "duplicate" }
  ],
  "expect": { "type": "ERROR", "title_contains": "Project", "message_contains": "mag er maar 1 investigationReason" }
}
```

- `source` (één bericht) of `sources` (lijst; de case draait per bericht). Het regime (en dus de XSLT) volgt uit het bericht. Voorbeeld- én testberichten mogen.
- `action`: `remove`, `set` (tekst → `value`), `set_attribute` (`name` + `value`), `duplicate`, `insert_xml` (`xml`; standaard als laatste kind, met `"position": "after"` erna). Met `"first_only": true` alleen het eerste gevonden element.
- `expect` mag een lijst zijn (ook leeg); `not_expect` = meldingen die juist níet mogen verschijnen; `waarom` = toelichting in het rapport.
- De verwachte melding moet *nieuw* zijn t.o.v. het onbewerkte bericht.
- Prefixen in XPath: `imsikb0101`, `immetingen`, `gml`, `om`, `sam`, `sams`, `spec`, `xlink`, `xsi`, `issad`, `sadcom`.

**Verschillen tussen versies:**
- Een waarde die per versie verschilt schrijf je als `${NAAM}` en zet je in elke `versie.json` onder `variabelen`. Voorbeeld: `${LAAG_GRINDGEHALTE}` is `urn:immetingen:KenmerkBodemlaag:id:9` in 14.9.0 en `urn:immetingen:Parameter:id:3688` in 15.0.
- Een case die maar voor één versie geldt krijgt `"versies": ["SAD Uitwisselberichten v15.0"]` (de mapnaam).

## Werkwijze bij veelvoorkomende wijzigingen

### Ik pas een voorbeeldbericht aan
De tests lezen de voorbeeldberichten bij elke run opnieuw in; automatische controles en testcases gebruiken dus direct de nieuwe inhoud. Wat je daarna doet:

1. Draai de tests voor die versie: `run_tests.bat` in `versies/<versie>` (of `python run_tests.py --versie "<versie>"`).
2. Waarschijnlijk faalt de groep **Baseline** voor dat bericht: het rapport toont precies welke meldingen erbij kwamen of verdwenen. Is dat wat je verwachtte? Leg het vast:
   ```
   python run_tests.py --versie "<versie>" --update-baseline
   ```
3. Het bericht moet nog steeds **0 ERRORs** geven (groep *Voorbeeldberichten*). Bevat het bewust een fout, zet dat dan in `bekende_afwijkingen.json` van die versie (zoals bij `1b`).
4. Heb je een element verwijderd of een `gml:id` veranderd waar een testcase naar verwijst, dan faalt die case met *"XPath vond geen element"*. Pas de XPath in `cases.json` aan (of kies een ander bronbericht).
5. Zijn T1–T4 van dit bericht afgeleid (3b, 3, 1), maak ze dan opnieuw: `python maak_testberichten.py "<versie>"`, en draai stap 2 opnieuw.
6. Een **nieuw** voorbeeldbericht in de innamemap wordt automatisch meegenomen; de eerste run maakt er een baseline voor aan.

### Ik breid een XSLT uit met een nieuwe controle
1. Pas de XSLT aan en draai de tests voor die versie.
2. De groep **Controlelijst** faalt met *"+ nieuw: sikb:…"*. Dat is de bevestiging dat de runner je nieuwe controle ziet.
3. Kijk wat voor controle het is:
   - **Een standaardfunctie met `.` als context** (`checkExistence`, `checkFilled`, `checkLookupId`, `checkLength`, `checkExactLength`, `checkDateBeforeDate`/`AfterDate`, `checkGeometryElement(s)`, `checkCoordinates`, `checkSamplingFeatureRelation`): die wordt **automatisch getest** (groep *Automatische controles*). Niets te doen, tenzij hij als *NIET TESTBAAR* verschijnt: dan heeft geen enkel voorbeeld- of testbericht het betreffende element. Voeg dan een testcase toe die het element met `insert_xml` toevoegt, of breid `maak_testberichten.py` uit.
   - **Een eigen melding (`sikb:createRecord`) of een functie met een andere context** (bijv. `$variabele` of `./iets`): die verschijnt onderaan de terminaluitvoer en in het rapport bij **Dekking → niet geraakt: regel …**. Schrijf daarvoor een testcase in `cases.json` (zie *Een testcase toevoegen*):
     1. zoek in de XSLT onder welke voorwaarde de melding ontstaat;
     2. kies een voorbeeldbericht (bij voorkeur `3. … IMBRO.xml` en `1. … IMBROA.xml` via `sources`, dan test je beide regimes);
     3. beschrijf met `mutations` hoe je het bericht fout maakt, en met `expect` een stukje van de verwachte `Title`/`Message`;
     4. probeer de case los uit: `python run_tests.py --versie "<versie>" --snel -k "<naam van je case>"`.
4. Alles zoals verwacht? Leg de controlelijst vast: `python run_tests.py --versie "<versie>" --update-baseline`.
5. Draai tot slot een volledige run en controleer dat de dekking weer 100% is.
6. Geldt de nieuwe controle maar voor één versie? Geef de case dan `"versies": ["<versie-map>"]` en voeg eventueel een case toe die in de andere versie juist géén melding verwacht (`"expect": []` met `not_expect`).

### Ik verander een meldingstekst of ERROR ↔ WARNING
De groepen **Baseline** (als een voorbeeldbericht die melding geeft), **Controlelijst** en de testcases met `message_contains`/`type` op die melding falen. Controleer in het rapport dat alleen verandert wat je bedoelde, pas de betreffende cases in `cases.json` aan en draai `--update-baseline`.

### Ik repareer een controle die in `onbereikbaar.json` staat
Haal hem uit `onbereikbaar.json` van die versie, draai de tests (de controlelijst meldt de gewijzigde aanroep) en daarna `--update-baseline`. Is het een standaardfunctie met `.` als context geworden, dan wordt hij automatisch getest; anders een testcase toevoegen.

## Wanneer `--update-baseline`?
Alleen als je een verandering **bewust** hebt gemaakt: een meldingstekst aangepast, een controle toegevoegd/verwijderd, of ERROR ↔ WARNING gewijzigd. Kijk eerst in het rapport (groepen *Baseline* en *Controlelijst*) wat er verandert. Combineer met `--versie` om alleen de baseline van die versie bij te werken. Pas daarna eventueel ook de testcases aan die op die melding controleren.

## Versies wisselen (bijv. 15.1 erbij, 14.9.0 vervalt)

De runner test elke geleverde map naast `SAD testsuite` waarvoor een gelijknamige map in `SAD testsuite/versies/` bestaat. Een versie toevoegen of laten vervallen is dus vooral mappen neerzetten of weghalen; de geleverde mappen zelf hoef je nooit aan te passen.

### Nieuwe versie toevoegen

1. **Map neerzetten** – zet de geleverde map (bijv. `SAD Uitwisselberichten v15.1`, met `Controle XSLT/` en `XSD en voorbeeld XML/` inclusief de voorbeeldberichten) naast de andere versies. Verder niets aan toevoegen. Een run meldt nu: *"heeft nog geen testconfiguratie"*.
2. **Tests klaarzetten** – vanuit `SAD testsuite`:
   ```
   python nieuwe_versie.py "SAD Uitwisselberichten v15.1" --van "SAD Uitwisselberichten v15.0"
   ```
   Dit maakt `versies/SAD Uitwisselberichten v15.1/` en kopieert daarin de instellingen (`versie.json`, `overrides.json`, `bekende_afwijkingen.json`, `onbereikbaar.json`, `run_tests.bat`) van de meest verwante versie, toont welke XSLT's/XSD's/lookups verschillen, haalt eventuele nieuwe externe schema's op en maakt de testberichten. Baseline en rapport worden bewust níet gekopieerd.
3. **`versie.json` nalopen** – kloppen de waarden (bijv. `LAAG_GRINDGEHALTE`) voor de nieuwe versie? Ontbreekt er een variabele, dan faalt de betreffende case met een duidelijke melding.
4. **Eerste run** – `python run_tests.py --versie "SAD Uitwisselberichten v15.1"`. Deze run legt de baseline en controlelijst vast; beoordeel daarna elke FAIL:
   - *verwacht verschil in deze versie* → pas `versie.json`, `bekende_afwijkingen.json` of `overrides.json` van die versie aan, of geef een case `"versies": [...]` (of juist een versie-variabele);
   - *onverwacht* → mogelijk een fout in de nieuwe XSLT.
5. Kijk naar de **dekking** in het rapport: nieuwe controles in de XSLT worden automatisch getest; staat er iets bij "niet geraakt", voeg dan een case toe aan `cases.json`.

### Versie laten vervallen

1. Haal de geleverde map weg uit `BRO XSLTs` (verplaats naar een archief buiten `BRO XSLTs`, of verwijder) **en** verwijder of archiveer `SAD testsuite/versies/<die map>/`. Alleen tijdelijk uitzetten? Verplaats dan alleen `versies/<die map>` naar bijv. `SAD testsuite/versies (uit)/`; zonder configuratie wordt de versie overgeslagen.
2. Opruimen in de gedeelde `cases.json` (niet verplicht, maar wel netjes):
   - cases met `"versies": ["<vervallen map>"]` kunnen weg;
   - staat de vervallen map in een lijst met meerdere versies, haal alleen die naam weg.
3. Draai `run_alle_versies.bat` ter controle.

Zie ook de docstring bovenin `nieuwe_versie.py`.

## Nieuwe voorbeeldberichten binnen een versie
Zet ze in de innamemap; ze worden automatisch meegenomen. Draai daarna `python maak_testberichten.py "<versie>"` en `python run_tests.py --versie "<versie>" --update-baseline`. Testcases met vaste `gml:id`'s in de XPath moeten dan mogelijk worden bijgewerkt.
