"""Optional offline embeddings of permission-filtered SOP chunks.

Only local model directories are accepted; this code never downloads a model or
sends SOP text to a provider. Cached vectors are never used as an access grant.
"""
import hashlib
import logging
import math
import re
from functools import lru_cache
from pathlib import Path
from threading import Lock

from django.conf import settings
from .chat_progress import ChatCancelled, emit

logger = logging.getLogger(__name__)
MODEL_LOCK = Lock()
DOCUMENT_LIMIT = 100
CHUNK_LIMIT = 32


def chunks(content, words=100, overlap=20):
    tokens = list(re.finditer(r"\S+", content))
    pieces = []
    for start in range(0, len(tokens), words - overlap):
        end = min(start + words, len(tokens))
        pieces.append({"text": content[tokens[start].start():tokens[end - 1].end()], "start": tokens[start].start(), "end": tokens[end - 1].end()})
        if end == len(tokens) or len(pieces) >= CHUNK_LIMIT:
            break
    return pieces


@lru_cache(maxsize=1)
def _model(directory):
    from sentence_transformers import SentenceTransformer
    path = Path(directory)
    if not path.is_absolute() or not path.is_dir():
        raise ValueError("SOP embedding model must be an existing absolute local directory.")
    return SentenceTransformer(str(path), device="cpu", local_files_only=True, trust_remote_code=False)


def _vectors(model, texts):
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False, batch_size=32).tolist()
    if len(vectors) != len(texts) or not vectors:
        raise ValueError("Invalid embedding batch.")
    dimension = len(vectors[0])
    if not 1 <= dimension <= 4096:
        raise ValueError("Invalid embedding dimension.")
    normalized = []
    for vector in vectors:
        if len(vector) != dimension or any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
            raise ValueError("Invalid embedding vector.")
        length = math.sqrt(sum(value * value for value in vector))
        if not math.isfinite(length) or length <= 0:
            raise ValueError("Invalid embedding norm.")
        normalized.append(tuple(value / length for value in vector))
    return tuple(normalized)


# Bounded in-process cache. The content hash invalidates edited sections; model
# directory changes invalidate vectors. Restart after replacing model files.
@lru_cache(maxsize=128)
def _document_vectors(directory, document_id, digest, texts):
    del document_id, digest
    return _vectors(_model(directory), list(texts))


def rank_documents(queryset, message):
    """Return None for disabled/unavailable models, or ranked accessible chunks."""
    directory = getattr(settings, "OPENLIMS_SOP_EMBEDDING_MODEL_PATH", "")
    if not directory:
        return None
    try:
        threshold = float(getattr(settings, "OPENLIMS_SOP_EMBEDDING_MIN_SCORE", .35))
        if not math.isfinite(threshold) or not -1 <= threshold <= 1:
            raise ValueError("Invalid SOP embedding threshold.")
        # Includes sections without any lexical/concept overlap. Access/status
        # filters are already applied by the caller, before text is encoded.
        candidates = list(queryset.order_by("-updated_at", "pk")[:DOCUMENT_LIMIT + 1])
        bounded = len(candidates) > DOCUMENT_LIMIT
        ranked, section_limit_reached = [], False
        from .sop_semantics import concepts, compatible_concepts
        query_concepts = concepts(message)
        from .sop_operations import _terms
        query_words = _terms(message)
        with MODEL_LOCK:
            emit("checkpoint")
            model = _model(directory)
            query_vector = _vectors(model, [message])[0]
            for document in candidates[:DOCUMENT_LIMIT]:
                emit("checkpoint")
                pieces = chunks(document.content)
                if not pieces:
                    continue
                section_limit_reached |= pieces[-1]["end"] < len(document.content)
                texts = tuple(f"{document.title}\n{document.section}\n{piece['text']}" for piece in pieces)
                vectors = _document_vectors(directory, document.pk, hashlib.sha256(document.content.encode()).hexdigest(), texts)
                if any(len(vector) != len(query_vector) for vector in vectors):
                    raise ValueError("Embedding dimensions changed; restart with a consistent model.")
                scored = []
                for piece, vector in zip(pieces, vectors):
                    doc_concepts = concepts(f"{document.title} {document.section} {piece['text']}")
                    if not compatible_concepts(query_concepts, doc_concepts):
                        continue
                    cosine = sum(left * right for left, right in zip(query_vector, vector))
                    if cosine < threshold:
                        continue
                    words = _terms(piece["text"])
                    lexical = len(query_words & words) / max(1, len(query_words))
                    concept_overlap = len(query_concepts & doc_concepts) / max(1, len(query_concepts))
                    scored.append((cosine + .1 * lexical + .1 * concept_overlap, piece, cosine, sorted(query_concepts & doc_concepts)))
                if scored:
                    score, piece, cosine, matches = max(scored, key=lambda row: row[0])
                    document.semantic_passage = " ".join(piece["text"].split())
                    document.semantic_chunk = {"start": piece["start"], "end": piece["end"], "similarity": round(cosine, 4)}
                    document.semantic_matches = matches
                    document.semantic_content_truncated = pieces[-1]["end"] < len(document.content)
                    ranked.append((score, document))
        ranked.sort(key=lambda row: (-row[0], row[1].document_code, row[1].section, row[1].pk))
        return [document for _, document in ranked[:3]], {"semantic_mode": "local-embeddings-1", "candidate_limit": DOCUMENT_LIMIT,
                "candidate_limit_reached": bounded, "section_chunk_limit_reached": section_limit_reached,
                "chunk_word_limit": 100, "chunk_overlap_words": 20, "chunks_per_section_limit": CHUNK_LIMIT}
    except ChatCancelled:
        raise
    except Exception:
        # Do not log document content, query text, local paths or model exceptions.
        logger.warning("Local SOP embedding retrieval unavailable; using lexical/concept retrieval.")
        return None
