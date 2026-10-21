"""Short-lived read-topic memory. Store references, never answers or actions."""
import re

from django.core import signing
from .lab_helpers import response
from .natural_requests import READS, normalize_request

SALT = 'assistant.read-topics.v1'
MAX_AGE = 3600
LIMIT = 5


def load_topics(context, user):
    token = (context or {}).get('dialogue_memory')
    if not isinstance(token, str) or len(token) > 6000:
        return []
    try:
        state = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except (signing.BadSignature, ValueError, TypeError):
        return []
    if not isinstance(state, dict) or state.get('user') != user.pk:
        return []
    items = state.get('topics')
    if not isinstance(items, list) or len(items) > LIMIT:
        return []
    return [item for item in items if isinstance(item, dict)
            and isinstance(item.get('intent'), str) and item['intent'] in READS
            and type(item.get('id')) is int and 0 < item['id'] < 2**63]


def resolve_topic(topic, user):
    kind, template = READS[topic['intent']]
    if kind == 'project':
        from .lab_reviews import _projects
        record = _projects(user).filter(pk=topic['id']).first()
        identifier = record.code if record else None
    else:
        from .sample_operations import _sample_queryset
        record = _sample_queryset(user).filter(pk=topic['id']).first()
        identifier = record.sample_id if record else None
    if identifier is None:
        return None
    return {'command': template.format(identifier), 'kind': kind, 'identifier': identifier}


def current_topic(context):
    intent = context.get('read_intent')
    if not isinstance(intent, str) or intent not in READS:
        return None
    if READS[intent][0] == 'project':
        pk = context.get('project_id')
    else:
        ids = context.get('sample_ids', [])
        if not isinstance(ids, list):
            return None
        ids = list(ids)
        if context.get('sample_id') is not None:
            ids.append(context['sample_id'])
        if not ids or any(type(pk) is not int for pk in ids) or len(set(ids)) != 1:
            return None
        pk = ids[0]
    return {'intent': intent, 'id': pk} if type(pk) is int and 0 < pk < 2**63 else None


def remember_topics(message, previous, result, user):
    context = result.get('context') or {}
    text = normalize_request(message).lower()
    if result.pop('clear_dialogue_memory', False) or text in {'start over', 'cancel', 'never mind', 'forget that'}:
        context.pop('dialogue_memory', None)
        return
    topics = [topic for topic in load_topics(previous, user) if resolve_topic(topic, user)]
    current = current_topic(context)
    if current and resolve_topic(current, user):
        topics = [topic for topic in topics if topic != current] + [current]
    context.pop('dialogue_memory', None)
    if topics:
        context['dialogue_memory'] = signing.dumps({'user': user.pk, 'topics': topics[-LIMIT:]}, salt=SALT, compress=True)
    result['context'] = context


def resume_topic(message, user, context):
    text = normalize_request(message)
    if re.fullmatch(r'(?:forget (?:this|our) conversation|clear (?:the )?conversation|start a new conversation|start over|reset (?:the )?conversation)', text, re.I):
        return None, response('Okay, we can start fresh. What would you like to work on?', clear_dialogue_memory=True)
    recap = re.fullmatch(r'what were we (?:talking about|discussing)|where were we|recap (?:our|this) conversation', text, re.I)
    back = re.fullmatch(r'(?:go |take me )?back to (?:the )?(?:previous|last) (project|sample|topic)', text, re.I)
    if not recap and not back:
        return None, None
    topics = [(topic, resolve_topic(topic, user)) for topic in load_topics(context, user)]
    topics = [(topic, resolved) for topic, resolved in topics if resolved]
    if recap:
        if not topics:
            return None, response('I do not have a recent accessible sample or project topic to recap. Which record should we look at?')
        commands = [resolved['command'] for _, resolved in reversed(topics)]
        return None, response('Our recent sample/project read tasks were:\n' + '\n'.join(f'- {command}' for command in commands)
                              + '\nChoose one to fetch its current records again.', context=dict(context), suggestions=commands)
    kind = back[1].lower()
    current = current_topic(context)
    for topic, resolved in reversed(topics):
        if kind != 'topic' and resolved['kind'] != kind:
            continue
        if current and (topic == current or (kind != 'topic' and READS[current['intent']][0] == kind and topic['id'] == current['id'])):
            continue
        return resolved['command'], None
    return None, response('I do not have an earlier accessible topic of that kind. Tell me the sample ID or project code and what you want to check.', context=dict(context))
