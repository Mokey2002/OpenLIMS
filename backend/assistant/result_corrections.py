"""Atomic natural corrections of one signed, typed result query."""
import re

from .result_filter_language import parse_filters

PREFIX = re.compile(r"^(?:no\b\s*,?\s*(?:(?:I\s+)?meant\s+)?|actually\b\s*,?\s*|instead\b\s*,?\s*)(.+)$", re.I)
TARGET = re.compile(r'(?:for\s+)?(sample|project)\s+("[^"\n]{1,128}"|[\w.:/-]{1,128})$', re.I)


def parse_correction(message):
    """Return (patch, clarification); None/None leaves unrelated requests alone."""
    text = message.strip().rstrip(".!?")
    prefix = PREFIX.fullmatch(text)
    body = prefix[1] if prefix else text
    if not prefix and not re.match(r"(?:use|switch to)\s+", body, re.I):
        return None, None
    # Quoted record identifiers may contain the word 'and'.
    parts = re.split(r'\s+and\s+(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)', body, flags=re.I)
    filters, target = {}, None
    for part in parts:
        clause = re.sub(r"^(?:use|switch to|I meant)\s+", "", part.strip(), flags=re.I)
        match = TARGET.fullmatch(clause)
        if match:
            if target:
                return None, "Choose one corrected sample or project; no result query was run."
            target = {"kind": match[1].lower(), "identifier": match[2].strip('"')}
            continue
        try:
            parsed = parse_filters(clause)
        except ValueError:
            parsed = None
        if not parsed or filters.keys() & parsed.keys():
            controls = " 'Controls' alone does not identify a recorded field." if re.search(r"\bcontrols?\b", clause, re.I) else ""
            return None, ("I could not preserve every correction. Use a supported date window, an exact sample/project identifier, "
                          "or exact result keys (for example, 'exclude key control')." + controls + " "
                          "No result query was run; the previous filters are retained.")
        filters.update(parsed)
    return {"filters": filters, "target": target}, None
