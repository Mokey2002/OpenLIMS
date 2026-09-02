import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./Layout";
import Login from "./pages/Login";
import { installRandomUUIDCompatibility } from "./utils/clientId";

installRandomUUIDCompatibility();

const MyWork = lazy(() => import("./pages/MyWork"));
const SamplesList = lazy(() => import("./pages/SamplesList"));
const SampleDetail = lazy(() => import("./pages/SampleDetail"));
const Inventory = lazy(() => import("./pages/Inventory"));
const Events = lazy(() => import("./pages/Events"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Analyze = lazy(() => import("./pages/Analyze"));
const Projects = lazy(() => import("./pages/Projects"));
const ProjectDetail = lazy(() => import("./pages/ProjectDetail"));
const Users = lazy(() => import("./pages/Users"));
const Imports = lazy(() => import("./pages/Imports"));
const Notifications = lazy(() => import("./pages/Notifications"));
const ImportDetail = lazy(() => import("./pages/ImportDetail"));
const Sequences = lazy(() => import("./pages/Sequences"));
const Alignments = lazy(() => import("./pages/Alignments"));
const AdminSettings = lazy(() => import("./pages/AdminSettings"));
const Reports = lazy(() => import("./pages/Reports"));
const SystemStatus = lazy(() => import("./pages/SystemStatus"));
const Search = lazy(() => import("./pages/Search"));
const Blast = lazy(() => import("./pages/Blast"));
const MassSpec = lazy(() => import("./pages/MassSpec"));
const MassSpecDetail = lazy(() => import("./pages/MassSpecDetail"));
const MassSpecCompare = lazy(() => import("./pages/MassSpecCompare"));
const GettingStarted = lazy(() => import("./pages/GettingStarted"));
const DataMigration = lazy(() => import("./pages/DataMigration"));
const Assistant = lazy(() => import("./pages/Assistant"));
const MigrationJobDetail = lazy(() => import("./pages/MigrationJobDetail"));
const SOPs = lazy(() => import("./pages/SOPs"));
const Batches = lazy(() => import("./pages/Batches"));
const QCReview = lazy(() => import("./pages/QCReview"));
const WorkQueue = lazy(() => import("./pages/WorkQueue"));
const Labels = lazy(() => import("./pages/Labels"));
const Comparisons = lazy(() => import("./pages/Comparisons"));
const Investigations = lazy(() => import("./pages/Investigations"));
const WorkflowDesigner = lazy(() => import("./pages/WorkflowDesigner"));
const Traceability = lazy(() => import("./pages/Traceability"));
const Registry = lazy(() => import("./pages/Registry"));
const NotebookPage = lazy(() => import("./pages/Notebook"));
const WorkflowRequests = lazy(() => import("./pages/WorkflowRequests"));

function RouteFallback() {
  return <div className="py-5 text-center text-muted">Loading…</div>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Layout />}>
            <Route index element={<MyWork />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="getting-started" element={<GettingStarted />} />
            <Route path="assistant" element={<Assistant />} />
            <Route path="samples" element={<SamplesList />} />
            <Route path="samples/:id" element={<SampleDetail />} />
            <Route path="traceability" element={<Traceability />} />
            <Route path="inventory" element={<Inventory />} />
            <Route path="events" element={<Events />} />
            <Route path="analyze" element={<Analyze />} />
            <Route path="projects" element={<Projects />} />
            <Route path="projects/:id" element={<ProjectDetail />} />
            <Route path="sequences" element={<Sequences />} />
            <Route path="registry" element={<Registry />} />
            <Route path="notebook" element={<NotebookPage />} />
            <Route path="alignments" element={<Alignments />} />
            <Route path="reports" element={<Reports />} />
            <Route path="system-status" element={<SystemStatus />} />
            <Route path="sops" element={<SOPs />} />
            <Route path="batches" element={<Batches />} />
            <Route path="qc-review" element={<QCReview />} />
            <Route path="work-queue" element={<WorkQueue />} />
            <Route path="labels" element={<Labels />} />
            <Route path="comparisons" element={<Comparisons />} />
            <Route path="investigations" element={<Investigations />} />
            <Route path="users" element={<Users />} />
            <Route path="settings" element={<AdminSettings />} />
            <Route path="workflow-designer" element={<WorkflowDesigner />} />
            <Route path="workflow-requests" element={<WorkflowRequests />} />
            <Route path="imports" element={<Imports />} />
            <Route path="data-migration" element={<DataMigration />} />
            <Route path="data-migration/jobs/:id" element={<MigrationJobDetail />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="imports/:id" element={<ImportDetail />} />
            <Route path="search" element={<Search />} />
            <Route path="blast" element={<Blast />} />
            <Route path="mass-spec" element={<MassSpec />} />
            <Route path="mass-spec/compare" element={<MassSpecCompare />} />
            <Route path="mass-spec/:id" element={<MassSpecDetail />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
