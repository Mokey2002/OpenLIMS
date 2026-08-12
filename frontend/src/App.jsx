import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./Layout";
import SamplesList from "./pages/SamplesList";
import SampleDetail from "./pages/SampleDetail";
import Inventory from "./pages/Inventory";
import Events from "./pages/Events";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Analyze from "./pages/Analyze";
import Projects from "./pages/Projects";
import ProjectDetail from "./pages/ProjectDetail";
import Users from "./pages/Users";
import Imports from "./pages/Imports";
import Notifications from "./pages/Notifications";
import { isLoggedIn } from "./auth";
import ImportDetail from "./pages/ImportDetail";
import Sequences from "./pages/Sequences";
import Alignments from "./pages/Alignments";
import AdminSettings from "./pages/AdminSettings";
import Reports from "./pages/Reports";
import SystemStatus from "./pages/SystemStatus";
import Search from "./pages/Search";
import Blast from "./pages/Blast";
import MassSpec from "./pages/MassSpec";
import MassSpecDetail from "./pages/MassSpecDetail";
import MassSpecCompare from "./pages/MassSpecCompare";
import GettingStarted from "./pages/GettingStarted";
import DataMigration from "./pages/DataMigration";
import Assistant from "./pages/Assistant";
import MigrationJobDetail from "./pages/MigrationJobDetail";
import SOPs from "./pages/SOPs";
import Batches from "./pages/Batches";
import QCReview from "./pages/QCReview";
import WorkQueue from "./pages/WorkQueue";
import Labels from "./pages/Labels";
import Comparisons from "./pages/Comparisons";
import Investigations from "./pages/Investigations";

function RequireAuth({ children }) {
  return isLoggedIn() ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="getting-started" element={<GettingStarted />} />
          <Route path="assistant" element={<Assistant />} />
          <Route path="samples" element={<SamplesList />} />
          <Route path="samples/:id" element={<SampleDetail />} />
          <Route path="inventory" element={<Inventory />} />
          <Route path="events" element={<Events />} />
          <Route path="analyze" element={<Analyze />} />
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:id" element={<ProjectDetail />} />
          <Route path="sequences" element={<Sequences />} />
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
    </BrowserRouter>
  );
}
