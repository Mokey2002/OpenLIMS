import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./Layout";
import SamplesList from "./pages/SamplesList";
import SampleDetail from "./pages/SampleDetail";
import Inventory from "./pages/Inventory";
import Events from "./pages/Events";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import { isLoggedIn } from "./auth";
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
    <Route index element={<Dashboard />}/>
    <Route path="samples" element={<SamplesList />} />
    <Route path="samples/:id" element={<SampleDetail />} />
    <Route path="inventory" element={<Inventory />} />
    <Route path="events" element={<Events />} />
  </Route>

  <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>    
</BrowserRouter>
  );
}
