import React, { useState, useEffect } from "react";
import { createClient } from "@supabase/supabase-js";
import { FileText, Upload, CheckCircle, AlertCircle, RefreshCw } from "lucide-react";

export default function CustomerPortal() {
  const [supabaseConfig, setSupabaseConfig] = useState<{ url: string; key: string } | null>(null);
  const [policyNumber, setPolicyNumber] = useState("POL-001");
  const [claimantId, setClaimantId] = useState("MEM-001");
  const [claimedAmount, setClaimedAmount] = useState("1200");
  const [dateOfLoss, setDateOfLoss] = useState(new Date().toISOString().split("T")[0]);
  const [dischargeFile, setDischargeFile] = useState<File | null>(null);
  const [billFile, setBillFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [progressMsg, setProgressMsg] = useState("");
  const [successClaimId, setSuccessClaimId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [simulated, setSimulated] = useState(false);

  // Fetch Supabase configuration from FastAPI backend
  useEffect(() => {
    fetch("/api/config/supabase")
      .then((res) => res.json())
      .then((data) => {
        if (data.supabase_url && data.supabase_key) {
          setSupabaseConfig({ url: data.supabase_url, key: data.supabase_key });
          setSimulated(false);
        } else {
          setSimulated(true);
        }
      })
      .catch(() => {
        setSimulated(true);
      });
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg(null);
    setSuccessClaimId(null);

    const claimId = `CLM-${Math.floor(10000 + Math.random() * 90000)}`;
    const submissionDate = new Date().toISOString().split("T")[0];

    if (simulated || !supabaseConfig) {
      // Run Simulated Mode (No Supabase keys available)
      setProgressMsg("Uploading proof documents (Simulation)...");
      await new Promise((resolve) => setTimeout(resolve, 1500));
      setProgressMsg("Writing metadata to claim queue (Simulation)...");
      await new Promise((resolve) => setTimeout(resolve, 1000));
      setSuccessClaimId(claimId);
      setLoading(false);
      setProgressMsg("");
      return;
    }

    try {
      const supabase = createClient(supabaseConfig.url, supabaseConfig.key);

      // 1. Upload Discharge Summary if present
      if (dischargeFile) {
        setProgressMsg("Uploading discharge summary to 'claim-discharges' bucket...");
        const cleanName = `${claimId}_discharge_${dischargeFile.name.replace(/[^a-zA-Z0-9.]/g, "_")}`;
        const { error: uploadErr } = await supabase.storage
          .from("claim-discharges")
          .upload(`discharge-summaries/${cleanName}`, dischargeFile, {
            upsert: true,
          });
        if (uploadErr) throw new Error(`Discharge upload failed: ${uploadErr.message}`);
      }

      // 2. Upload Hospital Bill if present
      if (billFile) {
        setProgressMsg("Uploading hospital bill to 'claim-bills' bucket...");
        const cleanName = `${claimId}_bill_${billFile.name.replace(/[^a-zA-Z0-9.]/g, "_")}`;
        const { error: uploadErr } = await supabase.storage
          .from("claim-bills")
          .upload(`hospital-bills/${cleanName}`, billFile, {
            upsert: true,
          });
        if (uploadErr) throw new Error(`Bill upload failed: ${uploadErr.message}`);
      }

      // 3. Write structured claim metadata to claim_submissions table
      setProgressMsg("Filing structured claim records in PostgreSQL...");
      const { error: dbErr } = await supabase.from("claim_submissions").insert({
        claim_id: claimId,
        policy_number: policyNumber,
        claimant_id: claimantId,
        date_of_loss: dateOfLoss,
        claimed_amount: parseInt(claimedAmount) || 0,
        submission_date: submissionDate,
        status: "SUBMITTED",
        is_fraud: 0,
      });

      if (dbErr) throw new Error(`Database insert failed: ${dbErr.message}`);

      // 4. Optionally write a dummy clinical record link
      await supabase.from("clinical_records").insert({
        claim_id: claimId,
        record_seq: 1,
        admission_date: dateOfLoss,
        discharge_date: dateOfLoss,
        hospital_id: "HOSP-001",
        diagnosis_icd: "J12.9",
        attending_physician_registration_number: "PHYS-9999",
      });

      setSuccessClaimId(claimId);
    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.message || "An unexpected error occurred during submission.");
    } finally {
      setLoading(false);
      setProgressMsg("");
    }
  };

  return (
    <div className="max-w-3xl mx-auto py-8 px-4">
      {/* Header */}
      <div className="text-center mb-10">
        <h1 className="text-3xl font-extrabold tracking-tight text-white mb-2">
          Customer Claim Submission Portal
        </h1>
        <p className="text-slate-400">
          File a new health insurance claim and upload supporting medical invoices or discharge certificates.
        </p>
        {simulated && (
          <div className="mt-4 inline-flex items-center gap-2 bg-amber-500/10 border border-amber-500/20 text-amber-300 px-3 py-1 rounded-full text-xs">
            <AlertCircle size={14} />
            <span>Supabase credentials not set. Running in Demo Simulation Mode.</span>
          </div>
        )}
      </div>

      {successClaimId ? (
        <div className="glass p-8 rounded-2xl border border-emerald-500/20 text-center animate-fade-in">
          <div className="w-16 h-16 bg-emerald-500/10 text-emerald-400 rounded-full flex items-center justify-center mx-auto mb-6 border border-emerald-500/20">
            <CheckCircle size={32} />
          </div>
          <h2 className="text-2xl font-bold text-white mb-2">Claim Submitted Successfully!</h2>
          <p className="text-slate-400 mb-6">
            Your claim has been logged in the system and queued for agentic validation.
          </p>
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 max-w-sm mx-auto mb-8">
            <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold mb-1">
              Tracking Claim ID
            </div>
            <div className="text-2xl font-mono text-emerald-400 font-bold">{successClaimId}</div>
          </div>
          <button
            onClick={() => setSuccessClaimId(null)}
            className="px-6 py-2.5 rounded-lg bg-indigo-600 text-white font-medium hover:bg-indigo-500 transition-colors shadow-lg shadow-indigo-600/20"
          >
            File Another Claim
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="glass p-8 rounded-2xl shadow-xl space-y-6">
          {errorMsg && (
            <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-300 flex items-start gap-3">
              <AlertCircle className="shrink-0 mt-0.5" size={18} />
              <div>
                <span className="font-semibold">Submission failed:</span> {errorMsg}
              </div>
            </div>
          )}

          {/* Form Fields Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">
                Policy Number
              </label>
              <select
                value={policyNumber}
                onChange={(e) => setPolicyNumber(e.target.value)}
                className="w-full bg-slate-900/60 border border-slate-700 rounded-xl px-4 py-2.5 text-white focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
              >
                <option value="POL-001">POL-001 (Gold Premium Plan)</option>
                <option value="POL-002">POL-002 (Silver Basic Plan)</option>
                <option value="POL-003">POL-003 (Standard Corporate Plan)</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">
                Claimant Member ID
              </label>
              <select
                value={claimantId}
                onChange={(e) => setClaimantId(e.target.value)}
                className="w-full bg-slate-900/60 border border-slate-700 rounded-xl px-4 py-2.5 text-white focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
              >
                <option value="MEM-001">MEM-001 (Primary Insured)</option>
                <option value="MEM-002">MEM-002 (Dependent Spouse)</option>
                <option value="MEM-003">MEM-003 (Dependent Child)</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">
                Claimed Amount ($ USD)
              </label>
              <input
                type="number"
                required
                value={claimedAmount}
                onChange={(e) => setClaimedAmount(e.target.value)}
                placeholder="Enter amount"
                className="w-full bg-slate-900/60 border border-slate-700 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">
                Date of Loss (Admission Date)
              </label>
              <input
                type="date"
                required
                value={dateOfLoss}
                onChange={(e) => setDateOfLoss(e.target.value)}
                className="w-full bg-slate-900/60 border border-slate-700 rounded-xl px-4 py-2.5 text-white focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
              />
            </div>
          </div>

          <hr className="border-slate-800" />

          {/* File Upload Area */}
          <div className="space-y-6">
            <h3 className="text-base font-semibold text-white">Upload Supporting Proofs</h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Discharge Summary Upload */}
              <div className="space-y-2">
                <label className="block text-sm font-medium text-slate-300">
                  Discharge Summary (PDF or TXT)
                </label>
                <div className="relative border-2 border-dashed border-slate-700 hover:border-indigo-500/50 rounded-xl p-4 transition-colors bg-slate-900/40">
                  <input
                    type="file"
                    accept=".pdf,.txt"
                    onChange={(e) => setDischargeFile(e.target.files?.[0] || null)}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                  />
                  <div className="flex flex-col items-center justify-center text-center py-2">
                    <Upload className="text-slate-500 mb-2" size={24} />
                    <span className="text-sm font-medium text-slate-300">
                      {dischargeFile ? dischargeFile.name : "Choose file or drag here"}
                    </span>
                    <span className="text-xs text-slate-500 mt-1">PDF or TXT up to 5MB</span>
                  </div>
                </div>
              </div>

              {/* Hospital Bills Upload */}
              <div className="space-y-2">
                <label className="block text-sm font-medium text-slate-300">
                  Hospital Bill Invoice (PDF or Image)
                </label>
                <div className="relative border-2 border-dashed border-slate-700 hover:border-indigo-500/50 rounded-xl p-4 transition-colors bg-slate-900/40">
                  <input
                    type="file"
                    accept=".pdf,.jpg,.jpeg,.png"
                    onChange={(e) => setBillFile(e.target.files?.[0] || null)}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                  />
                  <div className="flex flex-col items-center justify-center text-center py-2">
                    <Upload className="text-slate-500 mb-2" size={24} />
                    <span className="text-sm font-medium text-slate-300">
                      {billFile ? billFile.name : "Choose file or drag here"}
                    </span>
                    <span className="text-xs text-slate-500 mt-1">PDF, JPG, PNG up to 5MB</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="pt-4">
            <button
              type="submit"
              disabled={loading}
              className={`w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-white transition-all shadow-lg ${
                loading
                  ? "bg-slate-800 text-slate-400 cursor-not-allowed border border-slate-700"
                  : "bg-indigo-600 hover:bg-indigo-500 hover:shadow-indigo-600/20 active:scale-[0.98]"
              }`}
            >
              {loading ? (
                <>
                  <RefreshCw className="animate-spin text-indigo-400" size={18} />
                  <span>{progressMsg || "Processing submission..."}</span>
                </>
              ) : (
                <>
                  <FileText size={18} />
                  <span>Submit Claim</span>
                </>
              )}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
