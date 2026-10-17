"""Permission-scoped project briefings and explicit conversational follow-ups."""
import re
from django.db.models import Count, Q
from django.utils import timezone
from samples.access import get_sample_access_queryset
from samples.models import Sample
from results.models import WorkItem
from .lab_helpers import response
from .lab_reviews import _projects, _table


def project_samples(project, user):
    return get_sample_access_queryset(Sample.objects.filter(
        Q(project=project) | Q(linked_projects=project)).distinct(), user)


def project_briefing(project, user):
    samples = project_samples(project, user)
    work = WorkItem.objects.filter(sample__in=samples)
    active = ~Q(status__in=['COMPLETED', 'CANCELLED'])
    overdue = active & Q(due_at__lt=timezone.now())
    review = active & Q(qc_status__in=['REJECTED', 'RERUN_REQUIRED'])
    totals = work.aggregate(total=Count('pk'), unfinished=Count('pk', filter=active),
        overdue=Count('pk', filter=overdue), unassigned=Count('pk', filter=active & Q(assigned_to=None)),
        failed=Count('pk', filter=active & Q(status='FAILED')), qc=Count('pk', filter=review))
    groups = work.values('assigned_to_id', 'assigned_to__username').annotate(
        total=Count('pk'), unfinished=Count('pk', filter=active), overdue=Count('pk', filter=overdue),
        qc=Count('pk', filter=review), failed=Count('pk', filter=active & Q(status='FAILED'))).order_by('assigned_to__username', 'assigned_to_id')
    rows = [{**row, 'assignee': row['assigned_to__username'] or 'Unassigned'} for row in groups[:100]]
    statuses = ', '.join(f"{r['status']}: {r['count']}" for r in samples.values('status').annotate(count=Count('pk', distinct=True)).order_by('status')) or 'No samples'
    members = list(project.members.order_by('username').values_list('username', flat=True)[:101])
    member_text = ', '.join(members[:100]) or 'No members assigned'
    if len(members) > 100:
        member_text += ' (first 100 shown)'
    answer = (f"{project.code} — {project.name}\n\n"
        f"{samples.count()} accessible samples. Sample statuses: {statuses}.\n"
        f"Team members: {member_text}.\n"
        f"Work: {totals['total']} total, {totals['unfinished']} unfinished, "
        f"{totals['overdue']} overdue, {totals['unassigned']} unassigned, "
        f"{totals['failed']} failed, {totals['qc']} rejected or requiring a rerun.\n\n")
    if totals['overdue'] or totals['unassigned'] or totals['failed'] or totals['qc']:
        answer += 'Next: review overdue work, assign unowned work, and resolve failures or QC reruns where flagged below.'
    else:
        answer += 'No overdue, unassigned, failed or rejected/rerun work is recorded among unfinished items. Review remaining work and sample statuses for next steps.'
    return response(answer, context={'project_id': project.pk},
        links=[{'label': f'Open project {project.code}', 'url': f'/projects/{project.pk}'}],
        comparison=_table('Work by assignee', rows, [('assignee', 'Assignee'), ('total', 'Total work'),
            ('unfinished', 'Unfinished'), ('overdue', 'Overdue'), ('failed', 'Failed'), ('qc', 'QC rejected / rerun')],
            ['Includes accessible primary and linked samples. Team membership does not imply work assignment.',
             'Completed/cancelled work is excluded from attention counts; flags may overlap. This is not a dependency assessment.',
             'Up to 100 assignees shown; overall counts include all accessible work.']),
        suggestions=['Show me samples in that project', 'Who is assigned work in that project?'])


def project_sample_list(project, user):
    samples = project_samples(project, user).select_related('assigned_to').order_by('sample_id', 'pk')
    total = samples.count()
    shown = list(samples[:100])
    return response(f"Here are {len(shown)} of {total} accessible samples in {project.code}.",
        context={'project_id': project.pk},
        comparison=_table(f'Samples in {project.code}', [{'sample': s.sample_id, 'status': s.status,
            'assignee': s.assigned_to.username if s.assigned_to else 'Unassigned'} for s in shown],
            [('sample', 'Sample'), ('status', 'Status'), ('assignee', 'Sample assignee')],
            ['Includes primary and linked samples. Sample assignments can differ from work assignments. Up to 100 samples shown.']),
        links=[{'label': s.sample_id, 'url': f'/samples/{s.pk}'} for s in shown],
        suggestions=[f'Summarize project {project.code}'])


def project_request(message, user, context=None):
    text = str(message or '').strip().rstrip('?.!').strip()
    match = re.fullmatch(r'(?:please\s+)?(?:summarize|summarise|summary of|give me (?:a |the )?summary of|tell me about)\s+(?:the\s+)?project\s+(.+)', text, re.I)
    if not match:
        match = re.fullmatch(r'(?:summarize|summarise|tell me about)\s+(this project|that project|the project)', text, re.I)
    samples = re.fullmatch(r'(?:please\s+)?(?:show|list|show me|list all|show me all)\s+(?:the\s+)?samples\s+(?:in|for|from)\s+(.+)', text, re.I)
    if samples:
        # Preserve richer existing workflow/filter requests before the plain list.
        from .project_workflows import route_project_workflows
        workflow = route_project_workflows(message, user, context)
        if workflow is not None:
            return workflow
    assignments = re.fullmatch(r"who(?: is|'s) assigned(?: work)?(?: in| to)?\s+(.+)", text, re.I)
    selected = match or samples or assignments
    if not selected:
        return None
    target = selected.group(1).strip().strip('"\'')
    if target.lower() in {'that project', 'this project', 'the project', 'it', 'that', 'this'}:
        project_id = (context or {}).get('project_id')
        if type(project_id) is not int or not 0 < project_id < 2**63:
            return response('Which project do you mean? Tell me its exact project code.')
        projects = list(_projects(user).filter(pk=project_id)[:2])
    else:
        target = re.sub(r'^(?:the\s+)?project\s+', '', target, flags=re.I)
        projects = list(_projects(user).filter(Q(code__iexact=target) | Q(name__iexact=target)).distinct()[:2])
    if len(projects) != 1:
        return response('I could not identify one accessible project. Please give its exact project code.')
    return project_sample_list(projects[0], user) if samples else project_briefing(projects[0], user)
