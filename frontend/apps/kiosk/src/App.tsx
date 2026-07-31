import { createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router";

import { apiBaseUrl } from "@attendance/api-client";
import type { ServerMessage } from "@attendance/protocol";

const kioskRoute = createRootRoute({
  component: KioskHome,
});

const router = createRouter({ routeTree: kioskRoute });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export function App() {
  return <RouterProvider router={router} />;
}

function KioskHome() {
  const readyMessage: ServerMessage = {
    type: "ready",
    gallery_version: 0,
    settings_version: 0,
  };

  return (
    <main className="min-h-screen bg-slate-950 text-white">
      <section className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-6 px-6 text-center">
        <p className="rounded-full border border-cyan-300/30 px-4 py-1 text-sm uppercase tracking-[0.35em] text-cyan-200">
          Kiosk
        </p>
        <h1 className="text-5xl font-semibold tracking-tight">Ready for attendance scans</h1>
        <p className="max-w-xl text-lg text-slate-300">
          This bundle is the lean wall-kiosk shell. It imports only shared protocol/client
          primitives and deliberately contains no admin routes.
        </p>
        <dl className="grid gap-3 rounded-2xl border border-white/10 bg-white/5 p-5 text-left text-sm text-slate-200">
          <div>
            <dt className="font-medium text-slate-400">API base</dt>
            <dd>{apiBaseUrl}</dd>
          </div>
          <div>
            <dt className="font-medium text-slate-400">Protocol state</dt>
            <dd>{readyMessage.type}</dd>
          </div>
        </dl>
      </section>
    </main>
  );
}
