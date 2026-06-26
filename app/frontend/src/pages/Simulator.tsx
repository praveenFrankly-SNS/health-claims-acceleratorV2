import { useState, useEffect, useRef } from "react";
import { Play, Clipboard, CheckCircle, AlertCircle, Cpu, Zap, RefreshCw, FileText, ShieldCheck, ReceiptText, User, ChevronDown, ChevronUp, AlertTriangle } from "lucide-react";

interface Claim {
  claim_id: string;
  policy_number: string;
  claimant_id: string;
  date_of_loss: string;
  claimed_amount: number;
  status: string;
}

interface AgentNodeState {
  id: string;
  label: string;
  status: "idle" | "running" | "success" | "failed" | "halted";
  message: string;
}

interface ClaimDetails {
  claim?: Record<string, string | null>;
  clinical?: Record<string, string | null>;
  bills?: Record<string, string | null>[];
  policy?: Record<string, string | null>;
  policy_members?: Record<string, string | null>[];
  gold_decision?: any;
  documents?: {
    discharge_summary_available: boolean;
    discharge_summary_text?: string | null;
    hospital_bill_available: boolean;
  };
  failure_reason?: {
    status: string;
    error_detail: string;
    cross_validation_status?: string;
    member_validation_status?: string;
    completeness_score?: number;
    missing_fields?: string[];
  } | null;
}


export default function Simulator() {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [loadingQueue, setLoadingQueue] = useState(true);
  const [selectedClaimId, setSelectedClaimId] = useState<string>("");
  const [runMode, setRunMode] = useState<"queue" | "di">("queue");
  const [customClaimId, setCustomClaimId] = useState("");
  const [claimDetails, setClaimDetails] = useState<ClaimDetails | null>(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [detailsExpanded, setDetailsExpanded] = useState(true);
  
  // Running execution states
  const [running, setRunning] = useState(false);
  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const [finalState, setFinalState] = useState<any>(null);
  const [activeStep, setActiveStep] = useState<string>("");
  
  const terminalEndRef = useRef<HTMLDivElement>(null);

  // Nodes for the Flowchart
  const [nodes, setNodes] = useState<AgentNodeState[]>([
    { id: "setup", label: "State Hydration", status: "idle", message: "" },
    { id: "agent1_doc_intelligence", label: "Doc Intelligence (Agent 1)", status: "idle", message: "" },
    { id: "agent2_fraud", label: "Fraud Check (Agent 2)", status: "idle", message: "" },
    { id: "agent3_coverage", label: "Coverage Check (Agent 3)", status: "idle", message: "" },
    { id: "agent4_reserve", label: "Reserve Estimator (Agent 4)", status: "idle", message: "" },
    { id: "adjuster_allocation", label: "Allocation / Routing", status: "idle", message: "" },
    { id: "save", label: "Save Database (Gold)", status: "idle", message: "" },
  ]);

  // Load claims queue
  useEffect(() => {
    fetch("/api/claims")
      .then((res) => {
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        // Guard: ensure data is an array before setting state
        const safeData = Array.isArray(data) ? data : [];
        setClaims(safeData);
        if (safeData.length > 0 && runMode === "queue") {
          setSelectedClaimId(safeData[0].claim_id);
        }
      })
      .catch((err) => console.error("Error loading claims queue:", err))
      .finally(() => setLoadingQueue(false));
  }, [runMode]);

  // Scroll to bottom of terminal
  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [terminalLogs]);

  // Fetch claim details whenever selected claim changes
  const fetchDetails = (id: string) => {
    if (!id) { setClaimDetails(null); return; }
    setLoadingDetails(true);
    fetch(`/api/claims/${id}/details`)
      .then((r) => r.json())
      .then((d) => setClaimDetails(d))
      .catch(() => setClaimDetails(null))
      .finally(() => setLoadingDetails(false));
  };

  useEffect(() => {
    const id = runMode === "queue" ? selectedClaimId : customClaimId;
    fetchDetails(id);
  }, [selectedClaimId, customClaimId, runMode]);

  const updateNode = (id: string, updates: Partial<AgentNodeState>) => {
    setNodes((prev) =>
      prev.map((n) => (n.id === id ? { ...n, ...updates } : n))
    );
  };

  const resetFlow = () => {
    setNodes((prev) => prev.map((n) => ({ ...n, status: "idle", message: "" })));
    setTerminalLogs([]);
    setFinalState(null);
    setActiveStep("");
  };

  // Run Adjudication Orchestration
  const handleAdjudicate = async () => {
    if (running) return;
    resetFlow();
    setRunning(true);

    const log = (msg: string) => {
      setTerminalLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
    };

    const targetClaimId = runMode === "queue" ? selectedClaimId : customClaimId;
    if (!targetClaimId) {
      log("✗ Error: No claim ID specified.");
      setRunning(false);
      return;
    }

    log(`Initializing agent orchestration pipeline for claim ${targetClaimId}...`);

    // Run real-time Event Stream from FastAPI Backend
    const eventSource = new EventSource(`/api/adjudicate/stream/${targetClaimId}`);

    eventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        const { agent, status, message, data, state } = payload;

        if (status === "RUNNING") {
          setActiveStep(agent);
          updateNode(agent, { status: "running", message });
          log(`⚡ Active Agent: [${agent.toUpperCase()}] -> ${message}`);
        } else if (status === "SUCCESS") {
          updateNode(agent, { status: "success", message });
          log(`✓ Agent Completed: [${agent.toUpperCase()}]`);

          // Unpack step payloads for display
          if (agent === "setup" && state) {
            setFinalState((prev: any) => ({ ...prev, setup: state }));
          } else if (data) {
            setFinalState((prev: any) => ({ ...prev, [agent]: data }));
          }
        } else if (status === "FAILED") {
          updateNode(agent, { status: "failed", message });
          log(`✗ ERROR: [${agent.toUpperCase()}] failed: ${message}`);
          eventSource.close();
          setRunning(false);
        } else if (status === "HALTED") {
          // Validation halt handling
          updateNode("agent1_doc_intelligence", { status: "halted", message });
          log(`⚠ PIPELINE HALTED: ${message}`);
          eventSource.close();
          setRunning(false);
        }
      } catch (err) {
        log(`✗ Failed to parse event metadata: ${err}`);
      }
    };
    eventSource.onerror = (err) => {
      console.error("SSE Connection Error", err);
      log(`✗ SSE connection disconnected (Run finalized or server cold start).`);
      eventSource.close();
      setRunning(false);
      // Reload claim details to show gold decision results
      const id = runMode === "queue" ? selectedClaimId : customClaimId;
      setTimeout(() => fetchDetails(id), 1500);
    };
  };

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Configuration Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 glass p-6 rounded-2xl border border-slate-800 shadow-lg">
        {/* Toggle & Dropdown Options */}
        <div className="space-y-4 w-full md:w-auto">
          <div className="flex items-center gap-4">
            <span className="text-sm font-semibold text-slate-400">Run Mode:</span>
            <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800">
              <button
                onClick={() => setRunMode("queue")}
                disabled={running}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold uppercase transition-all ${
                  runMode === "queue" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white"
                }`}
              >
                Catalog Queue
              </button>
              <button
                onClick={() => setRunMode("di")}
                disabled={running}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold uppercase transition-all ${
                  runMode === "di" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white"
                }`}
              >
                DI from DB
              </button>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center gap-4">
            <span className="text-sm font-semibold text-slate-400">Select Claim:</span>
            {runMode === "queue" ? (
              <select
                value={selectedClaimId}
                onChange={(e) => setSelectedClaimId(e.target.value)}
                disabled={running || loadingQueue}
                className="bg-slate-900 border border-slate-855 rounded-xl px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500 w-full sm:w-80"
              >
                {loadingQueue ? (
                  <option>Loading claims queue...</option>
                ) : claims.length === 0 ? (
                  <option>No claims in silver_claims</option>
                ) : (
                  claims.map((claim) => (
                    <option key={claim.claim_id} value={claim.claim_id}>
                      {claim.claim_id} - Amount: ${claim.claimed_amount.toLocaleString()} ({claim.status})
                    </option>
                  ))
                )}
              </select>
            ) : (
              <input
                type="text"
                placeholder="Enter Unique Claim ID (e.g. CLM-58392)..."
                value={customClaimId}
                onChange={(e) => {
                  setCustomClaimId(e.target.value);
                  setSelectedClaimId(e.target.value);
                }}
                disabled={running}
                className="bg-slate-900 border border-slate-855 rounded-xl px-3.5 py-2 text-sm text-white focus:outline-none focus:border-indigo-500 w-full sm:w-80 font-mono font-bold placeholder-slate-600"
              />
            )}
          </div>
        </div>

        {/* Trigger Button */}
        <button
          onClick={handleAdjudicate}
          disabled={
            running || 
            (runMode === "queue" && (!selectedClaimId || claims.length === 0)) || 
            (runMode === "di" && !customClaimId.trim())
          }
          className={`w-full md:w-auto px-6 py-4 rounded-xl font-bold flex items-center justify-center gap-2 shadow-lg transition-all active:scale-[0.98] ${
            running
              ? "bg-slate-800 text-slate-400 cursor-not-allowed border border-slate-700"
              : "bg-indigo-600 hover:bg-indigo-500 text-white hover:shadow-indigo-600/20"
          }`}
        >
          {running ? (
            <>
              <RefreshCw className="animate-spin text-indigo-400" size={20} />
              <span>Orchestrating agents...</span>
            </>
          ) : (
            <>
              <Play fill="white" size={18} />
              <span>Run Agent Adjudication</span>
            </>
          )}
        </button>
      </div>

      {/* Claim Details Panel */}
      {(selectedClaimId || customClaimId) && (
        <div className="glass rounded-2xl border border-slate-800 shadow-xl overflow-hidden">
          <button
            onClick={() => setDetailsExpanded((v) => !v)}
            className="w-full flex items-center justify-between p-5 bg-slate-900/40 hover:bg-slate-800/40 transition-colors"
          >
            <span className="text-sm font-bold text-white flex items-center gap-2">
              <FileText size={16} className="text-indigo-400" />
              Claim Intelligence Brief — <span className="font-mono text-indigo-400">{runMode === "queue" ? selectedClaimId : customClaimId}</span>
            </span>
            {detailsExpanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
          </button>

          {detailsExpanded && (
            <div className="p-6">
              {loadingDetails ? (
                <div className="flex items-center gap-3 text-slate-400 text-sm py-4">
                  <RefreshCw size={16} className="animate-spin text-indigo-400" />
                  Loading claim data from Unity Catalog...
                </div>
              ) : !claimDetails ? (
                <p className="text-slate-500 text-sm">No details available.</p>
              ) : (<ClaimBrief details={claimDetails} />)}
            </div>
          )}
        </div>
      )}

      {/* Interactive Flowchart Visualizer */}
      <div className="glass p-8 rounded-2xl border border-slate-800 shadow-xl overflow-hidden">
        <h3 className="text-lg font-bold text-white mb-6 flex items-center gap-2">
          <Cpu className="text-indigo-400" size={20} />
          LangGraph Multi-Agent Flow Trace
        </h3>

        {/* SVG Flowchart Graph */}
        <div className="w-full overflow-x-auto">
          <div className="min-w-[1000px] h-48 relative flex items-center justify-between px-6">
            {/* SVG Connecting Paths */}
            <svg className="absolute inset-0 w-full h-full -z-10 pointer-events-none" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <linearGradient id="grad-active" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#6366F1" />
                  <stop offset="100%" stopColor="#38BDF8" />
                </linearGradient>
                <linearGradient id="grad-idle" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0%" stopColor="#334155" />
                  <stop offset="100%" stopColor="#334155" />
                </linearGradient>
              </defs>
              {/* Draw connected lines */}
              {nodes.slice(0, -1).map((node, index) => {
                const nextNode = nodes[index + 1];
                const segmentActive = node.status === "success" && nextNode.status !== "idle";
                const isHalted = node.status === "halted";

                return (
                  <path
                    key={index}
                    d={`M ${80 + index * 145} 96 L ${225 + index * 145} 96`}
                    stroke={isHalted ? "#EF4444" : segmentActive ? "url(#grad-active)" : "#334155"}
                    strokeWidth={segmentActive ? 4 : 2}
                    strokeDasharray={node.status === "running" ? "6 6" : "none"}
                    className={node.status === "running" ? "animate-pulse-slow" : ""}
                    style={{ transition: "stroke 0.5s ease" }}
                  />
                );
              })}
            </svg>

            {/* Render Nodes */}
            {nodes.map((node, index) => {
              const isActive = activeStep === node.id;
              const isSuccess = node.status === "success";
              const isHalted = node.status === "halted" || node.status === "failed";

              let glowClass = "border-slate-800 bg-slate-900 text-slate-500";
              if (isActive) glowClass = "border-indigo-500 bg-indigo-950/20 text-indigo-400 ring-2 ring-indigo-500/20 animate-pulse";
              if (isSuccess) glowClass = "border-emerald-500 bg-emerald-950/10 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.3)]";
              if (isHalted) glowClass = "border-red-500 bg-red-950/10 text-red-400 shadow-[0_0_15px_rgba(239,68,68,0.3)]";

              return (
                <div
                  key={node.id}
                  className={`w-32 flex flex-col items-center text-center p-3 rounded-2xl border transition-all duration-500 ${glowClass}`}
                >
                  <div className="w-8 h-8 rounded-full flex items-center justify-center bg-slate-950 mb-2 border border-inherit">
                    {isSuccess ? (
                      <CheckCircle size={16} className="text-emerald-400" />
                    ) : isHalted ? (
                      <AlertCircle size={16} className="text-red-400" />
                    ) : (
                      <span className="text-xs font-semibold">{index + 1}</span>
                    )}
                  </div>
                  <span className="text-[11px] font-bold text-white block truncate w-full">{node.label}</span>
                  <span className="text-[9px] text-slate-400 block mt-0.5 max-h-8 overflow-hidden truncate">
                    {node.status === "idle" ? "Waiting..." : node.status === "running" ? "Running" : "Done"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Terminal Logs & Output Panels */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Terminal Logs Console */}
        <div className="lg:col-span-2 glass rounded-2xl border border-slate-800 overflow-hidden shadow-xl flex flex-col h-96">
          <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-950">
            <span className="text-xs font-semibold text-slate-400 flex items-center gap-2">
              <Zap size={14} className="text-indigo-400" />
              Agent Reasoner Console Logs
            </span>
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-ping" />
          </div>
          <div className="flex-1 p-6 font-mono text-xs text-indigo-300 overflow-y-auto space-y-2 bg-slate-950">
            {terminalLogs.length === 0 ? (
              <span className="text-slate-600 italic">// Waiting for adjudication run command...</span>
            ) : (
              terminalLogs.map((log, index) => (
                <div key={index} className="leading-relaxed">
                  {log}
                </div>
              ))
            )}
            <div ref={terminalEndRef} />
          </div>
        </div>

        {/* Live Hydrated Metrics Output Panel */}
        <div className="glass p-6 rounded-2xl border border-slate-800 shadow-xl flex flex-col space-y-4">
          <h3 className="text-base font-bold text-white flex items-center gap-2">
            <Clipboard size={18} className="text-indigo-400" />
            Extracted Step Payloads
          </h3>

          <div className="flex-1 overflow-y-auto space-y-4 max-h-[300px] pr-1">
            {/* Step 1 Payload */}
            {finalState?.agent1_doc_intelligence && (
              <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800 space-y-2 animate-fade-in">
                <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest">
                  Agent 1: Document Intelligence
                </div>
                <div className="text-xs space-y-1">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Diagnosis Code:</span>
                    <span className="text-white font-mono">{finalState.agent1_doc_intelligence.diagnosis_icd}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Completeness:</span>
                    <span className="text-emerald-400 font-semibold">{finalState.agent1_doc_intelligence.completeness_score * 100}%</span>
                  </div>
                </div>
              </div>
            )}

            {/* Step 2 Payload */}
            {finalState?.agent2_fraud && (
              <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800 space-y-2 animate-fade-in">
                <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest">
                  Agent 2: Fraud Scoring Check
                </div>
                <div className="text-xs space-y-1">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Fraud Score Risk:</span>
                    <span className={`font-semibold ${finalState.agent2_fraud.fraud_score > 0.6 ? 'text-red-400' : 'text-emerald-400'}`}>
                      {Math.round(finalState.agent2_fraud.fraud_score * 100)}%
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Flags Raised:</span>
                    <span className="text-slate-200">
                      {finalState.agent2_fraud.risk_flags?.join(", ") || "None"}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Step 3 & 4 Allocation */}
            {finalState?.adjuster_allocation && (
              <div className="bg-slate-900/60 p-4 rounded-xl border border-slate-800 space-y-2 animate-fade-in">
                <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest">
                  Final Adjuster Route
                </div>
                <div className="text-xs space-y-1 flex items-center justify-between">
                  <span className="text-slate-400">Escalation Mode:</span>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    finalState.adjuster_allocation.adjuster_allocation === 'HUMAN_REVIEW'
                      ? 'bg-amber-500/10 text-amber-400'
                      : 'bg-emerald-500/10 text-emerald-400'
                  }`}>
                    {finalState.adjuster_allocation.adjuster_allocation}
                  </span>
                </div>
              </div>
            )}

            {!finalState && (
              <div className="text-center py-10 text-slate-600 text-xs italic">
                Payload data will be rendered as agents complete execution.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// ClaimBrief — inline claim context panel shown before/after adjudication
// ---------------------------------------------------------------------------
function KV({ label, value, highlight }: { label: string; value: string | null | undefined; highlight?: string }) {
  const colorClass = highlight === "money" ? "text-amber-400 font-bold"
    : highlight === "icd" ? "text-sky-400 font-bold"
    : highlight === "fraud" ? "text-red-400 font-bold"
    : highlight === "ok" ? "text-emerald-400 font-bold"
    : highlight === "tier" ? "text-indigo-400 font-bold"
    : "text-slate-200";
  return (
    <div className="flex justify-between gap-2 py-0.5 border-b border-slate-800/40 last:border-0">
      <span className="text-slate-500 capitalize shrink-0 text-[11px]">{label.replace(/_/g, " ")}</span>
      <span className={`font-mono text-right truncate max-w-[160px] text-[11px] ${colorClass}`} title={value ?? ""}>{value ?? "—"}</span>
    </div>
  );
}

function ClaimBrief({ details }: { details: ClaimDetails }) {
  const gd = details.gold_decision;
  const fr = details.failure_reason;

  return (
    <div className="space-y-5">
      {/* Row 1: Claim Submission | Policy | Members & Bills */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* Claim Submission + Clinical */}
        <div className="space-y-2">
          <h4 className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest flex items-center gap-1.5">
            <ReceiptText size={12} /> Claim Submission
          </h4>
          <div className="bg-slate-950/60 rounded-xl border border-slate-800 p-4 space-y-0.5">
            {details.claim && Object.entries(details.claim)
              .filter(([k]) => !["claim_form_metadata", "ingested_at"].includes(k))
              .map(([k, v]) => (
                <KV key={k} label={k} value={k === "claimed_amount" && v ? `₹${Number(v).toLocaleString()}` : v}
                  highlight={k === "claimed_amount" ? "money" : k === "is_fraud" ? (v === "1" ? "fraud" : "ok") : undefined} />
              ))}
            {details.clinical && (
              <>
                <div className="pt-2 pb-1 text-[10px] font-bold text-slate-500 uppercase tracking-wider">Clinical Record</div>
                {Object.entries(details.clinical)
                  .filter(([k]) => !["ingested_at", "record_seq"].includes(k))
                  .map(([k, v]) => (
                    <KV key={k} label={k} value={v} highlight={k === "diagnosis_icd" ? "icd" : undefined} />
                  ))}
              </>
            )}
          </div>
        </div>

        {/* Policy */}
        <div className="space-y-2">
          <h4 className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest flex items-center gap-1.5">
            <ShieldCheck size={12} /> Policy & Coverage
          </h4>
          <div className="bg-slate-950/60 rounded-xl border border-slate-800 p-4 space-y-0.5">
            {details.policy
              ? Object.entries(details.policy).map(([k, v]) => (
                  <KV key={k} label={k}
                    value={(k === "total_sum_insured" || k === "premium_paid") && v ? `₹${Number(v).toLocaleString()}` : v}
                    highlight={k === "total_sum_insured" || k === "premium_paid" ? "money"
                      : k === "status" ? (v === "ACTIVE" ? "ok" : "fraud")
                      : k === "plan_tier" ? "tier" : undefined} />
                ))
              : <p className="text-slate-500 italic text-xs">Policy not found</p>}
          </div>
        </div>

        {/* Members + Bills */}
        <div className="space-y-2">
          <h4 className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest flex items-center gap-1.5">
            <User size={12} /> Members & Bill Lines
          </h4>
          <div className="bg-slate-950/60 rounded-xl border border-slate-800 p-4 space-y-2 text-xs">
            {details.policy_members?.map((m, i) => (
              <div key={i} className="bg-slate-900/60 rounded-lg p-2.5 border border-slate-800/60">
                <div className="flex justify-between items-center">
                  <span className="font-semibold text-white text-[11px]">{m.member_name ?? m.member_id}</span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 font-bold">{m.relationship_to_primary}</span>
                </div>
                <div className="text-slate-500 text-[10px] mt-0.5">{m.coverage_start_date} → {m.coverage_end_date}</div>
              </div>
            ))}
            {details.bills && details.bills.length > 0 && (
              <>
                <div className="pt-1 text-[10px] font-bold text-slate-500 uppercase tracking-wider border-t border-slate-800">
                  Bill Lines ({details.bills.length})
                </div>
                <div className="space-y-1 max-h-36 overflow-y-auto pr-1">
                  {details.bills.map((b, i) => (
                    <div key={i} className="flex justify-between text-[11px] bg-slate-950/40 rounded p-1.5">
                      <span className="text-slate-400 truncate max-w-[130px]">{b.normalized_expense_type ?? b.raw_expense_label ?? "—"}</span>
                      <span className="text-amber-400 font-mono font-bold shrink-0">₹{Number(b.amount ?? 0).toLocaleString()}</span>
                    </div>
                  ))}
                </div>
                <div className="flex justify-between font-bold text-xs pt-1.5 border-t border-slate-800">
                  <span className="text-slate-400">Total Billed</span>
                  <span className="text-amber-400 font-mono">
                    ₹{details.bills.reduce((s, b) => s + Number(b.amount ?? 0), 0).toLocaleString()}
                  </span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Row 2: Discharge Summary | AI Decision */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

        {/* Discharge Summary */}
        <div className="space-y-2">
          <h4 className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest flex items-center gap-2">
            <FileText size={12} /> Discharge Summary
            <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${details.documents?.discharge_summary_available ? "bg-emerald-500/10 text-emerald-400" : "bg-amber-500/10 text-amber-400"}`}>
              {details.documents?.discharge_summary_available ? "FOUND" : "NOT IN VOLUME"}
            </span>
          </h4>
          <div className="bg-slate-950/60 rounded-xl border border-slate-800 overflow-hidden">
            {details.documents?.discharge_summary_text ? (
              <pre className="text-[11px] text-slate-300 leading-relaxed p-4 max-h-80 overflow-y-auto whitespace-pre-wrap font-mono">
                {details.documents.discharge_summary_text}
              </pre>
            ) : (
              <div className="p-4 text-slate-500 text-xs italic flex items-start gap-2">
                <AlertCircle size={13} className="text-amber-400 shrink-0 mt-0.5" />
                <span>
                  Discharge summary not found in deployed bundle. Upload to{" "}
                  <code className="text-amber-400">/Volumes/health_claims_dev/claims/raw_documents/discharge-summaries/</code>{" "}
                  to enable Agent 1 document extraction.
                </span>
              </div>
            )}
          </div>
        </div>

        {/* AI Decision Results */}
        <div className="space-y-2">
          <h4 className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest flex items-center gap-1.5">
            <AlertTriangle size={12} /> AI Decision Results
          </h4>
          <div className="bg-slate-950/60 rounded-xl border border-slate-800 p-4 space-y-3 text-xs">
            {gd ? (
              <>
                {/* Status banner */}
                <div className={`rounded-lg p-3 border ${gd.pipeline_status === "COMPLETED" ? "bg-emerald-950/20 border-emerald-500/20" : "bg-red-950/20 border-red-500/20"}`}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-bold text-white text-xs">Pipeline Status</span>
                    <span className={`text-[11px] font-bold ${gd.pipeline_status === "COMPLETED" ? "text-emerald-400" : "text-red-400"}`}>{gd.pipeline_status}</span>
                  </div>
                  {gd.adjuster_allocation && (
                    <div className="flex justify-between text-[11px]">
                      <span className="text-slate-400">Routed To</span>
                      <span className="text-indigo-400 font-bold">{gd.adjuster_allocation}</span>
                    </div>
                  )}
                  {gd.routing_reason && <div className="text-slate-500 text-[10px] mt-1 italic">{gd.routing_reason}</div>}
                </div>

                {/* Agent result cards */}
                <div className="grid grid-cols-2 gap-2">
                  {gd.fraud && (
                    <div className="bg-slate-900/60 rounded-lg p-3 border border-slate-800 space-y-1">
                      <div className="text-[10px] font-bold text-slate-500 uppercase">Fraud Score</div>
                      <div className={`text-xl font-bold font-mono ${gd.fraud.fraud_score > 0.6 ? "text-red-400" : gd.fraud.fraud_score > 0.3 ? "text-amber-400" : "text-emerald-400"}`}>
                        {Math.round((gd.fraud.fraud_score ?? 0) * 100)}%
                      </div>
                      <div className="text-[10px] text-slate-400">{gd.fraud.confidence} risk</div>
                      {gd.fraud.fraud_signals?.length > 0 && (
                        <div className="text-[10px] text-red-400 leading-relaxed">⚠ {gd.fraud.fraud_signals.join(" • ")}</div>
                      )}
                      {gd.fraud.reasoning && (
                        <div className="text-[10px] text-slate-500 italic leading-relaxed mt-1 border-t border-slate-800 pt-1">{gd.fraud.reasoning}</div>
                      )}
                    </div>
                  )}
                  {gd.coverage && (
                    <div className="bg-slate-900/60 rounded-lg p-3 border border-slate-800 space-y-1">
                      <div className="text-[10px] font-bold text-slate-500 uppercase">Coverage</div>
                      <div className={`text-sm font-bold ${gd.coverage.coverage_status === "COVERED" ? "text-emerald-400" : gd.coverage.coverage_status === "EXCLUDED" ? "text-red-400" : "text-amber-400"}`}>
                        {gd.coverage.coverage_status}
                      </div>
                      {gd.coverage.coverage_amount_estimate != null && (
                        <div className="text-[11px] text-slate-300 font-mono">Est. ₹{Number(gd.coverage.coverage_amount_estimate).toLocaleString()}</div>
                      )}
                      {gd.coverage.exclusions_triggered?.length > 0 && (
                        <div className="text-[10px] text-red-400">{gd.coverage.exclusions_triggered.join(", ")}</div>
                      )}
                      {gd.coverage.notes && (
                        <div className="text-[10px] text-slate-500 italic leading-relaxed mt-1 border-t border-slate-800 pt-1">{gd.coverage.notes}</div>
                      )}
                    </div>
                  )}
                  {gd.reserve && (
                    <div className="bg-slate-900/60 rounded-lg p-3 border border-slate-800 space-y-1 col-span-2">
                      <div className="text-[10px] font-bold text-slate-500 uppercase">Reserve Estimate</div>
                      <div className="flex items-end gap-3">
                        <span className="text-xl font-bold font-mono text-amber-400">
                          ₹{Number(gd.reserve.initial_reserve_amount ?? 0).toLocaleString()}
                        </span>
                        {gd.reserve.confidence_interval && (
                          <span className="text-[10px] text-slate-400 pb-0.5">
                            P10: ₹{Number(gd.reserve.confidence_interval.P10 ?? 0).toLocaleString()} — P90: ₹{Number(gd.reserve.confidence_interval.P90 ?? 0).toLocaleString()}
                          </span>
                        )}
                      </div>
                      {gd.reserve.reasoning && <div className="text-[10px] text-slate-400 italic leading-relaxed">{gd.reserve.reasoning}</div>}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="text-slate-500 text-xs italic py-6 text-center">
                No AI decision yet — press "Run Agent Adjudication" to process this claim.
              </div>
            )}

            {/* Failure reason */}
            {fr && (
              <div className="bg-red-950/20 border border-red-500/20 rounded-lg p-3 space-y-2">
                <div className="text-[10px] font-bold text-red-400 uppercase tracking-wider flex items-center gap-1">
                  <AlertCircle size={11} /> Why It Failed
                </div>
                <p className="text-red-300 leading-relaxed text-[11px]">{fr.error_detail}</p>
                {fr.missing_fields && fr.missing_fields.length > 0 && (
                  <div className="text-[10px] text-slate-400">
                    Missing fields: <span className="text-amber-400">{fr.missing_fields.join(", ")}</span>
                  </div>
                )}
                {fr.completeness_score != null && (
                  <div className="text-[10px] text-slate-400">
                    Completeness: <span className="text-red-400 font-bold">{Math.round((fr.completeness_score ?? 0) * 100)}%</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
