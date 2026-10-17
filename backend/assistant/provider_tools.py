"""Shared, bounded provider dispatch. Models propose; existing services authorize."""
import math
from importlib import import_module

# Public catalog doubles as the dispatch allow-list. No model-supplied module names.
COMMAND_TOOLS = {
    "analytics": ("analytics", "route_safe_analytics", "Group samples by project; Which instrument has the highest QC failure rate?"),
    "attention": ("attention", "route_attention_summary", "What needs attention?"),
    "barcode": ("barcode_operations", "route_barcode_operations", "Create barcode labels for batch B-100; Reprint barcode labels for sample S-100"),
    "calculation": ("calculations", "route_worklist_or_calculation", "How many samples are in QC?; What percentage of migration rows failed?"),
    "chart": ("charts", "route_assistant_chart", "Chart samples by status"),
    "comparison": ("comparisons", "route_comparison_analytics", "Compare projects ALPHA and BETA; Find unusual results in project ALPHA; Where are samples getting stuck in project ALPHA?; Export this comparison as PDF"),
    "confirmed_action": ("action_routes", "route_confirmed_action_proposal", "Run alignment for sequences 1, 2; Run import job 1; Create migration mappings for migration job 1"),
    "inventory": ("inventory_operations", "route_inventory_operations", "Move sample S-100 to freezer F2, rack R4, box B3; Reserve two units of reagent R-100 for Project Alpha; Mark lot L-204 as expired; Show inventory below its reorder level; Which reagents expire in the next 30 days?"),
    "investigation": ("investigations", "route_investigation_workbench", "Investigate why sample S-100 failed QC; Graph failures by operator; Export this investigation as PDF"),
    "notifications": ("notification_operations", "route_notification_operations", "List notification subscriptions; Cancel notification subscription 1; Notify me when sample S-100 is approved"),
    "qc": ("qc_operations", "route_qc_operations", "Show samples needing QC review; Show failed QC results; Approve result R-1 because the control passed; Reject result R-1 because the control failed; Flag result R-1 for review; Assign failed QC results to maria"),
    "reporting": ("reporting_operations", "route_reporting_operations", "Generate a PDF report for Project Alpha; Show approvals by maria"),
    "samples": ("sample_operations", "route_sample_management", "Find sample S-100; Register 3 DNA samples in project ALPHA; Summarize sample S-100; Archive sample S-100"),
    "sequences": ("sequences", "route_assistant_sequence", "Find sequences for sample S-100; BLAST sequence 1; Export sequences as FASTA"),
    "sop": ("sop_operations", "route_sop_assistant", "What does the SOP say about sample storage?"),
    "work_items": ("workitem_operations", "route_workitem_operations", "Create sequencing work for samples in batch B-100; Assign today's sequencing work to maria; Show pending work items"),
    "guided_actions": ("guided_actions", "route_guided_action", "Assign step 1 for sample S-100 to maria; Add result concentration = 43 to step 1 for sample S-100 unit ng/uL"),
    "sample_guidance": ("sample_guidance", "route_sample_guidance", "What next for sample S-100?"),
    "project_workflows": ("project_workflows", "route_project_workflows", "Which samples in project ALPHA are overdue and unassigned?; Explain this query; Refresh results"),
    "monitoring": ("monitoring", "route_system_monitoring", "Show system status"),
    "identity": ("tools", "answer_current_user", "Who am I?"),
    "record_search": ("tools", "search_samples", "Find sample S-100; Summarize project ALPHA"),
    "migration": ("tools", "search_migration_jobs", "Show failed migration jobs; Show skipped migration rows (admin only)"),
}
# arg names are positional service arguments; strings preserve exact record identity.
DIRECT_TOOLS = {
    "sample_history": ("lab_helpers", "sample_history", ("sample",)),
    "similar_experiments": ("lab_helpers", "similar_experiments", ("topic",)),
    "reagent_plan": ("lab_helpers", "inventory_plan", ("count", "procedure", "version")),
    "project_update": ("lab_helpers", "project_update", ("project",)),
    "quarantine_impact": ("lab_reviews", "quarantine_impact", ("lot",)),
    "data_quality": ("lab_reviews", "project_quality", ("project",)),
    "workflow_draft": ("lab_collaboration", "workflow_draft", ("procedures",)),
    "handover": ("lab_collaboration", "handover", ("source", "recipient")),
    "compare_runs": ("lab_collaboration", "compare_runs", ("left", "right")),
}
NO_CONTEXT = {"attention", "calculation", "chart", "confirmed_action", "identity"}


def catalog_prompt():
    lines = [f"- {name}: arguments {', '.join(fields)}" for name, (_, _, fields) in DIRECT_TOOLS.items()]
    lines += [f"- {name}: arguments command (supported examples: {example})" for name, (_, _, example) in COMMAND_TOOLS.items()]
    return "\n".join(lines)


def validate_tool_plan(data, threshold=0.65):
    if not isinstance(data, dict) or data.get("route") != "tool":
        return None
    if set(data) - {"route", "tool", "arguments", "confidence", "accepted", "provider"}:
        return None
    tool = data.get("tool")
    if not isinstance(tool, str) or tool not in {*DIRECT_TOOLS, *COMMAND_TOOLS}:
        return None
    confidence = data.get("confidence")
    if type(confidence) not in (int, float) or not math.isfinite(confidence) or not threshold <= confidence <= 1:
        return None
    args = data.get("arguments")
    fields = DIRECT_TOOLS[tool][2] if tool in DIRECT_TOOLS else ("command",)
    if not isinstance(args, dict) or set(args) - set(fields):
        return None
    for key, value in args.items():
        if key == "count":
            if type(value) is not int or not 1 <= value <= 100000:
                return None
        elif not isinstance(value, str) or len(value) > (2000 if key == "command" else 1000) or any(ord(c) < 32 for c in value) or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            return None
    return {"route": "tool", "tool": tool, "arguments": args, "confidence": confidence, "accepted": True}


def dispatch_tool(plan, user, context=None):
    from .lab_helpers import response
    from core.permissions import is_admin
    validated = validate_tool_plan(plan)
    if not validated or not user or not user.is_authenticated:
        return response("I could not validate that feature request. Please restate the action and exact record identifiers.")
    tool, args = validated["tool"], validated["arguments"]
    if tool == "handover":
        args = {key: user.username if value.casefold() in {"me", "myself", "mí"} else value for key, value in args.items()}
        plan = {**plan, "arguments": args}
    fields = DIRECT_TOOLS[tool][2] if tool in DIRECT_TOOLS else ("command",)
    missing = [field for field in fields if field != "version" and (field not in args or (isinstance(args[field], str) and not args[field].strip()))]
    from .provider_conversation import QUESTIONS, remember
    token = remember(plan, user)
    if missing:
        return response(QUESTIONS[missing[0]], clarification={"required": True, "fields": missing},
                        context={"provider_conversation": token} if token else {})
    if tool in DIRECT_TOOLS:
        module, name, fields = DIRECT_TOOLS[tool]
        fn = getattr(import_module(f"assistant.{module}"), name)
        result = fn(*(args.get(field) for field in fields), user=user)
    else:
        module, name, _ = COMMAND_TOOLS[tool]
        fn = getattr(import_module(f"assistant.{module}"), name)
        command = args["command"]
        if tool == "migration":
            # Legacy migration search has no per-user argument. Do not expose
            # global jobs/row payloads to non-administrators through this bridge.
            if not is_admin(user):
                return response("Director/admin access is required for migration search through the assistant.")
            from .tools import search_migration_rows
            result = search_migration_rows(command) if "row" in command.lower() else fn(command)
        elif tool == "record_search":
            from .tools import search_projects
            from .project_conversation import project_request
            result = project_request(command, user, context)
            if result is None:
                result = search_projects(command, user) if "project" in command.lower() else fn(command, user)
        elif tool in NO_CONTEXT:
            result = fn(command, user)
        else:
            result = fn(command, user, context=context or {})
    if not result:
        return response("That wording is not supported by the selected feature. Please specify the exact action and identifiers; nothing was changed.", clarification={"required": True})
    # Preserve deterministic evidence, drafts and server-generated confirmation
    # proposals; never let a second model call rewrite or manufacture these.
    result = {**result, "skip_llm": True}
    if token:
        result["context"] = {**(result.get("context") or {}), "provider_conversation": token}
    result["interpretation"] = {"provider": plan.get("provider", "llm"), "tool": tool, "arguments": args}
    return result
