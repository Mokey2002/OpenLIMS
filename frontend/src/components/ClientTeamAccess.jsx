import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";
import { useLanguage } from "../i18n";

const emptyPermissions = { can_submit: false, can_view_results: false };

function TeamMembers({ team, requesters, onSaved }) {
  const { t } = useLanguage();
  const [account, setAccount] = useState("");
  const [permissions, setPermissions] = useState(emptyPermissions);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const choices = new Map(requesters.map(row => [row.id, row.username]));
  for (const member of team.memberships) choices.set(member.user, member.username);

  function selectAccount(id) {
    const membership = team.memberships.find(row => String(row.user) === id);
    setAccount(id);
    setPermissions(membership ? {
      can_submit: membership.can_submit, can_view_results: membership.can_view_results,
    } : emptyPermissions);
    setSaved(false);
    setError("");
  }

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const membership = await apiPost(`/api/client-teams/${team.id}/member-access/`, {
        user: Number(account), ...permissions,
      });
      onSaved(membership);
      setSaved(true);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setSaving(false);
    }
  }

  return <>
    {team.memberships.length > 0 && <Table responsive className="app-table mb-3">
      <thead><tr>
        <th>{t("Requester account")}</th><th>{t("Submit requests")}</th><th>{t("View team requests and results")}</th>
      </tr></thead>
      <tbody>{team.memberships.map(member => <tr key={member.user}>
        <td><Button type="button" variant="link" className="p-0" disabled={saving}
          onClick={() => selectAccount(String(member.user))}>{member.username}</Button></td>
        <td>{t(member.can_submit ? "Yes" : "No")}</td>
        <td>{t(member.can_view_results ? "Yes" : "No")}</td>
      </tr>)}</tbody>
    </Table>}
    {choices.size ? <Form onSubmit={save} aria-label={t("Client team member access")}>
      <fieldset disabled={saving}>
        <Form.Group controlId="client-team-requester">
          <Form.Label>{t("Requester account")}</Form.Label>
          <Form.Select required value={account} onChange={event => selectAccount(event.target.value)}>
            <option value="">{t("Choose requester account")}</option>
            {[...choices].map(([id, username]) => <option key={id} value={id}>{username}</option>)}
          </Form.Select>
        </Form.Group>
        <div className="my-3">
          <Form.Check id="client-team-submit" label={t("Submit requests")} checked={permissions.can_submit}
            onChange={event => { setSaved(false); setPermissions({ ...permissions, can_submit: event.target.checked }); }} />
          <Form.Check id="client-team-results" label={t("View team requests and results")} checked={permissions.can_view_results}
            onChange={event => { setSaved(false); setPermissions({ ...permissions, can_view_results: event.target.checked }); }} />
          <Form.Text>{t("Clear both permissions to revoke team access.")}</Form.Text>
        </div>
        <Button type="submit" disabled={!account}>{t("Save access")}</Button>
      </fieldset>
    </Form> : <p className="text-muted mb-0">{t("Add a requester account to this project to grant team access.")}</p>}
    {error && <Alert variant="danger" className="mt-3 mb-0" role="alert">{error}</Alert>}
    {saved && <p className="text-success mt-3 mb-0" role="status">{t("Client team access saved.")}</p>}
  </>;
}

export default function ClientTeamAccess({ projectId, projectMembers }) {
  const { t } = useLanguage();
  const [data, setData] = useState(null);
  const [teamId, setTeamId] = useState("");
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const request = new AbortController();
    apiGet(`/api/client-teams/?project=${projectId}`, { signal: request.signal }).then(
      result => { if (!request.signal.aborted) setData(result); },
      failure => { if (!request.signal.aborted) setError(failure.message); },
    );
    return () => request.abort();
  }, [projectId, projectMembers]);

  const team = data?.teams.find(row => String(row.id) === teamId) ?? data?.teams[0];

  async function createTeam(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const created = await apiPost("/api/client-teams/", { name: name.trim(), project: Number(projectId) });
      setData(current => ({ ...current, teams: [...current.teams, created] }));
      setTeamId(String(created.id));
      setName("");
    } catch (failure) {
      setError(failure.message);
    } finally {
      setSaving(false);
    }
  }

  function updateMembership(membership) {
    setData(current => ({
      ...current,
      teams: current.teams.map(row => row.id === team.id ? {
        ...row, memberships: [...row.memberships.filter(member => member.user !== membership.user), membership]
          .sort((left, right) => left.username.localeCompare(right.username)),
      } : row),
    }));
  }

  return <Card className="app-card"><Card.Body>
    <h2 className="h5">{t("Client teams")}</h2>
    <p className="text-muted">{t("Grant requester accounts access to submit for a team or view its released results.")}</p>
    {error && <Alert variant="danger" role="alert">{error}</Alert>}
    {data ? <>
      <Form onSubmit={createTeam} className="mb-3">
        <Row className="g-2 align-items-end">
          <Col><Form.Group controlId="new-client-team">
            <Form.Label>{t("New client team name")}</Form.Label>
            <Form.Control required maxLength={100} value={name} onChange={event => setName(event.target.value)} />
          </Form.Group></Col>
          <Col xs="auto"><Button type="submit" disabled={saving || !name.trim()}>{t("Create client team")}</Button></Col>
        </Row>
      </Form>
      {team && <>
        <Form.Group controlId="project-client-team" className="mb-3">
          <Form.Label>{t("Client team")}</Form.Label>
          <Form.Select value={team.id} onChange={event => setTeamId(event.target.value)}>
            {data.teams.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
          </Form.Select>
        </Form.Group>
        <TeamMembers key={team.id} team={team} requesters={data.requesters} onSaved={updateMembership} />
      </>}
    </> : !error && <p role="status" className="mb-0">{t("Loading…")}</p>}
  </Card.Body></Card>;
}

export function RequestClientTeam({ requestId, projectId }) {
  const { t } = useLanguage();
  const endpoint = `/api/workflow-requests/${requestId}/client-team/`;
  const [data, setData] = useState(null);
  const [team, setTeam] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const request = new AbortController();
    apiGet(endpoint, { signal: request.signal }).then(
      result => {
        if (request.signal.aborted) return;
        setData(result);
        setTeam(String(result.client_team ?? ""));
      },
      failure => { if (!request.signal.aborted) setError(failure.message); },
    );
    return () => request.abort();
  }, [endpoint]);

  async function save(event) {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const result = await apiPost(endpoint, { client_team: team ? Number(team) : null });
      setData(result);
      setTeam(String(result.client_team ?? ""));
      setSaved(true);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setSaving(false);
    }
  }

  const canShare = data && (data.teams.length > 0 || data.client_team);
  return <Card className="app-card"><Card.Body>
    <h2 className="h5">{t("Client team sharing")}</h2>
    {error && <Alert variant="danger" role="alert">{error}</Alert>}
    {canShare && <Form onSubmit={save}>
      <Form.Group controlId="request-client-team" className="mb-2">
        <Form.Label>{t("Client team")}</Form.Label>
        <Form.Select value={team} disabled={saving} onChange={event => { setTeam(event.target.value); setSaved(false); }}>
          <option value="">{t("Private to the requester")}</option>
          {data.client_team && !data.teams.some(row => row.id === data.client_team)
            && <option value={data.client_team} disabled>{data.client_team_name}</option>}
          {data.teams.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
        </Form.Select>
        <Form.Text>{t("Team members need results access to see shared requests and released reports.")}</Form.Text>
      </Form.Group>
      <Button size="sm" type="submit" disabled={saving || team === String(data.client_team ?? "")}>{t("Save sharing")}</Button>
    </Form>}
    {data && !canShare && <p className="text-muted mb-0">
      {t("Add the requester to a client team before sharing this request.")}{" "}
      <Link to={`/projects/${projectId}`}>{t("Open project")}</Link>
    </p>}
    {!data && !error && <p role="status" className="mb-0">{t("Loading…")}</p>}
    {saved && <p className="text-success mt-2 mb-0" role="status">{t("Client team sharing saved.")}</p>}
  </Card.Body></Card>;
}
