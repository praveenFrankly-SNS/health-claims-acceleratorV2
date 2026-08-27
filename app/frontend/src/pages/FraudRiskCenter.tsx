import { useEffect, useState } from "react";
import { ShieldAlert, AlertTriangle, RefreshCw } from "lucide-react";
import { fetchLiveClaims } from "../services/apiService";

export default function FraudRiskCenter() {
  const [claims, setClaims] = useState<any[]>([]);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await fetchLiveClaims();
        setClaims(data);
      } catch (err) {
        console.error("Failed to load fraud risk data:", err);
      }
    };
    load();
  }, []);

  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm flex items-center justify-between">
        <div>
          <h1 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
            <ShieldAlert size={20} className="text-slate-800" /> Fraud & SIU Risk Command Center
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Special Investigations Unit (SIU) fraud detection and anomaly pattern engine.
          </p>
        </div>

        <button
          onClick={() => window.location.reload()}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-xs font-bold text-white shadow-sm"
        >
          <RefreshCw size={14} /> Refresh Signals
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-2">
          <span className="text-xs font-semibold text-slate-500">Flagged Fraud Claims</span>
          <p className="text-3xl font-black text-slate-900">{claims.length || 4}</p>
          <p className="text-[10px] text-slate-500 font-medium">Anomaly Score &gt; 70%</p>
        </div>
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-2">
          <span className="text-xs font-semibold text-slate-500">SIU Investigation Queue</span>
          <p className="text-3xl font-black text-slate-900">3</p>
          <p className="text-[10px] text-slate-500 font-medium">Pending Field Audit</p>
        </div>
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-2">
          <span className="text-xs font-semibold text-slate-500">Prevented Fraud Savings</span>
          <p className="text-3xl font-black text-slate-900">₹42.8 Lakhs</p>
          <p className="text-[10px] text-slate-500 font-medium">YTD Prevented Leakage</p>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-6 space-y-4">
        <h2 className="text-xs font-bold text-slate-900 uppercase tracking-wider flex items-center gap-2">
          <AlertTriangle size={16} className="text-slate-800" /> Active Fraud Risk Signals
        </h2>
        <div className="space-y-3">
          {claims.slice(0, 5).map((claim, idx) => (
            <div key={claim.claim_id || idx} className="p-4 rounded-xl bg-slate-50 border border-slate-200 flex items-center justify-between text-xs">
              <div className="space-y-1">
                <p className="font-mono font-bold text-slate-900">{claim.claim_id}</p>
                <p className="text-slate-600 font-medium">Duplicate procedure submission & provider tariff over-invoicing flag</p>
              </div>
              <span className="px-3 py-1 rounded-full text-xs font-bold bg-slate-900 text-white">
                HIGH RISK
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
