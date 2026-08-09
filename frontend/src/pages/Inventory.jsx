import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { apiGet, apiPost } from "../api";

export default function Inventory() {
  const [locations, setLocations] = useState([]);
  const [containers, setContainers] = useState([]);
  const [inventoryItems, setInventoryItems] = useState([]);
  const [inventoryLots, setInventoryLots] = useState([]);
  const [err, setErr] = useState("");
  const [locationName, setLocationName] = useState("");
  const [locationKind, setLocationKind] = useState("FREEZER");
  const [containerId, setContainerId] = useState("");
  const [containerKind, setContainerKind] = useState("BOX");
  const [containerLocation, setContainerLocation] = useState("");

  async function load() {
    setErr("");
    try {
      const [locs, conts, items, lots] = await Promise.all([
        apiGet("/api/locations/"),
        apiGet("/api/containers/"),
        apiGet("/api/inventory-items/"),
        apiGet("/api/inventory-lots/"),
      ]);
      setLocations(locs.results || locs || []);
      setContainers(conts.results || conts || []);
      setInventoryItems(items.results || items || []);
      setInventoryLots(lots.results || lots || []);
    } catch (e) { setErr(e.message || String(e)); }
  }
  useEffect(() => { load(); }, []);

  async function createLocation(e) {
    e.preventDefault();
    setErr("");
    try {
      await apiPost("/api/locations/", { name: locationName, kind: locationKind });
      setLocationName(""); setLocationKind("FREEZER");
      await load();
    } catch (e) { setErr(e.message || String(e)); }
  }

  async function createContainer(e) {
    e.preventDefault();
    setErr("");
    try {
      await apiPost("/api/containers/", { container_id: containerId, kind: containerKind, location: Number(containerLocation) });
      setContainerId(""); setContainerKind("BOX"); setContainerLocation("");
      await load();
    } catch (e) { setErr(e.message || String(e)); }
  }

  return (
    <div className="w-100">
      <div className="page-header"><div><h1 className="page-title">Inventory</h1><p className="page-subtitle">Manage storage locations and containers.</p></div></div>
      {err && <Alert variant="danger">{err}</Alert>}
      <div className="row g-4 mb-4">
        <div className="col-lg-6">
          <Card className="app-card"><Card.Body>
            <h5 className="section-title">Create Location</h5>
            <Form onSubmit={createLocation}>
              <Row className="g-2">
                <Col md={7}><Form.Control placeholder="Location name" value={locationName} onChange={(e) => setLocationName(e.target.value)} /></Col>
                <Col md={3}><Form.Select value={locationKind} onChange={(e) => setLocationKind(e.target.value)}><option value="FREEZER">FREEZER</option><option value="FRIDGE">FRIDGE</option><option value="ROOM">ROOM</option><option value="SHELF">SHELF</option></Form.Select></Col>
                <Col md={2}><Button type="submit" variant="dark" className="w-100">Create</Button></Col>
              </Row>
            </Form>
          </Card.Body></Card>
        </div>
        <div className="col-lg-6">
          <Card className="app-card"><Card.Body>
            <h5 className="section-title">Create Container</h5>
            <Form onSubmit={createContainer}>
              <Row className="g-2">
                <Col md={4}><Form.Control placeholder="Container ID" value={containerId} onChange={(e) => setContainerId(e.target.value)} /></Col>
                <Col md={3}><Form.Select value={containerKind} onChange={(e) => setContainerKind(e.target.value)}><option value="BOX">BOX</option><option value="RACK">RACK</option><option value="PLATE">PLATE</option><option value="TUBE">TUBE</option></Form.Select></Col>
                <Col md={3}><Form.Select value={containerLocation} onChange={(e) => setContainerLocation(e.target.value)}><option value="">Location</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</Form.Select></Col>
                <Col md={2}><Button type="submit" variant="dark" className="w-100">Create</Button></Col>
              </Row>
            </Form>
          </Card.Body></Card>
        </div>
      </div>

      <div className="row g-4">
        <div className="col-lg-5">
          <Card className="app-card"><Card.Body>
            <h5 className="section-title">Locations</h5>
            {locations.length === 0 ? <div className="empty-state">No locations yet.</div> : (
              <Table responsive hover className="app-table">
                <thead><tr><th>ID</th><th>Name</th><th>Kind</th></tr></thead>
                <tbody>{locations.map((l) => <tr key={l.id}><td>{l.id}</td><td>{l.name}</td><td>{l.kind}</td></tr>)}</tbody>
              </Table>
            )}
          </Card.Body></Card>
        </div>
        <div className="col-lg-7">
          <Card className="app-card"><Card.Body>
            <h5 className="section-title">Containers</h5>
            {containers.length === 0 ? <div className="empty-state">No containers yet.</div> : (
              <Table responsive hover className="app-table">
                <thead><tr><th>ID</th><th>Container ID</th><th>Kind</th><th>Storage path</th></tr></thead>
                <tbody>{containers.map((c) => <tr key={c.id}><td>{c.id}</td><td>{c.container_id}</td><td>{c.kind}</td><td>{c.path || c.location_name || c.location || "-"}</td></tr>)}</tbody>
              </Table>
            )}
          </Card.Body></Card>
        </div>
      </div>

      <div className="row g-4 mt-1">
        <div className="col-lg-5">
          <Card className="app-card h-100"><Card.Body>
            <h5 className="section-title">Reagents and supplies</h5>
            {inventoryItems.length === 0 ? <div className="empty-state">No inventory items yet.</div> : (
              <Table responsive hover className="app-table">
                <thead><tr><th>Code</th><th>Name</th><th>Available</th><th>Reorder</th></tr></thead>
                <tbody>{inventoryItems.map((item) => <tr key={item.id}><td>{item.code}</td><td>{item.name}</td><td>{item.available_quantity} {item.default_unit}</td><td>{item.reorder_level} {item.default_unit}</td></tr>)}</tbody>
              </Table>
            )}
          </Card.Body></Card>
        </div>

        <div className="col-lg-7">
          <Card className="app-card h-100"><Card.Body>
            <h5 className="section-title">Lots</h5>
            {inventoryLots.length === 0 ? <div className="empty-state">No inventory lots yet.</div> : (
              <Table responsive hover className="app-table">
                <thead><tr><th>Lot</th><th>Item</th><th>Available</th><th>Expires</th><th>Status</th><th>Container</th></tr></thead>
                <tbody>{inventoryLots.map((lot) => <tr key={lot.id}><td>{lot.lot_code}</td><td>{lot.item_code}</td><td>{lot.available_quantity} {lot.unit}</td><td>{lot.expiration_date || "-"}</td><td><Badge bg={lot.status === "ACTIVE" ? "success" : lot.status === "EXPIRED" ? "danger" : "secondary"}>{lot.status}</Badge></td><td>{lot.container_code || lot.location_name || "-"}</td></tr>)}</tbody>
              </Table>
            )}
          </Card.Body></Card>
        </div>
      </div>
    </div>
  );
}
