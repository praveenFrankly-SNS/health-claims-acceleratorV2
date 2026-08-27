import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  ShieldAlert,
  FileText,
  Building2,
  User,
  Stethoscope,
  IndianRupee,
  CheckCircle2,
  AlertTriangle,
  FileCheck,
  Send,
  History,
  Scale,
  RefreshCw,
} from "lucide-react";
import { fetchClaimDetails, submitHumanDecision } from "../services/apiService";
import type { AssignedRole } from "../types/claims";

interface ClaimWorkbenchProps {
  currentRole?: AssignedRole;
}

export default function ClaimWorkbench({ currentRole }: ClaimWorkbenchProps) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [activeTab, setActiveTab] = useState<"summary" | "assessment" | "documents" | "policy" | "timeline">("assessment");
  const [claimDetails, setClaimDetails] = useState<any>(null);

  // Adjudication State
  const [selectedAction, setSelectedAction] = useState<"APPROVE" | "APPROVE_CONDITIONAL" | "INFO_REQUESTED" | "INVESTIGATE" | "REJECT">("INVESTIGATE");
  const [remarks, setRemarks] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [decisionSubmitted, setDecisionSubmitted] = useState(false);

  const loadData = async () => {
    if (!id) return;
    try {
      const details = await fetchClaimDetails(id);
      setClaimDetails(details);
    } catch (err) {
      console.error("Error loading claim details:", err);
    }
  };

  useEffect(() => {
    loadData();
  }, [id]);

  const handleDecisionSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id) return;
    setSubmitting(true);
    try {
      const ok = await submitHumanDecision(id, selectedAction, remarks || `Adjudicated by ${currentRole || "Claims Specialist"}`);
      if (ok) {
        setDecisionSubmitted(true);
        setTimeout(() => loadData(), 1000);
      }
    } catch (err) {
      console.error("Failed to submit decision:", err);
    } finally {
      setSubmitting(false);
    }
  };

  const rawClaim = claimDetails?.claim || {};
  const rawClinical = claimDetails?.clinical || {};
  const rawGold = claimDetails?.gold_decision || {};

  const claimedAmt = parseInt(rawClaim.claimed_amount || "0", 10) || 380000;
  const fraudScore = rawGold.fraud?.fraud_score ? Math.round(rawGold.fraud.fraud_score * 100) : 92;
  const riskLevel = fraudScore > 75 ? "HIGH" : fraudScore > 40 ? "MEDIUM" : "LOW";

  return (
    <div className="space-y-6">
      {/* Navigation Top Bar */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-2 text-xs font-bold text-slate-600 hover:text-slate-900 transition-colors"
        >
          <ArrowLeft size={16} /> Back to Claims List
        </button>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 font-medium">Assigned View:</span>
          <span className="px-3 py-1 rounded-full text-xs font-bold bg-slate-900 text-white shadow-sm">
            {currentRole || "Claims Specialist"}
          </span>
        </div>
      </div>

      {/* Claim Banner Header */}
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-100 pb-4">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-black text-slate-900 font-mono">{id}</h1>

            <span className="px-3 py-1 rounded-full text-xs font-extrabold bg-slate-900 text-white border border-slate-900">
              {riskLevel} RISK ({fraudScore}%)
            </span>

            <span className="px-3 py-1 rounded-full text-xs font-bold bg-slate-100 text-slate-800 border border-slate-300">
              {decisionSubmitted ? "ADJUDICATED" : "NEEDS REVIEW"}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500 font-medium">Claim Type:</span>
            <span className="px-2.5 py-1 rounded-lg text-xs font-bold bg-slate-100 text-slate-800 border border-slate-200">
              {rawClaim.claim_form_metadata ? "CASHLESS" : "REIMBURSEMENT"}
            </span>
          </div>
        </div>

        {/* Consolidated Metadata Strip */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-xs">
          <div className="space-y-1">
            <span className="text-slate-500 font-medium flex items-center gap-1.5">
              <User size={14} className="text-slate-700" /> Patient
            </span>
            <p className="font-bold text-slate-900">Rajesh Kumar (45M)</p>
            <p className="text-[10px] text-slate-500">ID: {rawClaim.claimant_id || "PAT-88392"}</p>
          </div>

          <div className="space-y-1">
            <span className="text-slate-500 font-medium flex items-center gap-1.5">
              <FileText size={14} className="text-slate-700" /> Policy
            </span>
            <p className="font-bold text-slate-900">{rawClaim.policy_number || "POL-778899"}</p>
            <p className="text-[10px] text-slate-700 font-bold">Active • Silver Plan</p>
          </div>

          <div className="space-y-1">
            <span className="text-slate-500 font-medium flex items-center gap-1.5">
              <Building2 size={14} className="text-slate-700" /> Hospital
            </span>
            <p className="font-bold text-slate-900">{rawClinical.hospital_id || "XYZ Hospital"}</p>
            <p className="text-[10px] text-slate-700 font-bold">Out-of-Network</p>
          </div>

          <div className="space-y-1">
            <span className="text-slate-500 font-medium flex items-center gap-1.5">
              <Stethoscope size={14} className="text-slate-700" /> Treatment
            </span>
            <p className="font-bold text-slate-900">{rawClinical.diagnosis_icd || "Knee Replacement (M17.1)"}</p>
            <p className="text-[10px] text-slate-500">LOS: 4 Days</p>
          </div>

          <div className="space-y-1">
            <span className="text-slate-500 font-medium flex items-center gap-1.5">
              <IndianRupee size={14} className="text-slate-700" /> Requested Amount
            </span>
            <p className="text-base font-black text-slate-900">₹{claimedAmt.toLocaleString("en-IN")}</p>
            <p className="text-[10px] text-slate-500">Date: {rawClaim.date_of_loss || "2026-08-20"}</p>
          </div>
        </div>
      </div>

      {/* Main Grid: Workbench Tabs (Left) + Human Adjudication Panel (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column (2 Cols): Workbench Content Tabs */}
        <div className="lg:col-span-2 space-y-4">
          {/* Tab Headers */}
          <div className="flex items-center gap-2 border-b border-slate-200 pb-2">
            {[
              { id: "assessment", label: "Explainable AI Assessment", icon: ShieldAlert },
              { id: "summary", label: "Claim Summary", icon: FileText },
              { id: "documents", label: "Documents & Evidence", icon: FileCheck },
              { id: "policy", label: "Policy Clauses", icon: Scale },
              { id: "timeline", label: "Timeline", icon: History },
            ].map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.id}
                  onClick={() => setActiveTab(t.id as any)}
                  className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-bold transition-all ${
                    activeTab === t.id
                      ? "bg-slate-900 text-white shadow-sm"
                      : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
                  }`}
                >
                  <Icon size={14} />
                  <span>{t.label}</span>
                </button>
              );
            })}
          </div>

          {/* Tab 1: Explainable AI & System Assessment */}
          {activeTab === "assessment" && (
            <div className="space-y-4">
              {/* Fraud Risk Card */}
              <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ShieldAlert size={18} className="text-slate-800" />
                    <h3 className="text-xs font-extrabold text-slate-900 uppercase tracking-wider">
                      Fraud Risk Assessment — HIGH ({fraudScore}%)
                    </h3>
                  </div>
                  <span className="text-xs font-mono text-slate-700 font-bold">Confidence: 94%</span>
                </div>

                <div className="space-y-2">
                  <p className="text-xs font-bold text-slate-900">Why was this claim flagged?</p>
                  <ul className="space-y-1.5 text-xs text-slate-700 list-disc list-inside">
                    <li className="font-semibold">
                      Similar procedure claimed 5 months ago under member's secondary insurance policy.
                    </li>
                    <li className="font-semibold">
                      Out-of-network provider billing frequency for high-flexion implant is 3.8x above regional benchmark.
                    </li>
                    <li>Claimed implant invoice amount (₹1,45,000) exceeds standard distributor MRP ceiling.</li>
                    <li>Discharge summary timestamp precedes surgical procedure log completion time by 2 hours.</li>
                  </ul>
                </div>
              </div>

              {/* Coverage Eligibility Card */}
              <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-3">
                <h3 className="text-xs font-extrabold text-slate-900 uppercase tracking-wider flex items-center gap-2">
                  <CheckCircle2 size={16} className="text-slate-800" />
                  Coverage & Benefit Determination — ELIGIBLE (PARTIAL)
                </h3>

                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="flex items-center gap-2 text-slate-800 font-medium">
                    <CheckCircle2 size={14} /> <span>Treatment Covered under Policy</span>
                  </div>
                  <div className="flex items-center gap-2 text-slate-800 font-medium">
                    <CheckCircle2 size={14} /> <span>Policy Active & Sum Insured Available</span>
                  </div>
                  <div className="flex items-center gap-2 text-slate-700 font-medium">
                    <AlertTriangle size={14} /> <span>Room Rent Limit Applicable (Cap: ₹5,000/day)</span>
                  </div>
                  <div className="flex items-center gap-2 text-slate-700 font-medium">
                    <AlertTriangle size={14} /> <span>10% Non-Network Facility Co-pay Triggered</span>
                  </div>
                </div>
              </div>

              {/* AI System Recommendation */}
              <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-extrabold text-slate-900 uppercase tracking-wider">
                    AI System Recommendation
                  </span>
                  <span className="text-[10px] font-bold text-slate-700 bg-slate-100 px-2 py-0.5 rounded-full border border-slate-200">
                    Decision Support Only
                  </span>
                </div>
                <p className="text-sm font-black text-slate-900">
                  "Send for Investigation — High Fraud & Tariff Over-invoicing Risk"
                </p>
                <p className="text-xs text-slate-500">
                  Recommendation based on duplicate procedure history, out-of-network provider risk rating, and implant over-invoicing flags.
                </p>
              </div>
            </div>
          )}

          {/* Tab 2: Summary */}
          {activeTab === "summary" && (
            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-4">
              <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">Claim Line Itemization</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs text-slate-800">
                  <thead className="bg-slate-50 text-[11px] font-bold text-slate-600 uppercase border-b border-slate-200">
                    <tr>
                      <th className="py-2.5 px-3">Description</th>
                      <th className="py-2.5 px-3">Category</th>
                      <th className="py-2.5 px-3 text-right">Claimed (₹)</th>
                      <th className="py-2.5 px-3 text-right">Benchmark (₹)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    <tr>
                      <td className="py-2.5 px-3 font-semibold">Room Rent (Deluxe - 4 Days)</td>
                      <td className="py-2.5 px-3 text-slate-500">ROOM_RENT</td>
                      <td className="py-2.5 px-3 text-right font-bold text-slate-900">32,000</td>
                      <td className="py-2.5 px-3 text-right text-slate-500">20,000</td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold">Operation Theatre Charges</td>
                      <td className="py-2.5 px-3 text-slate-500">SURGEON_FEE</td>
                      <td className="py-2.5 px-3 text-right font-bold text-slate-900">65,000</td>
                      <td className="py-2.5 px-3 text-right text-slate-500">50,000</td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold">Surgeon & Anesthetist Fee</td>
                      <td className="py-2.5 px-3 text-slate-500">SURGEON_FEE</td>
                      <td className="py-2.5 px-3 text-right font-bold text-slate-900">90,000</td>
                      <td className="py-2.5 px-3 text-right text-slate-500">75,000</td>
                    </tr>
                    <tr>
                      <td className="py-2.5 px-3 font-semibold">High-Flexion Knee Implant Unit</td>
                      <td className="py-2.5 px-3 text-slate-500">IMPLANTS</td>
                      <td className="py-2.5 px-3 text-right font-bold text-slate-900">1,45,000</td>
                      <td className="py-2.5 px-3 text-right text-slate-500">1,05,000</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Tab 3: Documents & Evidence */}
          {activeTab === "documents" && (
            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-4">
              <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">Uploaded Documents</h3>
              <div className="space-y-2">
                {[
                  { name: "INV-2026-9921.pdf", type: "Itemized Hospital Bill", status: "VERIFIED" },
                  { name: "Discharge_RajeshKumar.pdf", type: "Discharge Summary & Surgery Notes", status: "INCONSISTENT" },
                  { name: "PreAuth_CLM10234.pdf", type: "Pre-Auth Form", status: "VERIFIED" },
                ].map((doc) => (
                  <div key={doc.name} className="p-3 rounded-xl bg-slate-50 border border-slate-200 flex items-center justify-between text-xs">
                    <div className="flex items-center gap-3">
                      <FileCheck size={16} className="text-slate-700" />
                      <div>
                        <p className="font-bold text-slate-900">{doc.type}</p>
                        <p className="text-[10px] text-slate-500">{doc.name}</p>
                      </div>
                    </div>
                    <span className={`px-2.5 py-1 rounded text-[10px] font-bold border ${
                      doc.status === "VERIFIED" ? "bg-slate-900 text-white border-slate-900" : "bg-slate-200 text-slate-800 border-slate-300"
                    }`}>
                      {doc.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tab 4: Policy Clauses */}
          {activeTab === "policy" && (
            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-3 text-xs">
              <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">Policy Clause Citations</h3>
              <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
                <p className="font-bold text-slate-900">Section 4.2 — Room Rent Limit</p>
                <p className="text-slate-700">"The policy covers room rent up to 1% of Base Sum Insured per day for Silver Plan tier."</p>
              </div>
              <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
                <p className="font-bold text-slate-900">Section 6.1 — Out-of-Network Facility Deduction</p>
                <p className="text-slate-700">"Claims from non-network facilities are subject to a mandatory 10% co-payment."</p>
              </div>
            </div>
          )}

          {/* Tab 5: Timeline */}
          {activeTab === "timeline" && (
            <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-3">
              <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">Claim Journey Timeline</h3>
              <div className="space-y-3 text-xs border-l-2 border-slate-200 pl-4">
                <div>
                  <p className="font-bold text-slate-900">Claim Submitted</p>
                  <p className="text-[10px] text-slate-500">2026-08-26 09:30 AM • TPA Desk</p>
                </div>
                <div>
                  <p className="font-bold text-slate-900">AI Risk Assessment Flagged (92%)</p>
                  <p className="text-[10px] text-slate-500">2026-08-26 09:35 AM • AI Fraud Engine</p>
                </div>
                <div>
                  <p className="font-bold text-slate-900">Assigned to HITL Review Queue</p>
                  <p className="text-[10px] text-slate-500">2026-08-26 09:36 AM • Orchestrator</p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right Column (1 Col): Human Claims Officer Decision & Financial Impact */}
        <div className="space-y-4">
          <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-4">
            <h2 className="text-xs font-extrabold text-slate-900 uppercase tracking-wider flex items-center gap-2">
              <Scale size={16} className="text-slate-800" />
              Human Officer Decision & Action
            </h2>

            {decisionSubmitted ? (
              <div className="p-4 rounded-xl bg-slate-100 border border-slate-300 text-center space-y-2">
                <CheckCircle2 size={28} className="text-slate-900 mx-auto" />
                <h4 className="text-sm font-bold text-slate-900">Decision Successfully Recorded</h4>
                <p className="text-xs text-slate-600">
                  Decision <strong className="text-slate-900">{selectedAction}</strong> has been logged to the audit repository.
                </p>
              </div>
            ) : (
              <form onSubmit={handleDecisionSubmit} className="space-y-4 text-xs">
                {/* Decision Options */}
                <div className="space-y-2">
                  <label className="font-bold text-slate-800 block">Select Adjudication Action:</label>
                  {[
                    { id: "APPROVE", label: "Approve & Authorize Cashless" },
                    { id: "APPROVE_CONDITIONAL", label: "Approve with Conditions (Cap Applied)" },
                    { id: "INFO_REQUESTED", label: "Request Additional Information" },
                    { id: "INVESTIGATE", label: "Send for SIU / Investigation" },
                    { id: "REJECT", label: "Reject / Repudiate Claim" },
                  ].map((act) => (
                    <label
                      key={act.id}
                      className={`flex items-center gap-2.5 p-2.5 rounded-xl border transition-all cursor-pointer ${
                        selectedAction === act.id
                          ? "bg-slate-900 border-slate-900 text-white font-bold"
                          : "bg-slate-50 border-slate-200 text-slate-800 hover:bg-slate-100"
                      }`}
                    >
                      <input
                        type="radio"
                        name="adjudicationAction"
                        value={act.id}
                        checked={selectedAction === act.id}
                        onChange={() => setSelectedAction(act.id as any)}
                        className="text-slate-900 focus:ring-slate-900"
                      />
                      <span>{act.label}</span>
                    </label>
                  ))}
                </div>

                {/* Remarks Textarea */}
                <div className="space-y-1">
                  <label className="font-bold text-slate-800 block">Officer Remarks & Justification:</label>
                  <textarea
                    rows={3}
                    value={remarks}
                    onChange={(e) => setRemarks(e.target.value)}
                    placeholder="Enter detailed adjudication rationale..."
                    className="w-full p-2.5 rounded-xl bg-slate-50 border border-slate-200 text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:border-slate-400"
                  />
                </div>

                {/* Financial Impact Summary */}
                <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 space-y-1.5">
                  <span className="text-[11px] font-bold text-slate-900 block">Claim Impact Calculation:</span>
                  <div className="flex justify-between text-slate-600">
                    <span>Claimed Amount:</span>
                    <span className="text-slate-900 font-bold">₹{claimedAmt.toLocaleString("en-IN")}</span>
                  </div>
                  <div className="flex justify-between text-slate-600">
                    <span>Room Rent Excess:</span>
                    <span className="text-slate-900 font-bold">-₹12,000</span>
                  </div>
                  <div className="flex justify-between text-slate-600">
                    <span>Facility Co-pay (10%):</span>
                    <span className="text-slate-900 font-bold">-₹36,800</span>
                  </div>
                  <div className="flex justify-between font-bold text-slate-900 pt-1.5 border-t border-slate-200">
                    <span>Net Admissible Amount:</span>
                    <span className="text-slate-900 font-black">₹3,16,200</span>
                  </div>
                </div>

                {/* Submit Action Button */}
                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-extrabold text-xs shadow-md flex items-center justify-center gap-2 transition-all"
                >
                  {submitting ? (
                    <RefreshCw size={14} className="animate-spin text-white" />
                  ) : (
                    <>
                      <Send size={14} /> Submit Adjudication Decision
                    </>
                  )}
                </button>
              </form>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
