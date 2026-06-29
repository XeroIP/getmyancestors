"""Markdown narrative writer.

An alternative to the GEDCOM serializer in tree.py. Where Tree.print() emits
pointer-based GEDCOM 5.5.1, this emits human- and LLM-readable Markdown: one
section per person with relationships resolved to names, all facts, notes and
memories inline, plus a "Research frontier" section listing the ancestors at
the edge of the downloaded tree (the people to chase to find more ancestors).

It reads the same Indi/Fam/Tree model objects after a crawl; it triggers no
network I/O of its own.
"""

import re
import sys
import time

# Friendly labels for the most common GedcomX fact-type URIs. Anything not
# listed falls back to the tail of the URI, so unknown facts still render.
FACT_LABELS = {
    "http://gedcomx.org/Birth": "Born",
    "http://gedcomx.org/Christening": "Christened",
    "http://gedcomx.org/Baptism": "Baptized",
    "http://gedcomx.org/Death": "Died",
    "http://gedcomx.org/Burial": "Buried",
    "http://gedcomx.org/Cremation": "Cremated",
    "http://gedcomx.org/Occupation": "Occupation",
    "http://gedcomx.org/Residence": "Residence",
    "http://gedcomx.org/Religion": "Religion",
    "http://gedcomx.org/Education": "Education",
    "http://gedcomx.org/MilitaryService": "Military service",
    "http://gedcomx.org/Immigration": "Immigrated",
    "http://gedcomx.org/Emigration": "Emigrated",
    "http://gedcomx.org/Naturalization": "Naturalized",
    "http://gedcomx.org/Nationality": "Nationality",
    "http://gedcomx.org/Caste": "Caste",
    "http://gedcomx.org/PhysicalDescription": "Description",
}

MARRIAGE = "http://gedcomx.org/Marriage"
BIRTH = "http://gedcomx.org/Birth"
DEATH = "http://gedcomx.org/Death"

FS_PERSON_URL = "https://www.familysearch.org/tree/person/details/%s"


def _full_name(indi):
    """Resolve an Indi to a display name, or 'Unknown'."""
    if indi and indi.name and (indi.name.given or indi.name.surname):
        name = ("%s %s" % (indi.name.given, indi.name.surname)).strip()
        if indi.name.suffix:
            name += " " + indi.name.suffix
        return name
    return "Unknown"


def _year(date_str):
    """Pull a 4-digit year out of a free-text date, for headings."""
    if not date_str:
        return ""
    match = re.search(r"\d{4}", date_str)
    return match.group(0) if match else ""


def _find_fact(indi, type_uri):
    for fact in indi.facts:
        if fact.type == type_uri:
            return fact
    return None


MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


def _pretty_date(date_str):
    """Turn a formal YYYYMMDD / +YYYY-MM-DD date into '11 August 1980'.
    Leaves already-readable dates (and year-only values) untouched."""
    if not date_str:
        return date_str
    match = re.fullmatch(r"\+?(\d{4})-?(\d{2})-?(\d{2})", date_str.strip())
    if match:
        year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return "%d %s %s" % (day, MONTHS[month - 1], year)
    return date_str


def _when_where(fact):
    """Format a fact's date/place as 'DATE in PLACE' (either part optional)."""
    parts = []
    if fact.date:
        parts.append(_pretty_date(fact.date))
    if fact.place:
        parts.append("in " + fact.place)
    return " ".join(parts)


def _anchor(indi):
    return "i%s" % indi.num


def _link(tree, fid):
    """In-document link to a person by fid, or None if they aren't in the tree."""
    indi = tree.indi.get(fid)
    if indi:
        return "[%s](#%s)" % (_full_name(indi), _anchor(indi))
    return None


def _marriage_detail(fam):
    if not fam:
        return ""
    for fact in fam.facts:
        if fact.type == MARRIAGE:
            detail = _when_where(fact)
            return (" — married " + detail) if detail else " — married"
    return ""


def _life_span(indi):
    birth = _find_fact(indi, BIRTH)
    death = _find_fact(indi, DEATH)
    by = _year(birth.date) if birth else ""
    dy = _year(death.date) if death else ""
    if by or dy:
        return " (%s–%s)" % (by, dy)
    return ""


def _write_person(tree, indi, file):
    file.write('<a id="%s"></a>\n' % _anchor(indi))
    file.write("## %s%s\n\n" % (_full_name(indi), _life_span(indi)))

    # Vital facts and other life events
    for type_uri in (BIRTH, "http://gedcomx.org/Christening", DEATH,
                     "http://gedcomx.org/Burial"):
        fact = _find_fact(indi, type_uri)
        if fact:
            detail = _when_where(fact)
            if detail:
                file.write("- **%s:** %s\n" % (FACT_LABELS[type_uri], detail))

    for fact in indi.facts:
        if fact.type in (BIRTH, "http://gedcomx.org/Christening", DEATH,
                         "http://gedcomx.org/Burial"):
            continue
        label = FACT_LABELS.get(
            fact.type,
            fact.type.rsplit("/", 1)[-1] if fact.type else None,
        )
        if not label:
            continue
        detail = _when_where(fact)
        if fact.value and fact.value != "Y":
            detail = (detail + " — " + fact.value) if detail else fact.value
        file.write("- **%s:** %s\n" % (label, detail or ""))

    # Parents (dedupe — a person can have several parent-relationship records
    # that share a parent)
    parent_links = []
    seen_parents = set()
    for father_fid, mother_fid in indi.famc_fid:
        for pfid in (father_fid, mother_fid):
            if not pfid or pfid in seen_parents:
                continue
            seen_parents.add(pfid)
            link = _link(tree, pfid)
            parent_links.append(link if link else "Unknown (not downloaded)")
    if parent_links:
        file.write("\n**Parents:** %s\n" % ", ".join(parent_links))

    # Spouses and children
    for husb_fid, wife_fid in indi.fams_fid:
        fam = tree.fam.get((husb_fid, wife_fid))
        spouse_fid = wife_fid if indi.fid == husb_fid else husb_fid
        spouse_link = _link(tree, spouse_fid) if spouse_fid else "Unknown spouse"
        file.write("\n**Spouse:** %s%s\n" % (
            spouse_link or "Unknown (not downloaded)", _marriage_detail(fam)))
        if fam and fam.chil_fid:
            child_links = []
            for cfid in fam.chil_fid:
                link = _link(tree, cfid)
                child_links.append(link if link else "Unknown (not downloaded)")
            if child_links:
                file.write("  - Children: %s\n" % ", ".join(child_links))

    # Notes and stories — the narrative content goal #1 cares about
    if indi.notes:
        file.write("\n**Notes & stories:**\n\n")
        for note in indi.notes:
            text = note.text.strip()
            if text:
                file.write("> %s\n>\n" % text.replace("\n", "\n> "))

    if indi.memories:
        file.write("\n**Memories:**\n")
        for memory in indi.memories:
            desc = memory.description or "memory"
            if memory.url:
                file.write("- [%s](%s)\n" % (desc.replace("\n", " "), memory.url))
            else:
                file.write("- %s\n" % desc.replace("\n", " "))

    file.write("\n[View on FamilySearch](%s) · `%s`\n\n---\n\n"
               % (FS_PERSON_URL % indi.fid, indi.fid))


def _write_frontier(tree, file):
    """List ancestors with no parents in the downloaded tree — the people to
    research next to extend the tree."""
    brick_walls = []   # no parents recorded in FamilySearch at all
    crawl_edge = []    # parents exist in FS but weren't downloaded

    for indi in tree.indi.values():
        has_parent = any(
            (h in tree.indi or w in tree.indi) for h, w in indi.famc_fid
        )
        if has_parent:
            continue
        if indi.parents:
            crawl_edge.append(indi)
        else:
            brick_walls.append(indi)

    if not (brick_walls or crawl_edge):
        return

    file.write("## Research frontier\n\n")
    file.write("Ancestors at the edge of your downloaded tree — the best "
               "places to look to find more ancestors.\n\n")

    if brick_walls:
        file.write("### Brick walls (no parents recorded in FamilySearch)\n\n")
        for indi in sorted(brick_walls, key=lambda i: i.num):
            birth = _find_fact(indi, BIRTH)
            where = (" — born %s" % _when_where(birth)) if birth and _when_where(birth) else ""
            file.write("- [%s](#%s)%s\n" % (_full_name(indi), _anchor(indi), where))
        file.write("\n")

    if crawl_edge:
        file.write("### Not yet downloaded (parents exist — re-run with a higher `--ascend`)\n\n")
        for indi in sorted(crawl_edge, key=lambda i: i.num):
            file.write("- [%s](#%s)\n" % (_full_name(indi), _anchor(indi)))
        file.write("\n")


def print_narrative(tree, file=sys.stdout):
    """Write the whole tree as a Markdown narrative."""
    file.write("# Family history of %s\n\n" % (tree.display_name or "Unknown"))
    file.write("_Exported %s from FamilySearch via getmyancestors._\n\n"
               % time.strftime("%d %b %Y"))
    file.write("%s individuals, %s families.\n\n---\n\n"
               % (len(tree.indi), len(tree.fam)))

    for indi in sorted(tree.indi.values(), key=lambda i: i.num):
        _write_person(tree, indi, file)

    _write_frontier(tree, file)
