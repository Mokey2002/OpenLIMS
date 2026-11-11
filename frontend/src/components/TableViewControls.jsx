import { useId } from "react";
import { Button, Form } from "react-bootstrap";
import { useLanguage } from "../i18n";
import { PAGE_SIZES } from "../utils/tablePreferences";

export default function TableViewControls({ title, columns, preferences, update, reset, sorts, search = true, filterOptions = [] }) {
  const id = useId();
  const { t } = useLanguage();
  return <div className="mb-3" aria-label={`${title} ${t("table settings")}`}>
    <div className="d-flex flex-wrap gap-2 align-items-end">
      {filterOptions.map(filter => <Form.Group key={filter.key} controlId={`${id}-${filter.key}-filter`}><Form.Label>{t(filter.label)}</Form.Label><Form.Select size="sm" value={preferences.filters[filter.key]} onChange={event => update({ filters: { ...preferences.filters, [filter.key]: event.target.value }, page: 1 })}><option value="">{t("All")}</option>{filter.options.map(option => <option key={option} value={option}>{t(option)}</option>)}</Form.Select></Form.Group>)}
      {search && <Form.Group controlId={`${id}-search`}><Form.Label>{t("Search this table")}</Form.Label><Form.Control size="sm" type="search" value={preferences.query} maxLength={200} onChange={event => update({ query: event.target.value, page: 1 })} /></Form.Group>}
      <Form.Group controlId={`${id}-sort`}><Form.Label>{t("Sort by")}</Form.Label><Form.Select size="sm" value={preferences.sort} onChange={event => update({ sort: event.target.value, page: 1 })}>{sorts.map(item => <option key={item.value} value={item.value}>{t(item.label)}{item.direction ? ` ${item.direction}` : ""}</option>)}</Form.Select></Form.Group>
      <Form.Group controlId={`${id}-size`}><Form.Label>{t("Rows per page")}</Form.Label><Form.Select size="sm" value={preferences.pageSize} onChange={event => update({ pageSize: Number(event.target.value), page: 1 })}>{PAGE_SIZES.map(size => <option key={size}>{size}</option>)}</Form.Select></Form.Group>
      <Button size="sm" variant="outline-secondary" onClick={reset}>{t("Reset table view")}</Button>
    </div>
    <details className="mt-2"><summary>{t("Visible columns")}</summary><fieldset className="mt-2"><legend className="visually-hidden">{title} {t("Visible columns")}</legend>{columns.map(column => <Form.Check inline key={column.key} id={`${id}-${column.key}`} label={t(column.label)} checked={preferences.columns.includes(column.key)} disabled={preferences.columns.length === 1 && preferences.columns.includes(column.key)} onChange={event => update({ columns: event.target.checked ? [...preferences.columns, column.key] : preferences.columns.filter(key => key !== column.key) })} />)}</fieldset></details>
    <div className="feed-meta mt-1">{t("This table view is remembered for your account in this browser.")}</div>
  </div>;
}
