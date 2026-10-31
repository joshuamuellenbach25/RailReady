import "@/App.css";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/lib/auth";
import { Loading } from "@/components/rr/ui";
import { ErrorBoundary } from "@/components/rr/ErrorBoundary";
import OfficeLayout from "@/components/rr/OfficeLayout";
import Home from "@/pages/Home";
import SceneWorkspace from "@/pages/SceneWorkspace";
import Login from "@/pages/Login";
import Jobs from "@/pages/Jobs";
import Inbox from "@/pages/Inbox";
import VisitReview from "@/pages/VisitReview";
import Estimate from "@/pages/Estimate";
import Proposal from "@/pages/Proposal";
import Contracts from "@/pages/Contracts";
import ContractDetail from "@/pages/ContractDetail";
import WorkOrder from "@/pages/WorkOrder";
import RepairDetail, { Repairs } from "@/pages/Repair";
import CustomerProposal from "@/pages/CustomerProposal";
import NotFound from "@/pages/NotFound";
import Templates from "@/pages/settings/Templates";
import TemplateDetail from "@/pages/settings/TemplateDetail";
import Processing from "@/pages/settings/Processing";
import Diagnostics from "@/pages/Diagnostics";

function RequireAuth({ children }) {
  const { user } = useAuth();
  const loc = useLocation();
  if (user === null) return <Loading text="Authenticating..." />;
  if (user === false) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return children;
}

const page = (el) => <ErrorBoundary>{el}</ErrorBoundary>;

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={page(<Home />)} />
          <Route path="/demo" element={page(<Home />)} />
          <Route path="/office/visits/:id/scene" element={<RequireAuth>{page(<SceneWorkspace />)}</RequireAuth>} />
          <Route path="/login" element={page(<Login />)} />
          <Route path="/p/:token" element={page(<CustomerProposal />)} />
          <Route path="/office" element={<RequireAuth><OfficeLayout /></RequireAuth>}>
            <Route index element={<Navigate to="/office/jobs" replace />} />
            <Route path="jobs" element={page(<Jobs />)} />
            <Route path="inbox" element={page(<Inbox />)} />
            <Route path="visits/:id" element={page(<VisitReview />)} />
            <Route path="visits/:id/estimate" element={page(<Estimate />)} />
            <Route path="proposals/:id" element={page(<Proposal />)} />
            <Route path="contracts" element={page(<Contracts />)} />
            <Route path="contracts/:id" element={page(<ContractDetail />)} />
            <Route path="work-orders/:id" element={page(<WorkOrder />)} />
            <Route path="repairs" element={page(<Repairs />)} />
            <Route path="repairs/:id" element={page(<RepairDetail />)} />
            <Route path="settings" element={<Navigate to="/office/settings/templates" replace />} />
            <Route path="settings/templates" element={page(<Templates />)} />
            <Route path="settings/templates/:id" element={page(<TemplateDetail />)} />
            <Route path="settings/processing" element={page(<Processing />)} />
            <Route path="diagnostics" element={page(<Diagnostics />)} />
            <Route path="calibration" element={<Navigate to="/office/diagnostics" replace />} />
            <Route path="*" element={<NotFound />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
