import { useState, type ChangeEvent } from "react";
import { Search, Bell, Shield, ChevronDown, UserCheck } from "lucide-react";
import type { AssignedRole } from "../types/claims";

interface HeaderProps {
  currentRole: AssignedRole;
  onRoleChange: (role: AssignedRole) => void;
  onSearch?: (query: string) => void;
}

export default function Header({ currentRole, onRoleChange, onSearch }: HeaderProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [isRoleDropdownOpen, setIsRoleDropdownOpen] = useState(false);

  const roles: AssignedRole[] = [
    "Claims Specialist",
    "Medical Reviewer",
    "Fraud / SIU Investigator",
    "Claims Manager",
  ];

  const handleSearchChange = (e: ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value;
    setSearchQuery(q);
    if (onSearch) onSearch(q);
  };

  return (
    <header className="h-16 border-b border-slate-200 sticky top-0 z-30 px-6 flex items-center justify-between bg-white">
      {/* Left: Global Search Bar */}
      <div className="flex items-center gap-4 max-w-md w-full">
        <div className="relative w-full">
          <Search
            size={16}
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400"
          />
          <input
            type="text"
            value={searchQuery}
            onChange={handleSearchChange}
            placeholder="Search claim #, patient name, hospital, ICD code..."
            className="w-full pl-10 pr-4 py-2 rounded-xl bg-slate-100 border border-slate-200 text-xs text-slate-900 placeholder-slate-400 focus:outline-none focus:border-slate-400 transition-all"
          />
        </div>
      </div>

      {/* Right Controls */}
      <div className="flex items-center gap-4">
        {/* Role Selector Dropdown */}
        <div className="relative">
          <button
            onClick={() => setIsRoleDropdownOpen(!isRoleDropdownOpen)}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-100 border border-slate-200 text-xs font-bold text-slate-800 hover:bg-slate-200 transition-all"
          >
            <Shield size={14} className="text-slate-600" />
            <span>Role: {currentRole}</span>
            <ChevronDown size={13} className="text-slate-500" />
          </button>

          {isRoleDropdownOpen && (
            <div className="absolute right-0 mt-2 w-56 border border-slate-200 rounded-xl shadow-xl py-1.5 z-50 bg-white">
              <div className="px-3 py-1 border-b border-slate-100 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                Switch Operational View
              </div>
              {roles.map((role) => (
                <button
                  key={role}
                  onClick={() => {
                    onRoleChange(role);
                    setIsRoleDropdownOpen(false);
                  }}
                  className={`w-full px-3 py-2 text-left text-xs font-medium flex items-center justify-between hover:bg-slate-100 transition-colors ${
                    currentRole === role ? "text-slate-900 font-bold bg-slate-100" : "text-slate-700"
                  }`}
                >
                  <span>{role}</span>
                  {currentRole === role && <UserCheck size={14} className="text-slate-900" />}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Notification Bell */}
        <button
          className="relative p-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors border border-slate-200"
          title="Notifications"
        >
          <Bell size={18} />
          <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-slate-400"></span>
        </button>
      </div>
    </header>
  );
}
