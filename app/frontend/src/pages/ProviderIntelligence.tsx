import { Building2 } from "lucide-react";

export default function ProviderIntelligence() {
  const providers = [
    { name: "Apollo Hospitals (Main Campus)", id: "HOSP-001", network: "IN-NETWORK", risk: "LOW", score: "98%" },
    { name: "Fortis Healthcare Center", id: "HOSP-002", network: "IN-NETWORK", risk: "LOW", score: "94%" },
    { name: "XYZ Specialty Clinic", id: "HOSP-088", network: "OUT-OF-NETWORK", risk: "HIGH", score: "42%" },
    { name: "City Care Nursing Home", id: "HOSP-099", network: "OUT-OF-NETWORK", risk: "MEDIUM", score: "68%" },
  ];

  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
        <h1 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Building2 size={20} className="text-slate-800" /> Provider Intelligence & Network Governance
        </h1>
        <p className="text-xs text-slate-500 mt-1">
          Hospital network tiering, billing benchmark compliance, and provider risk scores.
        </p>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <table className="w-full text-left text-xs text-slate-800">
          <thead className="bg-slate-50 text-[11px] font-bold text-slate-600 uppercase border-b border-slate-200">
            <tr>
              <th className="px-5 py-3.5">Hospital Name</th>
              <th className="px-5 py-3.5">Provider ID</th>
              <th className="px-5 py-3.5">Network Status</th>
              <th className="px-5 py-3.5">Billing Compliance Score</th>
              <th className="px-5 py-3.5 text-right">Risk Level</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {providers.map((p) => (
              <tr key={p.id} className="hover:bg-slate-50 transition-colors">
                <td className="px-5 py-4 font-bold text-slate-900">{p.name}</td>
                <td className="px-5 py-4 font-mono font-medium text-slate-700">{p.id}</td>
                <td className="px-5 py-4">
                  <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold border ${
                    p.network === "IN-NETWORK" ? "bg-slate-100 text-slate-800 border-slate-300" : "bg-slate-900 text-white border-slate-900"
                  }`}>
                    {p.network}
                  </span>
                </td>
                <td className="px-5 py-4 font-bold text-slate-900">{p.score}</td>
                <td className="px-5 py-4 text-right">
                  <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold border ${
                    p.risk === "HIGH" ? "bg-slate-900 text-white border-slate-900" : "bg-slate-100 text-slate-700 border-slate-300"
                  }`}>
                    {p.risk} RISK
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
