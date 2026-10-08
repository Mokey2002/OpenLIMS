"""Bounded conversational interpretation; never fuzzy-match record identifiers."""
import re


NEXT = re.compile(r"what(?:'s| is)? next|what should I do|next steps?|why.*blocked|explain.*(?:workflow|pipeline)|qué sigue|qu[eé].*hacer|pr[oó]ximo.*paso|por qu[eé].*bloquead|explica.*(?:flujo|pipeline)|what.*holding.*up|what.*(?:missing|left to do)|how.*(?:proceed|continue)|qu[eé] falta|qu[eé].*impide|c[oó]mo.*continu", re.I)
OWNER = re.compile(r"who.*(?:assigned|responsible|review)|qui[eé]n.*(?:asignad|responsable|revisa)", re.I)
STEP = re.compile(r"\b(?:step|paso)\s+(\d+)\b", re.I)
WRITE = re.compile(r"\b(?:approve|assign|complete|delete|cancel|create|update|aprobar|aprueba|asigna|completa|elimina|cancela|crea|actualiza)\b", re.I)
REFERENCE = re.compile(r"\b(?:sample|muestra)\s+([\w][\w./-]*)", re.I)


def interpret(message, context):
    text = str(message or "").replace("’", "'").strip().lstrip("¿¡")
    state = context.get("guidance") if isinstance(context.get("guidance"), dict) else {}
    if state and re.fullmatch(r"(?:start over|forget (?:this|that) sample|clear context|empezar de nuevo|olvida (?:esta|esa) muestra)[.!?]*", text, re.I):
        return {"reset": True}
    # Action requests must retain their existing permission/confirmation route.
    if WRITE.search(text):
        return None
    step_numbers = list(dict.fromkeys(int(n) for n in STEP.findall(text)))
    followup = bool(state) and bool(re.fullmatch(r"(?:and now|now what|why|and (?:this|that) one|y ahora|por qu[eé]|what about (?:step \d+|this sample)|y (?:el )?paso \d+)[?.! ]*", text, re.I))
    bare = bool(state.get("awaiting_sample")) and bool(re.fullmatch(r"[\w][\w./-]*[?.!]?", text))
    other_sample = re.fullmatch(r"(?:what about|how about|y)\s+(?:(?:sample|muestra)\s+)?([\w]+(?:[-_][\w]+)+)[?.! ]*", text, re.I) if state else None
    step_followup = bool(state) and bool(re.fullmatch(r"(?:(?:what about|explain|show|and|explica|y)\s+(?:el\s+)?)?(?:step|paso)\s+\d+[?.! ]*", text, re.I))
    if not (NEXT.search(text) or OWNER.search(text) or followup or bare or step_followup or other_sample):
        return None
    codes = [c for c in REFERENCE.findall(text) if c.casefold() not in {"is", "the", "this", "that", "está", "esta", "esa"}]
    if not codes:
        codes = re.findall(r"\b[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+\b", text)
    if bare and not codes:
        codes = [text.rstrip("?.!")]
    spanish = bool(re.search(r"\b(?:muestra|qué|que|sigue|hacer|paso|bloquead\w*|explica|qui[eé]n|falta|ahora|c[oó]mo)\b", text, re.I))
    # Short ID/step replies retain the conversation language.
    language = "es" if spanish or (bare and state.get("language") == "es") else "en"
    remembered_steps = state.get("steps", [])
    if not isinstance(remembered_steps, list) or not all(type(n) is int for n in remembered_steps):
        remembered_steps = []
    return {"codes": list(dict.fromkeys(c.rstrip(".").casefold() for c in codes)),
            "steps": step_numbers or (remembered_steps if bare else []),
            "focus": (state.get("focus", "next") if bare else "owner" if OWNER.search(text) else "next"),
            "language": language, "state": state}
