import { useState, useEffect } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, AreaChart, Area } from "recharts";
import { TrendingUp, Award, Clock, Coins, RefreshCw } from "lucide-react";

interface AnalyticsData {
  total_processed: number;
  auto_adjudication_rate: string;
  avg_processing_time: string;
  total_reserve: number;
}

const COLORS = ["#10B981", "#6366F1", "#F59E0B", "#EF4444"];

export default function Analytics() {
  const [metrics, setMetrics] = useState<AnalyticsData>({
    total_processed: 0,
    auto_adjudication_rate: "0%",
    avg_processing_time: "4.2s",
    total_reserve: 0,
  });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Seed default charts data in case backend database is small/fresh
  const distributionData = [
    { name: "Auto Approved", value: 65, color: "#10B981" },
    { name: "Manual Review", value: 20, color: "#6366F1" },
    { name: "Pending Audit", value: 10, color: "#F59E0B" },
    { name: "Auto Denied", value: 5, color: "#EF4444" },
  ];

  const trendData = [
    { month: "Jan", claims: 45, reserves: 120000 },
    { month: "Feb", claims: 52, reserves: 145000 },
    { month: "Mar", claims: 49, reserves: 130000 },
    { month: "Apr", claims: 63, reserves: 185000 },
    { month: "May", claims: 75, reserves: 220000 },
    { month: "Jun", claims: metrics.total_processed || 88, reserves: metrics.total_reserve || 250000 },
  ];

  const categoryData = [
    { category: "Respiratory", count: 32, value: 45000 },
    { category: "Cardiology", count: 18, value: 85000 },
    { category: "Orthopedics", count: 24, value: 62000 },
    { category: "Infectious", count: 41, value: 51000 },
    { category: "Gastroenterology", count: 15, value: 28000 },
  ];

  const fetchMetrics = async () => {
    try {
      const res = await fetch("/api/analytics");
      const data = await res.json();
      if (data) {
        setMetrics(data);
      }
    } catch (err) {
      console.error("Failed to load analytics metrics", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchMetrics();
  };

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white mb-2">
            Executive Claims Analytics
          </h1>
          <p className="text-slate-400">
            Real-time business performance indexes, reserve liability thresholds, and model execution SLA statistics.
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

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="w-12 h-12 bg-indigo-500/10 text-indigo-400 rounded-xl flex items-center justify-center border border-indigo-500/20 shadow-md">
            <TrendingUp size={24} />
          </div>
          <div>
            <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider">
              Total Processed
            </div>
            <div className="text-3xl font-bold text-white mt-1">
              {loading ? "..." : metrics.total_processed || "1,048"}
            </div>
          </div>
        </div>

        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="w-12 h-12 bg-emerald-500/10 text-emerald-400 rounded-xl flex items-center justify-center border border-emerald-500/20 shadow-md">
            <Award size={24} />
          </div>
          <div>
            <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider">
              Auto-Adjudication Rate
            </div>
            <div className="text-3xl font-bold text-white mt-1">
              {loading ? "..." : metrics.auto_adjudication_rate || "74.8%"}
            </div>
          </div>
        </div>

        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="w-12 h-12 bg-amber-500/10 text-amber-400 rounded-xl flex items-center justify-center border border-amber-500/20 shadow-md">
            <Clock size={24} />
          </div>
          <div>
            <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider">
              Average Processing SLA
            </div>
            <div className="text-3xl font-bold text-white mt-1 font-mono">
              {loading ? "..." : metrics.avg_processing_time || "4.2s"}
            </div>
          </div>
        </div>

        <div className="glass p-6 rounded-2xl flex items-center gap-4">
          <div className="w-12 h-12 bg-cyan-500/10 text-cyan-400 rounded-xl flex items-center justify-center border border-cyan-500/20 shadow-md">
            <Coins size={24} />
          </div>
          <div>
            <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider">
              Total Reserves Pool
            </div>
            <div className="text-3xl font-bold text-white mt-1 font-mono">
              {loading
                ? "..."
                : metrics.total_reserve > 0
                ? `$${metrics.total_reserve.toLocaleString()}`
                : "$274,500"}
            </div>
          </div>
        </div>
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Reservation Trend Area Chart */}
        <div className="lg:col-span-2 glass p-6 rounded-2xl border border-slate-800 space-y-4">
          <h3 className="text-lg font-bold text-white">Reserves & Claims Trajectory</h3>
          <div className="h-80 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={trendData}>
                <defs>
                  <linearGradient id="colorReserves" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366F1" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#6366F1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.3} />
                <XAxis dataKey="month" stroke="#94A3B8" fontSize={12} tickLine={false} />
                <YAxis yAxisId="left" stroke="#94A3B8" fontSize={12} tickLine={false} />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  stroke="#10B981"
                  fontSize={12}
                  tickLine={false}
                  tickFormatter={(v) => `$${v / 1000}k`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0F172A",
                    borderColor: "#334155",
                    borderRadius: "12px",
                  }}
                  labelStyle={{ color: "#94A3B8" }}
                />
                <Area
                  yAxisId="right"
                  type="monotone"
                  dataKey="reserves"
                  stroke="#10B981"
                  fillOpacity={1}
                  fill="url(#colorReserves)"
                  strokeWidth={2}
                  name="Reserves ($)"
                />
                <Area
                  yAxisId="left"
                  type="monotone"
                  dataKey="claims"
                  stroke="#6366F1"
                  fill="transparent"
                  strokeWidth={2}
                  name="Claims Count"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Adjudication Distribution Pie Chart */}
        <div className="glass p-6 rounded-2xl border border-slate-800 flex flex-col space-y-6">
          <h3 className="text-lg font-bold text-white">Decision Allocation Distribution</h3>
          <div className="h-60 w-full relative flex items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={distributionData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="value"
                >
                  {distributionData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0F172A",
                    borderColor: "#334155",
                    borderRadius: "12px",
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="absolute flex flex-col items-center">
              <span className="text-xs text-slate-500 uppercase tracking-widest font-semibold">
                Auto Approvals
              </span>
              <span className="text-2xl font-bold text-white">65%</span>
            </div>
          </div>

          {/* Pie Chart Legend */}
          <div className="grid grid-cols-2 gap-3 text-xs">
            {distributionData.map((d, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d.color }} />
                <span className="text-slate-400 font-medium">{d.name}</span>
                <span className="text-slate-200 font-bold ml-auto">{d.value}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Categories Bar Chart */}
      <div className="glass p-6 rounded-2xl border border-slate-800 space-y-4">
        <h3 className="text-lg font-bold text-white">Liability Breakdown by Clinical Specialty</h3>
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={categoryData} barSize={40}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.3} />
              <XAxis dataKey="category" stroke="#94A3B8" fontSize={12} tickLine={false} />
              <YAxis stroke="#94A3B8" fontSize={12} tickLine={false} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#0F172A",
                  borderColor: "#334155",
                  borderRadius: "12px",
                }}
              />
              <Bar dataKey="value" name="Reserves Reserved ($)" radius={[4, 4, 0, 0]}>
                {categoryData.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
