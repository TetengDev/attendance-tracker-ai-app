export const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ??
  (typeof window !== "undefined"
    ? `http://${window.location.hostname || "127.0.0.1"}:8001`
    : "http://127.0.0.1:8001");

export interface ApiClientOptions {
  baseUrl?: string;
  fetcher?: typeof fetch;
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = options.baseUrl ?? apiBaseUrl;
  const fetcher = options.fetcher ?? fetch;

  return {
    async health(): Promise<{ status: string }> {
      const response = await fetcher(new URL("/health", baseUrl));
      if (!response.ok) {
        throw new Error(`Health check failed with HTTP ${response.status}`);
      }
      return response.json() as Promise<{ status: string }>;
    },
  };
}
