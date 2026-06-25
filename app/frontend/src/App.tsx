import { Routes, Route, Link, useLocation } from "react-router-dom";
import Simulator from "./pages/Simulator";
import ReviewQueue from "./pages/ReviewQueue";
import GoldExplorer from "./pages/GoldExplorer";
import Analytics from "./pages/Analytics";
import { Cpu, ShieldAlert, Database, BarChart3, Activity } from "lucide-react";

export default function App() {
  const location = useLocation();

  // Highlight navigation tab based on active route
  const isActive = (path: string) => {
    return location.pathname === path
      ? "bg-indigo-600/10 text-indigo-400 border-indigo-500/50"
      : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/40";
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top Branding Navigation Bar */}
      <header className="glass border-b border-slate-800 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Logo */}
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-sky-400 flex items-center justify-center text-white shadow-md shadow-indigo-600/20">
                <Cpu size={18} className="animate-pulse" />
              </div>
              <div>
                <span className="font-extrabold text-sm tracking-wide text-white block">
                  HEALTH CLAIMS
                </span>
                <span className="text-[10px] font-bold text-sky-400 block tracking-widest uppercase -mt-0.5">
                  Agentic Accelerator v2
                </span>
              </div>
            </div>

            {/* Navigation Links */}
            <nav className="hidden md:flex items-center gap-1.5">
              <Link
                to="/"
                className={`px-3 py-2 rounded-xl text-xs font-semibold tracking-wider uppercase border transition-all ${isActive(
                  "/"
                )}`}
              >
                <span className="flex items-center gap-1.5">
                  <Activity size={14} />
                  Live Simulator
                </span>
              </Link>
              <Link
                to="/review"
                className={`px-3 py-2 rounded-xl text-xs font-semibold tracking-wider uppercase border transition-all ${isActive(
                  "/review"
                )}`}
              >
                <span className="flex items-center gap-1.5">
                  <ShieldAlert size={14} />
                  Review Queue
                </span>
              </Link>
              <Link
                to="/explorer"
                className={`px-3 py-2 rounded-xl text-xs font-semibold tracking-wider uppercase border transition-all ${isActive(
                  "/explorer"
                )}`}
              >
                <span className="flex items-center gap-1.5">
                  <Database size={14} />
                  Gold Explorer
                </span>
              </Link>
              <Link
                to="/analytics"
                className={`px-3 py-2 rounded-xl text-xs font-semibold tracking-wider uppercase border transition-all ${isActive(
                  "/analytics"
                )}`}
              >
                <span className="flex items-center gap-1.5">
                  <BarChart3 size={14} />
                  Analytics
                </span>
              </Link>
            </nav>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-grow max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Routes>
          <Route path="/" element={<Simulator />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/explorer" element={<GoldExplorer />} />
          <Route path="/analytics" element={<Analytics />} />
        </Routes>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800 py-6 text-center text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4">
          © {new Date().getFullYear()} Health Claims Agentic Accelerator • Powered by Databricks, LangGraph & Delta Lake.
        </div>
      </footer>
    </div>
  );
}
