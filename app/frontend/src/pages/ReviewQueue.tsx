import { useState, useEffect } from "react";
import { Shield, CheckCircle, XCircle, AlertTriangle, Search, Activity, UserCheck, RefreshCw } from "lucide-react";

interface ClaimReview {
  claim_id: string;
  pipeline_status: string;
  diagnosis: string;
  fraud_score: number;
  fraud_confidence: string;
  coverage_status: string;
  reserve_amount: number;
  assigned_adjuster: string;
}

interface AuditRecord {
  claim_id: string;
  action: string;
  reason: string;
  user: string;
  timestamp: string;
}

export default function ReviewQueue() {
  const [queue, setQueue] = useState<ClaimReview[]>([]);
  const [auditTrail, setAuditTrail] = useState<AuditRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedClaim, setSelectedClaim] = useState<ClaimReview | null>(null);
  const [decisionReason, setDecisionReason] = useState("");
  const [submittingDecision, setSubmittingDecision] = useState(false);
  const [activeTab, setActiveTab] = useState<"pending" | "all">("pending");

  const fetchData = async () => {
    try {
      const [queueRes, auditRes] = await Promise.all([
        fetch("/api/review/queue"),
        fetch("/api/review/audit"),
      ]);
      const queueData = await queueRes.json();
      const auditData = await auditRes.json();
      setQueue(queueData || []);
      setAuditTrail(auditData || []);
    } catch (err) {
      console.error("Failed to load review data", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  const handleAction = async (claimId: string, decision: string) => {
    if (!decisionReason.trim()) {
      alert("Please enter a justification reason for your decision.");
      return;
    }
    setSubmittingDecision(true);
    try {
      const res = await fetch("/api/decide", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          claim_id: claimId,
          decision,
          reason: decisionReason,
        }),
      });
      const data = await res.json();
      if (data.status === "SUCCESS") {
        setDecisionReason("");
        setSelectedClaim(null);
        fetchData();
      } else {
        alert("Failed to submit decision: " + data.message);
      }
    } catch (err) {
      alert("An error occurred during submission.");
      console.error(err);
    } finally {
      setSubmittingDecision(false);
    }
  };

  // Filter logic
  const pendingClaims = queue.filter(
    (c) => c.assigned_adjuster === "HUMAN_REVIEW" || c.assigned_adjuster === "manual"
  );
  
  const displayClaims = activeTab === "pending" ? pendingClaims : queue;
  const filteredClaims = displayClaims.filter(
    (c) =>
      c.claim_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.diagnosis?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.assigned_adjuster?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white mb-2">
            Adjuster Review Workspace
          </h1>
          <p className="text-slate-400">
            Audit automated agent decisions and process claims escalated for manual human review.
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="self-start inline-flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl border border-slate-700 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={refreshing ? "animate-spin text-indigo-400" : ""} size={16} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Stats Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="w-12 h-12 bg-amber-500/10 text-amber-400 rounded-xl flex items-center justify-center border border-amber-500/20 shadow-md">
            <Shield size={24} />
          </div>
          <div>
            <div className="text-sm text-slate-400 font-medium">Pending Human Action</div>
            <div className="text-3xl font-bold text-white mt-1">{pendingClaims.length}</div>
          </div>
        </div>

        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="w-12 h-12 bg-emerald-500/10 text-emerald-400 rounded-xl flex items-center justify-center border border-emerald-500/20 shadow-md">
            <UserCheck size={24} />
          </div>
          <div>
            <div className="text-sm text-slate-400 font-medium">Decisions Logged (Audit)</div>
            <div className="text-3xl font-bold text-white mt-1">{auditTrail.length}</div>
          </div>
        </div>

        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="w-12 h-12 bg-indigo-500/10 text-indigo-400 rounded-xl flex items-center justify-center border border-indigo-500/20 shadow-md">
            <Activity size={24} />
          </div>
          <div>
            <div className="text-sm text-slate-400 font-medium">Auto Adjudicated Ratio</div>
            <div className="text-3xl font-bold text-white mt-1">
              {queue.length > 0
                ? `${(((queue.length - pendingClaims.length) / queue.length) * 100).toFixed(0)}%`
                : "100%"}
            </div>
          </div>
        </div>
      </div>

      {/* Workspace Split */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main Claims Queue Table */}
        <div className="lg:col-span-2 space-y-6">
          <div className="glass rounded-2xl border border-slate-800 overflow-hidden shadow-xl">
            {/* Table Navigation Header */}
            <div className="p-6 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 bg-slate-900/40">
              <div className="flex gap-2 p-1 bg-slate-950 rounded-xl border border-slate-800 max-w-fit">
                <button
                  onClick={() => setActiveTab("pending")}
                  className={`px-4 py-1.5 rounded-lg text-xs font-semibold tracking-wider uppercase transition-colors ${
                    activeTab === "pending"
                      ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/10"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  Needs Action ({pendingClaims.length})
                </button>
                <button
                  onClick={() => setActiveTab("all")}
                  className={`px-4 py-1.5 rounded-lg text-xs font-semibold tracking-wider uppercase transition-colors ${
                    activeTab === "all"
                      ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/10"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  All Claims ({queue.length})
                </button>
              </div>

              {/* Search */}
              <div className="relative max-w-xs">
                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
                <input
                  type="text"
                  placeholder="Search claims..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-855 rounded-xl pl-10 pr-4 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>

            {/* List Table */}
            {loading ? (
              <div className="flex flex-col items-center justify-center py-20 text-slate-400 gap-3">
                <RefreshCw className="animate-spin text-indigo-500" size={32} />
                <p>Loading queue from Unity Catalog...</p>
              </div>
            ) : filteredClaims.length === 0 ? (
              <div className="text-center py-20 text-slate-500">
                No claims match the search or filter criteria.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-800 text-xs text-slate-400 uppercase tracking-wider bg-slate-950/20">
                      <th className="py-4 px-6 font-semibold">Claim ID</th>
                      <th className="py-4 px-6 font-semibold">Diagnosis</th>
                      <th className="py-4 px-6 font-semibold">Fraud Risk</th>
                      <th className="py-4 px-6 font-semibold">Coverage</th>
                      <th className="py-4 px-6 font-semibold">Reserve</th>
                      <th className="py-4 px-6 font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredClaims.map((claim) => (
                      <tr
                        key={claim.claim_id}
                        onClick={() => setSelectedClaim(claim)}
                        className={`border-b border-slate-800/60 hover:bg-slate-850/30 cursor-pointer transition-colors ${
                          selectedClaim?.claim_id === claim.claim_id
                            ? "bg-indigo-500/5 border-l-2 border-l-indigo-500"
                            : ""
                        }`}
                      >
                        <td className="py-4 px-6 font-mono text-sm text-indigo-400 font-bold">
                          {claim.claim_id}
                        </td>
                        <td className="py-4 px-6 font-medium text-slate-200">
                          {claim.diagnosis || "N/A"}
                        </td>
                        <td className="py-4 px-6">
                          <span
                            className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-semibold ${
                              claim.fraud_score > 0.6
                                ? "bg-red-500/10 text-red-400 border border-red-500/20"
                                : claim.fraud_score > 0.3
                                ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                                : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                            }`}
                          >
                            {Math.round(claim.fraud_score * 100)}%
                          </span>
                        </td>
                        <td className="py-4 px-6">
                          <span
                            className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-semibold ${
                              claim.coverage_status === "VERIFIED"
                                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                : "bg-red-500/10 text-red-400 border border-red-500/20"
                            }`}
                          >
                            {claim.coverage_status}
                          </span>
                        </td>
                        <td className="py-4 px-6 font-mono text-sm text-slate-300">
                          ${claim.reserve_amount ? claim.reserve_amount.toLocaleString() : "0"}
                        </td>
                        <td className="py-4 px-6">
                          <span
                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                              claim.assigned_adjuster === "HUMAN_REVIEW" ||
                              claim.assigned_adjuster === "manual"
                                ? "bg-amber-500/10 text-amber-300 border border-amber-500/20"
                                : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                            }`}
                          >
                            {claim.assigned_adjuster === "HUMAN_REVIEW" ||
                            claim.assigned_adjuster === "manual"
                              ? "MANUAL REVIEW"
                              : claim.assigned_adjuster}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Right Panel: Decision Action / Audit History */}
        <div className="space-y-6">
          {/* Action Card */}
          <div className="glass p-6 rounded-2xl border border-slate-800 shadow-xl relative overflow-hidden">
            {selectedClaim ? (
              <div className="space-y-6">
                <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                  <div>
                    <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">
                      Auditing Claim
                    </div>
                    <div className="text-xl font-mono text-indigo-400 font-bold">
                      {selectedClaim.claim_id}
                    </div>
                  </div>
                  <button
                    onClick={() => setSelectedClaim(null)}
                    className="text-xs text-slate-400 hover:text-white"
                  >
                    Close
                  </button>
                </div>

                {/* Score details */}
                <div className="space-y-4">
                  <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800 space-y-3">
                    <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                      Agent Diagnostic Trace
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-slate-400">Diagnosis Code:</span>
                      <span className="font-mono text-white">{selectedClaim.diagnosis || "N/A"}</span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-slate-400">Fraud Score:</span>
                      <span
                        className={`font-semibold ${
                          selectedClaim.fraud_score > 0.6 ? "text-red-400" : "text-emerald-400"
                        }`}
                      >
                        {Math.round(selectedClaim.fraud_score * 100)}%
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-slate-400">Coverage Verification:</span>
                      <span className="text-emerald-400 font-semibold">
                        {selectedClaim.coverage_status}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-slate-400">Suggested Reserve:</span>
                      <span className="font-mono text-white">
                        ${selectedClaim.reserve_amount?.toLocaleString()}
                      </span>
                    </div>
                  </div>

                  {/* Input Form */}
                  <div className="space-y-3">
                    <label className="block text-sm font-medium text-slate-300">
                      Adjuster Justification Reason
                    </label>
                    <textarea
                      rows={3}
                      required
                      placeholder="Input clinical rationale or fraud assessment details..."
                      value={decisionReason}
                      onChange={(e) => setDecisionReason(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl p-3 text-sm text-white focus:outline-none focus:border-indigo-500 placeholder-slate-600"
                    />
                  </div>

                  {/* Action Buttons */}
                  <div className="grid grid-cols-3 gap-2">
                    <button
                      onClick={() => handleAction(selectedClaim.claim_id, "APPROVED")}
                      disabled={submittingDecision}
                      className="bg-emerald-600 hover:bg-emerald-500 text-white py-2 rounded-xl text-xs font-bold transition-all shadow-md shadow-emerald-600/10 flex items-center justify-center gap-1.5"
                    >
                      <CheckCircle size={14} />
                      Approve
                    </button>
                    <button
                      onClick={() => handleAction(selectedClaim.claim_id, "DENIED")}
                      disabled={submittingDecision}
                      className="bg-red-600 hover:bg-red-500 text-white py-2 rounded-xl text-xs font-bold transition-all shadow-md shadow-red-600/10 flex items-center justify-center gap-1.5"
                    >
                      <XCircle size={14} />
                      Deny
                    </button>
                    <button
                      onClick={() => handleAction(selectedClaim.claim_id, "INVESTIGATE")}
                      disabled={submittingDecision}
                      className="bg-amber-600 hover:bg-amber-500 text-white py-2 rounded-xl text-xs font-bold transition-all shadow-md shadow-amber-600/10 flex items-center justify-center gap-1.5"
                    >
                      <AlertTriangle size={14} />
                      Investigate
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-12 text-center text-slate-500 flex flex-col items-center gap-3">
                <UserCheck size={36} className="text-slate-600" />
                <p className="text-sm">Select a claim from the queue to process a decision.</p>
              </div>
            )}
          </div>

          {/* Audit Trail Card */}
          <div className="glass p-6 rounded-2xl border border-slate-800 shadow-xl space-y-4">
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <Activity size={18} className="text-indigo-400" />
              Adjuster Audit Trail
            </h3>

            {auditTrail.length === 0 ? (
              <div className="text-center py-6 text-slate-600 text-xs">No recent audits recorded.</div>
            ) : (
              <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
                {auditTrail.map((audit, i) => (
                  <div key={i} className="bg-slate-900/40 p-3 rounded-xl border border-slate-800 text-xs space-y-1.5">
                    <div className="flex items-center justify-between font-semibold">
                      <span className="font-mono text-indigo-400 font-bold">{audit.claim_id}</span>
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-bold ${
                          audit.action === "APPROVED"
                            ? "bg-emerald-500/10 text-emerald-400"
                            : audit.action === "DENIED"
                            ? "bg-red-500/10 text-red-400"
                            : "bg-amber-500/10 text-amber-400"
                        }`}
                      >
                        {audit.action}
                      </span>
                    </div>
                    <p className="text-slate-400 leading-relaxed italic">"{audit.reason}"</p>
                    <div className="flex items-center justify-between text-[10px] text-slate-500 pt-1 border-t border-slate-800/40">
                      <span>By: {audit.user}</span>
                      <span>
                        {new Date(audit.timestamp).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
