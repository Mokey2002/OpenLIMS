"""A compact, backend-authored overview with verifiable source references."""


def build_overview(steps, citations):
    findings, unknowns, next_checks = [], [], []
    for step in steps:
        sources = [c["url"] for c in step.get("citations", []) if c.get("url")]
        if step["status"] != "completed":
            unknowns.append(step["answer"])
            continue
        facts = step.get("result_query")
        briefing = step.get("sample_briefing")
        if facts and step["operation"] == "result_detail":
            from .result_queries import explain_result
            text, missing = explain_result(facts["rows"][0])
            unknowns.extend(missing)
            next_checks.append("Review the cited result and its recorded provenance before deciding on follow-up work.")
        elif facts and facts.get("comparison_explanation"):
            explanation = facts["comparison_explanation"]
            text = explanation["text"]
            unknowns.extend(explanation["unknowns"])
            next_checks.extend(explanation["next_checks"])
            if facts["shown"] < facts["total"]:
                unknowns.append(f"Only {facts['shown']} of {facts['total']} selected results are displayed; aggregates include all matching records.")
        elif facts:
            text = (f"{facts['target']}: {facts['total']} matching results; {facts['failed']} failed checks and "
                    f"{facts['rejected']} rejected reviews. Showing {facts['shown']}. Window: {facts['window']}. {facts['filter_summary']}.")
            if facts.get("differences"):
                row = facts["differences"][0]
                text += f" Largest count difference: {row['key']}, {row['selected']} versus {row['comparison']} ({row['difference']:+d})."
                unknowns.append("Count differences do not identify their cause. Windows can have different durations; the count difference is not a failure-rate comparison.")
            if facts.get("statistics"):
                text += " QC rates use assessed checks, with unassessed results reported separately; numeric summaries are grouped by analysis, work type, key and compatible units."
            if facts["shown"] < facts["total"]:
                unknowns.append(f"Only {facts['shown']} of {facts['total']} results are displayed; narrow the filters to inspect the rest.")
            next_checks.append("Open the cited results and review their recorded values, QC decisions, and provenance.")
        elif briefing:
            text = (f"{step['arguments'].get('sample', 'Selected sample')}: {briefing['results']['total']} recorded results; "
                    f"{briefing['results']['failed_checks']} failed checks; {briefing['work']['unfinished']} unfinished work items.")
            unknowns.append("Recorded flags do not establish a scientific root cause or release approval.")
            next_checks.append("Review the flagged work and results in Sources and scope.")
        elif step["operation"] == "sop_search":
            text = f"Found {len(step.get('citations', []))} relevant approved SOP sections; matching passages and full sections are linked below."
            unknowns.append("A search match does not establish that an instruction applies to this sample.")
            next_checks.append("Check the full SOP section and its version before applying its instructions.")
        else:
            text = step["answer"].split("\n")[0]
        findings.append({"text": text, "sources": sources})
    findings = findings[:4]
    unknowns = list(dict.fromkeys(unknowns))[:4]
    next_checks = list(dict.fromkeys(next_checks))[:3]
    text = "\n".join(item["text"] for item in findings)
    if unknowns:
        text += "\n\nWhat remains unknown: " + " ".join(unknowns)
    if next_checks:
        text += "\n\nNext check: " + next_checks[0]
    return {"text": text or "The requested information was unavailable. See the step details.",
            "findings": findings, "unknowns": unknowns, "next_checks": next_checks}
