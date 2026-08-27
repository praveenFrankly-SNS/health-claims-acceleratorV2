import { BarChart3 } from "lucide-react";

export default function Analytics() {
  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
        <h1 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <BarChart3 size={20} className="text-slate-800" /> Claims Analytics & Operations BI
        </h1>
        <p className="text-xs text-slate-500 mt-1">
          Loss ratio metrics, straight-through processing rates, and SLA velocity analytics.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-2">
          <span className="text-xs font-semibold text-slate-500">Straight-Through Rate</span>
          <p className="text-3xl font-black text-slate-900">74.2%</p>
          <p className="text-[10px] text-slate-500 font-medium">Auto-Adjudicated</p>
        </div>
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-2">
          <span className="text-xs font-semibold text-slate-500">Average Turnaround</span>
          <p className="text-3xl font-black text-slate-900">4.2s</p>
          <p className="text-[10px] text-slate-500 font-medium">Processing Time</p>
        </div>
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-2">
          <span className="text-xs font-semibold text-slate-500">Loss Ratio (YTD)</span>
          <p className="text-3xl font-black text-slate-900">62.8%</p>
          <p className="text-[10px] text-slate-500 font-medium">Target: &lt; 65%</p>
        </div>
        <div className="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm space-y-2">
          <span className="text-xs font-semibold text-slate-500">HITL Agreement Rate</span>
          <p className="text-3xl font-black text-slate-900">96.5%</p>
          <p className="text-[10px] text-slate-500 font-medium">Human Alignment</p>
        </div>
      </div>
    </div>
  );
}
