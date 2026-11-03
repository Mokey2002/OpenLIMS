"""Atomic natural corrections of one signed, typed result query."""
import re

from .result_filter_language import parse_filters

PREFIX = re.compile(r"^(?:no\b\s*,?\s*(?:(?:I\s+)?meant\s+)?|actually\b\s*,?\s*|instead\b\s*,?\s*|(?:sorry\b\s*,?\s*)?I meant\s+)(.+)$", re.I)
TARGET = re.compile(r'(?:for\s+)?(sample|project)\s+("[^"\n]{1,128}"|[\w.:/-]{1,128})$', re.I)


def parse_correction(message, *, target_kind=None):
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
            filter_clause = re.sub(r"^(?:the )?(failed|passed|pending|rejected|approved)(?: (?:ones|results))?$",
                                   r"only \1", clause, flags=re.I)
            parsed = parse_filters(filter_clause)
        except ValueError:
            parsed = None
        # Infer only the record kind from one signed query, never from display
        # context. A bare identifier requires an explicit "I meant" correction.
        if (not parsed and target_kind in {"sample", "project"} and re.search(r"\bI meant\b", text, re.I)
                and re.fullmatch(r'"[^"\n]{1,128}"|[\w.:/-]{1,128}', clause)
                and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", clause)
                and not re.fullmatch(r"controls?|approve|reject|delete|archive|assign|all|them|it|this|that", clause, re.I)):
            if target:
                return None, "Choose one corrected sample or project; no result query was run."
            target = {"kind": target_kind, "identifier": clause.strip('"')}
            continue
        if not parsed or filters.keys() & parsed.keys():
            controls = " 'Controls' alone does not identify a recorded field." if re.search(r"\bcontrols?\b", clause, re.I) else ""
            return None, ("I could not preserve every correction. Use a supported date window, an exact sample/project identifier, "
                          "or exact result keys (for example, 'exclude key control')." + controls + " "
                          "No result query was run; the previous filters are retained.")
        filters.update(parsed)
    return {"filters": filters, "target": target}, None
