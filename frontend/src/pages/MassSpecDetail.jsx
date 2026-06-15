import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Row,
  Spinner,
  Table,
} from "react-bootstrap";
import { Link, useNavigate, useParams } from "react-router-dom";
import { apiGet } from "../api";
import { getAccessToken } from "../auth";

function statusVariant(status) {
  if (status === "COMPLETED") return "success";
  if (status === "FAILED") return "danger";
  if (status === "RUNNING") return "info";
  return "secondary";
}

function formatNumber(value) {
  if (value === null || value === undefined) return "-";
  return Number(value).toFixed(2);
}

function formatDate(value) {
  if (!value) return "-";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function prettyPayload(payload) {
  if (!payload) return "{}";

  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

function TicChart({ data }) {
  const width = 900;
  const height = 280;
  const padding = 44;

  const points = (data || [])
    .map((point) => ({
      rt: Number(point.rt),
      totalIntensity: Number(point.total_intensity),
      msLevel: point.ms_level,
    }))
    .filter(
      (point) =>
        Number.isFinite(point.rt) && Number.isFinite(point.totalIntensity)
    );

  if (!points.length) {
    return (
      <div className="empty-state">
        No chromatogram data yet. Reprocess a completed mzML run to generate TIC
        points.
      </div>
    );
  }

  const rtValues = points.map((point) => point.rt);
  const intensityValues = points.map((point) => point.totalIntensity);

  const minRt = Math.min(...rtValues);
  const maxRt = Math.max(...rtValues);
  const maxIntensity = Math.max(...intensityValues, 1);

  function xScale(rt) {
    if (maxRt === minRt) return width / 2;
    return padding + ((rt - minRt) / (maxRt - minRt)) * (width - padding * 2);
  }

  function yScale(intensity) {
    return (
      height -
      padding -
      (intensity / maxIntensity) * (height - padding * 2)
    );
  }

  const path = points
    .map((point, index) => {
      const command = index === 0 ? "M" : "L";
      return `${command} ${xScale(point.rt)} ${yScale(point.totalIntensity)}`;
    })
    .join(" ");

  return (
    <div>
      <div className="d-flex justify-content-between align-items-center mb-2">
        <div className="feed-meta">
          Total ion chromatogram: retention time vs total intensity.
        </div>
        <Badge bg="secondary">{points.length} points</Badge>
      </div>

      <div
        style={{
          width: "100%",
          overflowX: "auto",
          background: "#f8fafc",
          border: "1px solid #e5e7eb",
          borderRadius: "14px",
          padding: "12px",
        }}
      >
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Total Ion Chromatogram"
          style={{ width: "100%", minWidth: "640px", height: "280px" }}
        >
          <line
            x1={padding}
            y1={height - padding}
            x2={width - padding}
            y2={height - padding}
            stroke="#94a3b8"
            strokeWidth="1"
          />
          <line
            x1={padding}
            y1={padding}
            x2={padding}
            y2={height - padding}
            stroke="#94a3b8"
            strokeWidth="1"
          />

          <text x={padding} y={height - 12} fontSize="12" fill="#64748b">
            RT {formatNumber(minRt)}
          </text>
          <text
            x={width - padding - 90}
            y={height - 12}
            fontSize="12"
            fill="#64748b"
          >
            RT {formatNumber(maxRt)}
          </text>
          <text x="8" y={padding + 4} fontSize="12" fill="#64748b">
            {formatNumber(maxIntensity)}
          </text>
          <text x="8" y={height - padding} fontSize="12" fill="#64748b">
            0
          </text>

          <path
            d={path}
            fill="none"
            stroke="#0f172a"
            strokeWidth="3"
            strokeLinejoin="round"
            strokeLinecap="round"
          />

          {points.map((point, index) => (
            <circle
              key={`${point.rt}-${index}`}
              cx={xScale(point.rt)}
              cy={yScale(point.totalIntensity)}
              r={point.msLevel === 1 ? 5 : 4}
              fill={point.msLevel === 1 ? "#0f172a" : "#64748b"}
            />
          ))}
        </svg>
      </div>

      <div className="feed-meta mt-2">
        Dark points are MS1 spectra. Gray points are MS2 or other spectra.
      </div>
    </div>
  );
}

export default function MassSpecDetail() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [reprocessing, setReprocessing] = useState(false);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [runData, eventsData] = await Promise.all([
        apiGet(`/api/mass-spec-runs/${id}/`),
        apiGet(`/api/events/?entity_type=mass_spec_run&search=${id}`),
      ]);

      setRun(runData);

      const rawEvents = eventsData.results || eventsData || [];
      setEvents(
        rawEvents.filter(
          (event) =>
            String(event.entity_id) === String(id) &&
            event.entity_type === "mass_spec_run"
        )
      );
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function reprocessRun() {
    setErr("");
    setReprocessing(true);

    try {
      const token = getAccessToken();

      const response = await fetch(`/api/mass-spec-runs/${id}/reprocess/`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error(`Reprocess failed with status ${response.status}`);
      }

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setReprocessing(false);
    }
  }

  const fileUrl = useMemo(() => {
    if (!run?.uploaded_file) return "";

    if (run.uploaded_file.startsWith("http")) return run.uploaded_file;

    return run.uploaded_file;
  }, [run]);

  const chromatogramData = useMemo(
    () => run?.chromatogram_data || [],
    [run]
  );

  const topPeaks = useMemo(() => run?.top_peaks || [], [run]);
  const detectedFeatures = useMemo(
    () => run?.detected_features || [],
    [run]
  );

  const openmsSummary = useMemo(
    () => run?.openms_summary || {},
    [run]
  );

  if (loading) {
    return (
      <div className="d-flex align-items-center gap-2">
        <Spinner animation="border" size="sm" />
        <span>Loading mass spec run...</span>
      </div>
    );
  }

  if (!run) {
    return (
      <Alert variant="warning">
        Mass spec run not found. <Link to="/mass-spec">Back to Mass Spec</Link>
      </Alert>
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">{run.name}</h1>
          <p className="page-subtitle">
            Mass spectrometry run summary processed with pyOpenMS.
          </p>
        </div>

        <div className="inline-actions">
          <Button
            variant="outline-secondary"
            size="sm"
            onClick={() => navigate("/mass-spec")}
          >
            Back
          </Button>

          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>

          <Button
            variant="dark"
            size="sm"
            onClick={reprocessRun}
            disabled={reprocessing}
          >
            {reprocessing ? "Reprocessing..." : "Reprocess"}
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      {run.error_message && (
        <Alert variant="danger">
          <div className="fw-semibold mb-1">Processing Error</div>
          <div style={{ whiteSpace: "pre-wrap" }}>{run.error_message}</div>
        </Alert>
      )}

      <Row className="g-4 mb-4">
        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Status</div>
              <div className="mt-2">
                <Badge bg={statusVariant(run.status)}>{run.status}</Badge>
              </div>
              <div className="metric-note mt-2">
                Uploaded {formatDate(run.created_at)}
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Spectra</div>
              <div className="metric-value">{run.spectra_count}</div>
              <div className="metric-note">Total spectra detected</div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">MS1 / MS2</div>
              <div className="metric-value">
                {run.ms1_count} / {run.ms2_count}
              </div>
              <div className="metric-note">Spectrum level breakdown</div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Feature Count</div>
              <div className="metric-value">{run.feature_count || 0}</div>
              <div className="metric-note">Grouped detected features</div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col md={4}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Base Peak m/z</div>
              <div className="metric-value">
                {formatNumber(run.base_peak_mz)}
              </div>
              <div className="metric-note">Highest intensity peak m/z</div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={4}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Base Peak Intensity</div>
              <div className="metric-value">
                {formatNumber(run.base_peak_intensity)}
              </div>
              <div className="metric-note">Highest peak intensity</div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={4}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">TIC Points</div>
              <div className="metric-value">{chromatogramData.length}</div>
              <div className="metric-note">Chromatogram data points</div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Total Ion Chromatogram</h5>
              <div className="feed-meta">
                Retention time plotted against total intensity per spectrum.
              </div>
            </div>
          </div>

          <TicChart data={chromatogramData} />
        </Card.Body>
      </Card>

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Run Metadata</h5>

              <Table responsive className="app-table align-middle mb-0">
                <tbody>
                  <tr>
                    <th style={{ width: "180px" }}>Original File</th>
                    <td>{run.original_filename || "-"}</td>
                  </tr>

                  <tr>
                    <th>Download</th>
                    <td>
                      {fileUrl ? (
                        <a href={fileUrl} target="_blank" rel="noreferrer">
                          Open uploaded file
                        </a>
                      ) : (
                        "-"
                      )}
                    </td>
                  </tr>

                  <tr>
                    <th>Project</th>
                    <td>
                      {run.project ? (
                        <Link to={`/projects/${run.project}`}>
                          {run.project_code || `Project ${run.project}`}
                        </Link>
                      ) : (
                        "-"
                      )}
                    </td>
                  </tr>

                  <tr>
                    <th>Sample</th>
                    <td>
                      {run.sample ? (
                        <Link to={`/samples/${run.sample}`}>
                          {run.sample_id_value || `Sample ${run.sample}`}
                        </Link>
                      ) : (
                        "-"
                      )}
                    </td>
                  </tr>

                  <tr>
                    <th>Uploaded By</th>
                    <td>{run.uploaded_by_username || "-"}</td>
                  </tr>

                  <tr>
                    <th>Created</th>
                    <td>{formatDate(run.created_at)}</td>
                  </tr>

                  <tr>
                    <th>Processed</th>
                    <td>{formatDate(run.processed_at)}</td>
                  </tr>
                </tbody>
              </Table>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Signal Ranges</h5>

              <Table responsive className="app-table align-middle mb-0">
                <tbody>
                  <tr>
                    <th style={{ width: "180px" }}>RT Min</th>
                    <td>{formatNumber(run.rt_min)}</td>
                  </tr>

                  <tr>
                    <th>RT Max</th>
                    <td>{formatNumber(run.rt_max)}</td>
                  </tr>

                  <tr>
                    <th>m/z Min</th>
                    <td>{formatNumber(run.mz_min)}</td>
                  </tr>

                  <tr>
                    <th>m/z Max</th>
                    <td>{formatNumber(run.mz_max)}</td>
                  </tr>

                  <tr>
                    <th>MS1 Count</th>
                    <td>{run.ms1_count}</td>
                  </tr>

                  <tr>
                    <th>MS2 Count</th>
                    <td>{run.ms2_count}</td>
                  </tr>

                  <tr>
                    <th>Total Spectra</th>
                    <td>{run.spectra_count}</td>
                  </tr>
                </tbody>
              </Table>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Peak Summary</h5>
              <div className="feed-meta">
                Peak picking summary generated from pyOpenMS processing.
              </div>
            </div>

            <Badge bg="dark">{topPeaks.length} top peaks</Badge>
          </div>

          <Row className="g-3 mb-3">
            <Col md={4}>
              <div className="soft-card">
                <div className="feed-meta">Peak Count</div>
                <div className="fw-semibold">{run.peak_count || 0}</div>
              </div>
            </Col>

            <Col md={4}>
              <div className="soft-card">
                <div className="feed-meta">Base Peak m/z</div>
                <div className="fw-semibold">
                  {formatNumber(run.base_peak_mz)}
                </div>
              </div>
            </Col>

            <Col md={4}>
              <div className="soft-card">
                <div className="feed-meta">Base Peak Intensity</div>
                <div className="fw-semibold">
                  {formatNumber(run.base_peak_intensity)}
                </div>
              </div>
            </Col>
          </Row>

          {topPeaks.length === 0 ? (
            <div className="empty-state">
              No top peaks available. Reprocess a completed mass spec run.
            </div>
          ) : (
            <Table responsive hover className="app-table align-middle">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Retention Time</th>
                  <th>m/z</th>
                  <th>Intensity</th>
                  <th>MS Level</th>
                </tr>
              </thead>

              <tbody>
                {topPeaks.map((peak, index) => (
                  <tr key={`${peak.rt}-${peak.mz}-${index}`}>
                    <td>{index + 1}</td>
                    <td>{formatNumber(peak.rt)}</td>
                    <td>{formatNumber(peak.mz)}</td>
                    <td>{formatNumber(peak.intensity)}</td>
                    <td>{peak.ms_level || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>


      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Quality Metrics</h5>
              <div className="feed-meta">
                Run-level signal quality metrics calculated during pyOpenMS processing.
              </div>
            </div>

            <Badge bg="dark">QC summary</Badge>
          </div>

          <Row className="g-3">
            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">Total Ion Current</div>
                <div className="fw-semibold">
                  {formatNumber(run.total_ion_current)}
                </div>
              </div>
            </Col>

            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">Mean Total Intensity</div>
                <div className="fw-semibold">
                  {formatNumber(run.mean_total_intensity)}
                </div>
              </div>
            </Col>

            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">Max Total Intensity</div>
                <div className="fw-semibold">
                  {formatNumber(run.max_total_intensity)}
                </div>
              </div>
            </Col>

            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">Mean Peak Intensity</div>
                <div className="fw-semibold">
                  {formatNumber(run.mean_peak_intensity)}
                </div>
              </div>
            </Col>

            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">RT Span</div>
                <div className="fw-semibold">{formatNumber(run.rt_span)}</div>
              </div>
            </Col>

            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">m/z Span</div>
                <div className="fw-semibold">{formatNumber(run.mz_span)}</div>
              </div>
            </Col>

            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">MS1 Ratio</div>
                <div className="fw-semibold">
                  {formatNumber((run.ms1_ratio || 0) * 100)}%
                </div>
              </div>
            </Col>

            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">MS2 Ratio</div>
                <div className="fw-semibold">
                  {formatNumber((run.ms2_ratio || 0) * 100)}%
                </div>
              </div>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">OpenMS File Summary</h5>
              <div className="feed-meta">
                Parsed OpenMS output metadata for featureXML, consensusXML, and raw spectrum files.
              </div>
            </div>

            <Badge bg="dark">
              {openmsSummary.file_type || "unknown"}
            </Badge>
          </div>

          <Row className="g-3 mb-3">
            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">File Type</div>
                <div className="fw-semibold">
                  {openmsSummary.file_type || "-"}
                </div>
              </div>
            </Col>

            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">featureXML Count</div>
                <div className="fw-semibold">
                  {run.featurexml_count || 0}
                </div>
              </div>
            </Col>

            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">consensusXML Count</div>
                <div className="fw-semibold">
                  {run.consensusxml_count || 0}
                </div>
              </div>
            </Col>

            <Col md={3}>
              <div className="soft-card">
                <div className="feed-meta">Detected Features</div>
                <div className="fw-semibold">
                  {run.feature_count || detectedFeatures.length || 0}
                </div>
              </div>
            </Col>
          </Row>

          <details>
            <summary className="feed-meta">Raw OpenMS summary JSON</summary>
            <pre
              className="mb-0 mt-2"
              style={{
                maxHeight: "220px",
                overflow: "auto",
                fontSize: "0.78rem",
                background: "#f8fafc",
                border: "1px solid #e5e7eb",
                borderRadius: "12px",
                padding: "10px",
              }}
            >
              {JSON.stringify(openmsSummary, null, 2)}
            </pre>
          </details>
        </Card.Body>
      </Card>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Detected Features</h5>
              <div className="feed-meta">
                Lightweight feature detection groups high-signal peaks by m/z across retention time.
              </div>
            </div>

            <Badge bg="dark">{run.feature_count || detectedFeatures.length} features</Badge>
          </div>

          {detectedFeatures.length === 0 ? (
            <div className="empty-state">
              No detected features available. Reprocess a completed mass spec run.
            </div>
          ) : (
            <Table responsive hover className="app-table align-middle">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>m/z</th>
                  <th>RT Min</th>
                  <th>RT Max</th>
                  <th>Apex RT</th>
                  <th>Apex Intensity</th>
                  <th>Total Intensity</th>
                  <th>Peak Count</th>
                  <th>MS Level</th>
                </tr>
              </thead>

              <tbody>
                {detectedFeatures.map((feature, index) => (
                  <tr key={`${feature.mz}-${feature.apex_rt}-${index}`}>
                    <td>{index + 1}</td>
                    <td>{formatNumber(feature.mz)}</td>
                    <td>{formatNumber(feature.rt_min)}</td>
                    <td>{formatNumber(feature.rt_max)}</td>
                    <td>{formatNumber(feature.apex_rt)}</td>
                    <td>{formatNumber(feature.apex_intensity)}</td>
                    <td>{formatNumber(feature.total_intensity)}</td>
                    <td>{feature.peak_count || 0}</td>
                    <td>{feature.ms_level || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Chromatogram Points</h5>
              <div className="feed-meta">
                Raw TIC points extracted from each spectrum.
              </div>
            </div>

            <Badge bg="dark">{chromatogramData.length} points</Badge>
          </div>

          {chromatogramData.length === 0 ? (
            <div className="empty-state">No chromatogram points available.</div>
          ) : (
            <Table responsive hover className="app-table align-middle">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Retention Time</th>
                  <th>Total Intensity</th>
                  <th>MS Level</th>
                </tr>
              </thead>

              <tbody>
                {chromatogramData.map((point, index) => (
                  <tr key={`${point.rt}-${index}`}>
                    <td>{index + 1}</td>
                    <td>{formatNumber(point.rt)}</td>
                    <td>{formatNumber(point.total_intensity)}</td>
                    <td>{point.ms_level || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Audit Events</h5>
              <div className="feed-meta">
                Mass spec upload, processing, reprocessing, and failure events.
              </div>
            </div>

            <Badge bg="dark">{events.length} events</Badge>
          </div>

          {events.length === 0 ? (
            <div className="empty-state">No audit events found for this run.</div>
          ) : (
            <Table responsive hover className="app-table align-middle">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Payload</th>
                </tr>
              </thead>

              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    <td style={{ minWidth: "180px" }}>
                      {formatDate(event.timestamp)}
                    </td>
                    <td>{event.actor_username || event.actor || "-"}</td>
                    <td>
                      <Badge bg="secondary">{event.action}</Badge>
                    </td>
                    <td style={{ minWidth: "360px" }}>
                      <pre
                        className="mb-0"
                        style={{
                          maxHeight: "160px",
                          overflow: "auto",
                          fontSize: "0.78rem",
                          background: "#f8fafc",
                          border: "1px solid #e5e7eb",
                          borderRadius: "12px",
                          padding: "10px",
                        }}
                      >
                        {prettyPayload(event.payload)}
                      </pre>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}
