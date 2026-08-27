import { Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  FileText,
  Clock,
  ShieldAlert,
  Building2,
  BarChart3,
  History,
  Activity,
} from "lucide-react";

export default function Sidebar() {
  const location = useLocation();

  const navItems = [
    { path: "/", label: "Dashboard", icon: LayoutDashboard },
    { path: "/claims", label: "Claims", icon: FileText },
    { path: "/review-queue", label: "Review Queue", icon: Clock, badge: "14" },
    { path: "/fraud-risk", label: "Fraud & Risk", icon: ShieldAlert, badge: "3" },
    { path: "/providers", label: "Providers", icon: Building2 },
    { path: "/analytics", label: "Analytics", icon: BarChart3 },
    { path: "/audit", label: "Audit Trail", icon: History },
  ];

  const isActive = (path: string) => {
    if (path === "/") {
      return location.pathname === "/";
    }
    return location.pathname.startsWith(path);
  };

  return (
    <aside className="w-64 border-r border-slate-200 flex flex-col justify-between h-screen sticky top-0 shrink-0 z-40 bg-white">
      <div>
        {/* Logo & Header */}
        <div className="h-16 px-5 border-b border-slate-200 flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-slate-900 flex items-center justify-center text-white shadow-sm">
            <Activity size={20} className="stroke-[2.5]" />
          </div>
          <div>
            <h1 className="font-extrabold text-sm tracking-wide text-slate-900 leading-tight">
              HEALTH CLAIMS
            </h1>
            <p className="text-[10px] font-bold text-slate-500 tracking-wider uppercase">
              Command Center
            </p>
          </div>
        </div>

        {/* Navigation Items */}
        <nav className="p-3 space-y-1 mt-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.path);
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
                  active
                    ? "bg-slate-900 text-white shadow-sm font-bold"
                    : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon
                    size={18}
                    className={active ? "text-white" : "text-slate-500"}
                  />
                  <span>{item.label}</span>
                </div>
                {item.badge && (
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                      active
                        ? "bg-slate-800 text-white"
                        : "bg-slate-200 text-slate-700"
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Footer Profile Snippet */}
      <div className="p-4 border-t border-slate-200">
        <div className="p-2.5 rounded-xl bg-slate-50 flex items-center justify-between border border-slate-200">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-slate-900 text-white font-bold text-xs flex items-center justify-center">
              AK
            </div>
            <div>
              <p className="text-xs font-bold text-slate-900 leading-tight">
                Anand K.
              </p>
              <p className="text-[10px] text-slate-500 font-medium">
                Senior Claims Lead
              </p>
            </div>
          </div>
          <span className="w-2 h-2 rounded-full bg-slate-400" title="System Online"></span>
        </div>
      </div>
    </aside>
  );
}
