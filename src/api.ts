import type { Artifact, Operation, Project, ProjectSummary } from "./model";
import { t } from "./i18n";
export type AgentSetup = {
  skillPath: string;
  clientPath: string;
  pythonPath: string;
  shell: "powershell" | "posix";
  url: string;
};
export type ResearchWorkspace = { id: string; path: string; addedAt: string };
export type RuntimeSnapshot = {
  projectId: string;
  checkedAt: string;
  active: NonNullable<Project["runtimeActivity"]>;
};
export type FocusSession = {
  leaseId: string;
  ownerId: string;
  label: string;
  nodeIds: string[];
  startedAt: string;
  lastSeenAt: string;
  expiresAt: string;
  state: "active" | "stale" | "ended";
  revision: number;
};
export type FocusSnapshot = {
  projectId: string;
  checkedAt: string;
  sessions: FocusSession[];
};
export type UsageCollection = {
  projectId: string;
  available?: boolean;
  adapters: {
    source: string;
    state: string;
    eligibleCaptures: number;
    candidateLogs: number;
    readableLogs: number;
    nativeUsageRecords: number;
    matchedReceipts: number;
    collectedRecords: number;
    unassignedRecords: number;
    message?: string;
  }[];
};
export type DeliveryItem = {
  taskId: string;
  requestId?: string;
  nodeId?: string;
  title: string;
  state: "pending" | "blocked" | "interrupted";
  attempts: number;
  lastAttemptAt?: string | null;
  nextAttemptAt?: string | null;
  retryable?: boolean;
  waitingFor?: { taskId: string; nodeId: string; title: string }[];
  lastError: { code: string; message: string } | null;
};
export type DeliverySnapshot = {
  projectId: string;
  available: boolean;
  checkedAt: string;
  state: "synced" | "pending" | "blocked" | "unknown";
  scope: "connected-workspaces";
  pendingCount: number;
  blockedCount: number;
  interruptedCount: number;
  syncedCount: number;
  discoveryComplete?: boolean;
  items: DeliveryItem[];
};
type WorkspaceList = { workspaces: ResearchWorkspace[] };
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!r.ok) {
    let m;
    try {
      m = (await r.json()).error;
    } catch {
      m = r.statusText;
    }
    throw new ApiError(m || t("请求失败"), r.status);
  }
  return r.json();
}
export const api = {
  workspaces: () => request<WorkspaceList>("/api/workspaces"),
  addWorkspace: (path: string) =>
    request<WorkspaceList>("/api/workspaces", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  removeWorkspace: (id: string) =>
    request<WorkspaceList>("/api/workspaces/remove", {
      method: "POST",
      body: JSON.stringify({ id }),
    }),
  agentSetup: () => request<AgentSetup>("/api/agent-setup"),
  list: () => request<{ projects: ProjectSummary[] }>("/api/projects"),
  project: (id: string) =>
    request<Project>(`/api/projects/${encodeURIComponent(id)}`),
  deliveryStatus: (id: string, signal?: AbortSignal) =>
    request<DeliverySnapshot>(
      `/api/projects/${encodeURIComponent(id)}/delivery-status`,
      { signal },
    ),
  retryDelivery: (id: string, taskId?: string, signal?: AbortSignal) =>
    request<DeliverySnapshot>(
      `/api/projects/${encodeURIComponent(id)}/delivery/retry`,
      {
        method: "POST",
        body: JSON.stringify(taskId ? { taskId } : {}),
        signal,
      },
    ),
  usageStatus: (id: string) =>
    request<UsageCollection>(
      `/api/projects/${encodeURIComponent(id)}/usage-status`,
    ),
  focus: (id: string, signal?: AbortSignal) =>
    request<FocusSnapshot>(`/api/projects/${encodeURIComponent(id)}/focus`, {
      signal,
    }),
  runtime: (id: string) =>
    request<RuntimeSnapshot>(`/api/projects/${encodeURIComponent(id)}/runtime`),
  create: (name: string) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  batch: (project: Project, operations: Operation[]) =>
    request<Project>(`/api/projects/${encodeURIComponent(project.id)}/batch`, {
      method: "POST",
      body: JSON.stringify({
        expectedRevision: project.revision,
        requestId: crypto.randomUUID(),
        operations,
      }),
    }),
  import: (p: unknown) =>
    request<Project>("/api/import", {
      method: "POST",
      body: JSON.stringify(p),
    }),
  artifact: (id: string, data: Record<string, unknown>) =>
    request<Artifact>(`/api/projects/${encodeURIComponent(id)}/artifacts`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  history: (id: string) =>
    request<any>(`/api/projects/${encodeURIComponent(id)}/history`),
  restore: (p: Project, revision: number) =>
    request<Project>(`/api/projects/${encodeURIComponent(p.id)}/restore`, {
      method: "POST",
      body: JSON.stringify({ expectedRevision: p.revision, revision }),
    }),
};
