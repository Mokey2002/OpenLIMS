import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { apiGet, apiPost } from "../api";

export default function Inventory() {
  const [locations, setLocations] = useState([]);
  const [containers, setContainers] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  const [locationName, setLocationName] = useState("");
  const [locationKind, setLocationKind] = useState("freezer");

  const [containerId, setContainerId] = useState("");
  const [containerKind, setContainerKind] = useState("box");
  const [containerLocation, setContainerLocation] = useState("");

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const [locs, conts] = await Promise.all([
        apiGet("/api/locations/"),
        apiGet("/api/containers/"),
      ]);
      setLocations(locs);
      setContainers(conts);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function createLocation(e) {
    e.preventDefault();
    setErr("");

    try {
      await apiPost("/api/locations/", {
        name: locationName,
        kind: locationKind,
      });

      setLocationName("");
      setLocationKind("freezer");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function createContainer(e) {
    e.preventDefault();
    setErr("");

    try {
      await apiPost("/api/containers/", {
        container_id: containerId,
        kind: containerKind,
        location: Number(containerLocation),
      });

      setContainerId("");
      setContainerKind("box");
      setContainerLocation("");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  return (
    <div className="w-100">
      <h2 className="mb-3">Inventory</h2>

      {err && <Alert variant="danger">{err}</Alert>}

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="shadow-sm border-0">
            <Card.Body>
              <h5 className="mb-3">Add Location</h5>
              <Form onSubmit={createLocation}>
                <Row className="g-2">
                  <Col md={7}>
                    <Form.Control
                      placeholder="Location name (e.g. Freezer A)"
                      value={locationName}
                      onChange={(e) => setLocationName(e.target.value)}
                    />
                  </Col>
                  <Col md={3}>
                    <Form.Select
                      value={locationKind}
                      onChange={(e) => setLocationKind(e.target.value)}
                    >
                      <option value="freezer">freezer</option>
                      <option value="rack">rack</option>
                      <option value="shelf">shelf</option>
                      <option value="room">room</option>
                    </Form.Select>
                  </Col>
                  <Col md={2}>
                    <Button type="submit" variant="dark" className="w-100">
                      Add
                    </Button>
                  </Col>
                </Row>
              </Form>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="shadow-sm border-0">
            <Card.Body>
              <h5 className="mb-3">Add Container</h5>
              <Form onSubmit={createContainer}>
                <Row className="g-2">
                  <Col md={4}>
                    <Form.Control
                      placeholder="Container ID (e.g. C-001)"
                      value={containerId}
                      onChange={(e) => setContainerId(e.target.value)}
                    />
                  </Col>
                  <Col md={3}>
                    <Form.Select
                      value={containerKind}
                      onChange={(e) => setContainerKind(e.target.value)}
                    >
                      <option value="box">box</option>
                      <option value="tube">tube</option>
                      <option value="plate">plate</option>
                      <option value="vial">vial</option>
                    </Form.Select>
                  </Col>
                  <Col md={3}>
                    <Form.Select
                      value={containerLocation}
                      onChange={(e) => setContainerLocation(e.target.value)}
                    >
                      <option value="">Select location</option>
                      {locations.map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.name}
                        </option>
                      ))}
                    </Form.Select>
                  </Col>
                  <Col md={2}>
                    <Button type="submit" variant="dark" className="w-100">
                      Add
                    </Button>
                  </Col>
                </Row>
              </Form>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4">
        <Col lg={6}>
          <Card className="shadow-sm border-0">
            <Card.Body>
              <h5 className="mb-3">Locations</h5>
              {loading ? (
                <div>Loading...</div>
              ) : locations.length === 0 ? (
                <Alert variant="light" className="mb-0">
                  No locations yet.
                </Alert>
              ) : (
                <Table responsive hover className="mb-0">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Name</th>
                      <th>Kind</th>
                    </tr>
                  </thead>
                  <tbody>
                    {locations.map((l) => (
                      <tr key={l.id}>
                        <td>{l.id}</td>
                        <td>{l.name}</td>
                        <td>{l.kind}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="shadow-sm border-0">
            <Card.Body>
              <h5 className="mb-3">Containers</h5>
              {loading ? (
                <div>Loading...</div>
              ) : containers.length === 0 ? (
                <Alert variant="light" className="mb-0">
                  No containers yet.
                </Alert>
              ) : (
                <Table responsive hover className="mb-0">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Container ID</th>
                      <th>Kind</th>
                      <th>Location</th>
                    </tr>
                  </thead>
                  <tbody>
                    {containers.map((c) => (
                      <tr key={c.id}>
                        <td>{c.id}</td>
                        <td>{c.container_id}</td>
                        <td>{c.kind}</td>
                        <td>{c.location_name || c.location}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </div>
  );
}