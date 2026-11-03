import { useState } from "react";
import { Button, Form } from "react-bootstrap";

const LABELS = { qc: "QC", period: "Date", created_from: "From", created_before: "Before", keys: "Keys", exclude_keys: "Excluded keys", instrument: "Instrument", operator: "Entered by", compare_period: "Compare with" };
const CLEAR = { period: "date", created_from: "date", created_before: "date", exclude_keys: "excluded keys", compare_period: "comparison" };

export default function AssistantResultFilters({ context, onRun, disabled }) {
  const [field, setField] = useState("instrument");
  const [value, setValue] = useState("");
  const [end, setEnd] = useState("");
  const query = context?.result_query_context;
  const navigation = context?.investigation_navigation;
  if (!query && !navigation?.can_return) return null;
  function apply(event) {
    event.preventDefault();
    const input = value.trim();
    if (!input || (field === "date" && !end)) return;
    const command = field === "date" ? `From ${input} until ${end}`
      : field === "key" ? `Only key ${input}` : field === "since" ? `Since ${input}` : `Only ${field} ${input}`;
    onRun(command);
    setValue(""); setEnd("");
  }
  return <div className="w-100 mt-2" aria-label="Result query filters">
    {navigation?.can_return && <Button size="sm" variant="outline-primary" disabled={disabled}
      onClick={() => onRun(navigation.comparison ? "Back to comparison" : "Back to results")}>Back to {navigation.comparison ? "comparison" : "results"}</Button>}
    {query && <>
      <div className="d-flex flex-wrap gap-1" aria-label="Active result filters">
        {Object.entries(query.filters || {}).map(([key, item]) => LABELS[key] && <Button key={key} size="sm" variant="outline-secondary"
          disabled={disabled} aria-label={`Remove ${LABELS[key]} filter`} onClick={() => onRun(`Clear ${CLEAR[key] || key} filter`)}>
          {LABELS[key]}: {Array.isArray(item) ? item.join(", ") : String(item).replaceAll("_", " ")} ×
        </Button>)}
        {!Object.keys(query.filters || {}).length && <span className="small text-muted">All dates, QC statuses, keys, instruments and operators</span>}
      </div>
      <details className="mt-2">
        <summary>Edit result filters</summary>
        <Form.Select size="sm" className="my-2" aria-label="Result QC filter" disabled={disabled}
          value={query.filters?.qc || "all"} onChange={event => onRun(`Only ${event.target.value} QC results`)}>
          {["all", "failed", "passed", "pending", "rejected", "approved"].map(item => <option key={item} value={item}>{item} QC</option>)}
        </Form.Select>
        <form onSubmit={apply} className="d-flex flex-wrap gap-2">
          <Form.Select size="sm" aria-label="Result filter field" value={field} disabled={disabled}
            onChange={event => { setField(event.target.value); setValue(""); setEnd(""); }}>
            <option value="instrument">Instrument code</option><option value="operator">Entered by username</option>
            <option value="key">Result key</option><option value="since">Since weekday or date</option><option value="date">Date range (end exclusive)</option>
          </Form.Select>
          <Form.Control size="sm" type={field === "date" ? "date" : "text"} value={value} maxLength={128}
            aria-label="Result filter value" required disabled={disabled} onChange={event => setValue(event.target.value)} />
          {field === "date" && <Form.Control size="sm" type="date" value={end} aria-label="Result filter end date" required disabled={disabled} onChange={event => setEnd(event.target.value)} />}
          <Button size="sm" type="submit" disabled={disabled}>Apply filter</Button>
        </form>
      </details>
    </>}
  </div>;
}
