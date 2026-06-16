import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, Col, ProgressBar, Row } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet } from "../api";

const baseTutorialSteps = [
  {
    number: 1,
    title: "Dashboard overview",
    badge: "Overview",
    to: "/",
    button: "Open Dashboard",
    description:
      "Start with the high-level view of samples, projects, work items, and recent audit activity.",
    tryThis: [
      "Look at total samples, visible projects, and recent events.",
      "Notice that dashboard cards link directly into deeper records.",
    ],
    bestData: "Dashboard",
  },
  {
    number: 2,
    title: "Project workspace",
    badge: "Project",
    to: "/projects",
    button: "Open Projects",
    description:
      "Open PRJ-ALPHA to see a realistic project workspace with samples, project notes, and linked lab activity.",
    tryThis: [
      "Open PRJ-ALPHA.",
      "Review project notes and sample counts.",
      "Use this project later for imports, analysis, and mass spec comparison.",
    ],
    bestData: "PRJ-ALPHA",
  },
  {
    number: 3,
    title: "Sample traceability",
    badge: "Samples",
    to: "/samples",
    button: "Open Samples",
    description:
      "Inspect sample lifecycle status, linked work items, imported results, attachments, audit timeline, and mass spec runs.",
    tryThis: [
      "Open S-ALPHA-001.",
      "Review linked project, results, and audit activity.",
      "Look for linked mass spec runs on the sample detail page.",
    ],
    bestData: "S-ALPHA-001",
  },
  {
    number: 4,
    title: "Import lab data",
    badge: "Imports",
    to: "/imports",
    button: "Open Imports",
    description:
      "Review seeded instrument import jobs and see how OpenLIMS tracks uploaded lab data, processing status, matched samples, created results, and skipped rows.",
    tryThis: [
      "Open the Imports page as director or a tech user.",
      "Review completed demo imports such as NovaFlex, MiSeq, qPCR, NanoDrop, and plate reader data.",
      "Open an import job and inspect rows processed, matched samples, created results, and audit events.",
      "Explain how import jobs connect instruments, samples, work items, and results.",
    ],
    bestData: "NovaFlex / MiSeq imports",
  },
  {
    number: 5,
    title: "Analyze imported results",
    badge: "Analyze",
    to: "/analyze",
    button: "Open Analyze",
    description:
      "Use the Analyze page to explore numeric result trends from imported lab data such as concentration, purity, yield, qPCR values, and sequencing QC metrics.",
    tryThis: [
      "Select PRJ-ALPHA.",
      "Choose a numeric metric like concentration, purity, yield, or percent_q30.",
      "Use this page to explain how OpenLIMS turns imported results into reviewable trends.",
    ],
    bestData: "Alpha result metrics",
  },
  {
    number: 6,
    title: "Sequence workspaces",
    badge: "Sequences",
    to: "/sequences",
    button: "Open Sequences",
    description:
      "View seeded DNA sequence records linked to samples and projects. These records can feed alignment and BLAST workflows.",
    tryThis: [
      "Open Alpha GFP Construct Review.",
      "Review sequence metadata and linked sample/project context.",
      "Explain how sequence workspaces connect sample records to downstream analysis.",
    ],
    bestData: "Alpha GFP sequences",
  },
  {
    number: 7,
    title: "Clustal Omega alignments",
    badge: "Alignment",
    to: "/alignments",
    button: "Open Alignments",
    description:
      "Run or inspect Clustal Omega alignment jobs using sequence workspaces from the Alpha demo project.",
    tryThis: [
      "Create or inspect an alignment job using Alpha GFP demo sequences.",
      "Show that alignment jobs run asynchronously.",
      "Explain that completed jobs are linked back to project and sequence context.",
    ],
    bestData: "Alpha GFP variants",
  },
  {
    number: 8,
    title: "Local BLAST search",
    badge: "BLAST",
    to: "/blast",
    button: "Open BLAST",
    description:
      "Use the seeded demo BLAST database and query sequence to demonstrate local sequence similarity search.",
    tryThis: [
      "Use BLAST Demo Query as the query sequence.",
      "Use Demo DNA BLAST DB as the database.",
      "Run blastn and inspect ranked hits, identity, e-value, and alignment regions.",
    ],
    bestData: "Demo DNA BLAST DB",
  },
  {
    number: 9,
    title: "Mass spec run details",
    badge: "Mass Spec",
    to: "/mass-spec",
    button: "Open Mass Spec",
    description:
      "Open completed mass spec demo runs to inspect TIC charts, peak summaries, detected features, quality metrics, and protein/peptide ID summaries.",
    tryThis: [
      "Open Alpha LC-MS Demo Run 001.",
      "Review TIC chart, peak summary, detected features, and quality metrics.",
      "Open the featureXML or mzIdentML demo run to show file-specific summaries.",
    ],
    bestData: "Alpha LC-MS runs",
  },
  {
    number: 10,
    title: "Compare mass spec runs",
    badge: "Compare",
    to: "/mass-spec/compare",
    button: "Compare Runs",
    description:
      "Compare completed mass spec runs by project, by sample, or manually selected run sets.",
    tryThis: [
      "Choose By Project → PRJ-ALPHA.",
      "Choose By Sample → S-ALPHA-001.",
      "Try Manual Run Selection and select two or more completed runs.",
      "Review shared feature m/z and unique feature m/z by run.",
    ],
    bestData: "PRJ-ALPHA / S-ALPHA-001",
  },
  {
    number: 11,
    title: "Audit trail",
    badge: "Audit",
    to: "/events",
    button: "Open Audit Events",
    description:
      "Review who did what and when. Audit events record imports, samples, inventory actions, mass spec processing, sequence workflows, and admin actions.",
    tryThis: [
      "Create a new inventory location as director.",
      "Open Audit Events.",
      "Confirm LOCATION_CREATED shows actor=director.",
      "Use this to explain traceability and chain-of-custody foundations.",
    ],
    bestData: "Audit Events",
  },
];

const adminTutorialSteps = [
  {
    number: 12,
    title: "Admin settings",
    badge: "Admin",
    to: "/settings",
    button: "Open Settings",
    description:
      "Review system-level configuration such as lab name, import behavior, default sample status, security settings, and audit-related options.",
    tryThis: [
      "Open Settings as director.",
      "Review lab name, organization name, timezone, and default sample status.",
      "Explain that settings changes are admin-only and recorded in the audit trail.",
    ],
    bestData: "System settings",
  },
  {
    number: 13,
    title: "System status",
    badge: "Admin",
    to: "/system-status",
    button: "Open System Status",
    description:
      "Check runtime health for the database, Redis, Clustal Omega, BLAST tools, pyOpenMS, and background processing dependencies.",
    tryThis: [
      "Open System Status as director.",
      "Confirm database, Redis, BLAST, Clustal Omega, and pyOpenMS checks are healthy.",
      "Use this page to explain operational readiness and dependency monitoring.",
    ],
    bestData: "Health checks",
  },
];

function DemoAccountCard({ username, password, role, note }) {
  return (
    <div className="soft-card h-100">
      <div className="d-flex justify-content-between align-items-start gap-2">
        <div>
          <div className="fw-semibold">{username}</div>
          <div className="feed-meta">{role}</div>
        </div>

        <Badge bg="secondary">{password}</Badge>
      </div>

      {note && <div className="feed-meta mt-2">{note}</div>}
    </div>
  );
}

function StepPreviewCard({ step, active, onClick }) {
  return (
    <button
      type="button"
      className={`tutorial-step-preview ${active ? "active" : ""}`}
      onClick={onClick}
    >
      <div className="tutorial-step-preview-number">{step.number}</div>
      <div>
        <div className="fw-semibold">{step.title}</div>
        <div className="feed-meta">{step.badge}</div>
      </div>
    </button>
  );
}

export default function GettingStarted() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [me, setMe] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await apiGet("/api/me/");
        setMe(data);
      } catch {
        setMe(null);
      }
    })();
  }, []);

  const userIsAdmin = me?.roles?.includes("admin");

  const tutorialSteps = useMemo(() => {
    return userIsAdmin
      ? [...baseTutorialSteps, ...adminTutorialSteps]
      : baseTutorialSteps;
  }, [userIsAdmin]);

  useEffect(() => {
    if (activeIndex > tutorialSteps.length - 1) {
      setActiveIndex(tutorialSteps.length - 1);
    }
  }, [activeIndex, tutorialSteps.length]);

  const activeStep = tutorialSteps[activeIndex];
  const previousStep = activeIndex > 0 ? tutorialSteps[activeIndex - 1] : null;
  const nextStep =
    activeIndex < tutorialSteps.length - 1
      ? tutorialSteps[activeIndex + 1]
      : null;

  const progress = useMemo(() => {
    return Math.round(((activeIndex + 1) / tutorialSteps.length) * 100);
  }, [activeIndex]);

  function goPrevious() {
    setActiveIndex((current) => Math.max(0, current - 1));
  }

  function goNext() {
    setActiveIndex((current) =>
      Math.min(tutorialSteps.length - 1, current + 1)
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Getting Started</h1>
          <p className="page-subtitle">
            A guided walkthrough for exploring OpenLIMS without returning to the
            dashboard between steps.
          </p>
        </div>

        <div className="inline-actions">
          <Button
            as={Link}
            to={`${activeStep.to}?tour=${activeStep.number}`}
            variant="dark"
            size="sm"
          >
            Open Current Step
          </Button>

          {nextStep && (
            <Button variant="outline-dark" size="sm" onClick={goNext}>
              Next: {nextStep.title}
            </Button>
          )}
        </div>
      </div>

      <Card className="app-card mb-4 demo-hero-card">
        <Card.Body>
          <Row className="g-4 align-items-center">
            <Col lg={8}>
              <Badge bg="dark" className="mb-3">
                Step {activeStep.number} of {tutorialSteps.length}
              </Badge>

              <h2 className="mb-2">{activeStep.title}</h2>

              <p className="page-subtitle mb-3">{activeStep.description}</p>

              <ProgressBar now={progress} label={`${progress}%`} />

              <div className="inline-actions mt-3">
                <Button
                  variant="outline-secondary"
                  size="sm"
                  onClick={goPrevious}
                  disabled={!previousStep}
                >
                  Previous
                </Button>

                <Button
                  variant="outline-dark"
                  size="sm"
                  onClick={goNext}
                  disabled={!nextStep}
                >
                  Next Step
                </Button>

                <Button
                  as={Link}
                  to={`${activeStep.to}?tour=${activeStep.number}`}
                  variant="dark"
                  size="sm"
                >
                  {activeStep.button}
                </Button>
              </div>
            </Col>

            <Col lg={4}>
              <div className="soft-card">
                <div className="feed-meta mb-1">Best demo data to use</div>
                <div className="fs-4 fw-bold">
                  {activeStep.bestData || "Demo data"}
                </div>
                <div className="feed-meta">
                  Follow the suggestions below for a smooth demo path.
                </div>
              </div>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      <Row className="g-4 mb-4">
        <Col xl={4}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Tutorial steps</h5>
              <p className="page-subtitle mb-3">
                Click any step, or use Previous / Next to move through the demo.
              </p>

              <div className="tutorial-step-list">
                {tutorialSteps.map((step, index) => (
                  <StepPreviewCard
                    key={step.number}
                    step={step}
                    active={index === activeIndex}
                    onClick={() => setActiveIndex(index)}
                  />
                ))}
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col xl={8}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <div>
                  <Badge bg="secondary" className="mb-2">
                    {activeStep.badge}
                  </Badge>
                  <h5 className="section-title mb-0">
                    What to do on this step
                  </h5>
                </div>

                <Button
                  as={Link}
                  to={`${activeStep.to}?tour=${activeStep.number}`}
                  variant="dark"
                  size="sm"
                >
                  {activeStep.button}
                </Button>
              </div>

              <div className="d-grid gap-3">
                {activeStep.tryThis.map((item) => (
                  <div className="soft-card" key={item}>
                    <div className="d-flex gap-2">
                      <Badge bg="dark">Try</Badge>
                      <div>{item}</div>
                    </div>
                  </div>
                ))}
              </div>

              <div className="tutorial-next-panel mt-4">
                <div>
                  <div className="feed-meta">Next step</div>
                  <div className="fw-semibold">
                    {nextStep ? nextStep.title : "Tutorial complete"}
                  </div>
                </div>

                {nextStep ? (
                  <Button variant="outline-dark" size="sm" onClick={goNext}>
                    Continue
                  </Button>
                ) : (
                  <Button as={Link} to="/events" variant="outline-dark" size="sm">
                    Finish in Audit Trail
                  </Button>
                )}
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={7}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Suggested full demo script</h5>

              <div className="demo-timeline mt-3">
                <div className="demo-timeline-item">
                  <strong>Start:</strong> Dashboard → Projects → PRJ-ALPHA.
                </div>
                <div className="demo-timeline-item">
                  <strong>Traceability:</strong> Samples → S-ALPHA-001 → linked
                  results, imports, sequences, mass spec runs, and events.
                </div>
                <div className="demo-timeline-item">
                  <strong>Imports and analysis:</strong> Review import jobs, analyze result
                  metrics, inspect sequence workspaces, run/inspect alignments,
                  and test BLAST.
                </div>
                <div className="demo-timeline-item">
                  <strong>Mass Spec:</strong> Open Mass Spec → compare PRJ-ALPHA
                  or S-ALPHA-001 → review shared/unique feature m/z values.
                </div>
                <div className="demo-timeline-item">
                  <strong>Audit:</strong> Create a location as director → confirm
                  LOCATION_CREATED appears with actor=director.
                </div>
                {userIsAdmin && (
                  <div className="demo-timeline-item">
                    <strong>Admin:</strong> Review Settings and System Status to
                    show admin-only configuration and runtime health checks.
                  </div>
                )}
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={5}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Demo accounts</h5>
              <p className="page-subtitle mb-3">
                Use these accounts to demonstrate role-based access control.
              </p>

              <div className="d-grid gap-3">
                <DemoAccountCard
                  username="director"
                  password="Director123!"
                  role="Admin / director access"
                  note="Best account for exploring all workflows."
                />

                <DemoAccountCard
                  username="peter"
                  password="peter123"
                  role="Lab tech access"
                  note="Can perform lab workflow actions."
                />

                <DemoAccountCard
                  username="viewer"
                  password="viewer123"
                  role="Read-only access"
                  note="Can view records without editing them."
                />
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
