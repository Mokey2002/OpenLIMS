"""Source links built only from records already authorized by the caller."""


def sample_citations(sample, briefing):
    citations = [{"kind": "sample", "label": sample.sample_id, "url": f"/samples/{sample.pk}",
                  "scope": "Current work/result counts for this sample; flags may overlap."}]
    rows = {row["id"]: row for row in briefing["recent_results"] + briefing["attention"]["results"]}
    citations += [{"kind": "result", "label": f"R-{row['id']} · {row['key']}",
                   "url": f"/samples/{sample.pk}#result-{row['id']}",
                   "scope": "Recorded value, limits and QC evidence; checks and review decisions are separate."}
                  for row in rows.values()]
    citations += [{"kind": "work_item", "label": f"Work #{row['id']} · {row['name']}",
                   "url": f"/samples/{sample.pk}#work-item-{row['id']}",
                   "scope": "Displayed flagged work; completed/cancelled work is excluded."}
                  for row in briefing["attention"]["work_items"]]
    imports = {row["source_import"]["id"]: row["source_import"] for row in rows.values() if row.get("source_import")}
    citations += [{"kind": "import_job", "label": f"{job['instrument']} · {job['run_id'] or 'Import job ' + str(job['id'])}",
                   "url": f"/imports/{job['id']}",
                   "scope": "Linked import provenance for displayed results; it does not establish a failure cause."}
                  for job in imports.values()]
    return citations
