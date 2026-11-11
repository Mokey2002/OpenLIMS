import { useMemo } from "react";
import { Pagination, Table } from "react-bootstrap";
import { useLanguage } from "../i18n";
import useTablePreferences from "../hooks/useTablePreferences";
import { filterAndSortRows } from "../utils/tablePreferences";
import TableViewControls from "./TableViewControls";
const NO_FILTERS = [];

export default function PersonalTable({ userId, name, title, rows, columns, emptyMessage = "No matching records.", filterOptions = NO_FILTERS }) {
  const { t } = useLanguage();
  const sorts = useMemo(() => [{ value: "", label: "Default order" }, ...columns.filter(column => column.sortable !== false).flatMap(column => [
    { value: column.key, label: column.label, direction: "↑" }, { value: `-${column.key}`, label: column.label, direction: "↓" },
  ])], [columns]);
  const defaults = useMemo(() => ({ columns: columns.filter(column => column.optional !== false).map(column => column.key), sorts: sorts.map(sort => sort.value), sort: "", pageSize: 10, filters: Object.fromEntries(filterOptions.map(filter => [filter.key, ""])) }), [columns, sorts, filterOptions]);
  const { preferences, update, reset, ready } = useTablePreferences(userId, name, defaults);
  const filtered = useMemo(() => filterAndSortRows(rows, columns, preferences), [rows, columns, preferences]);
  const pages = Math.max(1, Math.ceil(filtered.length / preferences.pageSize));
  const page = Math.min(preferences.page, pages);
  const visible = columns.filter(column => column.optional === false || preferences.columns.includes(column.key));
  if (!ready) return null;
  return <section aria-label={t(title)}>
    <TableViewControls title={t(title)} columns={columns.filter(column => column.optional !== false)} preferences={preferences} update={update} reset={reset} sorts={sorts} filterOptions={filterOptions} />
    {!filtered.length ? <div className="empty-state">{t(emptyMessage)}</div> : <Table responsive hover className="app-table"><caption className="visually-hidden">{t(title)}</caption><thead><tr>{visible.map(column => <th key={column.key} scope="col">{t(column.label)}</th>)}</tr></thead><tbody>{filtered.slice((page - 1) * preferences.pageSize, page * preferences.pageSize).map(row => <tr key={row.public_id || row.id}>{visible.map(column => <td key={column.key}>{column.render ? column.render(row) : column.value(row) ?? "—"}</td>)}</tr>)}</tbody></Table>}
    <div className="d-flex gap-3 align-items-center"><span>{filtered.length} {t("records")}</span><Pagination size="sm" className="mb-0" aria-label={`${t(title)} ${t("pagination")}`}><Pagination.Prev aria-label={t("Previous page")} disabled={page === 1} onClick={() => update({ page: page - 1 })} /><Pagination.Item active>{page} / {pages}</Pagination.Item><Pagination.Next aria-label={t("Next page")} disabled={page === pages} onClick={() => update({ page: page + 1 })} /></Pagination></div>
  </section>;
}
