import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, RefreshCw } from "lucide-react";
import { fetchLiveClaims } from "../services/apiService";
import type { AssignedRole } from "../types/claims";

interface ReviewQueueProps {
  currentRole: AssignedRole;
}

export default function ReviewQueue({ currentRole }: ReviewQueueProps) {
  const [queue, setQueue] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const loadQueue = async () => {
    setLoading(true);
    try {
      const data = await fetchLiveClaims();
      setQueue(data);
    } catch (err) {
      console.error("Error loading review queue:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadQueue();
  }, []);

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-extrabold text-slate-900">HITL Review Queue</h1>
            <span className="px-3 py-1 rounded-full text-xs font-bold bg-slate-900 text-white">
              {currentRole}
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Claims requiring human adjudication and domain expert review.
          </p>
        </div>

        <button
          onClick={loadQueue}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-xs font-bold text-white border border-slate-900 transition-all self-start sm:self-auto shadow-sm"
        >
          <RefreshCw size={14} className={loading ? "animate-spin text-white" : "text-white"} />
          <span>Refresh Queue</span>
        </button>
      </div>

      {/* Queue Table */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-slate-500 space-y-3">
            <RefreshCw size={24} className="animate-spin text-slate-800 mx-auto" />
            <p className="text-xs font-medium">Loading review queue...</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-800">
              <thead className="bg-slate-50 text-[11px] font-bold text-slate-600 uppercase tracking-wider border-b border-slate-200">
                <tr>
                  <th className="px-5 py-3.5">Claim ID</th>
                  <th className="px-5 py-3.5">Policy Number</th>
                  <th className="px-5 py-3.5">Claimant ID</th>
                  <th className="px-5 py-3.5">Date of Loss</th>
                  <th className="px-5 py-3.5">Claimed Amount</th>
                  <th className="px-5 py-3.5">Risk Level</th>
                  <th className="px-5 py-3.5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {queue.map((claim) => (
                  <tr key={claim.claim_id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-5 py-4 font-mono font-bold text-slate-900">
                      {claim.claim_id}
                    </td>
                    <td className="px-5 py-4 font-medium text-slate-700">
                      {claim.policy_number || "POL-2024"}
                    </td>
                    <td className="px-5 py-4 text-slate-700">
                      {claim.claimant_id || "MEM-IN"}
                    </td>
                    <td className="px-5 py-4 text-slate-500">
                      {claim.date_of_loss || "2026-08-20"}
                    </td>
                    <td className="px-5 py-4 font-bold text-slate-900">
                      ₹{(claim.claimed_amount || 0).toLocaleString("en-IN")}
                    </td>
                    <td className="px-5 py-4">
                      <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-slate-900 text-white border border-slate-900">
                        HIGH RISK
                      </span>
                    </td>
                    <td className="px-5 py-4 text-right">
                      <Link
                        to={`/claim/${claim.claim_id}`}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-xs font-bold text-white transition-all shadow-sm"
                      >
                        Workbench <ChevronRight size={13} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
