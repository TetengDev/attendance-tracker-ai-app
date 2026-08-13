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
    { to: "/settings", label: "Settings", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" },
  ];

  return (
    <div className="w-64 bg-zinc-950 text-white flex flex-col h-screen border-r border-zinc-800">
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
            className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 text-zinc-400 hover:text-white hover:bg-white/5 active:bg-white/10"
            activeProps={{ className: "bg-cyan-500/10 text-cyan-400 font-semibold" }}
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
        <header className="h-16 bg-white border-b border-zinc-200 flex items-center justify-between px-8 shrink-0">
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
                <option value="employee">Employee</option>
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

const peopleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/people",
  component: function People() {
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [capturePerson, setCapturePerson] = useState<any>(null);
    
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
                      <button onClick={() => setCapturePerson(p)} className="text-cyan-600 hover:text-cyan-700 font-medium text-sm flex items-center gap-1 justify-end ml-auto">
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                        </svg>
                        Capture Face
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

    return (
      <div className="max-w-6xl mx-auto animate-in fade-in slide-in-from-bottom-4 duration-500">
        <DeviceRegistrationModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} onSuccess={() => { setIsModalOpen(false); refetch(); }} />
        
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
                    <td className="px-6 py-4 text-right">
                      {d.token_display_prefix === 'unpaired' && (
                        <button className="text-cyan-600 hover:text-cyan-700 font-medium text-sm">
                          Show Code
                        </button>
                      )}
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
      grouped[s.category].push(s);
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
                      <span className="text-xs font-medium text-zinc-400 bg-zinc-100 px-2 py-0.5 rounded-full">{grouped[cat].length}</span>
                      <svg className={`w-5 h-5 text-zinc-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                  </button>
                  {isExpanded && (
                    <div className="px-6 pb-5 border-t border-zinc-100">
                      <div className="divide-y divide-zinc-100">
                        {grouped[cat].map((s: any) => <SettingControl key={s.key} setting={s} />)}
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

const routeTree = rootRoute.addChildren([
  indexRoute,
  peopleRoute,
  devicesRoute,
  settingsRoute,
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
