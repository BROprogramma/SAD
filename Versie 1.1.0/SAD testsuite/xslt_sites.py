"""Analyse en instrumentatie van de controle-XSLT's.

Elke `<xsl:copy-of select="sikb:...(...)"/>` binnen een template is een *controle-aanroep* (site).
Voor de tests maken we in het geheugen een kopie van de XSLT waarin elke site zijn regelnummer
als attribuut `site` op de LogRecords zet. Zo weten we welke controle een melding gaf (dekking),
zonder dat de meldingen zelf veranderen. Het originele XSLT-bestand wordt niet aangepast.
"""
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

XSL = "http://www.w3.org/1999/XSL/Transform"
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
CALL = re.compile(r"\s*sikb:(\w+)\((.*)\)\s*$", re.S)

# Generieke check-functies waarvoor automatisch een fout bericht gemaakt kan worden
GENERIC = ("checkExistence", "checkFilled", "checkLookupId", "checkLength", "checkExactLength",
           "checkDateBeforeDate", "checkDateAfterDate", "checkGeometryElement", "checkGeometryElements",
           "checkCoordinates", "checkSamplingFeatureRelation")

MARK_FUNCTION = f"""
<xsl:param xmlns:xsl="{XSL}" xmlns:sikb="http://xslcontrole.sikb" name="sikb:testsuiteTrace" select="false()"/>
"""

REACHED_FUNCTION = f"""
<xsl:function xmlns:xsl="{XSL}" xmlns:sikb="http://xslcontrole.sikb" name="sikb:testsuiteReached">
    <xsl:param name="context"/>
    <xsl:param name="site"/>
    <xsl:if test="$context instance of element()">
        <xsl:element name="Reached">
            <xsl:attribute name="site" select="$site"/>
            <xsl:attribute name="index" select="count($context/preceding::*) + count($context/ancestor::*)"/>
        </xsl:element>
    </xsl:if>
</xsl:function>
"""

MARK_FUNCTION_BODY = f"""
<xsl:function xmlns:xsl="{XSL}" xmlns:sikb="http://xslcontrole.sikb" name="sikb:testsuiteMark">
    <xsl:param name="items"/>
    <xsl:param name="site"/>
    <xsl:for-each select="$items">
        <xsl:choose>
            <xsl:when test=". instance of element(LogRecord)">
                <xsl:element name="LogRecord">
                    <xsl:attribute name="site" select="if (@site) then @site else $site"/>
                    <xsl:copy-of select="node()"/>
                </xsl:element>
            </xsl:when>
            <xsl:when test=". instance of document-node()">
                <xsl:copy-of select="sikb:testsuiteMark(node(), $site)"/>
            </xsl:when>
            <xsl:otherwise>
                <xsl:copy-of select="."/>
            </xsl:otherwise>
        </xsl:choose>
    </xsl:for-each>
</xsl:function>
"""


def split_args(text):
    """Splitst 'a, f(b, c), 'd,e'' op komma's op het hoogste niveau."""
    args, depth, quote, current = [], 0, None, ""
    for ch in text:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(current.strip())
            current = ""
            continue
        current += ch
    if current.strip():
        args.append(current.strip())
    return args


def literal(arg):
    """'tekst' -> tekst; getal -> getal; anders None (variabele/expressie)."""
    if arg and len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in "'\"":
        return arg[1:-1]
    if arg and re.fullmatch(r"\d+", arg):
        return arg
    return None


@dataclass
class Site:
    regime: str
    line: int
    function: str
    args: list
    template: str
    in_for_each: bool
    select: str
    id: str = ""

    @property
    def field(self):
        return literal(self.args[2]) if len(self.args) > 2 else None

    @property
    def error_type(self):
        return literal(self.args[-1]) if self.args else None

    @property
    def base_id(self):
        field = self.field or "-"
        return f"{self.template}|{self.function}|{field}"

    def short(self):
        return " ".join(self.select.split())[:160]


def instrument(xslt_path, regime):
    """Geeft (geïnstrumenteerde XSLT-tekst, lijst met sites)."""
    xslt_path = Path(xslt_path)
    tree = etree.parse(str(xslt_path))
    root = tree.getroot()
    sites = []
    for el in root.iter(f"{{{XSL}}}copy-of"):
        match = CALL.match(el.get("select", ""))
        if not match:
            continue
        owner = next(a for a in el.iterancestors() if a.tag in (f"{{{XSL}}}template", f"{{{XSL}}}function"))
        if owner.tag != f"{{{XSL}}}template":
            continue
        in_for_each = False
        for a in el.iterancestors():
            if a is owner:
                break
            in_for_each |= a.tag == f"{{{XSL}}}for-each"
        site = Site(regime, el.sourceline, match.group(1), split_args(match.group(2)),
                    owner.get("match", owner.get("name", "?")), in_for_each, el.get("select"))
        sites.append(site)
        # Met de parameter testsuiteTrace=true() meldt elke site ook welk element hem bereikte
        el.set("select", f"(if ($sikb:testsuiteTrace) then sikb:testsuiteReached(., '{el.sourceline}') else (),"
                         f" sikb:testsuiteMark(({el.get('select')}), '{el.sourceline}'))")

    seen = Counter()
    for site in sites:
        seen[site.base_id] += 1
        site.id = site.base_id + (f"#{seen[site.base_id]}" if seen[site.base_id] > 1 else "")

    root.insert(0, etree.fromstring(MARK_FUNCTION))
    root.append(etree.fromstring(MARK_FUNCTION_BODY))
    root.append(etree.fromstring(REACHED_FUNCTION))
    # document('... lookup.xml') moet relatief aan de originele XSLT blijven werken
    root.set(XML_BASE, xslt_path.resolve().as_uri())
    return etree.tostring(tree, encoding="unicode"), sites
