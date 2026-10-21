"""Bounded natural wording and read-only task continuity shared by providers."""
import re

from .lab_helpers import response

# Values are fixed read commands, never client-supplied templates or writes.
READS = {
    'sample_summary': ('sample', 'Summarize sample {}'),
    'sample_history': ('sample', 'What happened to sample {}'),
    'sample_location': ('sample', 'Where is sample {}'),
    'sample_sequences': ('sample', 'Find sequences for sample {}'),
    'sample_explanation': ('sample', 'Explain sample {}'),
    'sample_evidence': ('sample', 'Show evidence for sample {}'),
    'sample_checks': ('sample', 'What should I check first for sample {}'),
    'sample_unknowns': ('sample', 'What is still unknown about sample {}'),
    'project_summary': ('project', 'Summarize project {}'),
    'project_samples': ('project', 'Show samples in project {}'),
    'project_quality': ('project', 'Review data quality for project {}'),
}


def normalize_request(message):
    text = str(message or '').strip().replace('’', "'").lstrip('¿¡').rstrip('?! .')
    text = re.sub(r'^(?:hey|hi|hello)[,!]\s*', '', text, flags=re.I)
    text = re.sub(r'^(?:can|could|would) you\s+(?:please\s+)?', '', text, flags=re.I)
    text = re.sub(r'^(?:please|por favor)[, ]+', '', text, flags=re.I)
    text = re.sub(r',\s*(?:please|por favor)$', '', text, flags=re.I)
    aliases = [
        (r'(?:give me|show me) (?:a |the )?(?:quick )?(?:summary|overview|rundown) (?:of|for) (project|sample) (.+)', lambda m: f'Summarize {m[1]} {m[2]}'),
        (r'how is (project|sample) (.+) doing', lambda m: f'Summarize {m[1]} {m[2]}'),
        (r'(?:what|which) samples (?:are|do we have) in (project .+|(?:that|this|the) project)', lambda m: f'Show samples in {m[1]}'),
        (r'(?:show me|give me) (?:a |the )?(?:summary|overview|rundown) (?:of|for) (it|this project|that project|this sample|that sample)', lambda m: f'Summarize {m[1]}'),
        (r'(?:resume|resumir|dame un resumen del?) (?:el )?proyecto (.+)', lambda m: f'Summarize project {m[1]}'),
        (r'(?:resume|resumir|dame un resumen de) (?:la )?muestra (.+)', lambda m: f'Summarize sample {m[1]}'),
        (r'(?:muestra|muéstrame|lista) (?:las )?muestras (?:de|del|en el) proyecto (.+)', lambda m: f'Show samples in project {m[1]}'),
        (r'(?:muestra|muéstrame|lista) (?:las )?muestras (?:de|en) (?:ese|este) proyecto', lambda m: 'Show samples in that project'),
        (r'(?:dónde está|donde esta) (?:la )?muestra (.+)', lambda m: f'Where is sample {m[1]}'),
        (r'(?:show me|tell me|give me) (?:what I should work on|my priorities|my to-do list)', lambda m: 'What do I need to work on?'),
    ]
    for pattern, replacement in aliases:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            return replacement(match)
    return text


def read_intent(message):
    for intent, (_, template) in READS.items():
        prefix = template.split('{}')[0]
        if re.fullmatch(re.escape(prefix) + r'.+', message, re.I):
            return intent
    return None


def _awaiting_context(intent, context):
    pending = {'awaiting_read': intent}
    if context.get('explanation_language') in ('en', 'es'):
        pending['explanation_language'] = context['explanation_language']
    return pending


def prepare_read_request(message, user, context):
    """Return a canonical command or a clarification, with access rechecked."""
    text = normalize_request(message)
    intent = None
    missing = {
        'sample_summary': r'summarize (?:a |the )?sample',
        'sample_history': r'(?:show (?:me )?(?:a |the )?sample history|what happened to (?:a |the )?sample)',
        'sample_location': r'where is (?:a |the )?sample',
        'sample_sequences': r'find sequences for (?:a |the )?sample',
        'sample_explanation': r'explain (?:a |the )?sample',
        'sample_evidence': r'show (?:the )?evidence for (?:a |the )?sample',
        'sample_checks': r'what should I check first for (?:a |the )?sample',
        'sample_unknowns': r'what is still unknown about (?:a |the )?sample',
        'project_summary': r'summarize (?:a |the )?project',
        'project_samples': r'show samples in (?:a |the )?project',
        'project_quality': r'review data quality for (?:a |the )?project',
    }
    for key, pattern in missing.items():
        if re.fullmatch(pattern, text, re.I):
            kind = READS[key][0]
            return text, response(f'Which {kind} should I use? Reply with its exact {"code" if kind == "project" else "ID"}.',
                                  context=_awaiting_context(key, context), clarification={'required': True})
    waiting = context.get('awaiting_read')
    previous = context.get('read_intent')
    continuation = re.fullmatch(r'(?:same for|what about|how about|and for|(?:no,? )?I meant|actually,?(?: I meant)?|sorry,? I meant)\s+(?:(sample|project)\s+)?(.+)', text, re.I)
    target = None
    if isinstance(previous, str) and previous in READS and continuation:
        intent = previous
        if continuation[1] and continuation[1].lower() != READS[intent][0]:
            return text, response('Do you want a sample or project review? Please name the task and record.')
        target = continuation[2]
    elif isinstance(waiting, str) and waiting in READS:
        if text.lower() in {'cancel', 'never mind', 'start over'}:
            return text, response('Okay, what would you like to check next?')
        if re.fullmatch(r'[\w.-]+|"[^"\n]+"', text) and text.lower() not in {'thanks', 'okay', 'ok', 'understood', 'yes', 'no', 'help', 'hello', 'hi'}:
            intent, target = waiting, text
    if target is None:
        return text, None
    target = target.strip().strip('"')
    kind, template = READS[intent]
    if kind == 'sample':
        from .sample_operations import _sample_queryset
        matches = list(_sample_queryset(user).filter(sample_id__iexact=target)[:2])
        identifier = matches[0].sample_id if len(matches) == 1 else None
    else:
        from django.db.models import Q
        from .lab_reviews import _projects
        matches = list(_projects(user).filter(Q(code__iexact=target) | Q(name__iexact=target)).distinct()[:2])
        identifier = matches[0].code if len(matches) == 1 else None
    if identifier is None:
        return text, response(f'I could not identify one accessible {kind}. Please give its exact identifier.',
                              context=_awaiting_context(intent, context), clarification={'required': True})
    return template.format(identifier), None


def remember_read(message, result):
    intent = read_intent(message)
    context = (result or {}).get('context') or {}
    if not intent:
        if re.fullmatch(r'(?:summarize|summarise) (?:it|this project|that project|this sample|that sample)', message, re.I):
            intent = 'sample_summary' if context.get('sample_id') or context.get('sample_ids') else 'project_summary'
        elif result.get('history') is not None:
            intent = 'sample_history'
        elif re.fullmatch(r'where is (?:it|this sample|that sample)(?: stored)?', message, re.I):
            intent = 'sample_location'
        elif re.fullmatch(r'(?:show|find|list|show me) (?:its sequences|sequences for (?:it|this sample|that sample))', message, re.I):
            intent = 'sample_sequences'
        elif re.fullmatch(r'(?:show|list|show me) (?:the )?samples (?:in|for|from) (?:this|that|the) project', message, re.I):
            intent = 'project_samples'
    if intent:
        kind = READS[intent][0]
        if (kind == 'sample' and (context.get('sample_id') or context.get('sample_ids'))) or (kind == 'project' and context.get('project_id')):
            result['context'] = {**context, 'read_intent': intent}
    return result
