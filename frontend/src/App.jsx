import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./Layout";
import SamplesList from "./pages/SamplesList";
import SampleDetail from "./pages/SampleDetail";
import Inventory from "./pages/Inventory";
import Events from "./pages/Events";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/samples" replace />} />
          <Route path="/samples" element={<SamplesList />} />
          <Route path="/samples/:id" element={<SampleDetail />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/events" element={<Events />} />
          <Route path="*" element={<div>Not Found</div>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
