"""Five in-chat laboratory workflows using validated native services."""
import re

from django.db import transaction
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import is_admin, is_tech
from imports.models import ImportJob, InstrumentProfile
from inventory.models import InventoryLot, InstrumentBooking
from notebook.models import ExperimentTemplate
from notebook.permissions import notebooks_for_user
from pipelines.models import PipelineRun
from samples.models import SampleBatch

from .actions import propose_action, serialize_action
from .lab_helpers import response
from .lab_operation_common import StrictSerializer, fingerprint, project_for_user
from .natural_requests import normalize_request

KINDS = {
    'batch': ('Manage batch work', 'Choose the exact project/batch, assignment and deadline changes. Preview lists eligible work and exceptions.'),
    'resources': ('Reserve instruments and reagents', 'Choose exact times with a time zone, and any stock lots. Availability covers OpenLIMS bookings; stock is reserved immediately.'),
    'repair': ('Repair rejected import rows', 'Select originally rejected rows, enter actual corrections, and validate a new child import. Original measurements are unchanged.'),
    'notebook': ('Draft a notebook from a run', 'Choose a writable project notebook and recorded pipeline/import run. Actual method notes remain your input.'),
    'handover': ('Complete a shift handover', 'Review unfinished work, recorded blockers, recipient access and the internal notification before confirming.'),
}
DEFAULT_FIELDS = {'project', 'batch', 'scope', 'assign_to', 'deadline_mode', 'due_at', 'mode', 'instrument', 'starts_at', 'ends_at',
                  'source_kind', 'source_id', 'notebook_id', 'template_id', 'parent_id', 'source', 'recipient', 'booking_id'}


def form_reply(kind, defaults=None):
    if kind not in KINDS:
        raise ValidationError('Choose a supported lab operation.')
    defaults = {key: value for key, value in (defaults or {}).items() if key in DEFAULT_FIELDS and isinstance(value, (str, int)) and not isinstance(value, bool)}
    title, help_text = KINDS[kind]
    return response(help_text, lab_operation_form={'kind': kind, 'title': title, 'help': help_text, 'defaults': defaults},
        context={'lab_operation': {'kind': kind, 'defaults': defaults}}, suggestions=['Start over'])


def operation_plan(kind, user, fields):
    if kind in {'batch', 'handover'}:
        from .batch_operations import work_plan
        return work_plan(user, fields, handover=kind == 'handover')
    if kind == 'resources':
        from .resource_planning import resource_plan
        return resource_plan(user, fields)
    if kind == 'notebook':
        from .notebook_drafts import notebook_plan
        return notebook_plan(user, fields)
    raise ValidationError('Choose a supported operation.')


def prepare_operation(kind, user, fields):
    if kind == 'repair':
        from .import_repairs import preview_repair
        return preview_repair(user, fields)
    plan = operation_plan(kind, user, fields)
    reply = form_reply(kind, plan['fields'])
    reply['operation_plan'] = {'preview': plan['preview'], 'draft_excerpt': plan.get('draft_excerpt', ''), 'result_count': plan.get('result_count')}
    if kind in {'batch', 'handover'} and not plan['eligible']:
        reply['lab_operation_form']['plan'] = plan['preview']
        reply['answer'] = 'No work is eligible for the requested metadata change. Review the exclusions; no action was proposed.'
        return reply
    operation = {'batch': 'BATCH_UPDATE', 'resources': 'RESOURCE_PLAN', 'notebook': 'NOTEBOOK_DRAFT', 'handover': 'SHIFT_HANDOVER'}[kind]
    payload = {'operation': operation, 'fields': plan['fields'], 'digest': fingerprint(plan['state']), 'preview': plan['preview']}
    if 'work_ids' in plan:
        payload['work_ids'] = plan['work_ids']
    action = propose_action(user, 'LAB_OPERATION', plan['preview']['title'], payload)
    # Keep the existing inline form mounted with its unsaved local inputs.
    reply.pop('lab_operation_form', None)
    reply['pending_action'] = serialize_action(action)
    reply['answer'] = 'Review the exact scope, changes and exclusions below. Nothing has changed; confirm this preview to execute.'
    return reply


def execute_lab_operation(action):
    operation = action.payload.get('operation')
    if operation in {'BATCH_UPDATE', 'SHIFT_HANDOVER'}:
        from .batch_operations import execute_work_plan
        result = execute_work_plan(action, handover=operation == 'SHIFT_HANDOVER')
    elif operation == 'RESOURCE_PLAN':
        from .resource_planning import execute_resources
        result = execute_resources(action)
    elif operation == 'NOTEBOOK_DRAFT':
        from .notebook_drafts import execute_notebook_draft
        result = execute_notebook_draft(action)
    else:
        raise ValidationError('Unsupported laboratory operation.')
    return 'COMPLETED', result


class OperationSerializer(StrictSerializer):
    kind = serializers.ChoiceField(choices=list(KINDS))
    fields = serializers.DictField()


class LabOperationPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=OperationSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = OperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            if serializer.validated_data['kind'] == 'repair':
                # The file-owning repair service must observe its own commit
                # failures so it can remove a newly stored source copy.
                reply = prepare_operation(serializer.validated_data['kind'], request.user, serializer.validated_data['fields'])
            else:
                with transaction.atomic():
                    reply = prepare_operation(serializer.validated_data['kind'], request.user, serializer.validated_data['fields'])
        except ValueError as exc:
            raise ValidationError({'detail': str(exc)}) from exc
        return Response(reply, status=201 if reply.get('pending_action') else 200)


class LabOperationOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        if set(request.query_params) - {'kind', 'project'} or any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
            raise ValidationError('Use one kind and one exact project code.')
        kind = request.query_params.get('kind', '')
        if kind not in KINDS:
            raise ValidationError('Choose a supported lab operation.')
        from .lab_reviews import _projects
        data = {'projects': list(_projects(request.user).order_by('code').values('code', 'name')[:100]),
                'timezone': timezone.get_current_timezone_name(), 'can_write': bool(request.user.is_active and (is_admin(request.user) or is_tech(request.user))),
                'notes': ['Selectors show at most 100 records. Exact codes/IDs are validated again at preview and confirmation.']}
        if kind == 'repair':
            data['imports'] = [{'id': job.pk, 'label': f'#{job.pk} — {job.instrument.code} / {job.run_id}'} for job in
                ImportJob.objects.filter(uploaded_by=request.user, status__in=['COMPLETED', 'FAILED'], summary__has_key='assistant_upload')
                    .select_related('instrument', 'project').order_by('-pk')[:100]
                if job.project_id and (is_admin(request.user) or job.project.members.filter(pk=request.user.pk).exists())]
        code = request.query_params.get('project')
        if not code:
            return Response(data)
        project = project_for_user(code, request.user)
        data['people'] = list(project.members.filter(is_active=True).order_by('username').values_list('username', flat=True)[:100])
        data['batches'] = list(SampleBatch.objects.filter(project=project).order_by('code').values_list('code', flat=True)[:100])
        if kind == 'resources':
            data['instruments'] = list(InstrumentProfile.objects.order_by('code').values('code', 'name')[:100])
            data['lots'] = [{'code': lot.lot_code, 'unit': lot.unit, 'available': str(lot.available_quantity)} for lot in
                InventoryLot.objects.filter(status='ACTIVE', item__category='REAGENT').prefetch_related('reservations').order_by('lot_code')[:100]]
            bookings = InstrumentBooking.objects.filter(project=project, status='ACTIVE').select_related('instrument')
            if not is_admin(request.user):
                bookings = bookings.filter(created_by=request.user)
            data['bookings'] = [{'id': row.pk, 'label': f'#{row.pk} — {row.instrument.code}, {row.starts_at.isoformat()} to {row.ends_at.isoformat()}'} for row in bookings.order_by('starts_at')[:100]]
        elif kind == 'notebook':
            from .lab_helpers import enabled
            if not enabled('notebook'):
                raise ValidationError('The notebook module is disabled.')
            notebooks = notebooks_for_user(request.user, 'write').filter(project=project, scope='PROJECT')
            data['notebooks'] = list(notebooks.order_by('name').values('id', 'name')[:100])
            data['can_write'] = bool(request.user.is_active and notebooks.exists())
            data['templates'] = list(ExperimentTemplate.objects.filter(notebook__in=notebooks, active=True).values('id', 'name', 'notebook_id')[:100])
            data['sources'] = [{'kind': 'pipeline', 'id': row.pk, 'label': f'Pipeline #{row.pk}: {row.sample.sample_id} / {row.template_code}'}
                for row in PipelineRun.objects.filter(sample__project=project).select_related('sample').order_by('-pk')[:100]]
            data['sources'] += [{'kind': 'import', 'id': row.pk, 'label': f'Import #{row.pk}: {row.run_id}'} for row in
                ImportJob.objects.filter(project=project, status='COMPLETED').order_by('-pk')[:100]]
        return Response(data)


class ImportRepairRowsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, pk):
        if set(request.query_params) - {'offset'} or len(request.query_params.getlist('offset')) > 1:
            raise ValidationError('Use one row offset.')
        field = serializers.IntegerField(min_value=0, max_value=10000)
        offset = field.run_validation(request.query_params.get('offset', 0))
        from .import_repairs import rejected_rows
        try:
            return Response(rejected_rows(pk, request.user, offset))
        except ValueError as exc:
            raise ValidationError({'detail': str(exc)}) from exc


def route_lab_operations(message, user, context=None):
    text = normalize_request(message)
    lower = text.lower()
    starters = {'manage batch work': 'batch', 'manage a whole batch': 'batch', 'batch management': 'batch',
        'reserve resources': 'resources', "plan tomorrow's sequencing run": 'resources', 'plan a sequencing run': 'resources',
        'repair rejected import rows': 'repair', 'fix rejected import rows': 'repair',
        'create a notebook draft from this run': 'notebook', 'draft a notebook from a run': 'notebook',
        'prepare a shift handover': 'handover', 'complete a shift handover': 'handover'}
    if lower in starters:
        kind = starters[lower]
        defaults = {'source': 'me'} if kind == 'handover' else {}
        project_id = (context or {}).get('project_id')
        if type(project_id) is int and 0 < project_id < 2**63:
            from .lab_reviews import _projects
            project = _projects(user).filter(pk=project_id).first()
            if project:
                defaults['project'] = project.code
        if kind == 'repair' and type((context or {}).get('instrument_import_job_id')) is int:
            defaults['parent_id'] = context['instrument_import_job_id']
        if kind == 'notebook':
            from django.http import Http404
            from rest_framework.exceptions import NotFound
            from .instrument_imports import accessible_job
            source_id = (context or {}).get('instrument_import_job_id')
            if type(source_id) is int and 0 < source_id < 2**63:
                try:
                    source = accessible_job(source_id, user)
                    if source.status == 'COMPLETED':
                        defaults.update(project=source.project.code, source_kind='import', source_id=source.pk, title=f'Run {source.run_id} — draft')
                except (Http404, NotFound):
                    pass
            elif (context or {}).get('workflow_guide'):
                from .workflow_guide import recall
                from .workflow_actions import state
                sample = recall(context, user)
                run = state(sample)[0] if sample else None
                if run and sample.project_id:
                    defaults.update(project=sample.project.code, source_kind='pipeline', source_id=run.pk, title=f'{run.template_code} run #{run.pk} — draft')
        return form_reply(kind, defaults)
    code, person = r'([\w.:/-]{1,64})', r'([\w.@+-]{1,150})'
    match = re.fullmatch(r'(?:manage|update) (?:the |a )?(?:whole )?batch ' + code + r'(?: in project ' + code + r')?', text, re.I)
    if match:
        return form_reply('batch', {'batch': match[1], **({'project': match[2]} if match[2] else {})})
    match = re.fullmatch(r"assign (?:project )?" + code + r"(?:'s)? unassigned work to " + person + r'(?: and set (?:next )?(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) deadlines)?', text, re.I)
    if match:
        reply = form_reply('batch', {'project': match[1], 'scope': 'unassigned', 'assign_to': match[2], 'deadline_mode': 'set' if match[3] else 'keep'})
        if match[3]:
            reply['answer'] += ' Choose the exact deadline and time zone; no time of day is assumed.'
        return reply
    if re.match(r"assign (?:project )?" + code + r"(?:'s)? unassigned work to ", text, re.I):
        return response('That extra condition is unsupported. State the exact project, assignment and deadline in the batch form; no scope was broadened.', clarification={'required': True})
    match = re.fullmatch(r'(?:reserve resources|plan a sequencing run) (?:for|in) project ' + code, text, re.I)
    if match:
        return form_reply('resources', {'project': match[1]})
    match = re.fullmatch(r'(?:book|reserve) instrument ' + code + r' (?:in|for) project ' + code, text, re.I)
    if match:
        return form_reply('resources', {'instrument': match[1], 'project': match[2]})
    match = re.fullmatch(r'cancel (?:instrument )?booking #?(\d+) in project ' + code, text, re.I)
    if match:
        return form_reply('resources', {'mode': 'cancel', 'booking_id': int(match[1]), 'project': match[2]})
    match = re.fullmatch(r'(?:repair|fix)(?: rejected rows from)? import #?(\d+)', text, re.I)
    if match:
        return form_reply('repair', {'parent_id': int(match[1])})
    match = re.fullmatch(r'(?:create|draft)(?: a)? notebook draft from (pipeline|import)(?: run)? #?(\d+) in project ' + code, text, re.I)
    if match:
        return form_reply('notebook', {'source_kind': match[1].lower(), 'source_id': int(match[2]), 'project': match[3]})
    match = re.fullmatch(r'hand(?: over)? my unfinished ' + code + r' work to ' + person, text, re.I)
    if match:
        return form_reply('handover', {'project': match[1], 'source': 'me', 'recipient': match[2]})
    match = re.fullmatch(r'hand(?: over)? my unfinished work in project ' + code + r' to ' + person, text, re.I)
    if match:
        return form_reply('handover', {'project': match[1], 'source': 'me', 'recipient': match[2]})
    state = (context or {}).get('lab_operation')
    if isinstance(state, dict) and isinstance(state.get('kind'), str) and state['kind'] in KINDS:
        if not isinstance(state.get('defaults'), dict):
            return response('The earlier operation fields are invalid. Start a new lab operation.')
        defaults = state['defaults']
        match = re.fullmatch(r'(?:use|only)(?: project)? ' + code, text, re.I)
        if match:
            return form_reply(state['kind'], {**defaults, 'project': match[1]})
        if state['kind'] == 'batch':
            match = re.fullmatch(r'assign to ' + person, text, re.I)
            if match:
                return form_reply('batch', {**defaults, 'assign_to': match[1]})
        if lower in {'why', 'what next', 'preview this plan', 'do it', 'yes'}:
            if defaults.get('project'):
                try:
                    project_for_user(defaults['project'], user)
                except ValidationError:
                    return response('The earlier project is unavailable. Start a new operation with an accessible project.')
            reply = form_reply(state['kind'], defaults)
            reply.pop('lab_operation_form', None)
            reply['answer'] = 'Review the fields in the inline form, then choose its preview button. No operation was executed.'
            return reply
    return None
