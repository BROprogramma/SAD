"""Regressietests voor de SAD controle-XSLT's (IMBRO en IMBRO/A), voor elke SIKB0101-versie.

Een versie is een geleverde map naast deze testsuite met 'Controle XSLT' en 'XSD en voorbeeld XML'
(bijv. 'SAD Uitwisselberichten' en 'SAD Uitwisselberichten v15.0'); die mappen blijven ongewijzigd.
Alles voor de tests staat in deze testsuite: de gedeelde code en cases.json, en per versie
versies/<naam van de versie-map>/ (baseline, testberichten, rapport, bekende afwijkingen, ...).

Gebruik:
    python run_tests.py                     alle versies testen
    python run_tests.py --versie "SAD Uitwisselberichten v15.0"   alleen deze versie
    python run_tests.py -k asbestos         alleen tests met 'asbestos' in de naam
    python run_tests.py --versie V --xslt-dir MAP   XSLT's uit MAP testen (bijv. een aangepaste kopie)
    python run_tests.py --update-baseline   huidige uitvoer + controlelijst vastleggen als nieuwe baseline
    python run_tests.py --snel              automatische controles overslaan (sneller, geen volledige dekking)
    python run_tests.py --workers 4         aantal parallelle processen (standaard: cores - 1, max 16)

Exitcode 0 = niets gefaald, 1 = minstens één test gefaald.
"""
import argparse
import copy
import os
import html
import json
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from lxml import etree
from saxonche import PySaxonProcessor

from xslt_sites import GENERIC, instrument, literal

SUITE_DIR = Path(__file__).resolve().parent          # gedeelde code, cases.json, schema-cache
ROOT_DIR = SUITE_DIR.parent                          # map met de versie-mappen
SCHEMA_CACHE = SUITE_DIR / "schema-cache"
VERSIONS_DIR = SUITE_DIR / "versies"                 # per versie: versies/<naam van de versie-map>/

# Paden van de versie die op dit moment getest wordt (gezet door configure())
SAD_DIR = TESTS_DIR = XSD_DIR = EXAMPLES_DIR = DISPATCH_DIR = DEFAULT_XSLT_DIR = None
TESTBERICHTEN_DIR = BASELINE_DIR = REPORT_FILE = None
VERSION_VARS = {}


def delivered_dirs():
    """Alle geleverde versie-mappen naast de testsuite (herkenbaar aan 'Controle XSLT')."""
    return sorted(d for d in ROOT_DIR.iterdir() if d.is_dir() and (d / "Controle XSLT").is_dir())


def version_dirs():
    """Geleverde versie-mappen waarvoor een testconfiguratie in versies/ bestaat."""
    return [d for d in delivered_dirs() if (VERSIONS_DIR / d.name).is_dir()]


def configure(sad_dir):
    global SAD_DIR, TESTS_DIR, XSD_DIR, EXAMPLES_DIR, DISPATCH_DIR, DEFAULT_XSLT_DIR
    global TESTBERICHTEN_DIR, BASELINE_DIR, REPORT_FILE, VERSION_VARS
    SAD_DIR = Path(sad_dir).resolve()
    TESTS_DIR = VERSIONS_DIR / SAD_DIR.name
    XSD_DIR = SAD_DIR / "XSD en voorbeeld XML"
    EXAMPLES_DIR = XSD_DIR / "Voorbeeldberichten innameservice"
    DISPATCH_DIR = XSD_DIR / "Voorbeeldberichten uitgifteservice"
    DEFAULT_XSLT_DIR = SAD_DIR / "Controle XSLT"
    TESTBERICHTEN_DIR = TESTS_DIR / "testberichten"
    BASELINE_DIR = TESTS_DIR / "baseline"
    REPORT_FILE = TESTS_DIR / "report" / "report.html"
    VERSION_VARS = load_json("versie.json", {}).get("variabelen", {})

# Kwaliteitsregime (waarde van qualityRegime in het bericht) -> XSLT-bestand
XSLT_PER_REGIME = {
    "IMBRO": "SIKB_SAD IMBRO.xslt",
    "IMBRO/A": "SIKB_SAD IMBROA.xslt",
}

# Prefixen die in de XPath's van cases.json en overrides.json gebruikt mogen worden
NAMESPACES = {
    "issad": "http://www.broservices.nl/xsd/issad/1.1",
    "sadcom": "http://www.broservices.nl/xsd/sadcommon/1.1",
    "imsikb0101": "http://www.sikb.nl/imsikb0101",
    "immetingen": "http://www.sikb.nl/immetingen",
    "gml": "http://www.opengis.net/gml/3.2",
    "om": "http://www.opengis.net/om/2.0",
    "sam": "http://www.opengis.net/sampling/2.0",
    "sams": "http://www.opengis.net/samplingSpatial/2.0",
    "spec": "http://www.opengis.net/samplingSpecimen/2.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"

# Maximaal aantal kandidaat-elementen dat per automatische controle geprobeerd wordt
MAX_CANDIDATES = 3

STATUSES = ("PASS", "FAIL", "BEKEND", "NIET TESTBAAR", "OVERGESLAGEN")


# ---------------------------------------------------------------------------
# Basistypen
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Record:
    type: str
    title: str
    message: str
    site: str = ""

    @property
    def key(self):
        """Waarop vergeleken wordt met de baseline (zonder site)."""
        return (self.type, self.title, self.message)

    def __str__(self):
        return f"[{self.type}] {self.title}: {self.message}"


@dataclass
class Result:
    group: str
    name: str
    status: str
    summary: str = ""
    details: list = field(default_factory=list)
    records: list = field(default_factory=list)
    records_label: str = "Meldingen van de XSLT"


@dataclass
class Example:
    path: Path
    regime: str
    tree: object
    group: str = "Voorbeeldberichten"

    @property
    def name(self):
        return self.path.name


def norm(text):
    return " ".join((text or "").split())


def load_json(name, default):
    path = TESTS_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def read_regime(tree):
    values = tree.xpath("//*[local-name()='qualityRegime']/text()")
    return norm(values[0]) if values else None


def parse_records(output):
    root = etree.fromstring(output.encode("utf-8"))
    return [Record(norm(r.findtext("Type")), norm(r.findtext("Title")), norm(r.findtext("Message")),
                   r.get("site", ""))
            for r in root.iter("LogRecord")]


def new_records(before, after):
    """Records die door een mutatie zijn bijgekomen (multiset-verschil, inclusief site)."""
    diff = Counter(after) - Counter(before)
    return list(diff.elements())


def record_diff(expected_keys, actual_keys):
    extra = Counter(actual_keys) - Counter(expected_keys)
    missing = Counter(expected_keys) - Counter(actual_keys)
    return list(extra.elements()), list(missing.elements())


def fmt_key(key):
    return f"[{key[0]}] {key[1]}: {key[2]}"


# ---------------------------------------------------------------------------
# XSLT uitvoeren
# ---------------------------------------------------------------------------

class Engine:
    """Compileert de XSLT's (origineel, meetversie, verkenningsversie) binnen één proces."""

    def __init__(self, proc, xslt_dir):
        self.proc = proc
        compiler = proc.new_xslt30_processor()
        self.plain, self.marked, self.traced, self.sites, self.errors = {}, {}, {}, {}, {}
        for regime, filename in XSLT_PER_REGIME.items():
            path = xslt_dir / filename
            try:
                self.plain[regime] = compiler.compile_stylesheet(stylesheet_file=str(path))
                text, sites = instrument(path, regime)
                self.marked[regime] = compiler.compile_stylesheet(stylesheet_text=text)
                self.traced[regime] = compiler.compile_stylesheet(stylesheet_text=text)
                self.traced[regime].set_parameter("{http://xslcontrole.sikb}testsuiteTrace",
                                                  proc.make_boolean_value(True))
                self.sites[regime] = sites
            except Exception as e:
                self.errors[regime] = str(e)

    def execute(self, mode, regime, xml_text):
        """mode: 'run' (meetversie), 'plain' (origineel) of 'reach' (verkenningsrun)."""
        executable = {"run": self.marked, "plain": self.plain, "reach": self.traced}[mode][regime]
        output = executable.transform_to_string(xdm_node=self.proc.parse_xml(xml_text=xml_text))
        if mode != "reach":
            return parse_records(output)
        reached = defaultdict(list)
        for el in etree.fromstring(output.encode("utf-8")).iter("Reached"):
            if int(el.get("index")) not in reached[el.get("site")]:
                reached[el.get("site")].append(int(el.get("index")))
        return dict(reached)


_WORKER_ENGINE = None


def _init_worker(xslt_dir):
    global _WORKER_ENGINE
    _WORKER_ENGINE = Engine(PySaxonProcessor(license=False), Path(xslt_dir))


def _work(job):
    return _WORKER_ENGINE.execute(*job)


class Transformer:
    """Voert transformaties uit, parallel via een pool van worker-processen (elk met een eigen Saxon)."""

    def __init__(self, engine, pool=None):
        self.engine, self.pool = engine, pool
        self.sites, self.errors = engine.sites, engine.errors
        self.hit = defaultdict(set)  # regime -> regelnummers van controles die een melding gaven
        self.count = 0

    def run_many(self, jobs):
        """jobs: lijst van (mode, regime, tree). Geeft de resultaten in dezelfde volgorde terug."""
        payload = [(mode, regime, etree.tostring(tree, encoding="unicode")) for mode, regime, tree in jobs]
        if self.pool and len(payload) > 1:
            results = list(self.pool.map(_work, payload, chunksize=1))
        else:
            results = [self.engine.execute(*job) for job in payload]
        self.count += len(payload)
        for (mode, regime, _), result in zip(jobs, results):
            if mode == "run":
                self.hit[regime].update(r.site for r in result if r.site)
        return results

    def run(self, regime, tree, plain=False):
        return self.run_many([("plain" if plain else "run", regime, tree)])[0]

    def reach(self, regime, tree):
        return self.run_many([("reach", regime, tree)])[0]


# ---------------------------------------------------------------------------
# Test: XSLT's compileren + instrumentatie is neutraal
# ---------------------------------------------------------------------------

def test_xslts(transformer, xslt_dir, examples, originals):
    results = []
    for regime, filename in XSLT_PER_REGIME.items():
        if regime in transformer.errors:
            results.append(Result("XSLT's", f"{filename} compileert", "FAIL", transformer.errors[regime]))
        else:
            n = len(transformer.sites[regime])
            results.append(Result("XSLT's", f"{filename} compileert", "PASS", f"{n} controle-aanroepen gevonden"))
    for lookup in sorted(xslt_dir.glob("*.xml")):
        try:
            etree.parse(str(lookup))
            results.append(Result("XSLT's", f"{lookup.name} is well-formed", "PASS"))
        except etree.XMLSyntaxError as e:
            results.append(Result("XSLT's", f"{lookup.name} is well-formed", "FAIL", str(e)))
    # De meetversie van de XSLT (met regelnummers) moet exact dezelfde meldingen geven als het origineel
    plain = transformer.run_many([("plain", ex.regime, ex.tree) for ex in examples])
    differences = [ex.name for ex, records in zip(examples, plain)
                   if Counter(r.key for r in records) != Counter(r.key for r in originals[ex.name])]
    if differences:
        results.append(Result("XSLT's", "Meetversie geeft dezelfde meldingen als origineel", "FAIL",
                              "verschil bij: " + ", ".join(differences)))
    else:
        results.append(Result("XSLT's", "Meetversie geeft dezelfde meldingen als origineel", "PASS",
                              f"{len(examples)} voorbeeldberichten vergeleken"))
    return results


# ---------------------------------------------------------------------------
# Test: XSD-validatie
# ---------------------------------------------------------------------------

class CacheResolver(etree.Resolver):
    """Stuurt http(s)-schema's naar de lokale kopie in schema-cache/."""

    def resolve(self, url, pubid, context):
        if url.startswith("http"):
            u = urlparse(url)
            local = SCHEMA_CACHE / u.netloc / u.path.lstrip("/")
            if not local.exists():
                raise FileNotFoundError(f"{url} staat niet in schema-cache (draai fetch_schemas.py)")
            return self.resolve_filename(str(local), context)
        return None


def test_xsd(known):
    results = []
    if not SCHEMA_CACHE.exists():
        return [Result("XSD-validatie", "schema-cache", "OVERGESLAGEN",
                       "schema-cache ontbreekt; draai eerst: python fetch_schemas.py")]
    for xsd_name, folder in (("issad-messages.xsd", EXAMPLES_DIR), ("dssad-messages.xsd", DISPATCH_DIR)):
        parser = etree.XMLParser(no_network=True)
        parser.resolvers.add(CacheResolver())
        try:
            schema = etree.XMLSchema(etree.parse(str(XSD_DIR / xsd_name), parser))
        except Exception as e:
            results.append(Result("XSD-validatie", xsd_name, "FAIL", f"schema laden mislukt: {e}"))
            continue
        for xml in sorted(folder.glob("*.xml")):
            name = f"{xml.name}  ({xsd_name})"
            ok = schema.validate(etree.parse(str(xml)))
            errors = [f"regel {e.line}: {e.message}" for e in schema.error_log]
            if ok:
                results.append(Result("XSD-validatie", name, "PASS"))
            elif xml.name in known:
                results.append(Result("XSD-validatie", name, "BEKEND", known[xml.name].get("reden", ""), errors[:10]))
            else:
                results.append(Result("XSD-validatie", name, "FAIL", errors[0] if errors else "ongeldig", errors[:10]))
    return results


# ---------------------------------------------------------------------------
# Test: voorbeeldberichten (0 ERRORs) + baseline
# ---------------------------------------------------------------------------

def load_examples():
    """Officiële voorbeeldberichten + afgeleide testberichten (zie maak_testberichten.py)."""
    examples, skipped = [], []
    for group, folder in (("Voorbeeldberichten", EXAMPLES_DIR), ("Testberichten", TESTBERICHTEN_DIR)):
        for path in sorted(folder.glob("*.xml")):
            tree = etree.parse(str(path))
            regime = read_regime(tree)
            if regime in XSLT_PER_REGIME:
                examples.append(Example(path, regime, tree, group))
            else:
                skipped.append(Result(group, path.name, "OVERGESLAGEN",
                                      f"onbekend of geen qualityRegime: {regime!r}"))
    return examples, skipped


def known_errors_match(errors, known):
    """Komen de ERRORs precies overeen met de bekende afwijkingen (elk patroon precies één keer)?"""
    remaining = list(errors)
    for pattern in known:
        hit = next((r for r in remaining if pattern.get("title_contains", "") in r.title
                    and pattern.get("message_contains", "") in r.message), None)
        if hit is None:
            return False
        remaining.remove(hit)
    return not remaining


def test_examples(transformer, examples, originals, known):
    results = []
    for ex in examples:
        label = f"{ex.regime} → {XSLT_PER_REGIME[ex.regime]}"
        records = originals[ex.name]
        errors = [r for r in records if r.type == "ERROR"]
        others = len(records) - len(errors)
        if not errors:
            results.append(Result(ex.group, ex.name, "PASS",
                                  f"{label}: 0 ERRORs, {others} overige melding(en)", records=records))
        elif ex.name in known and known_errors_match(errors, known[ex.name].get("errors", [])):
            results.append(Result(ex.group, ex.name, "BEKEND",
                                  f"{label}: {len(errors)} bekende ERROR(s) – {known[ex.name].get('reden', '')}",
                                  records=records))
        else:
            results.append(Result(ex.group, ex.name, "FAIL",
                                  f"{label}: {len(errors)} ERROR(s), verwacht 0",
                                  [str(e) for e in errors], records=records))
    return results


def baseline_path(ex):
    return BASELINE_DIR / f"{ex.path.stem}.xml"


def read_baseline(path):
    root = etree.parse(str(path)).getroot()
    return [(norm(r.findtext("Type")), norm(r.findtext("Title")), norm(r.findtext("Message")))
            for r in root.iter("LogRecord")]


def write_baseline(ex, records):
    root = etree.Element("Baseline", bericht=ex.name, regime=ex.regime, xslt=XSLT_PER_REGIME[ex.regime])
    for r in records:
        el = etree.SubElement(root, "LogRecord")
        for tag, value in zip(("Type", "Title", "Message"), r.key):
            etree.SubElement(el, tag).text = value
    BASELINE_DIR.mkdir(exist_ok=True)
    etree.ElementTree(root).write(str(baseline_path(ex)), encoding="utf-8", xml_declaration=True,
                                  pretty_print=True)


def test_baseline(examples, originals, update):
    results = []
    for ex in examples:
        records = originals[ex.name]
        path = baseline_path(ex)
        actual = [r.key for r in records]
        if not path.exists() or update:
            old = read_baseline(path) if path.exists() else []
            extra, missing = record_diff(old, actual)
            write_baseline(ex, records)
            what = "aangemaakt" if not old and not path.exists() else "bijgewerkt"
            details = [f"+ {fmt_key(k)}" for k in extra] + [f"- {fmt_key(k)}" for k in missing]
            results.append(Result("Baseline", ex.name, "PASS",
                                  f"baseline {what} ({len(actual)} meldingen, {len(extra)} erbij, {len(missing)} weg)",
                                  details))
            continue
        extra, missing = record_diff(read_baseline(path), actual)
        if not extra and not missing:
            results.append(Result("Baseline", ex.name, "PASS", f"gelijk aan baseline ({len(actual)} meldingen)"))
        else:
            details = [f"+ erbij: {fmt_key(k)}" for k in extra] + [f"- weg:   {fmt_key(k)}" for k in missing]
            results.append(Result("Baseline", ex.name, "FAIL",
                                  f"{len(extra)} melding(en) erbij, {len(missing)} weg t.o.v. baseline", details))
    return results


# ---------------------------------------------------------------------------
# Test: controlelijst (welke controles staan er in de XSLT, met welke parameters)
# ---------------------------------------------------------------------------

def checklist_path(regime):
    return BASELINE_DIR / f"controlelijst {XSLT_PER_REGIME[regime].replace('.xslt', '')}.json"


def checklist(sites):
    """{controle-id: aanroep} – zonder regelnummers, zodat verschuivende regels geen verschil geven."""
    return {site.id: " ".join(site.select.split()) for site in sites}


def test_checklist(transformer, update):
    results = []
    for regime, sites in transformer.sites.items():
        name = f"{XSLT_PER_REGIME[regime]}"
        path = checklist_path(regime)
        current = checklist(sites)
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        # Vergelijk de aanroepen zelf (als multiset), niet de id's: een nieuwe losse melding
        # verschuift anders de volgnummers (#2, #3, ...) van alle volgende.
        removed = list((Counter(old.values() if old else []) - Counter(current.values())).elements())
        added = list((Counter(current.values()) - Counter(old.values() if old else [])).elements())
        if old is None or update:
            BASELINE_DIR.mkdir(exist_ok=True)
            path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(Result("Controlelijst", name, "PASS",
                                  f"controlelijst {'aangemaakt' if old is None else 'bijgewerkt'} "
                                  f"({len(current)} controles"
                                  + ("" if old is None else f", {len(removed)} weg, {len(added)} nieuw") + ")",
                                  [f"- weg:   {c}" for c in removed] + [f"+ nieuw: {c}" for c in added]))
            continue
        if not (removed or added):
            results.append(Result("Controlelijst", name, "PASS", f"{len(current)} controles, ongewijzigd"))
            continue
        details = [f"- weg:   {c}" for c in removed] + [f"+ nieuw: {c}" for c in added]
        details.append("Een gewijzigde controle staat als '- weg' + '+ nieuw'. "
                       "Is dit bewust? Draai dan: python run_tests.py --update-baseline")
        results.append(Result("Controlelijst", name, "FAIL",
                              f"{len(removed)} weg, {len(added)} nieuw t.o.v. baseline", details))
    return results


# ---------------------------------------------------------------------------
# Test: automatisch gegenereerde controles
# ---------------------------------------------------------------------------

def elements(tree):
    """Alle elementen in documentvolgorde (zelfde telling als de verkenningsrun in de XSLT)."""
    return list(tree.iter(etree.Element))


def match_to_xpath(match):
    return match if match.startswith("/") else "//" + match


def field_children(node, name):
    return [c for c in node if isinstance(c.tag, str) and etree.QName(c).localname == name]


def mutated_lookup_value(value, mode):
    """onbekende_code: zelfde tabel, niet-bestaand id. verkeerde_tabel: zelfde id, andere tabelnaam."""
    if ":id:" not in value:
        return None
    prefix, identifier = value.rsplit(":id:", 1)
    if mode == "verkeerde_tabel":
        return prefix.rsplit(":", 1)[0] + ":TestsuiteOnbekendeTabel:id:" + identifier
    return prefix + ":id:999999"


GML = "http://www.opengis.net/gml/3.2"
SAM = "http://www.opengis.net/sampling/2.0"


def is_leaf(el):
    return len(el) == 0


def plan_mutation(site, node, lookup_mode="onbekende_code"):
    """Geeft (omschrijving, functie die de mutatie uitvoert) of None als dit element niet geschikt is.

    De functie krijgt het overeenkomstige element in een kopie van het bericht en past dat aan zodat
    precies deze controle hoort af te gaan.
    """
    fn, field = site.function, site.field

    if fn == "checkCoordinates":
        if not node.xpath(".//*[local-name()='pos' or local-name()='posList']"):
            return None
        def apply(n):
            pos = n.xpath(".//*[local-name()='pos' or local-name()='posList']")[0]
            values = (pos.text or "").split()
            pos.text = " ".join(["-1"] + values[1:])
        return "eerste coördinaat op -1 gezet (buiten Nederland)", apply

    if fn in ("checkGeometryElement", "checkGeometryElements"):
        geometry = field_children(node, "geometry")
        if not geometry or not len(geometry[0]):
            return None
        def apply(n):
            field_children(n, "geometry")[0][0].tag = f"{{{GML}}}TestsuiteOnbekendeGeometrie"
        return "geometrie-element hernoemd naar gml:TestsuiteOnbekendeGeometrie", apply

    if fn == "checkSamplingFeatureRelation":
        role = f"urn:immetingen:RelatedSamplingFeatureRollen:id:{literal(site.args[3])}"
        roles = [r for r in node.xpath("sam:relatedSamplingFeature/sam:SamplingFeatureComplex/sam:role",
                                       namespaces=NAMESPACES) if r.get(XLINK_HREF) == role]
        if not roles:
            return None
        def apply(n):
            for r in n.xpath("sam:relatedSamplingFeature/sam:SamplingFeatureComplex/sam:role", namespaces=NAMESPACES):
                if r.get(XLINK_HREF) == role:
                    r.set(XLINK_HREF, "urn:immetingen:RelatedSamplingFeatureRollen:id:999")
        return f"rol {role} gewijzigd naar id:999", apply

    children = field_children(node, field) if field else []
    if not children:
        return None
    first = children[0]

    if fn == "checkExistence":
        def apply(n):
            for c in field_children(n, field):
                n.remove(c)
        return f"element {field} verwijderd", apply

    if fn == "checkFilled":
        if not norm("".join(first.itertext())):
            return None
        def apply(n):
            c = field_children(n, field)[0]
            for child in list(c):
                c.remove(child)
            c.text = ""
        return f"element {field} leeggemaakt", apply

    if fn in ("checkLength", "checkExactLength"):
        size = literal(site.args[3]) if len(site.args) > 3 else None
        if size is None or not is_leaf(first):
            return None
        value = "X" * (int(size) + 1)
        def apply(n):
            field_children(n, field)[0].text = value
        return f"{field} op {len(value)} tekens gezet (grens {size})", apply

    if fn in ("checkDateBeforeDate", "checkDateAfterDate"):
        if not is_leaf(first) or not norm(first.text):
            return None
        date = literal(site.args[3])
        if fn == "checkDateBeforeDate" and date == "current":
            value = "2999-01-01"
        elif fn == "checkDateAfterDate" and date and date.startswith("1980"):
            value = "1970-01-01"
        else:
            return None
        def apply(n):
            field_children(n, field)[0].text = value
        return f"{field} op {value} gezet", apply

    if fn == "checkLookupId":
        # Zelfde volgorde als sikb:checkLookupId: xlink:href, dan @uom, dan de tekst
        if first.get(XLINK_HREF):
            where, value = "xlink:href", first.get(XLINK_HREF)
        elif first.get("uom"):
            where, value = "uom", first.get("uom")
        else:
            where, value = "tekst", norm(first.text)
        new_value = mutated_lookup_value(value, lookup_mode)
        if not new_value:
            return None
        def apply(n):
            c = field_children(n, field)[0]
            if where == "xlink:href":
                c.set(XLINK_HREF, new_value)
            elif where == "uom":
                c.set("uom", new_value)
            else:
                c.text = new_value
        return f"{field} ({where}) gezet op {new_value}", apply

    return None


def expected_type(site):
    # checkLookupId geeft bij een onbekende code altijd ERROR, ongeacht de errorType-parameter
    return "ERROR" if site.function == "checkLookupId" else site.error_type


def is_generic(site):
    needs_field = site.function not in ("checkCoordinates",)
    return (site.function in GENERIC and site.args and site.args[0] == "." and not site.in_for_each
            and (site.field is not None or not needs_field))


def find_override(overrides, site):
    for o in overrides:
        if o["check"] in (site.id, site.base_id) and o.get("regime", site.regime) == site.regime:
            return o
    return None


def test_generated(transformer, examples, originals, overrides, keyword):
    results = []
    # Kleinste berichten eerst: sneller en overzichtelijker
    by_regime = defaultdict(list)
    for ex in sorted(examples, key=lambda e: e.path.stat().st_size):
        by_regime[ex.regime].append(ex)

    reach_results = transformer.run_many([("reach", ex.regime, ex.tree) for ex in examples])
    reach = {ex.name: r for ex, r in zip(examples, reach_results)}
    element_lists = {ex.name: elements(ex.tree) for ex in examples}
    state, order = {}, []

    def candidates(key, site, override):
        """Levert (bericht, element, (omschrijving, mutatie)) op, in volgorde van voorkeur."""
        pool = by_regime[site.regime]
        if override and override.get("source"):
            pool = [ex for ex in pool if ex.name == override["source"]]
        for ex in pool:
            all_elements = element_lists[ex.name]
            if override and override.get("context_xpath"):
                nodes = ex.tree.xpath(override["context_xpath"], namespaces=NAMESPACES)
            else:
                nodes = [all_elements[i] for i in reach[ex.name].get(str(site.line), [])]
            if nodes:
                state[key]["reached"] = True
            for node in nodes:
                plan = plan_mutation(site, node, (override or {}).get("lookup_mutatie", "onbekende_code"))
                if plan:
                    yield ex, node, plan

    for regime, sites in transformer.sites.items():
        for site in sites:
            if not is_generic(site):
                continue
            name = f"{regime} · {site.id}"
            if keyword and keyword.lower() not in name.lower():
                continue
            override = find_override(overrides, site)
            key = regime + "|" + site.id
            order.append(key)
            state[key] = {"site": site, "name": name, "details": [f"XSLT regel {site.line}: {site.short()}"],
                          "tried": [], "passed": None, "reached": False,
                          "skip": override.get("skip") if override else None}
            if not state[key]["skip"]:
                state[key]["iter"] = candidates(key, site, override)

    # In rondes: elke controle probeert per ronde één kandidaat; alle mutaties van een ronde lopen parallel
    pending = [k for k in order if not state[k]["skip"]]
    while pending:
        jobs, meta = [], []
        for key in pending:
            nxt = next(state[key]["iter"], None)
            if nxt is None:
                continue
            ex, node, (description, apply) = nxt
            tree = copy.deepcopy(ex.tree)
            apply(elements(tree)[element_lists[ex.name].index(node)])
            jobs.append(("run", ex.regime, tree))
            meta.append((key, ex, f"{ex.name}: {ex.tree.getpath(node)} – {description}"))
        if not jobs:
            break
        pending = []
        for (key, ex, where), records in zip(meta, transformer.run_many(jobs)):
            st, site = state[key], state[key]["site"]
            added = new_records(originals[ex.name], records)
            hits = [r for r in added if r.site == str(site.line)
                    and (expected_type(site) is None or r.type == expected_type(site))]
            if hits:
                st["passed"] = (where, hits[0], added)
            else:
                st["tried"].append((where, added))
                if len(st["tried"]) < MAX_CANDIDATES:
                    pending.append(key)

    for key in order:
        st, site = state[key], state[key]["site"]
        name, details, tried = st["name"], st["details"], st["tried"]
        if st["skip"]:
            results.append(Result("Automatische controles", name, "OVERGESLAGEN", f"override: {st['skip']}", details))
        elif st["passed"]:
            where, hit, added = st["passed"]
            results.append(Result("Automatische controles", name, "PASS", str(hit),
                                  details + [f"Mutatie: {where}"], added, "Meldingen die door de mutatie bijkwamen"))
        elif not tried:
            reason = (f"wel bereikt, maar geen {site.template} met een geschikt {site.field}" if st["reached"]
                      else f"deze controle wordt in geen enkel {site.regime}-bericht bereikt")
            results.append(Result("Automatische controles", name, "NIET TESTBAAR", reason, details))
        else:
            details += [f"Geprobeerd: {w} → {len(a)} nieuwe melding(en), geen van regel {site.line}"
                        for w, a in tried]
            results.append(Result("Automatische controles", name, "FAIL",
                                  f"verwacht {expected_type(site) or 'een melding'} van regel {site.line}, "
                                  f"niet gekregen", details, tried[-1][1], "Meldingen die door de laatste mutatie bijkwamen"))
    return results


# ---------------------------------------------------------------------------
# Test: handgeschreven cases
# ---------------------------------------------------------------------------

def apply_mutations(tree, mutations):
    for m in mutations:
        nodes = tree.xpath(m["xpath"], namespaces=NAMESPACES)
        if not nodes:
            raise ValueError(f"XPath vond geen element: {m['xpath']}")
        if m.get("first_only"):
            nodes = nodes[:1]
        for node in nodes:
            action = m["action"]
            if action == "remove":
                node.getparent().remove(node)
            elif action == "set":
                node.text = m["value"]
            elif action == "set_attribute":
                name = m["name"]
                if ":" in name:
                    prefix, local = name.split(":", 1)
                    name = f"{{{NAMESPACES[prefix]}}}{local}"
                node.set(name, m["value"])
            elif action == "duplicate":
                node.addnext(copy.deepcopy(node))
            elif action == "insert_xml":
                ns = " ".join(f'xmlns:{p}="{u}"' for p, u in NAMESPACES.items())
                wrapper = etree.fromstring(f"<wrap {ns}>{m['xml']}</wrap>")
                for child in reversed(list(wrapper)):
                    node.addnext(child) if m.get("position") == "after" else node.append(child)
            else:
                raise ValueError(f"Onbekende actie: {action}")


def matches(record, expect):
    return (record.type == expect["type"]
            and expect.get("title_contains", "") in record.title
            and expect.get("message_contains", "") in record.message)


def describe_expect(expect):
    parts = [f"Type = {expect['type']}"]
    if expect.get("title_contains"):
        parts.append(f"Title bevat '{expect['title_contains']}'")
    if expect.get("message_contains"):
        parts.append(f"Message bevat '{expect['message_contains']}'")
    return ", ".join(parts)


def substitute(value):
    """Vervangt ${NAAM} door de waarde uit versie.json (variabelen)."""
    if isinstance(value, str):
        for name, replacement in VERSION_VARS.items():
            value = value.replace("${" + name + "}", replacement)
        return value
    if isinstance(value, list):
        return [substitute(v) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v) for k, v in value.items()}
    return value


def load_cases():
    """Gedeelde cases.json; cases met 'versies' gelden alleen voor die versie-mappen."""
    cases = json.loads((SUITE_DIR / "cases.json").read_text(encoding="utf-8"))["cases"]
    return [substitute(c) for c in cases if "versies" not in c or SAD_DIR.name in c["versies"]]


def expand_cases(cases):
    """Een case met 'sources' (lijst) wordt per bronbericht één test."""
    for case in cases:
        for source in case.get("sources", [case.get("source")]):
            yield case, source


def test_cases(transformer, examples, originals, keyword):
    by_name = {ex.name: ex for ex in examples}
    results, prepared = [], []
    for case, source in expand_cases(load_cases()):
        name = case["name"]
        ex = by_name.get(source)
        if len(case.get("sources", [])) > 1:
            name += f"  [{ex.regime if ex else source}]"
        if keyword and keyword.lower() not in name.lower():
            continue
        if ex is None:
            results.append(Result("Testcases", name, "FAIL", f"bronbericht niet gevonden: {source}"))
            continue
        expects = case["expect"] if isinstance(case["expect"], list) else [case["expect"]]
        details = [f"Bronbericht: {ex.name} ({ex.regime} → {XSLT_PER_REGIME[ex.regime]})"]
        details += [f"Mutatie: {m['action']} {m['xpath']}" + (f" = '{m['value']}'" if "value" in m else "")
                    for m in case["mutations"]]
        details += [f"Verwacht (nieuwe melding): {describe_expect(e)}" for e in expects]
        if case.get("waarom"):
            details.insert(0, case["waarom"])
        unresolved = sorted(set(re.findall(r"\$\{(\w+)\}", json.dumps(case))))
        if unresolved:
            results.append(Result("Testcases", name, "FAIL",
                                  f"variabele(n) {', '.join(unresolved)} ontbreken in {TESTS_DIR / 'versie.json'}",
                                  details))
            continue
        try:
            tree = copy.deepcopy(ex.tree)
            apply_mutations(tree, case["mutations"])
        except Exception as e:
            results.append(Result("Testcases", name, "FAIL", str(e), details))
            continue
        prepared.append((case, name, ex, expects, details, tree))

    outputs = transformer.run_many([("run", ex.regime, tree) for _, _, ex, _, _, tree in prepared])
    for (case, name, ex, expects, details, _), records in zip(prepared, outputs):
        added = new_records(originals[ex.name], records)
        missing = [e for e in expects if not any(matches(r, e) for r in added)]
        forbidden = [r for f in case.get("not_expect", []) for r in added if matches(r, f)]
        if missing or forbidden:
            problems = [f"niet gevonden: {describe_expect(e)}" for e in missing]
            problems += [f"had niet mogen verschijnen: {r}" for r in forbidden]
            results.append(Result("Testcases", name, "FAIL", "; ".join(problems), details, added,
                                  "Meldingen die door de mutatie bijkwamen"))
        else:
            summary = (str(next(r for r in added if matches(r, expects[0]))) if expects
                       else "geen verboden meldingen verschenen")
            results.append(Result("Testcases", name, "PASS", summary, details, added,
                                  "Meldingen die door de mutatie bijkwamen"))
    return results


# ---------------------------------------------------------------------------
# Dekking
# ---------------------------------------------------------------------------

def coverage(transformer, unreachable):
    """Per regime: (geraakt, totaal, niet-geraakte sites, uitgesloten sites met reden).

    Controles uit onbereikbaar.json tellen niet mee in het totaal, tenzij ze toch geraakt zijn."""
    reasons = {u["check"]: u["reden"] for u in unreachable}
    report = {}
    for regime, sites in transformer.sites.items():
        hit = transformer.hit[regime]
        excluded = [(s, reasons.get(s.id) or reasons.get(s.base_id)) for s in sites
                    if str(s.line) not in hit and (s.id in reasons or s.base_id in reasons)]
        excluded_sites = {id(s) for s, _ in excluded}
        counted = [s for s in sites if id(s) not in excluded_sites]
        uncovered = [s for s in counted if str(s.line) not in hit]
        report[regime] = (len(counted) - len(uncovered), len(counted), uncovered, excluded)
    return report


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------

def write_report(results, cover, xslt_dir, duration, transforms):
    REPORT_FILE.parent.mkdir(exist_ok=True)
    counts = Counter(r.status for r in results)
    esc = html.escape
    parts = []

    cover_html = []
    for regime, (covered, total, uncovered, excluded) in cover.items():
        pct = 100 * covered / total if total else 0
        rows = "".join(f"<tr><td>{s.line}</td><td>{esc(s.template)}</td><td><code>{esc(s.short())}</code></td></tr>"
                       for s in uncovered)
        excl_rows = "".join(f"<tr><td>{s.line}</td><td><code>{esc(s.short())}</code></td><td>{esc(reason)}</td></tr>"
                            for s, reason in excluded)
        cover_html.append(
            f"<div class='cov'><div class='covhead'><b>{esc(XSLT_PER_REGIME[regime])}</b>"
            f"<span>{covered} / {total} controles geraakt ({pct:.0f}%)</span></div>"
            f"<div class='bar'><div style='width:{pct:.1f}%'></div></div>"
            f"<details><summary>{len(uncovered)} niet-geraakte controles</summary>"
            f"<table><tr><th>Regel</th><th>Template</th><th>Aanroep</th></tr>{rows}</table></details>"
            f"<details><summary>{len(excluded)} uitgesloten als onbereikbaar (onbereikbaar.json)</summary>"
            f"<table><tr><th>Regel</th><th>Aanroep</th><th>Reden</th></tr>{excl_rows}</table></details></div>")
    parts.append("<h2>Dekking</h2><p class='muted'>Een controle telt als geraakt als hij in minstens één test "
                 "een melding gaf (voorbeeldberichten, automatische controles of testcases).</p>" + "".join(cover_html))

    for group in dict.fromkeys(r.group for r in results):
        items = [r for r in results if r.group == group]
        gc = Counter(r.status for r in items)
        tally = " · ".join(f"{gc[s]} {s.lower()}" for s in STATUSES if gc[s])
        parts.append(f"<h2>{esc(group)} <span class='muted small'>{tally}</span></h2>")
        for r in items:
            detail = "".join(f"<li>{esc(d)}</li>" for d in r.details)
            recs = "".join(f"<tr class='t-{esc(x.type.lower())}'><td>{esc(x.type)}</td><td>{esc(x.title)}</td>"
                           f"<td>{esc(x.message)}</td></tr>" for x in r.records)
            recs_html = (f"<p>{esc(r.records_label)} ({len(r.records)}):</p><table><tr><th>Type</th><th>Title</th>"
                         f"<th>Message</th></tr>{recs}</table>") if recs else ""
            cls = r.status.lower().replace(" ", "-")
            parts.append(
                f"<details class='test {cls}'{' open' if r.status == 'FAIL' else ''}>"
                f"<summary><span class='badge'>{esc(r.status)}</span> <b>{esc(r.name)}</b>"
                f"<span class='muted'> {esc(r.summary)}</span></summary>"
                f"<ul>{detail}</ul>{recs_html}</details>")

    stats = "".join(f"<div class='stat {s.lower().replace(' ', '-')}'><b>{counts[s]}</b>{s.lower()}</div>"
                    for s in STATUSES)
    page = f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SAD XSLT-tests {esc(SAD_DIR.name)}</title>
<style>
:root {{ --bg:#fff; --fg:#1d1d1f; --muted:#6b6b70; --line:#e2e2e6; --pass:#1a7f37; --fail:#cf222e; --known:#8250df; --skip:#9a6700; --card:#f6f6f8; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#16161a; --fg:#ececf0; --muted:#9a9aa2; --line:#2e2e35; --pass:#3fb950; --fail:#f85149; --known:#a371f7; --skip:#d29922; --card:#1f1f25; }} }}
body {{ background:var(--bg); color:var(--fg); font:14px/1.5 system-ui, sans-serif; max-width:1150px; margin:0 auto; padding:24px 16px; }}
h1 {{ margin:0 0 4px; }} h2 {{ margin-top:32px; border-bottom:1px solid var(--line); padding-bottom:4px; }}
.muted {{ color:var(--muted); }} .small {{ font-size:13px; font-weight:400; }}
.stats {{ display:flex; gap:12px; margin:16px 0; flex-wrap:wrap; }}
.stat {{ background:var(--card); border-radius:8px; padding:10px 16px; min-width:100px; }}
.stat b {{ font-size:22px; display:block; }}
.pass .badge, .stat.pass b {{ color:var(--pass); }} .fail .badge, .stat.fail b {{ color:var(--fail); }}
.bekend .badge, .stat.bekend b {{ color:var(--known); }}
.niet-testbaar .badge, .overgeslagen .badge, .stat.niet-testbaar b, .stat.overgeslagen b {{ color:var(--skip); }}
.badge {{ font-weight:700; font-family:ui-monospace, monospace; display:inline-block; min-width:4.5em; font-size:12px; }}
details.test {{ border:1px solid var(--line); border-radius:8px; padding:6px 12px; margin:6px 0; }}
details.fail {{ border-color:var(--fail); }}
summary {{ cursor:pointer; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; display:block; overflow-x:auto; }}
td, th {{ border-bottom:1px solid var(--line); padding:4px 8px; text-align:left; vertical-align:top; }}
code {{ font-size:12px; }}
.t-error td:first-child {{ color:var(--fail); font-weight:600; }}
.cov {{ background:var(--card); border-radius:8px; padding:12px 16px; margin:10px 0; }}
.covhead {{ display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; }}
.bar {{ height:8px; background:var(--line); border-radius:4px; margin:8px 0; overflow:hidden; }}
.bar div {{ height:100%; background:var(--pass); }}
label {{ user-select:none; }}
body.only-fail details.test:not(.fail) {{ display:none; }}
</style></head><body>
<h1>SAD XSLT-tests <span class="muted">· {esc(SAD_DIR.name)}</span></h1>
<div class="muted">{datetime.now():%d-%m-%Y %H:%M} · {duration:.0f} s · {transforms} transformaties · XSLT-map: {esc(str(xslt_dir))}</div>
<div class="stats">{stats}</div>
<label><input type="checkbox" onchange="document.body.classList.toggle('only-fail', this.checked)"> Alleen gefaalde tests tonen</label>
{''.join(parts)}
</body></html>"""
    REPORT_FILE.write_text(page, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

COLORS = {"PASS": "\033[32m", "FAIL": "\033[31m", "BEKEND": "\033[35m", "NIET TESTBAAR": "\033[33m",
          "OVERGESLAGEN": "\033[33m"}
QUIET_GROUPS = {"Automatische controles", "XSD-validatie", "Baseline", "Controlelijst"}


def print_results(results):
    for group in dict.fromkeys(r.group for r in results):
        items = [r for r in results if r.group == group]
        tally = Counter(r.status for r in items)
        print(f"\n{group}  ({', '.join(f'{tally[s]} {s.lower()}' for s in STATUSES if tally[s])})")
        for r in items:
            if group in QUIET_GROUPS and r.status in ("PASS", "NIET TESTBAAR", "OVERGESLAGEN"):
                continue
            print(f"  {COLORS[r.status]}{r.status:<6}\033[0m {r.name}  - {r.summary}")
            if r.status == "FAIL":
                for d in r.details[:12]:
                    print(f"           {d}")


def run_version(args, sad_dir):
    configure(sad_dir)
    xslt_dir = args.xslt_dir.resolve() if args.xslt_dir else DEFAULT_XSLT_DIR
    known = load_json("bekende_afwijkingen.json", {})
    overrides = load_json("overrides.json", {"overrides": []})["overrides"]
    start = time.time()
    print(f"\n{'=' * 78}\n{SAD_DIR.name}\n{'=' * 78}")

    workers = args.workers or max(1, min((os.cpu_count() or 2) - 1, 16))
    with PySaxonProcessor(license=False) as proc, \
            ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(str(xslt_dir),)) as pool:
        transformer = Transformer(Engine(proc, xslt_dir), pool if workers > 1 else None)
        examples, results = load_examples()
        examples = [ex for ex in examples if ex.regime not in transformer.errors]
        outputs = transformer.run_many([("run", ex.regime, ex.tree) for ex in examples])
        originals = {ex.name: records for ex, records in zip(examples, outputs)}

        results = test_xslts(transformer, xslt_dir, examples, originals) + results
        results += test_xsd(known.get("xsd", {}))
        results += test_examples(transformer, examples, originals, known.get("voorbeeldberichten", {}))
        results += test_baseline(examples, originals, args.update_baseline)
        results += test_checklist(transformer, args.update_baseline)
        if args.keyword:
            results = [r for r in results if args.keyword.lower() in r.name.lower()]
        if not args.snel:
            results += test_generated(transformer, examples, originals, overrides, args.keyword)
        results += test_cases(transformer, examples, originals, args.keyword)
        cover = coverage(transformer, load_json("onbereikbaar.json", {"onbereikbaar": []})["onbereikbaar"])
        transforms = transformer.count

    duration = time.time() - start
    print_results(results)
    partial = bool(args.keyword or args.snel)
    print("\nDekking (controles die minstens één keer een melding gaven)"
          + ("  – gedeeltelijke run, niet representatief" if partial else ""))
    for regime, (covered, total, uncovered, excluded) in cover.items():
        print(f"  {XSLT_PER_REGIME[regime]:<24} {covered:>3} / {total}  ({100 * covered / total:.0f}%)"
              f"   + {len(excluded)} onbereikbaar uitgesloten")
        for site in [] if partial else uncovered:
            print(f"      niet geraakt: regel {site.line}  {site.short()[:90]}")

    write_report(results, cover, xslt_dir, duration, transforms)
    tally = Counter(r.status for r in results)
    print("\n" + ", ".join(f"{tally[s]} {s.lower()}" for s in STATUSES) + f"  ({duration:.0f} s)")
    print(f"Rapport: {REPORT_FILE}")
    return tally


def main():
    parser = argparse.ArgumentParser(description="Regressietests voor de SAD controle-XSLT's")
    parser.add_argument("--versie", action="append",
                        help="naam of pad van een versie-map (mag vaker); standaard alle versies")
    parser.add_argument("-k", dest="keyword", help="alleen tests met deze tekst in de naam")
    parser.add_argument("--xslt-dir", type=Path, help="map met de te testen XSLT's (alleen samen met één --versie)")
    parser.add_argument("--update-baseline", action="store_true", help="huidige uitvoer vastleggen als baseline")
    parser.add_argument("--snel", action="store_true", help="automatische controles overslaan")
    parser.add_argument("--workers", type=int, help="aantal parallelle processen (standaard: aantal cores - 1, max 16)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if os.name == "nt":
        os.system("")  # zet kleurcodes (ANSI) aan in een Windows-consolevenster, bijv. bij dubbelklikken op een .bat

    if args.versie:
        versions = [ROOT_DIR / v if (ROOT_DIR / v).is_dir() else Path(v).resolve() for v in args.versie]
        missing = [str(v) for v in versions if not (v / "Controle XSLT").is_dir()]
        if missing:
            parser.error("geen versie-map (met 'Controle XSLT'): " + ", ".join(missing))
        unconfigured = [v.name for v in versions if not (VERSIONS_DIR / v.name).is_dir()]
        if unconfigured:
            parser.error("geen testconfiguratie in versies/ voor: " + ", ".join(unconfigured)
                         + ' (maak die met: python nieuwe_versie.py "<naam>" --van "<bestaande versie>")')
    else:
        versions = version_dirs()
        for d in delivered_dirs():
            if d not in versions:
                print(f"Let op: '{d.name}' heeft nog geen testconfiguratie in versies/ en wordt overgeslagen.\n"
                      f'        Maak die met: python nieuwe_versie.py "{d.name}" --van "<bestaande versie>"')
        for d in sorted(VERSIONS_DIR.iterdir()) if VERSIONS_DIR.is_dir() else []:
            if d.is_dir() and not (ROOT_DIR / d.name / "Controle XSLT").is_dir():
                print(f"Let op: testconfiguratie versies/{d.name} hoort bij geen geleverde map en wordt overgeslagen.")
    if args.xslt_dir and len(versions) != 1:
        parser.error("--xslt-dir kan alleen samen met precies één --versie")

    totals = {v.resolve().name: run_version(args, v) for v in versions}
    if len(totals) > 1:
        print(f"\n{'=' * 78}\nOverzicht")
        for name, tally in totals.items():
            status = "FAIL" if tally["FAIL"] else "OK  "
            print(f"  {COLORS['FAIL' if tally['FAIL'] else 'PASS']}{status}\033[0m {name:<34} "
                  + ", ".join(f"{tally[s]} {s.lower()}" for s in STATUSES if tally[s]))
    return 1 if any(t["FAIL"] for t in totals.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
