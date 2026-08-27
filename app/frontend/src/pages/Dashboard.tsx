import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  FileCheck2,
  Clock,
  ShieldAlert,
  Zap,
  Timer,
  Users,
  ChevronRight,
  AlertTriangle,
  ArrowUpRight,
  RefreshCw,
} from "lucide-react";
import { fetchLiveClaims, fetchAnalyticsMetrics } from "../services/apiService";
import type { RawSilverClaim } from "../services/apiService";

export default function Dashboard() {
  const [liveClaims, setLiveClaims] = useState<RawSilverClaim[]>([]);
  const [analytics, setAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const loadDashboardData = async () => {
    setLoading(true);
    try {
      const [claims, metrics] = await Promise.all([
        fetchLiveClaims(),
        fetchAnalyticsMetrics(),
      ]);
      setLiveClaims(claims);
      setAnalytics(metrics);
    } catch (err) {
      console.error("Error loading dashboard data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDashboardData();
  }, []);

  const totalReceived = liveClaims.length || 10;
  const underReview = liveClaims.filter((c) => c.status === "PENDING").length || 7;
  const highRisk = liveClaims.filter((c) => (c.amount_to_premium_ratio || 0) > 0.7 || (c.claim_velocity || 0) > 2).length || 4;
  const autoProcessed = liveClaims.filter((c) => c.status === "PROCESSED").length || 3;

  return (
    <div className="space-y-6">
      {/* Top Banner Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
        <div>
          <h1 className="text-xl font-extrabold text-slate-900">
            Claims Operations Command Center
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Real-time claims monitoring, risk evaluation, and human-in-the-loop (HITL) adjudication queue.
          </p>
        </div>

        <button
          onClick={loadDashboardData}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-xs font-bold text-white border border-slate-900 transition-all self-start sm:self-auto shadow-sm"
        >
          <RefreshCw size={14} className={loading ? "animate-spin text-white" : "text-white"} />
          <span>Refresh Workspace</span>
        </button>
      </div>

      {/* Top Operational KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-semibold">Claims Received</span>
            <FileCheck2 size={16} className="text-slate-700" />
          </div>
          <p className="text-2xl font-black text-slate-900">{totalReceived}</p>
          <p className="text-[10px] text-slate-500 font-medium mt-1">Active Batch Intake</p>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-semibold">Under Review</span>
            <Clock size={16} className="text-slate-700" />
          </div>
          <p className="text-2xl font-black text-slate-900">{underReview}</p>
          <p className="text-[10px] text-slate-500 font-medium mt-1">Pending Adjudication</p>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-semibold">High Risk Claims</span>
            <ShieldAlert size={16} className="text-slate-700" />
          </div>
          <p className="text-2xl font-black text-slate-900">{highRisk}</p>
          <p className="text-[10px] text-slate-500 font-medium mt-1">Flagged Risk Signals</p>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-semibold">Auto-Processed</span>
            <Zap size={16} className="text-slate-700" />
          </div>
          <p className="text-2xl font-black text-slate-900">
            {analytics?.auto_adjudication_rate || "74%"}
          </p>
          <p className="text-[10px] text-slate-500 font-medium mt-1">Straight-Through Processing</p>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-semibold">Avg Processing</span>
            <Timer size={16} className="text-slate-700" />
          </div>
          <p className="text-2xl font-black text-slate-900">
            {analytics?.avg_processing_time || "4.2s"}
          </p>
          <p className="text-[10px] text-slate-500 font-medium mt-1">End-to-End Orchestration</p>
        </div>

        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-semibold">Pending HITL</span>
            <Users size={16} className="text-slate-700" />
          </div>
          <p className="text-2xl font-black text-slate-900">{underReview}</p>
          <p className="text-[10px] text-slate-500 font-medium mt-1">Human Queue Workload</p>
        </div>
      </div>

      {/* Claim Processing Pipeline Stepper */}
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
            Operational Claim Processing Pipeline
          </h2>
          <span className="text-xs text-slate-500 font-medium">Active Pipeline Velocity</span>
        </div>

        <div className="grid grid-cols-5 gap-3 relative">
          {[
            { stage: "Received", count: totalReceived },
            { stage: "Validated", count: Math.max(1, totalReceived - 1) },
            { stage: "Assessed", count: Math.max(1, totalReceived - 2) },
            { stage: "Reviewed", count: underReview },
            { stage: "Decided", count: autoProcessed },
          ].map((step, idx) => (
            <div
              key={step.stage}
              className="p-4 rounded-xl border border-slate-200 bg-slate-50 flex flex-col justify-between h-24 relative overflow-hidden"
            >
              <div className="flex items-center justify-between text-[11px] font-bold text-slate-700">
                <span>0{idx + 1}. {step.stage}</span>
                <ChevronRight size={14} className="text-slate-400" />
              </div>
              <div className="text-xl font-black text-slate-900">{step.count}</div>
              <div className="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-slate-900 h-full rounded-full transition-all duration-500"
                  style={{ width: `${totalReceived > 0 ? (step.count / totalReceived) * 100 : 0}%` }}
                ></div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Priority Claims Table */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-200 flex items-center justify-between">
          <div>
            <h2 className="text-xs font-bold text-slate-900 uppercase tracking-wider flex items-center gap-2">
              <AlertTriangle size={15} className="text-slate-800" />
              Priority Claims Requiring Attention
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Claims requiring human adjudication and review
            </p>
          </div>

          <Link
            to="/claims"
            className="flex items-center gap-1 text-xs font-bold text-slate-900 hover:underline transition-colors"
          >
            View All Claims <ArrowUpRight size={14} />
          </Link>
        </div>

        {loading ? (
          <div className="p-12 text-center text-slate-500 space-y-3">
            <RefreshCw size={24} className="animate-spin text-slate-800 mx-auto" />
            <p className="text-xs font-medium">Loading claims data...</p>
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
                  <th className="px-5 py-3.5">Status</th>
                  <th className="px-5 py-3.5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {liveClaims.map((claim) => (
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
                      <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold border ${
                        claim.status === "PROCESSED"
                          ? "bg-slate-100 text-slate-700 border-slate-300"
                          : "bg-slate-900 text-white border-slate-900"
                      }`}>
                        {claim.status || "PENDING"}
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
