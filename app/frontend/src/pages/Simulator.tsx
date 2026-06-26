import { useState, useEffect, useRef } from "react";
import { Play, Clipboard, CheckCircle, AlertCircle, Cpu, Zap, RefreshCw } from "lucide-react";

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


export default function Simulator() {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [loadingQueue, setLoadingQueue] = useState(true);
  const [selectedClaimId, setSelectedClaimId] = useState<string>("");
  const [runMode, setRunMode] = useState<"queue" | "di">("queue");
  const [customClaimId, setCustomClaimId] = useState("");
  
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
      .then((res) => res.json())
      .then((data) => {
        setClaims(data || []);
        if (data && data.length > 0) {
          if (runMode === "queue") {
            setSelectedClaimId(data[0].claim_id);
          }
        }
      })
      .catch((err) => console.error("Error loading claims queue:", err))
      .finally(() => setLoadingQueue(false));
  }, [runMode]);

  // Scroll to bottom of terminal
  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [terminalLogs]);

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
