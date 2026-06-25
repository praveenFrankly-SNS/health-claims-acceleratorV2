import { useState, useEffect } from "react";
import { Database, Search, ChevronDown, ChevronRight, FileCode, RefreshCw } from "lucide-react";

interface GoldClaimDecision {
  claim_id: string;
  pipeline_status: string;
  coverage_status: string;
  fraud_score: number;
  adjuster_allocation: string;
  payload: any;
}

export default function GoldExplorer() {
  const [decisions, setDecisions] = useState<GoldClaimDecision[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedDecision, setSelectedDecision] = useState<GoldClaimDecision | null>(null);

  const fetchExplorerData = async () => {
    try {
      const res = await fetch("/api/explorer");
      const data = await res.json();
      setDecisions(data || []);
    } catch (err) {
      console.error("Error loading gold explorer data", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchExplorerData();
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchExplorerData();
  };

  const filteredDecisions = decisions.filter(
    (d) =>
      d.claim_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      d.adjuster_allocation.toLowerCase().includes(searchTerm.toLowerCase()) ||
      d.coverage_status.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white mb-2">
            Gold Decisions Explorer
          </h1>
          <p className="text-slate-400">
            Audit delta tables in Unity Catalog containing finalized multi-agent decisions.
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Table List of Decisions */}
        <div className="lg:col-span-2 space-y-6">
          <div className="glass rounded-2xl border border-slate-800 overflow-hidden shadow-xl">
            {/* Search */}
            <div className="p-6 border-b border-slate-800 flex items-center justify-between gap-4 bg-slate-900/40">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Database size={18} className="text-indigo-400" />
                Table: gold_claim_decisions
              </h3>

              <div className="relative max-w-xs w-full">
                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" size={16} />
                <input
                  type="text"
                  placeholder="Search claim records..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-10 pr-4 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>

            {loading ? (
              <div className="flex flex-col items-center justify-center py-20 text-slate-400 gap-3">
                <RefreshCw className="animate-spin text-indigo-500" size={32} />
                <p>Reading Unity Catalog Delta logs...</p>
              </div>
            ) : filteredDecisions.length === 0 ? (
              <div className="text-center py-20 text-slate-500">
                No finalized claims database records found.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-800 text-xs text-slate-400 uppercase tracking-wider bg-slate-950/20">
                      <th className="py-4 px-6 font-semibold">Claim ID</th>
                      <th className="py-4 px-6 font-semibold">Pipeline Status</th>
                      <th className="py-4 px-6 font-semibold">Coverage Status</th>
                      <th className="py-4 px-6 font-semibold">Fraud Risk</th>
                      <th className="py-4 px-6 font-semibold">Assigned Route</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredDecisions.map((dec) => (
                      <tr
                        key={dec.claim_id}
                        onClick={() => setSelectedDecision(dec)}
                        className={`border-b border-slate-800/60 hover:bg-slate-850/30 cursor-pointer transition-colors ${
                          selectedDecision?.claim_id === dec.claim_id
                            ? "bg-indigo-500/5 border-l-2 border-l-indigo-500"
                            : ""
                        }`}
                      >
                        <td className="py-4 px-6 font-mono text-sm text-indigo-400 font-bold">
                          {dec.claim_id}
                        </td>
                        <td className="py-4 px-6">
                          <span
                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] uppercase font-bold ${
                              dec.pipeline_status === "COMPLETED"
                                ? "bg-emerald-500/10 text-emerald-400"
                                : "bg-red-500/10 text-red-400"
                            }`}
                          >
                            {dec.pipeline_status}
                          </span>
                        </td>
                        <td className="py-4 px-6 font-semibold text-slate-300">
                          {dec.coverage_status}
                        </td>
                        <td className="py-4 px-6 font-mono text-slate-400">
                          {Math.round(dec.fraud_score * 100)}%
                        </td>
                        <td className="py-4 px-6">
                          <span className="font-semibold text-slate-200">
                            {dec.adjuster_allocation === "HUMAN_REVIEW"
                              ? "Manual Review"
                              : dec.adjuster_allocation}
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

        {/* JSON Viewer Sidebar */}
        <div className="space-y-6">
          <div className="glass p-6 rounded-2xl border border-slate-800 shadow-xl min-h-[500px] flex flex-col">
            {selectedDecision ? (
              <div className="flex-1 flex flex-col space-y-4">
                <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                  <div className="flex items-center gap-2">
                    <FileCode size={18} className="text-indigo-400" />
                    <div>
                      <h4 className="text-sm font-semibold text-white">State Metadata Document</h4>
                      <p className="text-[10px] text-slate-400 font-mono">{selectedDecision.claim_id}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => setSelectedDecision(null)}
                    className="text-xs text-slate-400 hover:text-white"
                  >
                    Clear
                  </button>
                </div>

                {/* Collapsible tree component */}
                <div className="flex-1 overflow-auto max-h-[550px] font-mono text-xs text-slate-300 bg-slate-950 p-4 rounded-xl border border-slate-800/80">
                  <JsonNode value={selectedDecision.payload} name="claim_state" isLast={true} />
                </div>
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center text-slate-500 gap-3 py-20 text-center">
                <FileCode size={36} className="text-slate-600" />
                <p className="text-sm max-w-[200px]">
                  Select a claim database row to inspect the full structured JSON.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// Collapsible JSON Tree Node
function JsonNode({ value, name, isLast = true }: { value: any; name: string; isLast?: boolean }) {
  const [collapsed, setCollapsed] = useState(false);

  const type = typeof value;
  const isObject = value !== null && type === "object";

  if (value === null) {
    return (
      <div className="pl-4 py-0.5">
        <span className="text-slate-500 font-semibold">{name}: </span>
        <span className="text-slate-400">null</span>
        {!isLast && <span className="text-slate-500">,</span>}
      </div>
    );
  }

  if (!isObject) {
    let renderedVal = String(value);
    let valColor = "text-amber-300";

    if (type === "number") valColor = "text-cyan-400";
    if (type === "boolean") valColor = "text-rose-400";
    if (type === "string") renderedVal = `"${value}"`;

    return (
      <div className="pl-4 py-0.5">
        <span className="text-slate-400 font-semibold">{name}: </span>
        <span className={valColor}>{renderedVal}</span>
        {!isLast && <span className="text-slate-500">,</span>}
      </div>
    );
  }

  // Handle Arrays & Objects
  const isArray = Array.isArray(value);
  const keys = Object.keys(value);
  const startBrace = isArray ? "[" : "{";
  const endBrace = isArray ? "]" : "}";

  if (keys.length === 0) {
    return (
      <div className="pl-4 py-0.5">
        <span className="text-slate-400 font-semibold">{name}: </span>
        <span className="text-slate-500">
          {startBrace}
          {endBrace}
        </span>
        {!isLast && <span className="text-slate-500">,</span>}
      </div>
    );
  }

  return (
    <div className="py-0.5">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-1 text-slate-400 font-semibold hover:text-white transition-colors"
      >
        {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        <span>{name}:</span>
        <span className="text-slate-500 text-[10px]">
          {startBrace} {collapsed && `... ${keys.length} items ${endBrace}`}
        </span>
      </button>

      {!collapsed && (
        <div className="border-l border-slate-800 pl-4 ml-1.5 mt-0.5 space-y-0.5">
          {keys.map((key, index) => (
            <JsonNode
              key={key}
              name={key}
              value={value[key]}
              isLast={index === keys.length - 1}
            />
          ))}
        </div>
      )}

      {!collapsed && <div className="text-slate-500 pl-4">{endBrace}{!isLast && ","}</div>}
    </div>
  );
}
