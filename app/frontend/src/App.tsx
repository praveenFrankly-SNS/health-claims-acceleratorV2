import { useState } from "react";
import { Routes, Route } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Header from "./components/Header";

// Operational Command Center Pages
import Dashboard from "./pages/Dashboard";
import ClaimsList from "./pages/ClaimsList";
import ReviewQueue from "./pages/ReviewQueue";
import FraudRiskCenter from "./pages/FraudRiskCenter";
import ProviderIntelligence from "./pages/ProviderIntelligence";
import Analytics from "./pages/Analytics";
import AuditTrail from "./pages/AuditTrail";
import ClaimWorkbench from "./pages/ClaimWorkbench";

import type { AssignedRole } from "./types/claims";

export default function App() {
  const [currentRole, setCurrentRole] = useState<AssignedRole>("Claims Specialist");

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900 font-sans antialiased">
      {/* Fixed Left Navigation Sidebar */}
      <Sidebar />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Header Controls */}
        <Header currentRole={currentRole} onRoleChange={setCurrentRole} />

        {/* Page View Body */}
        <main className="flex-1 p-6 max-w-7xl w-full mx-auto space-y-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/claims" element={<ClaimsList />} />
            <Route path="/review-queue" element={<ReviewQueue currentRole={currentRole} />} />
            <Route path="/fraud-risk" element={<FraudRiskCenter />} />
            <Route path="/providers" element={<ProviderIntelligence />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/audit" element={<AuditTrail />} />
            
            {/* Centerpiece Drill-Down Experience */}
            <Route path="/claim/:id" element={<ClaimWorkbench currentRole={currentRole} />} />
          </Routes>
        </main>

        {/* Footer */}
        <footer className="border-t border-slate-200 py-4 text-center text-xs text-slate-500 bg-white">
          <div className="max-w-7xl mx-auto px-6 flex items-center justify-between">
            <span>© {new Date().getFullYear()} Health Claims Command Center • Enterprise Claims Operations</span>
            <span className="text-[11px] text-slate-500 font-medium">Claims Operations Management</span>
          </div>
        </footer>
      </div>
    </div>
  );
}
