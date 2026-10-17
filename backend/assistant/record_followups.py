"""Resolve narrow read-only pronoun requests against one accessible record."""
import re
from .lab_helpers import response
from .sample_operations import _sample_queryset

SAMPLE_READS = [
    (r'(?:summarize|summarise) (?:it|this sample|that sample)', 'Summarize sample {code}'),
    (r'(?:show|show me|summarize) (?:its history|the history of (?:it|this sample|that sample))', 'What happened to sample {code}'),
    (r'what happened to (?:it|this sample|that sample)', 'What happened to sample {code}'),
    (r'where is (?:it|this sample|that sample)(?: stored)?', 'Where is sample {code}'),
    (r'who last moved (?:it|this sample|that sample)', 'Who last moved sample {code}'),
    (r"(?:what(?:'s| is)? next|what should I do next)(?: for (?:it|this sample|that sample))?", 'What next for sample {code}?'),
    (r'(?:show|find|list|show me) (?:its sequences|sequences for (?:it|this sample|that sample))', 'Find sequences for sample {code}'),
]


def resolve_read_followup(message, user, context):
    text = str(message or '').strip().replace('’', "'").rstrip('?.!')
    if re.fullmatch(r'(?:preview (?:quarantine )?impact (?:for|of)|what would be affected if (?:we|I) quarantine) (?:it|this lot|that lot)', text, re.I):
        from inventory.models import InventoryLot
        ids = context.get('inventory_lot_ids', [])
        ids = list(ids) if isinstance(ids, list) else [None]
        if context.get('inventory_lot_id') is not None:
            ids.append(context['inventory_lot_id'])
        if not ids or any(type(pk) is not int or not 0 < pk < 2**63 for pk in ids) or len(set(ids)) != 1:
            return None, response('Which lot do you mean? Please give one exact lot code.', clarification={'required': True})
        lot = InventoryLot.objects.filter(pk=ids[0]).first()
        if lot is None:
            return None, response('That lot is no longer available. Please give its exact lot code.')
        return f'Preview quarantine impact for lot {lot.lot_code}', None
    if re.fullmatch(r'(?:summarize|summarise) it', text, re.I) and context.get('project_id') and not (context.get('sample_id') or context.get('sample_ids')):
        return 'Summarize this project', None
    template = next((command for pattern, command in SAMPLE_READS if re.fullmatch(pattern, text, re.I)), None)
    if not template:
        return None, None
    ids = context.get('sample_ids', [])
    if not isinstance(ids, list):
        ids = []
    ids = list(ids)
    if context.get('sample_id') is not None:
        ids.append(context['sample_id'])
    if not ids or any(type(pk) is not int or not 0 < pk < 2**63 for pk in ids) or len(set(ids)) != 1:
        return None, response('Which sample do you mean? Please give one exact sample ID.', clarification={'required': True})
    sample = _sample_queryset(user).filter(pk=ids[0]).first()
    if sample is None:
        return None, response('That sample is no longer accessible. Please choose an accessible sample.', clarification={'required': True})
    return template.format(code=sample.sample_id), None
