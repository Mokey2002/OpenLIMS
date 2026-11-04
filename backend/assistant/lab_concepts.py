"""Public application concepts, kept separate from requests for lab records."""
import re

from .lab_helpers import response
from .natural_requests import normalize_request


CONCEPTS = {
    "sample": ("sample", "A sample is the laboratory specimen record. It has an identifier, project, status and traceability history."),
    "work_item": ("work item", "A work item is a task linked to a sample. It records the assigned person, deadline, execution status and any results."),
    "result": ("result", "A result is a recorded measurement or observation linked to a work item. Its value, units, automated QC check and human review are separate fields."),
    "project": ("project", "A project organizes laboratory work and its members. Access to project records is checked for the current user."),
    "pipeline": ("pipeline", "A pipeline defines ordered or dependent steps for processing a sample, including required results and QC gates."),
}
TERM = r"(?:a |an |the )?(sample|work[ -]item|result|project|pipeline)s?"
FOLLOWUP = re.compile(
    r"(?:can (?:you|I) )?(?:give me|show me|show) (?:a |an )?(?:simple |short )?example|"
    r"explain (?:that|it|this)(?: (?:more simply|in plain language|in more detail))?|"
    r"tell me more|make (?:it|that) (?:shorter|simpler)", re.I)


def explain_concepts(keys, example=False):
    if not isinstance(keys, list) or not 1 <= len(keys) <= 2 or any(not isinstance(key, str) or key not in CONCEPTS for key in keys):
        return None
    lines = [CONCEPTS[key][1] for key in keys]
    if example:
        lines.append("Illustrative example: a specimen is the sample; measuring its DNA concentration is a work item; the concentration value and units are a result. This example does not describe an actual laboratory record.")
    return response("\n\n".join(lines), context={"lab_concept": keys},
        suggestions=["Give me a simple example", "What is a result?", "What should I work on today?"],
        lab_concept={"keys": keys, "example": example})


def route_lab_concepts(message, user=None, context=None):
    text = normalize_request(message)
    pair = re.fullmatch(r"(?:explain |tell me |what(?:'s| is) )?(?:the )?difference between " + TERM + r" and " + TERM, text, re.I)
    single = re.fullmatch(r"(?:define |what(?:'s| is) (?:a |an )?)(sample|work[ -]item|result|project|pipeline)s?", text, re.I)
    terms = list(pair.groups()) if pair else list(single.groups()) if single else None
    if terms:
        keys = [term.lower().replace("-", "_").replace(" ", "_") for term in terms]
        return explain_concepts(keys)
    keys = (context or {}).get("lab_concept")
    if keys and FOLLOWUP.fullmatch(text):
        return explain_concepts(keys, example="example" in text.lower())
    return None
