"""Maakt extra testberichten in testberichten/, afgeleid van de officiële voorbeeldberichten.

Sommige delen van de XSLT's worden door geen enkel voorbeeldbericht geraakt (bijv. een Trench in
IMBRO/A of een immetingen:MeasurementObject). Deze afgeleide berichten vullen dat gat, zodat de
automatische controles en de dekking ook die templates meenemen. Elk testbericht moet zelf 'goed'
zijn (0 ERRORs); dat controleert run_tests.py.

Gebruik: python maak_testberichten.py                  alle versies (overschrijft versies/<versie>/testberichten/)
         python maak_testberichten.py "SAD Uitwisselberichten v15.0"   alleen deze versie
"""
import copy
import sys
from pathlib import Path

from lxml import etree

SUITE_DIR = Path(__file__).resolve().parent
# Gezet per versie door main()
EXAMPLES_DIR = OUT_DIR = None

IMSIKB = "http://www.sikb.nl/imsikb0101"
IMMETINGEN = "http://www.sikb.nl/immetingen"
GML = "http://www.opengis.net/gml/3.2"
SAM = "http://www.opengis.net/sampling/2.0"
XLINK = "http://www.w3.org/1999/xlink"
NS = {"imsikb0101": IMSIKB, "immetingen": IMMETINGEN}


def load(name):
    return etree.parse(str(EXAMPLES_DIR / name))


def set_regime(tree, regime):
    tree.xpath("//*[local-name()='qualityRegime']")[0].text = regime


def borehole_to_measurement_object(tree):
    """Hernoemt de eerste Borehole naar immetingen:MeasurementObject; de inhoud blijft gelijk."""
    borehole = tree.xpath("//imsikb0101:Borehole", namespaces=NS)[0]
    borehole.tag = f"{{{IMMETINGEN}}}MeasurementObject"


def remove_samples_with_specimen_type(tree, ids):
    for sample in tree.xpath("//imsikb0101:Sample", namespaces=NS):
        value = "".join(sample.xpath("*[local-name()='specimenType']/@xlink:href",
                                     namespaces={"xlink": "http://www.w3.org/1999/xlink"}))
        if value.rsplit(":id:", 1)[-1] in ids:
            member = sample.getparent()
            member.getparent().remove(member)


def link_sample_to_measurement_object(tree, mo_id, sample_id):
    """Voegt aan een meetpunt een relatie met rol 1 (monster) naar een Sample toe."""
    mo = tree.xpath(f"//*[@gml:id='{mo_id}']", namespaces={"gml": GML})[0]
    complex_xml = (f'<sam:relatedSamplingFeature xmlns:sam="{SAM}" xmlns:xlink="{XLINK}"><sam:SamplingFeatureComplex>'
                   f'<sam:role xlink:href="urn:immetingen:RelatedSamplingFeatureRollen:id:1"/>'
                   f'<sam:relatedSamplingFeature xlink:href="#{sample_id}"/></sam:SamplingFeatureComplex>'
                   f'</sam:relatedSamplingFeature>')
    existing = mo.xpath("sam:relatedSamplingFeature", namespaces={"sam": SAM})
    existing[-1].addnext(etree.fromstring(complex_xml))


def add_soil_location(tree):
    """Voegt een geldige SoilLocation toe (geometrie gekopieerd van het Project)."""
    project_member = tree.xpath("//imsikb0101:featureMember[imsikb0101:Project]", namespaces=NS)[0]
    geometry = copy.deepcopy(tree.xpath("//imsikb0101:Project/imsikb0101:geometry", namespaces=NS)[0])
    for el in geometry.iter():
        if el.get(f"{{{GML}}}id"):
            el.set(f"{{{GML}}}id", "_1" + el.get(f"{{{GML}}}id")[2:])
    uid = "5011d0c1-0000-4000-8000-000000000001"
    member = etree.fromstring(
        f'<imsikb0101:featureMember xmlns:imsikb0101="{IMSIKB}" xmlns:immetingen="{IMMETINGEN}" xmlns:gml="{GML}">'
        f'<imsikb0101:SoilLocation gml:id="_{uid}">'
        f'<imsikb0101:identification><immetingen:NEN3610ID><immetingen:namespace>SIKB</immetingen:namespace>'
        f'<immetingen:lokaalID>{uid}</immetingen:lokaalID></immetingen:NEN3610ID></imsikb0101:identification>'
        f'</imsikb0101:SoilLocation></imsikb0101:featureMember>')
    member[0].insert(0, geometry)
    project_member.addnext(member)


def save(tree, name, description):
    OUT_DIR.mkdir(exist_ok=True)
    root = tree.getroot()
    root.insert(0, etree.Comment(f" TESTBERICHT (gegenereerd door maak_testberichten.py): {description} "))
    tree.write(str(OUT_DIR / name), encoding="UTF-8", xml_declaration=True)
    print(f"  {name}")


def main():
    global EXAMPLES_DIR, OUT_DIR
    names = sys.argv[1:]
    versions = [SUITE_DIR.parent / n for n in names] if names else sorted(
        d for d in SUITE_DIR.parent.iterdir()
        if (d / "Controle XSLT").is_dir() and (SUITE_DIR / "versies" / d.name).is_dir())
    for version in versions:
        EXAMPLES_DIR = version / "XSD en voorbeeld XML" / "Voorbeeldberichten innameservice"
        OUT_DIR = SUITE_DIR / "versies" / version.name / "testberichten"
        make_all()


def make_all():
    for old in OUT_DIR.glob("*.xml"):
        old.unlink()
    print(f"Testberichten in {OUT_DIR}:")

    tree = load("3b. SAD_registrationRequest IMBRO - Asbest.xml")
    set_regime(tree, "IMBRO/A")
    remove_samples_with_specimen_type(tree, {"7", "8"})
    save(tree, "T1. IMBROA met Trench (van 3b).xml",
         "3b omgezet naar IMBRO/A; asbest-monsters (monstertype 7 en 8, niet geldig voor IMBRO/A) verwijderd")

    tree = load("3. SAD_registrationRequest IMBRO.xml")
    borehole_to_measurement_object(tree)
    add_soil_location(tree)
    save(tree, "T2. IMBRO met MeasurementObject en SoilLocation (van 3).xml",
         "eerste Borehole omgezet naar immetingen:MeasurementObject; SoilLocation toegevoegd")

    tree = load("1. SAD_registrationRequest IMBROA.xml")
    borehole_to_measurement_object(tree)
    add_soil_location(tree)
    save(tree, "T3. IMBROA met MeasurementObject en SoilLocation (van 1).xml",
         "eerste Borehole omgezet naar immetingen:MeasurementObject; SoilLocation toegevoegd")

    tree = load("3b. SAD_registrationRequest IMBRO - Asbest.xml")
    set_regime(tree, "IMBRO/A")
    remove_samples_with_specimen_type(tree, {"7", "8"})
    link_sample_to_measurement_object(tree, "_e9d65836-99c6-4d77-a7e5-c25895cd480e",
                                      "_4e97feaa-14bf-41fc-9684-a6c209f90e7d")
    save(tree, "T4. IMBROA met bereikbaar conclusiemonster (van 3b).xml",
         "als T1, plus relatie (rol 1) van Trench naar conclusiemonster, zodat de IMBRO/A-XSLT het conclusiemonster controleert")


if __name__ == "__main__":
    main()
