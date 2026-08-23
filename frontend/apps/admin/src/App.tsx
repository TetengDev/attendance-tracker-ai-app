import React, { useState } from "react";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";

import { apiBaseUrl } from "@attendance/api-client";

const queryClient = new QueryClient();

// ----------------------
// Layout & Components
// ----------------------

function Sidebar() {
  const navItems = [
    { to: "/", label: "Dashboard", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" },
    { to: "/people", label: "People & Enrollment", icon: "M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" },
    { to: "/devices", label: "Kiosks & Devices", icon: "M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" },
    { to: "/reports", label: "Reports & Export", icon: "M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
    { to: "/settings", label: "Settings", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" },
    { to: "/muster", label: "Emergency Muster Roll", icon: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z", isEmergency: true },
  ];

  return (
    <div className="w-64 bg-zinc-950 text-white flex flex-col h-screen border-r border-zinc-800 no-print">
      <div className="p-6 flex items-center gap-3">
        <div className="h-8 w-8 rounded-lg bg-gradient-to-tr from-cyan-500 to-blue-500 flex items-center justify-center shadow-lg shadow-cyan-500/20">
          <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.121 17.804A13.937 13.937 0 0112 16c2.5 0 4.847.655 6.879 1.804M15 10a3 3 0 11-6 0 3 3 0 016 0zm6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <span className="font-bold tracking-wider text-sm uppercase">Aegis Admin</span>
      </div>
      
      <nav className="flex-1 px-4 py-4 space-y-1">
        {navItems.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            className={item.isEmergency 
              ? "flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 text-rose-400 hover:text-white hover:bg-rose-500/10 active:bg-rose-500/20"
              : "flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 text-zinc-400 hover:text-white hover:bg-white/5 active:bg-white/10"
            }
            activeProps={{ 
              className: item.isEmergency 
                ? "bg-rose-500/25 text-rose-400 font-bold border-l-4 border-rose-500 pl-2" 
                : "bg-cyan-500/10 text-cyan-400 font-semibold" 
            }}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              {item.label === "Settings" && <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={item.icon} />}
              {item.label === "Settings" && <circle cx="12" cy="12" r="3" strokeWidth={1.5} />}
              {item.label !== "Settings" && <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={item.icon} />}
            </svg>
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="p-4 mt-auto">
        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
          <p className="text-xs text-zinc-400 mb-2">API Endpoint</p>
          <p className="text-[10px] font-mono text-cyan-400 break-all">{apiBaseUrl}</p>
        </div>
      </div>
    </div>
  );
}

function AdminLayout() {
  return (
    <div className="flex min-h-screen bg-zinc-50 font-sans text-zinc-900">
      <Sidebar />
      <div className="flex-1 flex flex-col h-screen overflow-hidden">
        <header className="h-16 bg-white border-b border-zinc-200 flex items-center justify-between px-8 shrink-0 no-print">
          <h2 className="text-sm font-semibold text-zinc-500 uppercase tracking-wider">Console Overview</h2>
          <div className="flex items-center gap-4">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs font-semibold text-emerald-600 tracking-wide uppercase">System Healthy</span>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

// ----------------------
// Routes
// ----------------------

const rootRoute = createRootRoute({
  component: AdminLayout,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: function Dashboard() {
    const { data: metrics, isLoading, isError } = useQuery({
      queryKey: ["dashboard-metrics"],
      queryFn: async () => {
        const res = await fetch(`${apiBaseUrl}/api/dashboard/metrics`, {
          headers: {
            "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70"
          }
        });
        if (!res.ok) throw new Error("Failed to fetch metrics");
        return res.json();
      }
    });

    return (
      <div className="max-w-6xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500">
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight text-zinc-900">Dashboard</h1>
          <p className="text-zinc-500 mt-1">Overview of your attendance and biometric operations.</p>
        </div>

        {isLoading ? (
          <div className="flex justify-center p-12">
            <div className="h-8 w-8 border-4 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin"></div>
          </div>
        ) : isError ? (
          <div className="p-12 text-center text-red-500 font-medium">Error loading dashboard metrics.</div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
              {[
                { label: "Active People", value: metrics?.active_people || 0, trend: "Current", icon: "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" },
                { label: "Registered Kiosks", value: metrics?.active_kiosks || 0, trend: "All online", icon: "M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z" },
                { label: "Scans Today", value: metrics?.scans_today || 0, trend: "Today's logs", icon: "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" },
              ].map((stat, i) => (
                <div key={i} className="bg-white rounded-2xl p-6 border border-zinc-200 shadow-sm hover:shadow-md transition-shadow">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-sm font-medium text-zinc-500">{stat.label}</p>
                      <p className="text-3xl font-bold text-zinc-900 mt-2">{stat.value}</p>
                    </div>
                    <div className="p-3 bg-cyan-50 text-cyan-600 rounded-xl">
                      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={stat.icon} />
                      </svg>
                    </div>
                  </div>
                  <p className="text-sm text-zinc-500 mt-4 font-medium">{stat.trend}</p>
                </div>
              ))}
            </div>

            <div className="bg-white rounded-2xl border border-zinc-200 p-8 shadow-sm">
              <h3 className="text-lg font-semibold text-zinc-900 mb-6">Recent Activity</h3>
              {!metrics?.recent_activity || metrics.recent_activity.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-zinc-400">
                  <svg className="w-12 h-12 mb-4 text-zinc-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <p>No activity recorded today.</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {metrics.recent_activity.map((activity: any) => (
                    <div key={activity.id} className="flex items-center justify-between p-4 rounded-xl border border-zinc-100 bg-zinc-50/50 hover:bg-zinc-50 transition-colors">
                      <div className="flex items-center gap-4">
                        <div className={`p-2 rounded-lg ${activity.outcome === 'accepted' ? 'bg-emerald-100 text-emerald-600' : 'bg-red-100 text-red-600'}`}>
                          {activity.outcome === 'accepted' ? (
                            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
                          ) : (
                            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                          )}
                        </div>
                        <div>
                          <p className="font-semibold text-zinc-900">{activity.person_name}</p>
                          <p className="text-xs text-zinc-500 capitalize">Scan {activity.direction} • {activity.outcome}</p>
                        </div>
                      </div>
                      <div className="text-sm text-zinc-500 font-medium">
                        {new Date(activity.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    );
  }
});

function EnrollPersonModal({ isOpen, onClose, onSuccess }: { isOpen: boolean; onClose: () => void; onSuccess: () => void }) {
  const queryClient = useQueryClient();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    const formData = new FormData(e.currentTarget);
    const payload = {
      display_name: formData.get("display_name") as string,
      kind: formData.get("kind") as string,
      is_active: true,
      locale: "en"
    };

    try {
      const res = await fetch(`${apiBaseUrl}/api/people`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70"
        },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        throw new Error("Failed to create person");
      }
      await queryClient.invalidateQueries({ queryKey: ["people"] });
      onSuccess();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-zinc-950/40 backdrop-blur-sm z-50 flex items-center justify-center animate-in fade-in duration-200">
      <div className="bg-white rounded-3xl shadow-2xl border border-zinc-200 w-full max-w-md overflow-hidden animate-scale-up">
        <div className="px-6 py-4 border-b border-zinc-100 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-zinc-900">Enroll New Person</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-6">
          {error && <div className="mb-4 text-sm text-red-600 bg-red-50 p-3 rounded-xl border border-red-100">{error}</div>}
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-zinc-700 mb-1">Full Name</label>
              <input required name="display_name" type="text" className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2.5 px-3 border outline-none" placeholder="e.g. Jane Doe" />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-700 mb-1">Role / Kind</label>
              <select required name="kind" className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2.5 px-3 border outline-none">
                <option value="staff">Staff / Employee</option>
                <option value="student">Student</option>
                <option value="visitor">Visitor</option>
                <option value="contractor">Contractor</option>
              </select>
            </div>
          </div>
          <div className="mt-8 flex justify-end gap-3">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium text-zinc-600 hover:text-zinc-900">Cancel</button>
            <button type="submit" disabled={isSubmitting} className="bg-cyan-600 text-white px-5 py-2 rounded-xl text-sm font-medium hover:bg-cyan-700 disabled:opacity-50 transition-colors shadow-sm shadow-cyan-600/20">
              {isSubmitting ? "Creating..." : "Create Profile"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function EditPersonModal({ person, isOpen, onClose, onSuccess }: { person: any; isOpen: boolean; onClose: () => void; onSuccess: () => void }) {
  const queryClient = useQueryClient();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // States
  const [displayName, setDisplayName] = useState("");
  const [preferredName, setPreferredName] = useState("");
  const [externalId, setExternalId] = useState("");
  const [kind, setKind] = useState("staff");
  const [isActive, setIsActive] = useState(true);

  // Synchronize state when modal opens
  React.useEffect(() => {
    if (person && isOpen) {
      setDisplayName(person.display_name || "");
      setPreferredName(person.preferred_name || "");
      setExternalId(person.external_id || "");
      setKind(person.kind || "staff");
      setIsActive(person.is_active !== false);
      setError(null);
    }
  }, [person, isOpen]);

  if (!isOpen || !person) return null;

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    
    const payload = {
      display_name: displayName,
      preferred_name: preferredName || null,
      external_id: externalId || null,
      kind: kind,
      is_active: isActive,
    };

    try {
      const res = await fetch(`${apiBaseUrl}/api/people/${person.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70"
        },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || "Failed to update person");
      }
      await queryClient.invalidateQueries({ queryKey: ["people"] });
      onSuccess();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-zinc-950/40 backdrop-blur-sm z-50 flex items-center justify-center animate-in fade-in duration-200">
      <div className="bg-white rounded-3xl shadow-2xl border border-zinc-200 w-full max-w-md overflow-hidden animate-scale-up">
        <div className="px-6 py-4 border-b border-zinc-100 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-zinc-900">Edit Person Profile</h2>
          <button type="button" onClick={onClose} className="text-zinc-400 hover:text-zinc-600">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-6">
          {error && <div className="mb-4 text-sm text-red-600 bg-red-50 p-3 rounded-xl border border-red-100">{error}</div>}
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-zinc-700 mb-1">Display Name</label>
              <input 
                required 
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                type="text" 
                className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2.5 px-3 border outline-none text-zinc-800" 
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-700 mb-1">Preferred Name</label>
              <input 
                value={preferredName}
                onChange={(e) => setPreferredName(e.target.value)}
                type="text" 
                className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2.5 px-3 border outline-none text-zinc-800" 
                placeholder="e.g. John"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-700 mb-1">External ID</label>
              <input 
                value={externalId}
                onChange={(e) => setExternalId(e.target.value)}
                type="text" 
                className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2.5 px-3 border outline-none text-zinc-800 font-mono text-sm" 
                placeholder="e.g. EMP-1049"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-zinc-700 mb-1">Role / Kind</label>
              <select 
                required 
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2.5 px-3 border outline-none text-zinc-800"
              >
                <option value="staff">Staff / Employee</option>
                <option value="student">Student</option>
                <option value="visitor">Visitor</option>
                <option value="contractor">Contractor</option>
              </select>
            </div>
            <div className="flex items-center gap-2 pt-2">
              <input 
                id="edit_is_active"
                type="checkbox" 
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="h-4 w-4 rounded border-zinc-300 text-cyan-600 focus:ring-cyan-500"
              />
              <label htmlFor="edit_is_active" className="text-sm font-semibold text-zinc-700 select-none">
                Active status in the system
              </label>
            </div>
          </div>
          <div className="mt-8 flex justify-end gap-3 border-t border-zinc-100 pt-4">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium text-zinc-600 hover:text-zinc-900">Cancel</button>
            <button type="submit" disabled={isSubmitting} className="bg-cyan-600 text-white px-5 py-2 rounded-xl text-sm font-medium hover:bg-cyan-700 disabled:opacity-50 transition-colors shadow-sm shadow-cyan-600/20">
              {isSubmitting ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function DeletePersonModal({ person, isOpen, onClose, onSuccess }: { person: any; isOpen: boolean; onClose: () => void; onSuccess: () => void }) {
  const queryClient = useQueryClient();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen || !person) return null;

  async function handleDelete() {
    setIsSubmitting(true);
    setError(null);

    try {
      const res = await fetch(`${apiBaseUrl}/api/people/${person.id}`, {
        method: "DELETE",
        headers: {
          "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70"
        }
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || "Failed to delete person");
      }
      await queryClient.invalidateQueries({ queryKey: ["people"] });
      onSuccess();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-zinc-950/40 backdrop-blur-sm z-50 flex items-center justify-center animate-in fade-in duration-200">
      <div className="bg-white rounded-3xl shadow-2xl border border-zinc-200 w-full max-w-md overflow-hidden animate-scale-up">
        <div className="p-6 text-center">
          <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-rose-100 text-rose-600 mb-4">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <h3 className="text-lg font-bold text-zinc-900 mb-2">Delete Profile</h3>
          <p className="text-sm text-zinc-500 mb-6">
            Are you sure you want to delete <span className="font-semibold text-zinc-950">{person.display_name}</span>? 
            This action is permanent and will delete all associated biometric templates and attendance records.
          </p>
          {error && <div className="mb-4 text-xs text-red-600 bg-red-50 p-3 rounded-xl border border-red-100">{error}</div>}
          <div className="flex justify-center gap-3">
            <button 
              type="button" 
              onClick={onClose} 
              className="px-4 py-2 text-sm font-medium text-zinc-600 hover:text-zinc-900 border border-zinc-200 rounded-xl"
            >
              Cancel
            </button>
            <button 
              type="button" 
              onClick={handleDelete}
              disabled={isSubmitting}
              className="bg-rose-600 hover:bg-rose-700 text-white px-5 py-2 rounded-xl text-sm font-medium disabled:opacity-50 transition-colors shadow-sm shadow-rose-600/20"
            >
              {isSubmitting ? "Deleting..." : "Delete Profile"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function CaptureFaceModal({ person, isOpen, onClose, onSuccess }: { person: any; isOpen: boolean; onClose: () => void; onSuccess: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [isCapturing, setIsCapturing] = useState(false);
  const videoRef = React.useRef<HTMLVideoElement>(null);

  React.useEffect(() => {
    if (isOpen && videoRef.current) {
      navigator.mediaDevices.getUserMedia({ video: true })
        .then(stream => {
          if (videoRef.current) videoRef.current.srcObject = stream;
        })
        .catch(err => {
          console.error(err);
          setError("Failed to access webcam. Please check permissions.");
        });
    } else {
      if (videoRef.current && videoRef.current.srcObject) {
        (videoRef.current.srcObject as MediaStream).getTracks().forEach(t => t.stop());
      }
    }
  }, [isOpen]);

  if (!isOpen || !person) return null;

  async function handleCapture() {
    if (!videoRef.current) return;
    setIsCapturing(true);
    setError(null);
    try {
      const canvas = document.createElement("canvas");
      canvas.width = videoRef.current.videoWidth;
      canvas.height = videoRef.current.videoHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Could not create canvas context");
      ctx.drawImage(videoRef.current, 0, 0);

      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob(b => b ? resolve(b) : reject(new Error("Canvas toBlob failed")), "image/jpeg", 0.95);
      });

      // 1. Create Consent
      try {
        const consentRes = await fetch(`${apiBaseUrl}/api/consents/biometric-enrollment`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70"
          },
          body: JSON.stringify({ 
            person_id: person.id, 
            grantor: "self",
            method: "admin_attestation",
            policy_version: "1.0" 
          })
        });
        // We don't throw an error here because if they retry, it might return a 500/409 duplicate key error
        // since the consent was already created on the first attempt.
      } catch (e) {
        console.warn("Consent creation warning (likely duplicate):", e);
      }

      // 2. Authorize Consent
      const authRes = await fetch(`${apiBaseUrl}/api/consents/biometric-enrollment/authorize`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70"
        },
        body: JSON.stringify({
          person_id: person.id,
          policy_version: "1.0"
        })
      });
      if (!authRes.ok) throw new Error("Failed to authorize consent");

      // 3. Upload Face
      const formData = new FormData();
      formData.append("policy_version", "1.0");
      formData.append("capture_pose", "frontal");
      formData.append("file", blob, "face.jpg");

      const uploadRes = await fetch(`${apiBaseUrl}/api/enrollment/${person.id}/capture`, {
        method: "POST",
        headers: {
          "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70"
        },
        body: formData
      });
      if (!uploadRes.ok) {
        const errorText = await uploadRes.text();
        throw new Error(errorText || "Failed to upload face");
      }

      onSuccess();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsCapturing(false);
    }
  }

  function handleClose() {
    if (videoRef.current && videoRef.current.srcObject) {
      (videoRef.current.srcObject as MediaStream).getTracks().forEach(t => t.stop());
    }
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-zinc-950/40 backdrop-blur-sm z-50 flex items-center justify-center animate-in fade-in duration-200">
      <div className="bg-white rounded-3xl shadow-2xl border border-zinc-200 w-full max-w-lg overflow-hidden animate-scale-up">
        <div className="px-6 py-4 border-b border-zinc-100 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-zinc-900">Enroll Face: {person.display_name}</h2>
          <button onClick={handleClose} className="text-zinc-400 hover:text-zinc-600">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="p-6">
          {error && <div className="mb-4 text-sm text-red-600 bg-red-50 p-3 rounded-xl border border-red-100">{error}</div>}
          <div className="rounded-2xl overflow-hidden bg-zinc-100 relative aspect-video flex items-center justify-center">
            <video ref={videoRef} autoPlay playsInline muted className="w-full h-full object-cover" />
            <div className="absolute inset-0 border-4 border-cyan-500/30 rounded-2xl pointer-events-none"></div>
          </div>
          <p className="mt-4 text-sm text-zinc-500 text-center">
            Ensure the face is well-lit and clearly visible in the frame.
          </p>
          <div className="mt-6 flex justify-end gap-3">
            <button type="button" onClick={handleClose} className="px-4 py-2 text-sm font-medium text-zinc-600 hover:text-zinc-900">Cancel</button>
            <button type="button" onClick={handleCapture} disabled={isCapturing} className="bg-cyan-600 text-white px-5 py-2 rounded-xl text-sm font-medium hover:bg-cyan-700 disabled:opacity-50 transition-colors shadow-sm shadow-cyan-600/20">
              {isCapturing ? "Processing..." : "Capture & Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function OverrideModal({ isOpen, onClose, onSuccess, row }: { isOpen: boolean; onClose: () => void; onSuccess: () => void; row: any }) {
  const [status, setStatus] = useState<string>("excused");
  const [reason, setReason] = useState<string>("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => {
    if (row) {
      setStatus(row.status || "excused");
      setReason(row.reason || "");
      setError(null);
    }
  }, [row]);

  if (!isOpen || !row) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reason.trim()) {
      setError("Reason is required");
      return;
    }
    setIsSubmitting(true);
    setError(null);

    try {
      const res = await fetch(`${apiBaseUrl}/api/attendance/overrides`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70",
        },
        body: JSON.stringify({
          person_id: row.person_id,
          business_date: row.business_date,
          shift_id: row.shift_id,
          period_label: "day",
          status,
          reason: reason.trim(),
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to submit override");
      }

      onSuccess();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-zinc-950/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl border border-zinc-200 w-full max-w-md shadow-2xl p-6 overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        <h3 className="text-lg font-bold text-zinc-900 mb-2">Override Attendance</h3>
        <p className="text-xs text-zinc-500 mb-6">
          Manually override status for <strong className="text-zinc-800">{row.name}</strong> on <strong className="text-zinc-800">{row.business_date}</strong>.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-2">Status</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-full bg-zinc-50 border border-zinc-200/80 rounded-xl px-4 py-2.5 text-sm font-medium text-zinc-800 focus:outline-none focus:ring-2 focus:ring-cyan-500/20"
            >
              <option value="present">Present</option>
              <option value="late">Late</option>
              <option value="absent">Absent</option>
              <option value="excused">Excused</option>
              <option value="holiday">Holiday</option>
              <option value="pending">Pending</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-2">Reason</label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason for manual modification..."
              rows={3}
              className="w-full bg-zinc-50 border border-zinc-200/80 rounded-xl px-4 py-2.5 text-sm text-zinc-800 focus:outline-none focus:ring-2 focus:ring-cyan-500/20"
            />
          </div>

          {error && <div className="text-red-500 text-xs font-medium bg-red-50 border border-red-100 p-2.5 rounded-xl">{error}</div>}

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-zinc-100">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-sm font-semibold text-zinc-500 hover:text-zinc-800 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="bg-cyan-600 hover:bg-cyan-700 text-white font-semibold py-2 px-4 rounded-xl text-sm tracking-wider uppercase transition-colors shadow-sm disabled:opacity-50"
            >
              {isSubmitting ? "Saving..." : "Apply Override"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

const peopleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/people",
  component: function People() {
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [capturePerson, setCapturePerson] = useState<any>(null);
    const [editPerson, setEditPerson] = useState<any>(null);
    const [deletePerson, setDeletePerson] = useState<any>(null);
    
    const { data: people, isLoading, isError, refetch } = useQuery({
      queryKey: ["people"],
      queryFn: async () => {
        const res = await fetch(`${apiBaseUrl}/api/people`, {
          headers: {
            "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70"
          }
        });
        if (!res.ok) throw new Error("Failed to fetch people");
        return res.json() as Promise<any[]>;
      }
    });

    return (
      <div className="max-w-6xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500">
        <EnrollPersonModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} onSuccess={() => setIsModalOpen(false)} />
        <CaptureFaceModal 
          person={capturePerson} 
          isOpen={!!capturePerson} 
          onClose={() => setCapturePerson(null)} 
          onSuccess={() => { setCapturePerson(null); refetch(); }} 
        />
        <EditPersonModal 
          person={editPerson} 
          isOpen={!!editPerson} 
          onClose={() => setEditPerson(null)} 
          onSuccess={() => { setEditPerson(null); refetch(); }} 
        />
        <DeletePersonModal 
          person={deletePerson} 
          isOpen={!!deletePerson} 
          onClose={() => setDeletePerson(null)} 
          onSuccess={() => { setDeletePerson(null); refetch(); }} 
        />
        
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-zinc-900">People & Enrollment</h1>
            <p className="text-zinc-500 mt-1">Manage users, view profiles, and handle biometric enrollment.</p>
          </div>
          <button onClick={() => setIsModalOpen(true)} className="bg-cyan-600 text-white px-4 py-2 rounded-xl text-sm font-medium hover:bg-cyan-700 transition-colors shadow-sm shadow-cyan-600/20">
            + Enroll Person
          </button>
        </div>
        
        <div className="bg-white rounded-2xl border border-zinc-200 overflow-hidden shadow-sm">
          {isLoading ? (
            <div className="p-12 flex justify-center">
              <div className="h-8 w-8 border-4 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin"></div>
            </div>
          ) : isError ? (
            <div className="p-12 text-center text-red-500 font-medium">Error loading people.</div>
          ) : people?.length === 0 ? (
            <div className="p-12 text-center text-zinc-500">No people found in the database.</div>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="bg-zinc-50 border-b border-zinc-200 text-zinc-500 font-medium">
                <tr>
                  <th className="px-6 py-4">Name</th>
                  <th className="px-6 py-4">Kind</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {people?.map((p) => (
                  <tr key={p.id} className="hover:bg-zinc-50/50 transition-colors">
                    <td className="px-6 py-4">
                      <div className="font-semibold text-zinc-900">{p.display_name}</div>
                      <div className="text-xs text-zinc-500 font-mono mt-0.5">{p.id}</div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="bg-zinc-100 text-zinc-600 border border-zinc-200 px-2 py-1 rounded text-xs uppercase tracking-wider font-semibold">
                        {p.kind}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      {p.is_active ? (
                        <span className="flex items-center gap-1.5 text-emerald-600 text-xs font-semibold uppercase tracking-wider">
                          <span className="h-1.5 w-1.5 bg-emerald-500 rounded-full"></span> Active
                        </span>
                      ) : (
                        <span className="flex items-center gap-1.5 text-zinc-400 text-xs font-semibold uppercase tracking-wider">
                          <span className="h-1.5 w-1.5 bg-zinc-300 rounded-full"></span> Inactive
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="flex items-center justify-end gap-3.5">
                        <button type="button" onClick={() => setCapturePerson(p)} className="text-cyan-600 hover:text-cyan-700 font-medium text-xs flex items-center gap-1">
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                          </svg>
                          Capture Face
                        </button>
                        <button type="button" onClick={() => setEditPerson(p)} className="text-zinc-600 hover:text-zinc-900 font-medium text-xs flex items-center gap-1">
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                          </svg>
                          Edit
                        </button>
                        <button type="button" onClick={() => setDeletePerson(p)} className="text-rose-600 hover:text-rose-700 font-medium text-xs flex items-center gap-1">
                          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-4v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    );
  }
});

function DeviceRegistrationModal({ isOpen, onClose, onSuccess }: { isOpen: boolean; onClose: () => void; onSuccess: () => void }) {
  const queryClient = useQueryClient();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pairingCode, setPairingCode] = useState<string | null>(null);

  const { data: locations } = useQuery({
    queryKey: ["locations"],
    queryFn: async () => {
      const res = await fetch(`${apiBaseUrl}/api/locations?limit=100&offset=0`, {
        headers: { "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70" }
      });
      if (!res.ok) return [];
      return res.json() as Promise<any[]>;
    },
    enabled: isOpen
  });

  if (!isOpen) return null;

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    const formData = new FormData(e.currentTarget);
    const locationId = formData.get("location_id") as string;
    const payload: Record<string, any> = {
      form_factor: formData.get("form_factor") as string,
      mode: locationId ? "fixed" : "roaming",
      direction: "bidirectional",
      token_hash: "unpaired",
      token_display_prefix: "unpaired"
    };
    if (locationId) {
      payload.location_id = locationId;
    }

    try {
      const res = await fetch(`${apiBaseUrl}/api/devices`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70"
        },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const errBody = await res.text();
        throw new Error(errBody || "Failed to register device");
      }
      const device = await res.json();

      // Generate pairing code
      const pairRes = await fetch(`${apiBaseUrl}/api/devices/${device.id}/pairing-code`, {
        method: "POST",
        headers: { "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70" }
      });
      if (!pairRes.ok) throw new Error("Failed to generate pairing code");
      const pairData = await pairRes.json();
      
      setPairingCode(pairData.pairing_code);
      await queryClient.invalidateQueries({ queryKey: ["devices"] });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-zinc-950/40 backdrop-blur-sm z-50 flex items-center justify-center animate-in fade-in duration-200">
      <div className="bg-white rounded-3xl shadow-2xl border border-zinc-200 w-full max-w-md overflow-hidden animate-scale-up">
        <div className="px-6 py-4 border-b border-zinc-100 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-zinc-900">Register Kiosk Device</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        
        {pairingCode ? (
          <div className="p-8 text-center">
            <div className="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
            </div>
            <h3 className="text-xl font-bold text-zinc-900 mb-2">Registration Successful</h3>
            <p className="text-zinc-500 mb-6">Enter this pairing code on the physical device to complete setup:</p>
            <div className="bg-zinc-100 text-zinc-900 font-mono text-4xl tracking-[0.2em] py-4 rounded-xl font-bold">
              {pairingCode}
            </div>
            <p className="text-xs text-zinc-400 mt-4">This code expires in 15 minutes.</p>
            <button onClick={onSuccess} className="w-full mt-6 bg-cyan-600 text-white py-3 rounded-xl font-medium hover:bg-cyan-700 transition-colors shadow-sm shadow-cyan-600/20">
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="p-6">
            {error && <div className="mb-4 text-sm text-red-600 bg-red-50 p-3 rounded-xl border border-red-100">{error}</div>}
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-zinc-700 mb-1">Form Factor</label>
                <select name="form_factor" className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2.5 px-3 border outline-none">
                  <option value="tablet">Tablet / iPad</option>
                  <option value="phone">Mobile Phone</option>
                  <option value="desktop">Desktop / Laptop</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-zinc-700 mb-1">Location</label>
                <select name="location_id" className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2.5 px-3 border outline-none">
                  {locations?.map((loc: any) => (
                    <option key={loc.id} value={loc.id}>{loc.name}</option>
                  ))}
                </select>
                <p className="text-xs text-zinc-400 mt-1">The device will be assigned to this location.</p>
              </div>
            </div>
            <div className="mt-8 flex justify-end gap-3">
              <button type="button" onClick={onClose} className="px-4 py-2 text-sm font-medium text-zinc-600 hover:text-zinc-900">Cancel</button>
              <button type="submit" disabled={isSubmitting} className="bg-cyan-600 text-white px-5 py-2 rounded-xl text-sm font-medium hover:bg-cyan-700 disabled:opacity-50 transition-colors shadow-sm shadow-cyan-600/20">
                {isSubmitting ? "Registering..." : "Generate Pairing Code"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

const devicesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/devices",
    component: function Devices() {
      const [isModalOpen, setIsModalOpen] = useState(false);
      const [showCodeDetails, setShowCodeDetails] = useState<{ id: string; code: string } | null>(null);
      const [isGeneratingCode, setIsGeneratingCode] = useState<string | null>(null);
      
      const { data: devices, isLoading, isError, refetch } = useQuery({
        queryKey: ["devices"],
        queryFn: async () => {
          const res = await fetch(`${apiBaseUrl}/api/devices?limit=100&offset=0`, {
            headers: {
              "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70"
            }
          });
          if (!res.ok) throw new Error("Failed to fetch devices");
          return res.json() as Promise<any[]>;
        }
      });

      const handleShowCode = async (deviceId: string) => {
        setIsGeneratingCode(deviceId);
        try {
          const res = await fetch(`${apiBaseUrl}/api/devices/${deviceId}/pairing-code`, {
            method: "POST",
            headers: { "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70" }
          });
          if (!res.ok) throw new Error("Failed to generate pairing code");
          const data = await res.json();
          setShowCodeDetails({ id: deviceId, code: data.pairing_code });
        } catch (err: any) {
          alert(err.message || "Failed to generate pairing code");
        } finally {
          setIsGeneratingCode(null);
        }
      };

      const handleDeleteDevice = async (deviceId: string) => {
        if (!window.confirm("Are you sure you want to unregister and delete this device? This will immediately disconnect the device if it is active.")) {
          return;
        }
        try {
          const res = await fetch(`${apiBaseUrl}/api/devices/${deviceId}`, {
            method: "DELETE",
            headers: { "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70" }
          });
          if (!res.ok) throw new Error("Failed to delete device");
          await refetch();
        } catch (err: any) {
          alert(err.message || "Failed to delete device");
        }
      };

      return (
        <div className="max-w-6xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500">
          <DeviceRegistrationModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} onSuccess={() => { setIsModalOpen(false); refetch(); }} />
          
          {showCodeDetails && (
            <div className="fixed inset-0 bg-zinc-950/40 backdrop-blur-sm z-50 flex items-center justify-center animate-in fade-in duration-200">
              <div className="bg-white rounded-3xl shadow-2xl border border-zinc-200 w-full max-w-md overflow-hidden animate-scale-up p-8 text-center">
                <div className="w-16 h-16 bg-cyan-100 text-cyan-600 rounded-full flex items-center justify-center mx-auto mb-4">
                  <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v1m6 11h2m-6 0h-2v4m0-11v3m0 0h.01M12 12h4.01M16 20h4M4 12h4m12 0h.01M5 8h2a1 1 0 001-1V5a1 1 0 00-1-1H5a1 1 0 00-1 1v2a1 1 0 001 1z" />
                  </svg>
                </div>
                <h3 className="text-xl font-bold text-zinc-900 mb-2">Device Pairing Code</h3>
                <p className="text-zinc-500 mb-6 font-medium text-sm">Enter this pairing code on the physical device to pair it:</p>
                <div className="bg-zinc-100 text-zinc-900 font-mono text-4xl tracking-[0.2em] py-4 rounded-xl font-bold select-all">
                  {showCodeDetails.code}
                </div>
                <p className="text-xs text-zinc-400 mt-4">This code expires in 15 minutes.</p>
                <button 
                  onClick={() => setShowCodeDetails(null)} 
                  className="w-full mt-6 bg-zinc-900 text-white py-3 rounded-xl font-medium hover:bg-zinc-800 transition-colors shadow-sm"
                >
                  Close
                </button>
              </div>
            </div>
          )}

          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-3xl font-bold tracking-tight text-zinc-900">Kiosks & Devices</h1>
              <p className="text-zinc-500 mt-1">Monitor connected physical devices and attendance kiosks.</p>
            </div>
            <button onClick={() => setIsModalOpen(true)} className="bg-cyan-600 text-white px-4 py-2 rounded-xl text-sm font-medium hover:bg-cyan-700 transition-colors shadow-sm shadow-cyan-600/20">
              + Register Device
            </button>
          </div>
          
          <div className="bg-white rounded-2xl border border-zinc-200 overflow-hidden shadow-sm">
            {isLoading ? (
              <div className="p-12 flex justify-center">
                <div className="h-8 w-8 border-4 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin"></div>
              </div>
            ) : isError ? (
              <div className="p-12 text-center text-red-500 font-medium">Error loading devices.</div>
            ) : devices?.length === 0 ? (
              <div className="p-12 text-center text-zinc-500">No registered devices found.</div>
            ) : (
              <table className="w-full text-left text-sm">
                <thead className="bg-zinc-50 border-b border-zinc-200 text-zinc-500 font-medium">
                  <tr>
                    <th className="px-6 py-4">ID Prefix</th>
                    <th className="px-6 py-4">Form Factor</th>
                    <th className="px-6 py-4">Mode</th>
                    <th className="px-6 py-4">Status</th>
                    <th className="px-6 py-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {devices?.map((d) => (
                    <tr key={d.id} className="hover:bg-zinc-50/50 transition-colors">
                      <td className="px-6 py-4">
                        <div className="font-semibold text-zinc-900 font-mono">{d.id.substring(0, 8)}...</div>
                        <div className="text-xs text-zinc-500 mt-0.5">Token: {d.token_display_prefix === 'unpaired' ? 'Unpaired' : `***${d.token_display_prefix}`}</div>
                      </td>
                      <td className="px-6 py-4 capitalize font-medium text-zinc-700">
                        {d.form_factor}
                      </td>
                      <td className="px-6 py-4">
                        <span className="bg-zinc-100 text-zinc-600 border border-zinc-200 px-2 py-1 rounded text-xs uppercase tracking-wider font-semibold">
                          {d.mode}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        {d.token_display_prefix !== 'unpaired' ? (
                          <span className="flex items-center gap-1.5 text-emerald-600 text-xs font-semibold uppercase tracking-wider">
                            <span className="h-1.5 w-1.5 bg-emerald-500 rounded-full animate-pulse"></span> Paired
                          </span>
                        ) : (
                          <span className="flex items-center gap-1.5 text-amber-500 text-xs font-semibold uppercase tracking-wider">
                            <span className="h-1.5 w-1.5 bg-amber-400 rounded-full"></span> Unpaired
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-right flex items-center justify-end gap-3">
                        {d.token_display_prefix === 'unpaired' && (
                          <button 
                            onClick={() => handleShowCode(d.id)}
                            disabled={isGeneratingCode === d.id}
                            className="text-cyan-600 hover:text-cyan-700 disabled:text-zinc-400 font-medium text-sm"
                          >
                            {isGeneratingCode === d.id ? "Generating..." : "Show Code"}
                          </button>
                        )}
                        <button 
                          onClick={() => handleDeleteDevice(d.id)}
                          className="text-red-500 hover:text-red-700 font-medium text-sm"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      );
    }
});

const CATEGORY_META: Record<string, { label: string; icon: string; description: string }> = {
  face: { label: "Face Recognition", icon: "M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z", description: "Thresholds for face matching, detection, and duplicate prevention." },
  liveness: { label: "Liveness Detection", icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z", description: "Anti-spoofing controls for scan verification." },
  scan: { label: "Scan Behavior", icon: "M12 4v1m6 11h2m-6 0h-2v4m0-11v3m0 0h.01M12 12h4.01M16 20h4M4 12h4m12 0h.01M5 8h2a1 1 0 001-1V5a1 1 0 00-1-1H5a1 1 0 00-1 1v2a1 1 0 001 1z", description: "Cooldowns, rate limits, and scan deduplication." },
  session: { label: "Sessions", icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z", description: "Session timeouts, geofencing, and operator requirements." },
  kiosk: { label: "Kiosk Display", icon: "M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z", description: "Camera, greeting text, UI behavior, and quality gates." },
  branding: { label: "Branding", icon: "M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01", description: "Organization name, colors, and logo." },
  attendance: { label: "Attendance Rules", icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4", description: "Grace periods, absence thresholds, and pairing strategies." },
  privacy: { label: "Privacy & Compliance", icon: "M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z", description: "Data storage policies and regional compliance." },
  retention: { label: "Data Retention", icon: "M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16", description: "How long embeddings, images, events, and audit logs are kept." },
};

function SettingControl({ setting }: { setting: any }) {
  const keyLabel = setting.key.split(".").slice(1).join(" ").replace(/_/g, " ");

  if (setting.type === "bool") {
    return (
      <div className="flex items-center justify-between py-3">
        <div>
          <p className="text-sm font-medium text-zinc-800 capitalize">{keyLabel}</p>
          {setting.note && <p className="text-xs text-zinc-400">{setting.note}</p>}
        </div>
        <div className={`w-10 h-6 rounded-full relative cursor-pointer transition-colors ${setting.value ? 'bg-cyan-500' : 'bg-zinc-300'}`}>
          <div className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${setting.value ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
        </div>
      </div>
    );
  }

  if (setting.type === "enum" && setting.enum) {
    return (
      <div className="flex items-center justify-between py-3">
        <div>
          <p className="text-sm font-medium text-zinc-800 capitalize">{keyLabel}</p>
          {setting.note && <p className="text-xs text-zinc-400">{setting.note}</p>}
        </div>
        <select disabled className="text-sm bg-zinc-50 border border-zinc-200 rounded-lg px-3 py-1.5 text-zinc-700 outline-none" defaultValue={setting.value}>
          {setting.enum.map((opt: string) => <option key={opt} value={opt}>{opt}</option>)}
        </select>
      </div>
    );
  }

  if (setting.type === "float" || setting.type === "int") {
    return (
      <div className="flex items-center justify-between py-3">
        <div className="flex-1 mr-6">
          <p className="text-sm font-medium text-zinc-800 capitalize">{keyLabel}</p>
          <div className="flex items-center gap-2 mt-1">
            {setting.min != null && <span className="text-[10px] text-zinc-400">{setting.min}</span>}
            <div className="flex-1 h-1.5 bg-zinc-200 rounded-full relative">
              <div
                className="absolute h-1.5 bg-cyan-500 rounded-full"
                style={{ width: setting.min != null && setting.max != null ? `${((setting.value - setting.min) / (setting.max - setting.min)) * 100}%` : '50%' }}
              />
            </div>
            {setting.max != null && <span className="text-[10px] text-zinc-400">{setting.max}</span>}
          </div>
          {setting.note && <p className="text-xs text-zinc-400 mt-0.5">{setting.note}</p>}
        </div>
        <span className="text-sm font-mono font-semibold text-zinc-700 bg-zinc-100 px-2.5 py-1 rounded-lg min-w-[60px] text-center">{setting.value}</span>
      </div>
    );
  }

  // str type
  return (
    <div className="flex items-center justify-between py-3">
      <div>
        <p className="text-sm font-medium text-zinc-800 capitalize">{keyLabel}</p>
        {setting.note && <p className="text-xs text-zinc-400">{setting.note}</p>}
        {setting.format && <span className="text-[10px] text-zinc-400 font-mono">{setting.format}</span>}
      </div>
      {setting.format === "hex" ? (
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md border border-zinc-200 shadow-sm" style={{ backgroundColor: setting.value || '#ccc' }} />
          <span className="text-sm font-mono text-zinc-600">{setting.value || '—'}</span>
        </div>
      ) : (
        <span className="text-sm text-zinc-600 font-mono bg-zinc-50 px-3 py-1 rounded-lg border border-zinc-200 max-w-[200px] truncate">{setting.value || '—'}</span>
      )}
    </div>
  );
}

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: function Settings() {
    const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(["face", "branding"]));
    const { data, isLoading, isError } = useQuery({
      queryKey: ["settings"],
      queryFn: async () => {
        const res = await fetch(`${apiBaseUrl}/api/settings`, {
          headers: { "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70" }
        });
        if (!res.ok) throw new Error("Failed to fetch settings");
        return res.json();
      }
    });

    const toggleCategory = (cat: string) => {
      setExpandedCategories(prev => {
        const next = new Set(prev);
        if (next.has(cat)) next.delete(cat);
        else next.add(cat);
        return next;
      });
    };

    // Group settings by category
    const grouped: Record<string, any[]> = {};
    for (const s of data?.settings || []) {
      if (!grouped[s.category]) grouped[s.category] = [];
      grouped[s.category]?.push(s);
    }

    const categoryOrder = ["face", "liveness", "scan", "session", "kiosk", "branding", "attendance", "privacy", "retention"];

    return (
      <div className="max-w-4xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500">
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight text-zinc-900">Settings</h1>
          <p className="text-zinc-500 mt-1">Configure global application preferences. Changes require a backend restart.</p>
        </div>

        {isLoading ? (
          <div className="flex justify-center p-12">
            <div className="h-8 w-8 border-4 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin"></div>
          </div>
        ) : isError ? (
          <div className="p-12 text-center text-red-500 font-medium">Error loading settings.</div>
        ) : (
          <div className="space-y-4">
            {categoryOrder.filter(cat => grouped[cat]).map(cat => {
              const meta = CATEGORY_META[cat] || { label: cat, icon: "", description: "" };
              const isExpanded = expandedCategories.has(cat);
              return (
                <div key={cat} className="bg-white rounded-2xl border border-zinc-200 shadow-sm overflow-hidden">
                  <button
                    onClick={() => toggleCategory(cat)}
                    className="w-full px-6 py-5 flex items-center justify-between hover:bg-zinc-50/50 transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <div className="p-2.5 bg-cyan-50 text-cyan-600 rounded-xl">
                        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={meta.icon} />
                        </svg>
                      </div>
                      <div className="text-left">
                        <h3 className="font-semibold text-zinc-900">{meta.label}</h3>
                        <p className="text-xs text-zinc-500 mt-0.5">{meta.description}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-medium text-zinc-400 bg-zinc-100 px-2 py-0.5 rounded-full">{grouped[cat]?.length || 0}</span>
                      <svg className={`w-5 h-5 text-zinc-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                  </button>
                  {isExpanded && (
                    <div className="px-6 pb-5 border-t border-zinc-100">
                      <div className="divide-y divide-zinc-100">
                        {grouped[cat]?.map((s: any) => <SettingControl key={s.key} setting={s} />)}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }
});

async function handleDownloadFile(url: string, filename: string) {
  try {
    const res = await fetch(url, {
      headers: {
        "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70"
      }
    });
    if (!res.ok) throw new Error("Download failed");
    const blob = await res.blob();
    const blobUrl = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(blobUrl);
  } catch (err: any) {
    alert("Failed to download file: " + err.message);
  }
}

function formatCell(val: any, header: string) {
  if (val === null || val === undefined) return "—";
  if (typeof val === "object") return JSON.stringify(val);
  if (typeof val === "boolean") return val ? "Yes" : "No";
  if (header === "status" && typeof val === "string") {
    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider
        ${val === "on_time" || val === "complete" || val === "Active" ? "bg-emerald-100 text-emerald-800 border border-emerald-200" : ""}
        ${val === "late" ? "bg-amber-100 text-amber-800 border border-amber-200" : ""}
        ${val === "absent" || val === "Offline" ? "bg-rose-100 text-rose-800 border border-rose-200" : ""}
        ${val === "excused" || val === "holiday" ? "bg-zinc-100 text-zinc-800 border border-zinc-200" : ""}
        ${val === "present_unscheduled" ? "bg-blue-100 text-blue-800 border border-blue-200" : ""}
      `}>
        {val.replace("_", " ")}
      </span>
    );
  }
  if (typeof val === "string" && (header.includes("_at") || header.includes("occurred") || header.includes("actual") || header.includes("expected") || header.includes("observed"))) {
    try {
      const d = new Date(val);
      if (!isNaN(d.getTime())) {
        return d.toLocaleString();
      }
    } catch {}
  }
  return String(val);
}

const reportsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/reports",
  component: function Reports() {
    const [reportType, setReportType] = useState("daily_register");
    const [dateFrom, setDateFrom] = useState(() => {
      const d = new Date();
      d.setDate(d.getDate() - 30);
      return d.toISOString().split("T")[0];
    });
    const [dateTo, setDateTo] = useState(() => new Date().toISOString().split("T")[0]);
    const [groupId, setGroupId] = useState("");
    const [personId, setPersonId] = useState("");
    const [minAbsences, setMinAbsences] = useState(3);
    const [activeTab, setActiveTab] = useState<"preview" | "jobs">("preview");
    const [isExporting, setIsExporting] = useState<string | null>(null);
    const [asyncBanner, setAsyncBanner] = useState<{ message: string; jobId: string } | null>(null);
    const [overrideRow, setOverrideRow] = useState<any>(null);
    const [isOverrideModalOpen, setIsOverrideModalOpen] = useState(false);

    const queryClient = useQueryClient();

    const handleRemoveOverride = async (overrideId: string) => {
      if (!confirm("Are you sure you want to remove this manual override?")) return;
      try {
        const res = await fetch(`${apiBaseUrl}/api/attendance/overrides/${overrideId}`, {
          method: "DELETE",
          headers: {
            "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70",
          },
        });

        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || "Failed to delete override");
        }

        queryClient.invalidateQueries({ queryKey: ["report-preview"] });
      } catch (err: any) {
        alert(err.message);
      }
    };

    // Query groups
    const { data: groups } = useQuery({
      queryKey: ["groups"],
      queryFn: async () => {
        const res = await fetch(`${apiBaseUrl}/api/groups`, {
          headers: { "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70" }
        });
        if (!res.ok) throw new Error("Failed to fetch groups");
        return res.json() as Promise<any[]>;
      }
    });

    // Query people
    const { data: people } = useQuery({
      queryKey: ["people"],
      queryFn: async () => {
        const res = await fetch(`${apiBaseUrl}/api/people`, {
          headers: { "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70" }
        });
        if (!res.ok) throw new Error("Failed to fetch people");
        return res.json() as Promise<any[]>;
      }
    });

    // Query preview
    const { data: previewData, isLoading: isPreviewLoading, isError: isPreviewError } = useQuery({
      queryKey: ["report-preview", reportType, dateFrom, dateTo, groupId, personId, minAbsences],
      queryFn: async () => {
        const params = new URLSearchParams({
          report_type: reportType,
          date_from: dateFrom || "",
          date_to: dateTo || "",
        });
        if (groupId) params.append("group_id", groupId);
        if (personId && reportType === "timesheet") params.append("person_id", personId);
        if (reportType === "truancy") params.append("min_absences", String(minAbsences));

        const res = await fetch(`${apiBaseUrl}/api/reports/preview?${params.toString()}`, {
          headers: { "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70" }
        });
        if (!res.ok) throw new Error("Failed to fetch report preview");
        return res.json();
      }
    });

    // Query background jobs (poll if there are pending jobs)
    const { data: jobs } = useQuery({
      queryKey: ["report-jobs"],
      queryFn: async () => {
        const res = await fetch(`${apiBaseUrl}/api/reports/jobs`, {
          headers: { "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70" }
        });
        if (!res.ok) throw new Error("Failed to fetch jobs");
        return res.json() as Promise<any[]>;
      },
      refetchInterval: (query) => {
        const hasPending = query.state.data?.some(j => j.status === "pending");
        return hasPending ? 3000 : false;
      }
    });

    const handleExport = async (format: string) => {
      setIsExporting(format);
      setAsyncBanner(null);
      try {
        const res = await fetch(`${apiBaseUrl}/api/reports/export`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70",
          },
          body: JSON.stringify({
            report_type: reportType,
            format: format,
            date_from: dateFrom || null,
            date_to: dateTo || null,
            group_id: groupId || null,
            person_id: personId || null,
            min_absences: minAbsences,
          }),
        });

        if (!res.ok) {
          throw new Error("Export request failed");
        }

        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
          const data = await res.json();
          if (data.status === "pending") {
            setAsyncBanner({
              message: `Dataset contains ${data.row_count} rows and is being processed in the background.`,
              jobId: data.job_id
            });
            setActiveTab("jobs");
            queryClient.invalidateQueries({ queryKey: ["report-jobs"] });
          }
        } else {
          // Direct file download
          const blob = await res.blob();
          const blobUrl = window.URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = blobUrl;
          link.download = `${reportType}_export.${format}`;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          window.URL.revokeObjectURL(blobUrl);
        }
      } catch (err: any) {
        alert("Export failed: " + err.message);
      } finally {
        setIsExporting(null);
      }
    };

    const handleDownloadJob = async (jobId: string, format: string, type: string) => {
      const url = `${apiBaseUrl}/api/reports/jobs/${jobId}/download`;
      const filename = `${type}_async_export.${format}`;
      await handleDownloadFile(url, filename);
    };

    return (
      <div className="max-w-6xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500">
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight text-zinc-900">Reports & Export</h1>
          <p className="text-zinc-500 mt-1">Generate dynamic registers, sheets, and analytics exports.</p>
        </div>

        {asyncBanner && (
          <div className="mb-6 bg-cyan-50 border border-cyan-200 text-cyan-800 p-4 rounded-2xl flex items-center justify-between shadow-sm animate-in slide-in-from-top-2 duration-300">
            <div className="flex items-center gap-3">
              <span className="h-2 w-2 rounded-full bg-cyan-500 animate-ping shrink-0" />
              <div>
                <p className="text-sm font-semibold">{asyncBanner.message}</p>
                <p className="text-xs text-cyan-600 mt-0.5">Job ID: {asyncBanner.jobId}</p>
              </div>
            </div>
            <button onClick={() => setAsyncBanner(null)} className="text-cyan-600 hover:text-cyan-800 font-medium text-sm">Dismiss</button>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Filters card */}
          <div className="space-y-6">
            <div className="bg-white rounded-2xl border border-zinc-200 p-6 shadow-sm">
              <h3 className="text-base font-semibold text-zinc-900 mb-4">Report Type</h3>
              <select
                value={reportType}
                onChange={(e) => { setReportType(e.target.value); setPersonId(""); }}
                className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 py-2.5 px-3 border outline-none bg-zinc-50 font-medium text-sm text-zinc-800"
              >
                <option value="daily_register">Daily Register</option>
                <option value="timesheet">Timesheet</option>
                <option value="payroll_summary">Payroll Summary</option>
                <option value="tardiness">Tardiness Report</option>
                <option value="absence">Absence Report</option>
                <option value="truancy">Truancy Report</option>
                <option value="perfect_attendance">Perfect Attendance</option>
                <option value="headcount_by_hour">Headcount By Hour</option>
                <option value="muster_roll">Muster / Fire Roll</option>
                <option value="exception_report">Exception Report</option>
                <option value="device_health">Device Health Status</option>
              </select>

              <h3 className="text-base font-semibold text-zinc-900 mt-6 mb-4">Filters</h3>
              <div className="space-y-4">
                {reportType !== "muster_roll" && reportType !== "device_health" && (
                  <>
                    <div>
                      <label className="block text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1">Date From</label>
                      <input
                        type="date"
                        value={dateFrom}
                        onChange={(e) => setDateFrom(e.target.value)}
                        className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2 px-3 border outline-none text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1">Date To</label>
                      <input
                        type="date"
                        value={dateTo}
                        onChange={(e) => setDateTo(e.target.value)}
                        className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2 px-3 border outline-none text-sm"
                      />
                    </div>
                  </>
                )}

                {reportType !== "muster_roll" && reportType !== "device_health" && (
                  <div>
                    <label className="block text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1">Group Scope</label>
                    <select
                      value={groupId}
                      onChange={(e) => setGroupId(e.target.value)}
                      className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2 px-3 border outline-none text-sm"
                    >
                      <option value="">All Groups</option>
                      {groups?.map((g) => (
                        <option key={g.id} value={g.id}>{g.name}</option>
                      ))}
                    </select>
                  </div>
                )}

                {reportType === "timesheet" && (
                  <div>
                    <label className="block text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1">Filter Person</label>
                    <select
                      value={personId}
                      onChange={(e) => setPersonId(e.target.value)}
                      className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2 px-3 border outline-none text-sm"
                    >
                      <option value="">All People</option>
                      {people?.map((p) => (
                        <option key={p.id} value={p.id}>{p.display_name}</option>
                      ))}
                    </select>
                  </div>
                )}

                {reportType === "truancy" && (
                  <div>
                    <label className="block text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1">Min Absences Threshold</label>
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={minAbsences}
                      onChange={(e) => setMinAbsences(Number(e.target.value))}
                      className="w-full rounded-xl border-zinc-200 shadow-sm focus:border-cyan-500 focus:ring-cyan-500 bg-zinc-50 py-2 px-3 border outline-none text-sm"
                    />
                  </div>
                )}
              </div>
            </div>

            <div className="bg-white rounded-2xl border border-zinc-200 p-6 shadow-sm space-y-3">
              <h3 className="text-base font-semibold text-zinc-900 mb-2">Export Document</h3>
              
              <button
                disabled={!!isExporting}
                onClick={() => handleExport("csv")}
                className="w-full flex items-center justify-center gap-2 bg-zinc-900 hover:bg-zinc-800 text-white disabled:bg-zinc-300 py-3 rounded-xl text-sm font-semibold transition-colors shadow-sm shadow-zinc-900/10"
              >
                {isExporting === "csv" ? (
                  <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                )}
                Export CSV Format
              </button>

              <button
                disabled={!!isExporting}
                onClick={() => handleExport("xlsx")}
                className="w-full flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white disabled:bg-emerald-300 py-3 rounded-xl text-sm font-semibold transition-colors shadow-sm shadow-emerald-600/10"
              >
                {isExporting === "xlsx" ? (
                  <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                )}
                Export Excel Spreadsheet
              </button>

              <button
                disabled={!!isExporting}
                onClick={() => handleExport("pdf")}
                className="w-full flex items-center justify-center gap-2 bg-rose-600 hover:bg-rose-700 text-white disabled:bg-rose-300 py-3 rounded-xl text-sm font-semibold transition-colors shadow-sm shadow-rose-600/10"
              >
                {isExporting === "pdf" ? (
                  <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                )}
                Export PDF Document
              </button>
            </div>
          </div>

          {/* Main output panel */}
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-white rounded-2xl border border-zinc-200 overflow-hidden shadow-sm flex flex-col h-[650px]">
              <div className="flex border-b border-zinc-200 bg-zinc-50/50 p-2 shrink-0">
                <button
                  onClick={() => setActiveTab("preview")}
                  className={`flex-1 py-2.5 px-4 rounded-xl text-sm font-semibold transition-all duration-200 ${activeTab === "preview" ? "bg-white text-zinc-900 shadow-sm border border-zinc-200/50" : "text-zinc-500 hover:text-zinc-800"}`}
                >
                  Report Live Preview
                </button>
                <button
                  onClick={() => setActiveTab("jobs")}
                  className={`flex-1 py-2.5 px-4 rounded-xl text-sm font-semibold transition-all duration-200 flex items-center justify-center gap-2 ${activeTab === "jobs" ? "bg-white text-zinc-900 shadow-sm border border-zinc-200/50" : "text-zinc-500 hover:text-zinc-800"}`}
                >
                  Background Exports List
                  {jobs && jobs.some(j => j.status === "pending") && (
                    <span className="h-2 w-2 rounded-full bg-cyan-500 animate-ping" />
                  )}
                </button>
              </div>

              <div className="flex-1 overflow-auto">
                {activeTab === "preview" ? (
                  isPreviewLoading ? (
                    <div className="flex flex-col items-center justify-center h-full text-zinc-400">
                      <div className="h-8 w-8 border-4 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin mb-4" />
                      <p className="text-sm font-medium">Running query and rendering preview...</p>
                    </div>
                  ) : isPreviewError ? (
                    <div className="flex flex-col items-center justify-center h-full text-red-500">
                      <svg className="w-12 h-12 mb-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                      <p className="font-semibold">Error querying report preview data.</p>
                    </div>
                  ) : !previewData || previewData.rows.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-zinc-400">
                      <svg className="w-12 h-12 mb-4 text-zinc-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                      <p className="font-semibold">No records match filters.</p>
                    </div>
                  ) : (
                    <div className="w-full">
                      <table className="w-full border-collapse text-left text-xs text-zinc-700">
                        <thead className="bg-zinc-50 border-b border-zinc-200 sticky top-0 font-semibold text-zinc-800 uppercase tracking-wider">
                          <tr>
                            {previewData.headers.map((h: string) => (
                              <th key={h} className="px-6 py-4 border-r border-zinc-200/50">{h.replace("_", " ")}</th>
                            ))}
                            {(reportType === "daily_register" || reportType === "timesheet") && (
                              <th className="px-6 py-4 text-right">Actions</th>
                            )}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-200">
                          {previewData.rows.map((row: any, rIdx: number) => (
                            <tr key={rIdx} className="hover:bg-zinc-50 transition-colors">
                              {previewData.headers.map((h: string) => (
                                <td key={h} className="px-6 py-3.5 max-w-[200px] truncate border-r border-zinc-100/50">{formatCell(row[h], h)}</td>
                              ))}
                              {(reportType === "daily_register" || reportType === "timesheet") && (
                                <td className="px-6 py-3.5 text-right font-medium whitespace-nowrap">
                                  {row.override_id ? (
                                    <button
                                      onClick={() => handleRemoveOverride(row.override_id)}
                                      className="text-rose-600 hover:text-rose-700 mr-3"
                                    >
                                      Remove Override
                                    </button>
                                  ) : null}
                                  <button
                                    onClick={() => {
                                      setOverrideRow(row);
                                      setIsOverrideModalOpen(true);
                                    }}
                                    className="text-cyan-600 hover:text-cyan-700"
                                  >
                                    {row.override_id ? "Edit" : "Override"}
                                  </button>
                                </td>
                              )}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )
                ) : (
                  /* Background jobs list */
                  !jobs || jobs.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-zinc-400">
                      <svg className="w-12 h-12 mb-4 text-zinc-300" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M8 7v12m0 0l-4-4m4 4l4-4m0 6V4" /></svg>
                      <p className="font-semibold">No background export jobs found.</p>
                    </div>
                  ) : (
                    <div className="w-full">
                      <table className="w-full border-collapse text-left text-xs text-zinc-700">
                        <thead className="bg-zinc-50 border-b border-zinc-200 sticky top-0 font-semibold text-zinc-800 uppercase tracking-wider">
                          <tr>
                            <th className="px-6 py-4">Report Type</th>
                            <th className="px-6 py-4">Format</th>
                            <th className="px-6 py-4">Status</th>
                            <th className="px-6 py-4">Rows</th>
                            <th className="px-6 py-4">Created Date</th>
                            <th className="px-6 py-4 text-right">Actions</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-200">
                          {jobs.map((job) => (
                            <tr key={job.id} className="hover:bg-zinc-50 transition-colors">
                              <td className="px-6 py-4 font-medium text-zinc-950 capitalize">{job.report_type.replace("_", " ")}</td>
                              <td className="px-6 py-4 uppercase font-bold text-[10px] text-zinc-500">{job.format}</td>
                              <td className="px-6 py-4">
                                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold tracking-wider capitalize
                                  ${job.status === "completed" ? "bg-emerald-100 text-emerald-800" : ""}
                                  ${job.status === "pending" ? "bg-cyan-100 text-cyan-800 animate-pulse" : ""}
                                  ${job.status === "failed" ? "bg-rose-100 text-rose-800" : ""}
                                `}>
                                  {job.status}
                                </span>
                              </td>
                              <td className="px-6 py-4 font-medium font-mono">{job.row_count !== null ? job.row_count.toLocaleString() : "—"}</td>
                              <td className="px-6 py-4 text-zinc-500">{new Date(job.created_at).toLocaleString()}</td>
                              <td className="px-6 py-4 text-right">
                                {job.status === "completed" && (
                                  <button
                                    onClick={() => handleDownloadJob(job.id, job.format, job.report_type)}
                                    className="bg-cyan-600 hover:bg-cyan-700 text-white font-semibold py-1.5 px-3 rounded-lg text-xs tracking-wider uppercase transition-colors"
                                  >
                                    Download
                                  </button>
                                )}
                                {job.status === "pending" && (
                                  <div className="inline-flex h-5 w-5 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
                                )}
                                {job.status === "failed" && (
                                  <span className="text-red-500 font-medium text-xs max-w-[120px] truncate block ml-auto" title={job.error_message || "Unknown error"}>
                                    {job.error_message || "Failed"}
                                  </span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )
                )}
              </div>
            </div>
          </div>
        </div>
        <OverrideModal
          key={overrideRow?.id || 'new'}
          isOpen={isOverrideModalOpen}
          onClose={() => setIsOverrideModalOpen(false)}
          onSuccess={() => {
            setIsOverrideModalOpen(false);
            queryClient.invalidateQueries({ queryKey: ["report-preview"] });
          }}
          row={overrideRow}
        />
      </div>
    );
  }
});

const musterRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/muster",
  component: function MusterRoll() {
    const { data, isLoading, isError } = useQuery({
      queryKey: ["muster-roll-preview"],
      queryFn: async () => {
        const res = await fetch(`${apiBaseUrl}/api/reports/preview?report_type=muster_roll`, {
          headers: { "x-admin-id": "14d75b41-d558-4a73-9369-93f32ef86a70" }
        });
        if (!res.ok) throw new Error("Failed to fetch muster roll");
        const json = await res.json();
        // Save to cache
        localStorage.setItem("aegis_cached_muster", JSON.stringify(json));
        localStorage.setItem("aegis_cached_muster_time", String(Date.now()));
        return json;
      },
      retry: 1,
    });

    // Determine state
    let displayRows: any[] = [];
    let isCached = false;
    let cacheAgeStr = "";

    if (data) {
      displayRows = data.rows || [];
    } else {
      // Try to fallback to localStorage
      const cachedStr = localStorage.getItem("aegis_cached_muster");
      const cachedTimeStr = localStorage.getItem("aegis_cached_muster_time");
      if (cachedStr) {
        try {
          const cachedJson = JSON.parse(cachedStr);
          displayRows = cachedJson.rows || [];
          isCached = true;
          if (cachedTimeStr) {
            const ms = Date.now() - Number(cachedTimeStr);
            const mins = Math.floor(ms / 60000);
            if (mins < 1) {
              cacheAgeStr = "Just now";
            } else if (mins < 60) {
              cacheAgeStr = `${mins}m ago`;
            } else {
              const hrs = Math.floor(mins / 60);
              cacheAgeStr = `${hrs}h ago`;
            }
          }
        } catch (_) {
          // ignore
        }
      }
    }

    return (
      <div className="space-y-6 print-container w-full">
        <style dangerouslySetInnerHTML={{ __html: `
          @media print {
            .no-print { display: none !important; }
            body { background: white; color: black; font-family: sans-serif; }
            .print-container { width: 100% !important; max-width: 100% !important; padding: 0 !important; margin: 0 !important; border: none !important; box-shadow: none !important; }
            table { border-collapse: collapse; width: 100%; margin-top: 15px; }
            th, td { border: 1px solid #000 !important; padding: 6px !important; font-size: 11px !important; text-align: left; }
            h1, h2 { color: black !important; }
          }
        `}} />

        <div className="flex items-center justify-between no-print">
          <div className="flex items-center gap-3">
            <span className="flex h-3 w-3 relative">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${isCached ? "bg-amber-400" : "bg-emerald-400"}`}></span>
              <span className={`relative inline-flex rounded-full h-3 w-3 ${isCached ? "bg-amber-500" : "bg-emerald-500"}`}></span>
            </span>
            <h1 className="text-2xl font-bold text-zinc-900 tracking-tight">Emergency Muster / Fire Roll</h1>
          </div>
          <button
            onClick={() => window.print()}
            className="flex items-center gap-2 bg-rose-600 hover:bg-rose-700 text-white font-semibold py-2.5 px-5 rounded-xl text-sm transition-all duration-200 shadow-lg shadow-rose-600/10 active:scale-95"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" /></svg>
            Print Roster
          </button>
        </div>

        <div className={`p-4 rounded-2xl border flex items-center justify-between ${
          isCached 
            ? "bg-amber-50 border-amber-200 text-amber-800" 
            : "bg-emerald-50 border-emerald-200 text-emerald-800"
        }`}>
          <div className="flex items-center gap-3">
            {isCached ? (
              <svg className="w-6 h-6 text-amber-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
            ) : (
              <svg className="w-6 h-6 text-emerald-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            )}
            <div>
              <p className="font-bold text-sm">
                {isCached ? "API UNREACHABLE - Showing Cached Roster" : "Live Evacuation Roster"}
              </p>
              <p className="text-xs opacity-90">
                {isCached 
                  ? `Showing the last successfully retrieved copy from ${cacheAgeStr}`
                  : "Roster matches real-time server records."}
              </p>
            </div>
          </div>
          <div className="text-right shrink-0">
            <span className="text-2xl font-black">{displayRows.length}</span>
            <span className="text-xs uppercase font-bold tracking-wider block opacity-75">Present Inside</span>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-zinc-200 overflow-hidden shadow-sm">
          <table className="w-full border-collapse text-left text-xs text-zinc-700">
            <thead className="bg-zinc-50 border-b border-zinc-200 sticky top-0 font-semibold text-zinc-800 uppercase tracking-wider no-print">
              <tr>
                <th className="px-6 py-4">Name</th>
                <th className="px-6 py-4">External ID</th>
                <th className="px-6 py-4">Group</th>
                <th className="px-6 py-4">Location</th>
                <th className="px-6 py-4">Device</th>
                <th className="px-6 py-4">Checked In At</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200">
              {displayRows.map((row: any, idx: number) => (
                <tr key={idx} className="hover:bg-zinc-50 transition-colors">
                  <td className="px-6 py-3.5 font-semibold text-zinc-950">{row.name}</td>
                  <td className="px-6 py-3.5 font-mono">{row.external_id || "—"}</td>
                  <td className="px-6 py-3.5">{row.group_name || "—"}</td>
                  <td className="px-6 py-3.5">{row.location_name || "—"}</td>
                  <td className="px-6 py-3.5 font-mono">{row.device_name || "—"}</td>
                  <td className="px-6 py-3.5 font-mono">
                    {row.checked_in_at ? new Date(row.checked_in_at).toLocaleTimeString() : "—"}
                  </td>
                </tr>
              ))}
              {displayRows.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center py-10 text-zinc-400 font-medium text-sm">
                    No individuals are currently marked as present inside.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    );
  }
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  peopleRoute,
  devicesRoute,
  reportsRoute,
  settingsRoute,
  musterRoute,
]);

const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
