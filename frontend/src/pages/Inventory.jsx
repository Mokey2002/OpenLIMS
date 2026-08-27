import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Table,
} from "react-bootstrap";
import { apiGet, apiGetAll, apiPost } from "../api";
import { canWrite, isAdmin } from "../authz";
import ConfirmedOperationCard from "../components/ConfirmedOperationCard";
import useConfirmedOperation from "../hooks/useConfirmedOperation";

export default function Inventory() {
  const [locations, setLocations] = useState([]);
  const [containers, setContainers] = useState([]);
  const [inventoryItems, setInventoryItems] = useState([]);
  const [inventoryLots, setInventoryLots] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [cycleCounts, setCycleCounts] = useState([]);
  const [projects, setProjects] = useState([]);
  const [me, setMe] = useState(null);
  const [err, setErr] = useState("");
  const [locationName, setLocationName] = useState("");
  const [locationCode, setLocationCode] = useState("");
  const [locationParent, setLocationParent] = useState("");
  const [locationKind, setLocationKind] = useState("FREEZER");
  const [containerId, setContainerId] = useState("");
  const [containerKind, setContainerKind] = useState("BOX");
  const [containerLocation, setContainerLocation] = useState("");
  const [containerRows, setContainerRows] = useState("8");
  const [containerColumns, setContainerColumns] = useState("12");
  const [operationType, setOperationType] = useState("RESERVE");
  const [itemId, setItemId] = useState("");
  const [lotId, setLotId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [unit, setUnit] = useState("");
  const [ledgerForm, setLedgerForm] = useState({ barcode: "", lot: "", operation: "CONSUME", amount: "", unit: "", reason: "", to_location: "", to_container: "" });
  const [barcodeForm, setBarcodeForm] = useState({ lot: "", barcode: "" });

  async function load() {
    setErr("");
    try {
      const [locs, conts, items, lots, reservationRows, projectRows, meData, transactionRows, alertRows, countRows] =
        await Promise.all([
          apiGetAll("/api/locations/"),
          apiGetAll("/api/containers/"),
          apiGetAll("/api/inventory-items/"),
          apiGetAll("/api/inventory-lots/"),
          apiGetAll("/api/inventory-reservations/"),
          apiGetAll("/api/projects/"),
          apiGet("/api/me/"),
          apiGetAll("/api/inventory-transactions/"),
          apiGetAll("/api/inventory-alerts/"),
          apiGetAll("/api/inventory-cycle-counts/"),
        ]);
      setLocations(locs);
      setContainers(conts);
      setInventoryItems(items);
      setInventoryLots(lots);
      setReservations(reservationRows);
      setProjects(projectRows);
      setMe(meData);
      setTransactions(transactionRows);
      setAlerts(alertRows);
      setCycleCounts(countRows);
    } catch (requestError) {
      setErr(requestError.message || String(requestError));
    }
  }

  const operation = useConfirmedOperation(load);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  async function createLocation(event) {
    event.preventDefault();
    setErr("");
    try {
      await apiPost("/api/locations/", {
        code: locationCode || null,
        name: locationName,
        kind: locationKind,
        parent: locationParent ? Number(locationParent) : null,
      });
      setLocationName("");
      setLocationCode("");
      setLocationParent("");
      setLocationKind("FREEZER");
      await load();
    } catch (requestError) {
      setErr(requestError.message || String(requestError));
    }
  }

  async function createContainer(event) {
    event.preventDefault();
    setErr("");
    try {
      await apiPost("/api/containers/", {
        container_id: containerId,
        kind: containerKind,
        location: Number(containerLocation),
        rows: containerKind === "PLATE" ? Number(containerRows) : null,
        columns: containerKind === "PLATE" ? Number(containerColumns) : null,
      });
      setContainerId("");
      setContainerKind("BOX");
      setContainerLocation("");
      await load();
    } catch (requestError) {
      setErr(requestError.message || String(requestError));
    }
  }

  async function proposeInventoryOperation(event) {
    event.preventDefault();
    const lot = inventoryLots.find((row) => String(row.id) === String(lotId));

    if (operationType === "RESERVE") {
      const item = inventoryItems.find((row) => String(row.id) === String(itemId));
      const project = projects.find((row) => String(row.id) === String(projectId));
      if (!item || !project || !quantity || !unit.trim()) return;
      await operation.propose(
        `Reserve ${quantity} ${unit.trim()} of reagent ${item.code} for ${project.code}`
      );
      return;
    }

    if (!lot) return;
    if (operationType === "CONSUME") {
      if (!quantity || !unit.trim()) return;
      await operation.propose(
        `Record consumption of ${quantity} ${unit.trim()} from lot ${lot.lot_code}`
      );
      return;
    }

    await operation.propose(`Mark lot ${lot.lot_code} as expired`);
  }

  async function executeLedgerOperation(event) {
    event.preventDefault();
    setErr("");
    try {
      await apiPost("/api/inventory-transactions/", {
        barcode: ledgerForm.barcode || undefined,
        lot: ledgerForm.barcode ? undefined : Number(ledgerForm.lot),
        operation: ledgerForm.operation,
        amount: ledgerForm.amount || 0,
        unit: ledgerForm.unit,
        reason: ledgerForm.reason,
        to_location: ledgerForm.to_location ? Number(ledgerForm.to_location) : null,
        to_container: ledgerForm.to_container ? Number(ledgerForm.to_container) : null,
      });
      setLedgerForm({ barcode: "", lot: "", operation: "CONSUME", amount: "", unit: "", reason: "", to_location: "", to_container: "" });
      await load();
    } catch (requestError) {
      setErr(requestError.message || String(requestError));
    }
  }

  async function assignLotBarcode(event) {
    event.preventDefault();
    const lot = inventoryLots.find((row) => String(row.id) === barcodeForm.lot);
    if (!lot) return;
    try {
      await apiPost("/api/inventory-barcodes/", {
        barcode: barcodeForm.barcode,
        entity_type: "inventory_lot",
        target_public_id: lot.public_id,
      });
      setBarcodeForm({ lot: "", barcode: "" });
    } catch (requestError) {
      setErr(requestError.message || String(requestError));
    }
  }

  async function refreshAlerts() {
    await apiPost("/api/inventory-alerts/refresh/", {});
    await load();
  }

  const userIsAdmin = isAdmin(me);
  const writable = canWrite(me);

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Inventory</h1>
          <p className="page-subtitle">
            Manage storage, reserve reagents, record lot consumption, and expire lots.
          </p>
        </div>
        <Button variant="outline-dark" size="sm" onClick={load}>Refresh</Button>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      {userIsAdmin && (
        <Row className="g-4 mb-4">
          <Col lg={6}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Create Location</h5>
                <Form onSubmit={createLocation}>
                  <Row className="g-2">
                    <Col md={3}><Form.Control placeholder="Location code" value={locationCode} onChange={(event) => setLocationCode(event.target.value)} /></Col>
                    <Col md={4}><Form.Control placeholder="Location name" value={locationName} onChange={(event) => setLocationName(event.target.value)} /></Col>
                    <Col md={3}><Form.Select value={locationKind} onChange={(event) => setLocationKind(event.target.value)}><option value="SITE">SITE</option><option value="BUILDING">BUILDING</option><option value="LABORATORY">LABORATORY</option><option value="ROOM">ROOM</option><option value="FREEZER">FREEZER</option><option value="SHELF">SHELF</option><option value="RACK">RACK</option><option value="BOX">BOX</option><option value="WELL">WELL</option></Form.Select></Col>
                    <Col md={2}><Button type="submit" variant="dark" className="w-100">Create</Button></Col>
                    <Col xs={12}><Form.Select value={locationParent} onChange={(event) => setLocationParent(event.target.value)}><option value="">Top-level location</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.path || location.name}</option>)}</Form.Select></Col>
                  </Row>
                </Form>
              </Card.Body>
            </Card>
          </Col>
          <Col lg={6}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Create Container</h5>
                <Form onSubmit={createContainer}>
                  <Row className="g-2">
                    <Col md={4}><Form.Control placeholder="Container ID" value={containerId} onChange={(event) => setContainerId(event.target.value)} /></Col>
                    <Col md={3}><Form.Select value={containerKind} onChange={(event) => setContainerKind(event.target.value)}><option value="BOX">BOX</option><option value="RACK">RACK</option><option value="PLATE">PLATE</option><option value="TUBE">TUBE</option></Form.Select></Col>
                    <Col md={3}><Form.Select value={containerLocation} onChange={(event) => setContainerLocation(event.target.value)}><option value="">Location</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</Form.Select></Col>
                    <Col md={2}><Button type="submit" variant="dark" className="w-100">Create</Button></Col>
                    {containerKind === "PLATE" && <><Col md={6}><Form.Control type="number" min="1" required placeholder="Plate rows" value={containerRows} onChange={(event) => setContainerRows(event.target.value)} /></Col><Col md={6}><Form.Control type="number" min="1" required placeholder="Plate columns" value={containerColumns} onChange={(event) => setContainerColumns(event.target.value)} /></Col></>}
                  </Row>
                </Form>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      )}

      {writable ? (
        <Card className="app-card mb-4">
          <Card.Body>
            <div className="toolbar-row"><div><h5 className="section-title mb-1">Scan-based immutable transaction</h5><div className="feed-meta">Receive, move, transfer, count, consume, adjust, quarantine, dispose, or return material. Every operation records before/after quantity, actor, reason, and linked execution provenance.</div></div><Badge bg="dark">Inventory v2</Badge></div>
            <Form onSubmit={executeLedgerOperation} className="mt-3"><Row className="g-2 align-items-end"><Col md={2}><Form.Label>Scanned barcode</Form.Label><Form.Control value={ledgerForm.barcode} onChange={(event) => setLedgerForm({ ...ledgerForm, barcode: event.target.value })} placeholder="LOT:..." /></Col><Col md={2}><Form.Label>Or choose lot</Form.Label><Form.Select value={ledgerForm.lot} onChange={(event) => { const lot = inventoryLots.find((row) => String(row.id) === event.target.value); setLedgerForm({ ...ledgerForm, lot: event.target.value, unit: lot?.unit || "" }); }}><option value="">Lot</option>{inventoryLots.map((lot) => <option key={lot.id} value={lot.id}>{lot.lot_code}</option>)}</Form.Select></Col><Col md={2}><Form.Label>Operation</Form.Label><Form.Select value={ledgerForm.operation} onChange={(event) => setLedgerForm({ ...ledgerForm, operation: event.target.value })}>{["RECEIVE", "MOVE", "TRANSFER", "COUNT", "CONSUME", "ADJUST", "QUARANTINE", "DISPOSE", "RETURN"].map((name) => <option key={name}>{name}</option>)}</Form.Select></Col><Col md={1}><Form.Label>Amount</Form.Label><Form.Control type="number" step="any" value={ledgerForm.amount} onChange={(event) => setLedgerForm({ ...ledgerForm, amount: event.target.value })} /></Col><Col md={1}><Form.Label>Unit</Form.Label><Form.Control value={ledgerForm.unit} onChange={(event) => setLedgerForm({ ...ledgerForm, unit: event.target.value })} /></Col><Col md={3}><Form.Label>Required reason</Form.Label><Form.Control required value={ledgerForm.reason} onChange={(event) => setLedgerForm({ ...ledgerForm, reason: event.target.value })} /></Col><Col md={1}><Button type="submit" className="w-100">Record</Button></Col>{["MOVE", "TRANSFER"].includes(ledgerForm.operation) && <><Col md={6}><Form.Select value={ledgerForm.to_location} onChange={(event) => setLedgerForm({ ...ledgerForm, to_location: event.target.value, to_container: "" })}><option value="">Destination location</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.path || location.name}</option>)}</Form.Select></Col><Col md={6}><Form.Select value={ledgerForm.to_container} onChange={(event) => setLedgerForm({ ...ledgerForm, to_container: event.target.value })}><option value="">Destination container</option>{containers.filter((container) => !ledgerForm.to_location || String(container.location) === ledgerForm.to_location).map((container) => <option key={container.id} value={container.id}>{container.path}</option>)}</Form.Select></Col></>}</Row></Form>
            <Form onSubmit={assignLotBarcode} className="mt-3"><Row className="g-2"><Col md={5}><Form.Select required value={barcodeForm.lot} onChange={(event) => setBarcodeForm({ ...barcodeForm, lot: event.target.value })}><option value="">Assign barcode to lot</option>{inventoryLots.map((lot) => <option key={lot.id} value={lot.id}>{lot.lot_code}</option>)}</Form.Select></Col><Col md={5}><Form.Control required value={barcodeForm.barcode} onChange={(event) => setBarcodeForm({ ...barcodeForm, barcode: event.target.value })} placeholder="Barcode identity" /></Col><Col md={2}><Button type="submit" variant="outline-dark" className="w-100">Assign barcode</Button></Col></Row></Form>
          </Card.Body>
        </Card>
      ) : null}

      {writable ? (
        <Card className="app-card mb-4">
          <Card.Body>
            <h5 className="section-title">Inventory operation</h5>
            <Form onSubmit={proposeInventoryOperation}>
              <Row className="g-3 align-items-end">
                <Col md={3}>
                  <Form.Label>Operation</Form.Label>
                  <Form.Select value={operationType} onChange={(event) => setOperationType(event.target.value)}>
                    <option value="RESERVE">Reserve reagent</option>
                    <option value="CONSUME">Consume from lot</option>
                    <option value="EXPIRE">Mark lot expired</option>
                  </Form.Select>
                </Col>
                {operationType === "RESERVE" ? (
                  <>
                    <Col md={3}>
                      <Form.Label>Reagent</Form.Label>
                      <Form.Select value={itemId} onChange={(event) => {
                        setItemId(event.target.value);
                        const item = inventoryItems.find((row) => String(row.id) === event.target.value);
                        setUnit(item?.default_unit || "");
                      }}>
                        <option value="">Select reagent</option>
                        {inventoryItems.filter((item) => item.category === "REAGENT").map((item) => <option key={item.id} value={item.id}>{item.code} — {item.name}</option>)}
                      </Form.Select>
                    </Col>
                    <Col md={3}>
                      <Form.Label>Project</Form.Label>
                      <Form.Select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                        <option value="">Select project</option>
                        {projects.map((project) => <option key={project.id} value={project.id}>{project.code} — {project.name}</option>)}
                      </Form.Select>
                    </Col>
                  </>
                ) : (
                  <Col md={6}>
                    <Form.Label>Lot</Form.Label>
                    <Form.Select value={lotId} onChange={(event) => {
                      setLotId(event.target.value);
                      const lot = inventoryLots.find((row) => String(row.id) === event.target.value);
                      setUnit(lot?.unit || "");
                    }}>
                      <option value="">Select lot</option>
                      {inventoryLots.map((lot) => <option key={lot.id} value={lot.id}>{lot.lot_code} — {lot.item_code} ({lot.available_quantity} {lot.unit} available)</option>)}
                    </Form.Select>
                  </Col>
                )}
                {operationType !== "EXPIRE" && (
                  <>
                    <Col md={2}>
                      <Form.Label>Quantity</Form.Label>
                      <Form.Control type="number" min="0" step="any" value={quantity} onChange={(event) => setQuantity(event.target.value)} />
                    </Col>
                    <Col md={1}>
                      <Form.Label>Unit</Form.Label>
                      <Form.Control value={unit} onChange={(event) => setUnit(event.target.value)} />
                    </Col>
                  </>
                )}
                <Col md={operationType === "EXPIRE" ? 3 : 12}>
                  <Button type="submit" variant="dark">Preview operation</Button>
                </Col>
              </Row>
            </Form>
          </Card.Body>
        </Card>
      ) : me ? (
        <Alert variant="info">Inventory operations require a Tech or Director role.</Alert>
      ) : null}

      <ConfirmedOperationCard operation={operation} />

      <Row className="g-4 mt-1">
        <Col lg={5}>
          <Card className="app-card h-100"><Card.Body>
            <h5 className="section-title">Reagents and supplies</h5>
            {inventoryItems.length === 0 ? <div className="empty-state">No inventory items yet.</div> : (
              <Table responsive hover className="app-table"><thead><tr><th>Code</th><th>Name</th><th>Available</th><th>Reorder</th></tr></thead><tbody>{inventoryItems.map((item) => <tr key={item.id}><td>{item.code}</td><td>{item.name}</td><td>{item.available_quantity} {item.default_unit}</td><td>{item.reorder_level} {item.default_unit}</td></tr>)}</tbody></Table>
            )}
          </Card.Body></Card>
        </Col>
        <Col lg={7}>
          <Card className="app-card h-100"><Card.Body>
            <h5 className="section-title">Lots</h5>
            {inventoryLots.length === 0 ? <div className="empty-state">No inventory lots yet.</div> : (
              <Table responsive hover className="app-table"><thead><tr><th>Lot</th><th>Item</th><th>Available</th><th>Expires</th><th>Status</th><th>Container</th></tr></thead><tbody>{inventoryLots.map((lot) => <tr key={lot.id}><td>{lot.lot_code}</td><td>{lot.item_code}</td><td>{lot.available_quantity} {lot.unit}</td><td>{lot.expiration_date || "—"}</td><td><Badge bg={lot.status === "ACTIVE" ? "success" : lot.status === "EXPIRED" ? "danger" : "secondary"}>{lot.status}</Badge></td><td>{lot.container_code || lot.location_name || "—"}</td></tr>)}</tbody></Table>
            )}
          </Card.Body></Card>
        </Col>
      </Row>

      <Card className="app-card mt-4">
        <Card.Body>
          <h5 className="section-title">Reservations</h5>
          {reservations.length === 0 ? <div className="empty-state">No accessible reservations.</div> : (
            <Table responsive hover className="app-table"><thead><tr><th>Reservation</th><th>Item / lot</th><th>Project</th><th>Quantity</th><th>Status</th><th>Created by</th></tr></thead><tbody>{reservations.map((reservation) => <tr key={reservation.id}><td>#{reservation.id}</td><td>{reservation.item_code} / {reservation.lot_code}</td><td>{reservation.project_code}</td><td>{reservation.quantity} {reservation.unit}</td><td>{reservation.status}</td><td>{reservation.created_by_username || "—"}</td></tr>)}</tbody></Table>
          )}
        </Card.Body>
      </Card>

      <Row className="g-4 mt-1">
        <Col lg={5}><Card className="app-card h-100"><Card.Body><h5 className="section-title">Hierarchical lab spaces</h5>{locations.length === 0 ? <div className="empty-state">No locations yet.</div> : <Table responsive hover className="app-table"><thead><tr><th>Code</th><th>Path</th><th>Kind</th></tr></thead><tbody>{locations.map((location) => <tr key={location.id}><td>{location.code || location.id}</td><td>{location.path || location.name}</td><td>{location.kind}</td></tr>)}</tbody></Table>}</Card.Body></Card></Col>
        <Col lg={7}><Card className="app-card h-100"><Card.Body><h5 className="section-title">Containers</h5>{containers.length === 0 ? <div className="empty-state">No containers yet.</div> : <Table responsive hover className="app-table"><thead><tr><th>ID</th><th>Container ID</th><th>Kind</th><th>Storage path</th></tr></thead><tbody>{containers.map((container) => <tr key={container.id}><td>{container.id}</td><td>{container.container_id}</td><td>{container.kind}</td><td>{container.path || container.location_name || container.location || "—"}</td></tr>)}</tbody></Table>}</Card.Body></Card></Col>
      </Row>

      <Row className="g-4 mt-1"><Col lg={8}><Card className="app-card h-100"><Card.Body><h5 className="section-title">Immutable inventory ledger</h5>{transactions.length === 0 ? <div className="empty-state">No inventory transactions yet.</div> : <Table responsive hover className="app-table"><thead><tr><th>Time</th><th>Lot</th><th>Operation</th><th>Change</th><th>Before → after</th><th>Actor</th><th>Reason</th></tr></thead><tbody>{transactions.map((row) => <tr key={row.public_id}><td>{new Date(row.occurred_at).toLocaleString()}</td><td>{row.lot_code}</td><td>{row.operation}</td><td>{row.amount} {row.unit}</td><td>{row.before_quantity} → {row.after_quantity}</td><td>{row.actor_username}</td><td>{row.reason}</td></tr>)}</tbody></Table>}</Card.Body></Card></Col><Col lg={4}><Card className="app-card h-100"><Card.Body><div className="toolbar-row"><h5 className="section-title">Stock and expiration alerts</h5>{writable && <Button size="sm" variant="outline-dark" onClick={refreshAlerts}>Refresh</Button>}</div>{alerts.filter((row) => row.status === "OPEN").map((row) => <Alert variant={row.alert_type === "EXPIRATION" ? "warning" : "info"} key={row.public_id}>{row.message}</Alert>)}{alerts.filter((row) => row.status === "OPEN").length === 0 && <div className="empty-state">No open alerts.</div>}<h6 className="mt-4">Cycle counts</h6>{cycleCounts.map((count) => <div className="feed-item mb-2" key={count.public_id}><strong>{count.name}</strong><div className="feed-meta">{count.location_name} · {count.status} · {count.lines.length} lots</div></div>)}</Card.Body></Card></Col></Row>
    </div>
  );
}
