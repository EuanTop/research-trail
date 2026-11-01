import type { Edge, Node } from "@xyflow/react";
import { t, intlLocale } from "./i18n";
import { getNodeUsage } from "./usage";
import { facingSides } from "./edge-routing";
import { estimateCardHeight } from "./card-sizing";
import {
  isNodeProcessing,
  nodePresentation,
  type NodePresentation,
} from "./node-presentation";
export type NodeTab = "overview" | "runs" | "evidence" | "usage";
export type JsonValue =
  null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type Metrics = Record<string, JsonValue>;

export type QuestionOrigin = {
  type: string;
  nodeIds?: string[];
  artifactIds?: string[];
  url?: string;
  reason?: string;
  retrospective?: boolean;
  recordedAt?: string;
  [key: string]: unknown;
};
export type ResearchNode = {
  id: string;
  title: string;
  kind: string;
  status: string;
  questionOrigin?: QuestionOrigin;
  importance?: "normal" | "critical";
  importanceReason?: string;
  pauseReason?: string;
  resumeWhen?: string;
  parentId: string | null;
  summary: string;
  conclusion?: string;
  notes: string;
  nextAction: string;
  tags: string[];
  position: { x: number; y: number };
  collapsed: boolean;
  isContainer?: boolean;
  createdAt?: string;
  updatedAt?: string;
  [key: string]: unknown;
};
export type ResearchEdge = {
  id: string;
  source: string;
  target: string;
  relation: string;
  label?: string;
  basis?: string;
  runIds?: string[];
};
export type Run = {
  id: string;
  nodeId: string;
  title: string;
  status: string;
  configuration: Record<string, unknown>;
  metrics: Metrics;
  startedAt: string | null;
  finishedAt?: string | null;
  capturedAt?: string;
  durationMs?: number | null;
  events: { id: string; type: string; message: string; at: string }[];
  artifactIds: string[];
  origin: string;
};
export type Artifact = {
  id: string;
  title: string;
  path: string;
  sha256: string;
  bytes: number;
  mime: string;
  nodeId?: string;
  runId?: string;
  origin: string;
};
export const isExecutionRun = (run: Run) =>
  run.configuration?.capturedExternalResult !== true;
export type Assessment = {
  id: string;
  runId: string;
  rubric: string;
  metrics: Metrics;
  conclusion: string;
  limitations: string;
  supersedes?: string;
  artifactIds?: string[];
  createdAt?: string;
};
export type Decision = {
  id: string;
  nodeId: string;
  title: string;
  conclusion: string;
  scope: string;
  nextAction: string;
  runIds: string[];
  artifactIds: string[];
};
export type Observation = {
  id: string;
  nodeId: string;
  title: string;
  status: "running" | "finished";
  startedAt: string;
  finishedAt: string | null;
  durationMs: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  usageSource: string;
  usageRef?: string;
  origin: string;
};
export type HostUsageRecord = {
  id: string;
  nodeId: string | null;
  source: string;
  sourceRef: string;
  agentId?: string;
  provider: string;
  model: string;
  inputTokens: number | null;
  outputTokens: number | null;
  cacheReadTokens: number | null;
  cacheWriteTokens: number | null;
  startedAt: string | null;
  finishedAt: string | null;
  scope?: "agent" | "execution";
  timestampScope?: "inference" | "execution";
  attribution?: string;
};
export type Project = {
  id: string;
  name: string;
  description: string;
  revision: number;
  createdAt: string;
  updatedAt: string;
  nodes: ResearchNode[];
  edges: ResearchEdge[];
  runs: Run[];
  artifacts: Artifact[];
  assessments: Assessment[];
  decisions: Decision[];
  nodeAliases?: Record<string, string>;
  observations?: Observation[];
  usageRecords?: HostUsageRecord[];
  runtimeActivity?: { id: string; nodeId: string; source: string }[];
  activity: {
    id: string;
    at: string;
    message?: string;
    type?: string;
    operations?: { op: string; data?: Record<string, unknown> }[];
  }[];
};
export type ProjectSummary = Pick<
  Project,
  "id" | "name" | "description" | "revision" | "updatedAt"
> & { nodeCount: number };
export type Operation = { op: string; data: Record<string, unknown> };
export const uid = (prefix = "n") =>
  `${prefix}-${crypto.randomUUID().slice(0, 12)}`;
export const statuses: Record<string, string> = {
  proposed: "未开始",
  active: "开放中",
  completed: "已完成",
  paused: "已暂停",
  rejected: "已排除",
  running: "运行中",
  failed: "运行错误",
  invalid: "无效",
};
export const kinds: Record<string, string> = {
  goal: "研究目标",
  question: "问题",
  hypothesis: "假设",
  experiment: "实验",
  algorithm: "算法",
  finding: "发现",
  correction: "纠正",
  direction: "方向调整",
  decision: "决策",
  group: "容器",
  reference: "资料",
  plan: "计划",
};
export const relations: Record<string, string> = {
  branches: "分支",
  supports: "支持",
  refutes: "反驳",
  tests: "验证",
  revises: "修订",
  revisits: "回访",
  leads_to: "引出",
  uses: "复用",
  motivates: "触发",
  compares: "对比",
  has_finding: "发现",
  summarizes: "汇总",
  has_correction: "纠正",
  has_direction: "方向调整",
  related_to: "关联",
  collapsed_path: "折叠路径",
  recorded_after: "后续记录",
};
export function descendants(nodes: ResearchNode[], id: string): string[] {
  const result: string[] = [];
  const visit = (p: string) => {
    for (const n of nodes.filter((n) => n.parentId === p)) {
      if (!result.includes(n.id)) {
        result.push(n.id);
        visit(n.id);
      }
    }
  };
  visit(id);
  return result;
}
export function ancestry(
  nodes: ResearchNode[],
  id: string | null,
): ResearchNode[] {
  const result: ResearchNode[] = [];
  const visited = new Set<string>();
  let current = nodes.find((n) => n.id === id);
  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    result.unshift(current);
    current = nodes.find((n) => n.id === current!.parentId);
  }
  return result;
}
export type CanvasData = {
  node: ResearchNode;
  presentation: NodePresentation;
  processing?: boolean;
  children: number;
  runs: number;
  latest?: Run;
  expanded: boolean;
  usage?: import("./usage").NodeUsage;
  onInspect?: (id: string, tab: NodeTab) => void;
  onToggle: (id: string) => void;
  onEnter: (id: string) => void;
  [key: string]: unknown;
};
export const NODE_SIZE = { w: 368, h: 230 };
export function isVisualContainer(node: ResearchNode): boolean {
  return node.isContainer ?? node.kind === "group";
}

export function visualParent(
  nodes: ResearchNode[],
  node: ResearchNode,
): ResearchNode | undefined {
  const seen = new Set<string>();
  let id = node.parentId;
  while (id && !seen.has(id)) {
    seen.add(id);
    const parent = nodes.find((candidate) => candidate.id === id);
    if (!parent) return;
    if (isVisualContainer(parent)) return parent;
    id = parent.parentId;
  }
}

/** Parentage is ownership; every parent with children is a navigable container.
 * Explicit empty containers are useful while a branch is still being opened. */
export function isResearchContainer(
  nodes: ResearchNode[],
  node: ResearchNode,
): boolean {
  return (
    isVisualContainer(node) || nodes.some((child) => child.parentId === node.id)
  );
}

export function boundaryRelations(
  project: Project,
  scope: string,
): ResearchEdge[] {
  const members = new Set(descendants(project.nodes, scope));
  const inside = new Set([scope, ...members]);
  return project.edges.filter(
    (edge) =>
      inside.has(edge.source) !== inside.has(edge.target) ||
      (edge.source === scope && members.has(edge.target)) ||
      (edge.target === scope && members.has(edge.source)),
  );
}

export function toCanvas(
  project: Project,
  scope: string | null,
  selected: string[],
  actions: {
    onToggle: (id: string) => void;
    onEnter: (id: string) => void;
    onInspect?: (id: string, tab: NodeTab) => void;
  },
  view: { expandedIds?: ReadonlySet<string> } = {},
): { nodes: Node<CanvasData>[]; edges: Edge[] } {
  // Expansion is view state, independent of scientific records and other readers.
  const original = project;
  project = {
    ...project,
    nodes: project.nodes.map((node) => ({
      ...node,
      isContainer: isResearchContainer(project.nodes, node),
      collapsed: !view.expandedIds?.has(node.id),
    })),
  };
  const byId = new Map(project.nodes.map((n) => [n.id, n]));
  const within = new Set(
    scope ? descendants(project.nodes, scope) : project.nodes.map((n) => n.id),
  );
  const hidden = new Set<string>();
  for (const n of project.nodes)
    if (within.has(n.id) && isVisualContainer(n) && n.collapsed)
      for (const id of descendants(project.nodes, n.id)) hidden.add(id);
  const visible = project.nodes.filter(
    (n) => within.has(n.id) && !hidden.has(n.id),
  );
  const visibleIds = new Set(visible.map((n) => n.id));
  const dimensions = new Map<string, { w: number; h: number }>();
  function size(n: ResearchNode): { w: number; h: number } {
    if (dimensions.has(n.id)) return dimensions.get(n.id)!;
    const children = visible.filter(
      (c) => visualParent(project.nodes, c)?.id === n.id,
    );
    let w = NODE_SIZE.w;
    let h =
      estimateCardHeight(nodePresentation(project, n), w) +
      (n.kind === "question" ? 22 : 0);
    if (isVisualContainer(n) && children.length && !n.collapsed) {
      w = Math.max(
        330,
        ...children.map((c) => c.position.x - n.position.x + size(c).w + 28),
      );
      h = Math.max(
        230,
        ...children.map((c) => c.position.y - n.position.y + size(c).h + 28),
      );
    }
    const s = { w, h };
    dimensions.set(n.id, s);
    return s;
  }
  const result = visible
    .sort(
      (a, b) =>
        ancestry(project.nodes, a.id).length -
        ancestry(project.nodes, b.id).length,
    )
    .map((n) => {
      const children = project.nodes.filter((c) => c.parentId === n.id);
      const ancestor = visualParent(project.nodes, n);
      const parent =
        ancestor && visibleIds.has(ancestor.id) ? ancestor : undefined;
      const container = isVisualContainer(n);
      const runs = project.runs.filter(
        (r) => r.nodeId === n.id && isExecutionRun(r),
      );
      const d = size(n);
      const memberIds = new Set([n.id, ...descendants(project.nodes, n.id)]);
      return {
        id: n.id,
        type: "research",
        position: {
          x: n.position.x - (parent?.position.x || 0),
          y: n.position.y - (parent?.position.y || 0),
        },
        parentId: parent?.id,
        selected: selected.includes(n.id),
        dragHandle: ".node-grip",
        style: { width: d.w, height: d.h },
        zIndex: container && children.length && !n.collapsed ? 0 : 2,
        data: {
          node: original.nodes.find((node) => node.id === n.id)!,
          presentation: nodePresentation(project, n),
          processing: project.nodes.some(
            (member) =>
              memberIds.has(member.id) && isNodeProcessing(project, member),
          ),
          children: children.length,
          container,
          runs: runs.length,
          latest: project.runs.filter((run) => run.nodeId === n.id).at(-1),
          usage: getNodeUsage(project, n.id),
          expanded: container && !!children.length && !n.collapsed,
          ...actions,
        },
      } as Node<CanvasData>;
    });
  function resolve(id: string): string | undefined {
    const seen = new Set<string>();
    while (!visibleIds.has(id)) {
      if (seen.has(id)) return;
      seen.add(id);
      const n = byId.get(id);
      if (!n?.parentId || n.parentId === scope) return;
      id = n.parentId;
    }
    return id;
  }
  // Collapse endpoints to their visible owner. Group parallel boundary links,
  // retaining EVERY original relation for inspection rather than losing duplicates.
  const groups = new Map<
    string,
    { source: string; target: string; originals: ResearchEdge[] }
  >();
  const resolved = project.edges.flatMap((edge) => {
    const source = resolve(edge.source),
      target = resolve(edge.target);
    if (!source || !target || source === target) return [];
    const boundary = source !== edge.source || target !== edge.target;
    if (boundary && edge.relation === "recorded_after") return [];
    return [{ edge, source, target, boundary }];
  });
  const boundaryPairs = new Set(
    resolved
      .filter((item) => item.boundary)
      .map(({ source, target }) => JSON.stringify([source, target])),
  );
  for (const { edge, source, target } of resolved) {
    const pair = JSON.stringify([source, target]);
    const key = boundaryPairs.has(pair) ? pair : edge.id;
    const group = groups.get(key) || { source, target, originals: [] };
    group.originals.push(edge);
    groups.set(key, group);
  }
  const edges: Edge[] = [];
  for (const { source, target, originals } of groups.values()) {
    const e = originals[0];
    const boundary = originals.some(
      (edge) => edge.source !== source || edge.target !== target,
    );
    const mixed = new Set(originals.map((edge) => edge.relation)).size > 1;
    const basis =
      new Set(originals.map((edge) => edge.basis || "unknown")).size === 1
        ? e.basis
        : "unknown";
    const sourceNode = byId.get(source)!,
      targetNode = byId.get(target)!;
    const sourceSize = dimensions.get(source)!,
      targetSize = dimensions.get(target)!;
    const [sourceHandle, targetHandle] = facingSides(
      { ...sourceNode.position, width: sourceSize.w, height: sourceSize.h },
      { ...targetNode.position, width: targetSize.w, height: targetSize.h },
    );
    edges.push({
      id: boundary ? `boundary:${e.id}` : e.id,
      source,
      target,
      type: "research",
      sourceHandle,
      targetHandle,
      label: mixed
        ? t("关联 · {count}", { count: originals.length })
        : e.relation === "recorded_after"
          ? ""
          : e.relation === "has_direction"
            ? t(relations[e.relation])
            : (e.label ||
                (relations[e.relation]
                  ? t(relations[e.relation])
                  : e.relation)) +
              (originals.length > 1 ? ` · ${originals.length}` : ""),
      style: {
        stroke: basis === "hypothesis" ? "#94a3b8" : "#71717a",
        strokeWidth: e.relation === "recorded_after" ? 1 : 1.4,
        opacity: e.relation === "recorded_after" ? 0.35 : 1,
        strokeDasharray:
          e.relation === "recorded_after"
            ? "3 6"
            : basis === "hypothesis" || e.relation === "collapsed_path"
              ? "5 5"
              : undefined,
      },
      labelStyle: { fill: "var(--muted)", fontSize: 10, fontWeight: 500 },
      labelBgStyle: { fill: "var(--panel)", fillOpacity: 0.95 },
      labelBgPadding: [8, 5],
      labelBgBorderRadius: 5,
      markerEnd: {
        type: "arrowclosed" as any,
        width: 12,
        height: 12,
        color: "#71717a",
      },
      data: {
        original: e,
        layoutRelation: mixed ? "related_to" : e.relation,
        originals,
        boundary,
        orderOnly: e.relation === "recorded_after",
        active:
          result.find((node) => node.id === source)?.data.processing ||
          result.find((node) => node.id === target)?.data.processing,
      },
    });
  }
  const pairs = new Map<string, Edge[]>();
  for (const edge of edges) {
    const key = JSON.stringify([edge.source, edge.target].sort());
    pairs.set(key, [...(pairs.get(key) ?? []), edge]);
  }
  for (const pair of pairs.values()) {
    const reciprocal = pair.some((edge) => edge.source !== pair[0].source);
    for (const direction of new Set(pair.map((edge) => edge.source))) {
      const sameDirection = pair
        .filter((edge) => edge.source === direction)
        .sort((a, b) => a.id.localeCompare(b.id));
      sameDirection.forEach((edge, index) => {
        edge.data = {
          ...edge.data,
          lane: reciprocal
            ? (edge.source < edge.target ? -1 : 1) * (18 + index * 14)
            : (index - (sameDirection.length - 1) / 2) * 18,
        };
      });
    }
  }
  return { nodes: result, edges };
}
export function effectiveAssessments(project: Project): Assessment[] {
  const replaced = new Set(
    project.assessments.map((a) => a.supersedes).filter(Boolean),
  );
  return project.assessments.filter((a) => !replaced.has(a.id));
}
export function metricLabel(key: string): string {
  const label = (
    {
      latency_ms: "延迟 · ms",
      p50_ms: "P50 · ms",
      p95_ms: "P95 · ms",
      recall_at_5: "Recall@5",
      quality: "质量",
      total_seconds: "总耗时 · s",
      accuracy: "准确率",
      mean_ms: "平均耗时 · ms",
      build_ms: "构建 · ms",
      consistent: "结果一致",
      speedup: "加速比",
      query_ms: "查询 · ms",
      memory_bytes: "内存 · bytes",
      wallTimeMs: "执行耗时 · ms",
      exitCode: "退出码",
      buildMedianMs: "构建中位数 · ms",
      warmBatchMedianMs: "查询批次中位数 · ms",
      warmMeanQueryMs: "平均查询耗时 · ms",
      updateMs: "更新耗时 · ms",
      initialConsistent: "初始输出一致",
      updatedConsistent: "更新后输出一致",
    } as Record<string, string>
  )[key];
  return typeof label === "string" ? t(label) : key;
}
export function formatMetric(v: unknown): string {
  if (v === undefined) return "—";
  if (v === null) return "null";
  if (typeof v === "boolean") return t(v ? "是" : "否");
  if (typeof v === "number")
    return Number.isInteger(v)
      ? String(v)
      : v.toLocaleString(intlLocale(), { maximumSignificantDigits: 8 });
  if (typeof v === "object") return JSON.stringify(v);
  if (v === "") return '""';
  return String(v);
}
export function validateProject(p: Project): string[] {
  const errors: string[] = [];
  const ids = new Set(p.nodes.map((n) => n.id));
  for (const n of p.nodes) {
    if (n.parentId && !ids.has(n.parentId))
      errors.push(t("缺少容器：{id}", { id: n.id }));
    let id: string | null = n.parentId;
    const seen = new Set([n.id]);
    while (id) {
      if (seen.has(id)) {
        errors.push(t("循环嵌套：{id}", { id: n.id }));
        break;
      }
      seen.add(id);
      id = p.nodes.find((a) => a.id === id)?.parentId || null;
    }
  }
  for (const e of p.edges)
    if (!ids.has(e.source) || !ids.has(e.target))
      errors.push(t("关系端点不存在：{id}", { id: e.id }));
  return errors;
}
