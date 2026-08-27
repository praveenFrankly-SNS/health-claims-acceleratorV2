import { History } from "lucide-react";

export default function AuditTrail() {
  const auditLogs = [
    { id: "LOG-9001", claimId: "CLM-2026-00439", action: "ADJUDICATED", actor: "Anand K. (Claims Lead)", decision: "INVESTIGATE", timestamp: "2026-08-27 10:45 AM" },
    { id: "LOG-9002", claimId: "CLM-41674", action: "AI_EVALUATION", actor: "AI Fraud Agent 2", decision: "HIGH_RISK_FLAG", timestamp: "2026-08-27 10:42 AM" },
    { id: "LOG-9003", claimId: "CLM-2026-00437", action: "SYSTEM_INTAKE", actor: "Ingestion Orchestrator", decision: "RECEIVED", timestamp: "2026-08-27 10:35 AM" },
  ];

  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
        <h1 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <History size={20} className="text-slate-800" /> Regulatory & Compliance Audit Trail
        </h1>
        <p className="text-xs text-slate-500 mt-1">
          Immutable log of AI evaluations, human overrides, and claims decision timestamps.
        </p>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-left text-xs text-slate-800">
          <thead className="bg-slate-50 text-[11px] font-bold text-slate-600 uppercase border-b border-slate-200">
            <tr>
              <th className="px-5 py-3.5">Log ID</th>
              <th className="px-5 py-3.5">Claim ID</th>
              <th className="px-5 py-3.5">Event Type</th>
              <th className="px-5 py-3.5">Actor</th>
              <th className="px-5 py-3.5">Logged Decision</th>
              <th className="px-5 py-3.5 text-right">Timestamp</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {auditLogs.map((log) => (
              <tr key={log.id} className="hover:bg-slate-50 transition-colors">
                <td className="px-5 py-4 font-mono font-bold text-slate-900">{log.id}</td>
                <td className="px-5 py-4 font-mono font-bold text-slate-900">{log.claimId}</td>
                <td className="px-5 py-4 font-medium text-slate-700">{log.action}</td>
                <td className="px-5 py-4 text-slate-700">{log.actor}</td>
                <td className="px-5 py-4">
                  <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-slate-900 text-white border border-slate-900">
                    {log.decision}
                  </span>
                </td>
                <td className="px-5 py-4 text-right font-medium text-slate-500">{log.timestamp}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
