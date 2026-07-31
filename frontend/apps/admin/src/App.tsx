import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router";

import { apiBaseUrl } from "@attendance/api-client";
import type { ErrorCode } from "@attendance/protocol";

const queryClient = new QueryClient();

const adminRoute = createRootRoute({
  component: AdminHome,
});

const router = createRouter({ routeTree: adminRoute });

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

function AdminHome() {
  const importantError: ErrorCode = "DEVICE_REVOKED";

  return (
    <main className="min-h-screen bg-zinc-100 text-zinc-950">
      <section className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center gap-8 px-8">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.3em] text-blue-700">
            Admin console
          </p>
          <h1 className="mt-4 text-5xl font-semibold tracking-tight">
            Manage attendance operations
          </h1>
          <p className="mt-5 max-w-2xl text-lg text-zinc-600">
            This is the separate admin bundle shell for authenticated dashboards, enrollment,
            devices, settings, and reports.
          </p>
        </div>
        <div className="grid gap-4 rounded-3xl border border-zinc-200 bg-white p-6 shadow-sm md:grid-cols-2">
          <div>
            <h2 className="text-sm font-medium text-zinc-500">API base</h2>
            <p className="mt-2 font-mono text-sm">{apiBaseUrl}</p>
          </div>
          <div>
            <h2 className="text-sm font-medium text-zinc-500">Admin-only route marker</h2>
            <p className="mt-2 font-mono text-sm">{importantError}</p>
          </div>
        </div>
      </section>
    </main>
  );
}
