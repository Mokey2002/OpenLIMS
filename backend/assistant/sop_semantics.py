"""Local semantic concepts for SOP retrieval. No document leaves the server.

Concept vectors make lab synonyms comparable; lexical coverage breaks ties.
This deliberately bounded vocabulary is inspectable, versioned, and testable.
"""
import math
import re

CONCEPT_VERSION = "lab-concepts-1"
CONCEPTS = {
    "low_concentration": ("low concentration", "too dilute", "diluted dna", "insufficient concentration", "dna too dilute"),
    "high_concentration": ("high concentration", "too concentrated", "excess concentration"),
    "repeat_measurement": ("repeat measurement", "rerun", "re-run", "run again", "repeat the test", "retest"),
    "cold_storage": ("cold storage", "freezer", "refrigerator", "refrigerated", "frozen storage"),
    "temperature_excursion": ("temperature excursion", "too warm", "overheated", "temperature exceeded", "temperature deviation"),
    "sample_identification": ("sample identification", "sample identifier", "specimen id", "barcode", "sample label", "mislabeled"),
    "quality_review": ("quality control", "qc review", "quality review", "approve results", "result approval", "release review"),
    "calibration": ("calibration", "calibrate", "calibration control", "instrument control", "control drift"),
    "contamination": ("contamination", "contaminated", "carryover", "cross contamination"),
    "sample_receipt": ("sample receipt", "receive a sample", "receiving samples", "specimen intake"),
    "chain_of_custody": ("chain of custody", "sample custody", "sample handoff", "custody transfer"),
    "dna_degradation": ("dna degradation", "degraded dna", "fragmented dna", "dna integrity"),
    "reagent_expiry": ("reagent expiry", "expired reagent", "expiration date", "reagent expiration", "expired lot"),
    "insufficient_volume": ("insufficient volume", "too little sample", "not enough volume", "low volume"),
    "equipment_failure": ("equipment failure", "instrument failure", "instrument error", "device malfunction"),
}


def concepts(text):
    text = " ".join(re.findall(r"[\w-]+", text.casefold()))
    return {name for name, phrases in CONCEPTS.items() if any(
        re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text) for phrase in phrases)}


def expanded_terms(message, original_terms):
    expanded = set(original_terms)
    for name in concepts(message):
        expanded.update(word for word in CONCEPTS[name][0].split() if len(word) > 2)
    return sorted(expanded)[:24]


def rerank(documents, message, terms):
    query_concepts = concepts(message)
    opposite = {"low_concentration": "high_concentration", "high_concentration": "low_concentration"}
    candidates = []
    for document in documents:
        doc_concepts = concepts(f"{document.title} {document.section} {document.content}")
        if not any(inverse in doc_concepts and inverse not in query_concepts and concept not in doc_concepts
                   for concept, inverse in opposite.items() if concept in query_concepts):
            candidates.append(document)
    documents = candidates
    query_words = set(terms)
    def score(document):
        text = f"{document.title} {document.section} {document.content}"
        doc_concepts = concepts(text)
        overlap = query_concepts & doc_concepts
        cosine = len(overlap) / math.sqrt(len(query_concepts) * len(doc_concepts)) if query_concepts and doc_concepts else 0
        words = set(re.findall(r"[\w-]+", text.casefold()))
        coverage = len(words & query_words) / max(1, len(query_words))
        document.semantic_matches = sorted(overlap)
        return (-4 * cosine - coverage - min(float(document.search_rank), 1), document.document_code, document.section, document.pk)
    return sorted(documents, key=score)[:3]
