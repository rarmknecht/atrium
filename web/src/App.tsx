import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { Context } from "./pages/Context";
import { Dashboard } from "./pages/Dashboard";
import { ModuleDetail } from "./pages/ModuleDetail";
import { Modules } from "./pages/Modules";
import { Reports } from "./pages/Reports";
import { Settings } from "./pages/Settings";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="modules" element={<Modules />} />
        <Route path="modules/:id" element={<ModuleDetail />} />
        <Route path="context" element={<Context />} />
        <Route path="reports" element={<Reports />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
