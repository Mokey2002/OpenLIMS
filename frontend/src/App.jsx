import { Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { lazyPage } from "./utils/lazyPage";
import Layout from "./Layout";
import Login from "./pages/Login";
import { installRandomUUIDCompatibility } from "./utils/clientId";

installRandomUUIDCompatibility();

const MyWork = lazyPage(() => import("./pages/MyWork"));
const SamplesList = lazyPage(() => import("./pages/SamplesList"));
const SampleDetail = lazyPage(() => import("./pages/SampleDetail"));
const Inventory = lazyPage(() => import("./pages/Inventory"));
const Events = lazyPage(() => import("./pages/Events"));
const Dashboard = lazyPage(() => import("./pages/Dashboard"));
const Analyze = lazyPage(() => import("./pages/Analyze"));
const Projects = lazyPage(() => import("./pages/Projects"));
const ProjectDetail = lazyPage(() => import("./pages/ProjectDetail"));
const Users = lazyPage(() => import("./pages/Users"));
const Imports = lazyPage(() => import("./pages/Imports"));
const Notifications = lazyPage(() => import("./pages/Notifications"));
const ImportDetail = lazyPage(() => import("./pages/ImportDetail"));
const Sequences = lazyPage(() => import("./pages/Sequences"));
const Alignments = lazyPage(() => import("./pages/Alignments"));
const AdminSettings = lazyPage(() => import("./pages/AdminSettings"));
const Reports = lazyPage(() => import("./pages/Reports"));
const SystemStatus = lazyPage(() => import("./pages/SystemStatus"));
const Search = lazyPage(() => import("./pages/Search"));
const Blast = lazyPage(() => import("./pages/Blast"));
const MassSpec = lazyPage(() => import("./pages/MassSpec"));
const MassSpecDetail = lazyPage(() => import("./pages/MassSpecDetail"));
const MassSpecCompare = lazyPage(() => import("./pages/MassSpecCompare"));
const GettingStarted = lazyPage(() => import("./pages/GettingStarted"));
const DataMigration = lazyPage(() => import("./pages/DataMigration"));
const Assistant = lazyPage(() => import("./pages/Assistant"));
const MigrationJobDetail = lazyPage(() => import("./pages/MigrationJobDetail"));
const SOPs = lazyPage(() => import("./pages/SOPs"));
const Batches = lazyPage(() => import("./pages/Batches"));
const QCReview = lazyPage(() => import("./pages/QCReview"));
const WorkQueue = lazyPage(() => import("./pages/WorkQueue"));
const Labels = lazyPage(() => import("./pages/Labels"));
const Comparisons = lazyPage(() => import("./pages/Comparisons"));
const Investigations = lazyPage(() => import("./pages/Investigations"));
const WorkflowDesigner = lazyPage(() => import("./pages/WorkflowDesigner"));
const Traceability = lazyPage(() => import("./pages/Traceability"));
const Registry = lazyPage(() => import("./pages/Registry"));
const NotebookPage = lazyPage(() => import("./pages/Notebook"));
const WorkflowRequests = lazyPage(() => import("./pages/WorkflowRequests"));

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
