import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Search, ChevronRight, RefreshCw, FileText } from "lucide-react";
import { fetchLiveClaims } from "../services/apiService";
import type { RawSilverClaim } from "../services/apiService";

export default function ClaimsList() {
  const [claims, setClaims] = useState<RawSilverClaim[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");

  const loadClaims = async () => {
    setLoading(true);
    try {
      const data = await fetchLiveClaims();
      setClaims(data);
    } catch (err) {
      console.error("Failed to load claims list:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadClaims();
  }, []);

  const filteredClaims = claims.filter((claim) => {
    const matchesSearch =
      (claim.claim_id || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
      (claim.policy_number || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
      (claim.claimant_id || "").toLowerCase().includes(searchQuery.toLowerCase());

    const matchesStatus =
      statusFilter === "ALL" ||
      (statusFilter === "PROCESSED" && claim.status === "PROCESSED") ||
      (statusFilter === "PENDING" && claim.status !== "PROCESSED");

    return matchesSearch && matchesStatus;
  });

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
        <div>
          <h1 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
            <FileText size={20} className="text-slate-700" />
            Claims Repository
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Search, filter, and inspect claims synchronized across operational repositories.
          </p>
        </div>

        <button
          onClick={loadClaims}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-xs font-bold text-white border border-slate-900 transition-all self-start sm:self-auto shadow-sm"
        >
          <RefreshCw size={14} className={loading ? "animate-spin text-white" : "text-white"} />
          <span>Refresh Claims</span>
        </button>
      </div>

      {/* Filter Controls Bar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col md:flex-row items-center justify-between gap-4">
        {/* Search */}
        <div className="relative w-full md:w-96">
          <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search claim #, policy #, claimant ID..."
            className="w-full pl-10 pr-4 py-2 rounded-xl bg-slate-100 border border-slate-200 text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:border-slate-400"
          />
        </div>

        {/* Status Filter */}
        <div className="flex items-center gap-3 w-full md:w-auto">
          <div className="flex items-center gap-2 bg-slate-100 p-1 rounded-xl border border-slate-200 text-xs">
            <button
              onClick={() => setStatusFilter("ALL")}
              className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                statusFilter === "ALL" ? "bg-slate-900 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              All ({claims.length})
            </button>
            <button
              onClick={() => setStatusFilter("PENDING")}
              className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                statusFilter === "PENDING" ? "bg-slate-900 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              Pending ({claims.filter((c) => c.status !== "PROCESSED").length})
            </button>
            <button
              onClick={() => setStatusFilter("PROCESSED")}
              className={`px-3 py-1.5 rounded-lg font-bold transition-all ${
                statusFilter === "PROCESSED" ? "bg-slate-900 text-white shadow-sm" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              Processed ({claims.filter((c) => c.status === "PROCESSED").length})
            </button>
          </div>
        </div>
      </div>

      {/* Main Claims Table */}
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
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
                  <th className="px-5 py-3.5">Days Since Inception</th>
                  <th className="px-5 py-3.5">Claimed Amount</th>
                  <th className="px-5 py-3.5">Status</th>
                  <th className="px-5 py-3.5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredClaims.map((claim) => (
                  <tr key={claim.claim_id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-5 py-4 font-mono font-bold text-slate-900">
                      {claim.claim_id}
                    </td>
                    <td className="px-5 py-4 font-medium text-slate-700">
                      {claim.policy_number || "N/A"}
                    </td>
                    <td className="px-5 py-4 text-slate-700">
                      {claim.claimant_id || "N/A"}
                    </td>
                    <td className="px-5 py-4 text-slate-500">
                      {claim.date_of_loss || "N/A"}
                    </td>
                    <td className="px-5 py-4 text-slate-500">
                      {claim.days_since_inception ?? "N/A"} days
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
