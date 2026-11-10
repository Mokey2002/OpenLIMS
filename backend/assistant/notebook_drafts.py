"""Create native DRAFT experiments from recorded run evidence, never invented methods."""
import math

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError

from imports.models import ImportJob
from events.models import Event
from notebook.models import Notebook, Experiment, ExperimentTemplate
from notebook.permissions import notebooks_for_user
from notebook.services import create_revision, instantiate_template
from pipelines.models import PipelineRun, PipelineStepRun
from results.models import WorkItem, Result
from samples.access import get_sample_access_queryset
from samples.models import Sample

from .lab_helpers import enabled
from .lab_operation_common import StrictSerializer, assert_unchanged, plain, preview, project_for_user


class NotebookDraftSerializer(StrictSerializer):
    project = serializers.CharField(max_length=64)
    source_kind = serializers.ChoiceField(choices=['pipeline', 'import'])
    source_id = serializers.IntegerField(min_value=1, max_value=2**63 - 1)
    notebook_id = serializers.IntegerField(min_value=1, max_value=2**63 - 1)
    template_id = serializers.IntegerField(min_value=1, max_value=2**63 - 1, required=False, allow_null=True, default=None)
    title = serializers.CharField(max_length=255)
    method_notes = serializers.CharField(max_length=4000, required=False, allow_blank=True, default='')


def _value(value):
    return 'Invalid non-finite number' if isinstance(value, float) and not math.isfinite(value) else value


def notebook_plan(user, fields, *, lock=False):
    if not enabled('notebook') or not user.is_active:
        raise PermissionDenied('The notebook module is unavailable.')
    serializer = NotebookDraftSerializer(data=fields)
    serializer.is_valid(raise_exception=True)
    fields = serializer.validated_data
    project = project_for_user(fields['project'], user, lock=lock)
    notebook = notebooks_for_user(user, 'write').filter(pk=fields['notebook_id'], scope='PROJECT', project=project).first()
    if notebook is None:
        raise PermissionDenied('Choose a writable project notebook in this project.')
    if lock:
        notebook = Notebook.objects.select_for_update().get(pk=notebook.pk)
    template = None
    if fields['template_id']:
        template = ExperimentTemplate.objects.filter(pk=fields['template_id'], notebook=notebook, active=True).first()
        if template is None:
            raise ValidationError('Choose an active template belonging to the selected notebook.')
        if lock:
            template = ExperimentTemplate.objects.select_for_update().get(pk=template.pk)
    links, methods, source_state = [], [], {}
    if fields['source_kind'] == 'pipeline':
        source = PipelineRun.objects.select_related('sample').filter(pk=fields['source_id'], sample__project=project).first()
        if source is None:
            raise PermissionDenied('Pipeline run unavailable in this project.')
        sample_ids = [source.sample_id]
        source_label = f'Pipeline {source.template_code}, run #{source.pk}'
        work_ids = list(source.steps.exclude(work_item=None).values_list('work_item_id', flat=True))
        source_state = {'id': source.pk, 'status': source.status, 'template': source.template_code, 'updated_at': source.updated_at}
        links.append({'entity_type': 'pipeline_run', 'entity_public_id': str(source.public_id), 'relation_type': 'source'})
    else:
        jobs = ImportJob.objects.select_for_update(of=('self',)) if lock else ImportJob.objects.all()
        source = jobs.select_related('instrument').filter(pk=fields['source_id'], project=project, status='COMPLETED').first()
        if source is None:
            raise PermissionDenied('Choose a completed import in this project.')
        work_ids = list(source.work_items.values_list('pk', flat=True))
        sample_ids = list(source.work_items.values_list('sample_id', flat=True).distinct())
        source_label = f'Instrument {source.instrument.code}, import #{source.pk}, run {source.run_id}'
        source_state = {'id': source.pk, 'status': source.status, 'instrument': source.instrument.code,
            'run_id': source.run_id, 'file_sha256': source.summary.get('assistant_upload', {}).get('file_sha256', ''),
            'repair': source.summary.get('repair', {})}
        methods = ['Instrument mappings describe data conversion. They do not establish the physical experimental method.']
    if len(work_ids) > 100:
        raise ValidationError('This run exceeds 100 work items. A larger draft requires a separate reviewed export.')
    samples = get_sample_access_queryset(Sample.objects.filter(pk__in=sample_ids, project=project), user)
    if samples.count() != len(set(sample_ids)):
        raise PermissionDenied('Some source samples are inaccessible or belong to a different primary project.')
    if lock:
        list(Sample.objects.select_for_update().filter(pk__in=sample_ids).order_by('pk'))
        if fields['source_kind'] == 'pipeline':
            source = PipelineRun.objects.select_for_update().get(pk=source.pk)
            source_state.update(status=source.status, updated_at=source.updated_at)
            list(source.steps.select_for_update().order_by('pk'))
        list(WorkItem.objects.select_for_update().filter(pk__in=work_ids).order_by('pk'))
        list(Result.objects.select_for_update().filter(work_item_id__in=work_ids).order_by('pk'))
    member_ids = set(project.members.values_list('pk', flat=True))
    audience = {notebook.owner_id}
    for relation in ['team_members', 'readers', 'editors', 'commenters', 'reviewers', 'lockers']:
        audience.update(getattr(notebook, relation).values_list('pk', flat=True))
    if len(audience | member_ids) > 500:
        raise ValidationError('This notebook audience is too large for an automatic source-access check.')
    from django.contrib.auth import get_user_model
    for reader in get_user_model().objects.filter(pk__in=audience - member_ids):
        if get_sample_access_queryset(Sample.objects.filter(pk__in=sample_ids), reader).count() != len(set(sample_ids)):
            raise PermissionDenied('A notebook reader cannot access all source samples. Choose a notebook with a compatible audience.')
    steps = []
    if fields['source_kind'] == 'pipeline':
        steps = list(source.steps.order_by('position').values('id', 'position', 'name', 'procedure_code', 'procedure_version', 'status', 'work_item_id', 'updated_at'))
        if len(steps) > 100:
            raise ValidationError('This pipeline exceeds the 100-step draft limit.')
        methods = [f"{row['position']}. Configured procedure {row['procedure_code']}@{row['procedure_version']} — {row['name']}; recorded step status {row['status']}." for row in steps]
    work = list(WorkItem.objects.filter(pk__in=work_ids).select_related('sample').order_by('pk'))
    if any(row.sample_id not in sample_ids for row in work):
        raise ValidationError('A work item no longer belongs to the selected source.')
    results = list(Result.objects.filter(work_item__in=work).select_related('work_item__sample').order_by('pk')[:501])
    if len(results) > 500:
        raise ValidationError('This source exceeds 500 results. No partial notebook draft was selected.')
    evidence = [{key: _value(getattr(row, key)) for key in ['id', 'key', 'value_type', 'value_string', 'value_number', 'value_boolean',
        'unit', 'reference_min', 'reference_max', 'qc_passed', 'qc_status', 'qc_failure_reason', 'qc_review_note', 'updated_at']} for row in results]
    for row in work:
        links.append({'entity_type': 'work_item', 'entity_public_id': str(row.public_id), 'relation_type': 'source'})
    table = [['Result', 'Sample', 'Measurement', 'Value', 'Units', 'Automated QC', 'Human review', 'Recorded reason / note']]
    for row in results:
        value = _value(row.value)
        table.append([f'R-{row.pk}', row.work_item.sample.sample_id, row.key, str(value) if value is not None else 'Not recorded', row.unit,
            'Not assessed' if row.qc_passed is None else 'Passed' if row.qc_passed else 'Failed', row.qc_status,
            (row.qc_failure_reason + ('; ' if row.qc_failure_reason and row.qc_review_note else '') + row.qc_review_note)[:1000]])
    blocks = [
        {'block_type': 'HEADING', 'data': {'text': 'Recorded run evidence — draft for review', 'level': 2}},
        {'block_type': 'RICH_TEXT', 'data': {'text': source_label + '\n' + '\n'.join(f'{key}: {value}' for key, value in plain(source_state).items())}},
        {'block_type': 'HEADING', 'data': {'text': 'Methods and recorded workflow', 'level': 2}},
        {'block_type': 'RICH_TEXT', 'data': {'text': '\n'.join(methods) + '\nActual execution details must be reviewed and completed by the scientist.'}},
        {'block_type': 'RICH_TEXT', 'data': {'text': 'User-provided method notes: ' + (fields['method_notes'] or 'Not provided.')}},
        {'block_type': 'TABLE', 'data': {'rows': table}},
        {'block_type': 'RICH_TEXT', 'data': {'text': f'{len(results)} recorded results. Notes are excerpted at 1000 characters. No scientific conclusion, completion, QC approval or release readiness is inferred.'}},
    ]
    state = {'source': source_state, 'steps': steps, 'work': [[row.pk, row.sample_id, row.status, row.qc_status, row.updated_at] for row in work],
        'samples': list(samples.order_by('pk').values('id', 'sample_id', 'status', 'updated_at')), 'evidence': evidence,
        'notebook': [notebook.pk, notebook.project_id, notebook.scope, notebook.updated_at], 'audience': sorted(audience | member_ids),
        'existing_drafts': list(notebook.experiments.order_by('-pk').values_list('pk', flat=True)[:1]),
        'template': [template.pk, template.updated_at, template.blocks, template.workflow_steps] if template else None}
    return {'fields': plain(fields), 'state': state, 'notebook': notebook, 'template': template, 'blocks': blocks, 'links': links,
        'preview': preview('Create notebook draft from run', user, project,
            [{'label': source_label, 'current': {'Results': len(results)}, 'proposed': {'Notebook': notebook.name, 'Title': fields['title'], 'Status': 'DRAFT'}}],
            proposed={'Method notes': fields['method_notes'] or 'Not provided', 'Template': template.name if template else 'No template',
                      **({'Template workflow steps': template.workflow_steps} if template else {})},
            warnings=['Creates a new draft using native notebook revisions and source links. Existing experiments and source data are unchanged.',
                      'All current notebook readers must be able to access the source samples. No result or scientific conclusion is invented.',
                      *(['The selected template initializes the displayed workflow steps and may create native internal assignment notifications.'] if template else [])]),
        'draft_excerpt': '\n'.join(methods)[:4000], 'result_count': len(results)}


def execute_notebook_draft(action):
    plan = notebook_plan(action.requested_by, action.payload['fields'], lock=True)
    assert_unchanged(action, plan)
    reason = 'Created notebook draft from recorded run'
    if plan['template']:
        experiment = instantiate_template(
            plan['template'], action.requested_by, title=plan['fields']['title'], links=plan['links'],
            extra_blocks=plan['blocks'], revision_reason=reason, audit_action='DRAFT_CREATED_FROM_RUN',
        )
        revision = experiment.current_revision
    else:
        experiment = Experiment.objects.create(notebook=plan['notebook'], title=plan['fields']['title'], created_by=action.requested_by)
        revision, _ = create_revision(experiment=experiment, actor=action.requested_by, blocks=plan['blocks'], links=plan['links'],
            reason=reason, audit_action='DRAFT_CREATED_FROM_RUN')
    experiment.refresh_from_db()
    experiment.status = Experiment.STATUS_DRAFT
    experiment.save(update_fields=['status', 'updated_at'])
    # Enrich the new, uncommitted native audit entries with their originating
    # action. No prior experiment or revision is edited.
    for event in Event.objects.filter(entity_type__iexact='experiment', entity_id=str(experiment.public_id), action='DRAFT_CREATED_FROM_RUN'):
        event.payload = {**event.payload, 'assistant_action_id': str(action.pk), 'project_id': experiment.project.pk,
                         'source_kind': plan['fields']['source_kind'], 'source_id': plan['fields']['source_id'], 'status': 'DRAFT'}
        event.save(update_fields=['payload'])
    return {'operation': 'NOTEBOOK_DRAFT', 'succeeded_count': 1, 'failed_count': 0, 'experiment_id': experiment.pk,
        'experiment_public_id': str(experiment.public_id), 'revision': revision.number, 'checksum_sha256': revision.checksum,
        'url': f'/notebook?experiment={experiment.public_id}',
        'details': [{'label': plan['fields']['title'], 'outcome': 'DRAFT created', 'results': plan['result_count'], 'revision': revision.number}],
        'message': 'Created a native notebook draft with recorded results and provenance. Review and complete its methods before any sign-off.'}
