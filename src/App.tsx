import {
  Background,
  BackgroundVariant,
  ConnectionMode,
  MiniMap,
  ReactFlow,
  SelectionMode,
  useEdgesState,
  useNodesState,
  useReactFlow,
  useStore,
  type Connection,
  type Edge,
  type Node,
} from "@xyflow/react";
import {
  Activity,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  Files,
  FlaskConical,
  FolderOpen,
  FolderPlus,
  History,
  Layers,
  LayoutGrid,
  Languages,
  Maximize2,
  Moon,
  MoreHorizontal,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Sun,
  Terminal,
  Upload,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { t, useLocale } from "./i18n";
import { api, ApiError, type AgentSetup, type RuntimeSnapshot } from "./api";
import { nodeReference } from "./node-reference";
import { BoundaryInspector } from "./components/BoundaryInspector";
import {
  ancestry,
  boundaryRelations,
  isResearchContainer,
  descendants,
  kinds,
  isExecutionRun,
  toCanvas,
  uid,
  type Artifact,
  type CanvasData,
  type NodeTab,
  type Operation,
  type Project,
  type ProjectSummary,
} from "./model";

import {
  ArtifactDialog,
  CreateDialog,
  SkillPanel,
  type DialogState,
} from "./components/Dialogs";
import {
  EdgeInspector,
  NodeInspector,
  ProjectInspector,
} from "./components/Inspectors";
import { OutlineTree } from "./components/OutlineTree";
import { date, IconButton, time } from "./components/Primitives";
import { ResearchCard } from "./components/ResearchCard";
import { CurrentWork } from "./components/CurrentWork";
import { initialResearchScope, nodeNavigation } from "./current-work";
import { DeliveryStatus } from "./components/DeliveryStatus";
import { ResearchEdge } from "./components/ResearchEdge";
import { layoutCanvas } from "./graph-layout";
import { CompareView, EvidenceView, RunsView } from "./components/Views";
const nodeTypes = { research: ResearchCard };
const edgeTypes = { research: ResearchEdge };
type View = "graph" | "runs" | "compare" | "evidence";
type Motion = "system" | "on" | "off";
const motionDuration = (duration: number) => {
  const preference = document.documentElement.dataset.motion;
  return preference === "off" ||
    (preference !== "on" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches)
    ? 0
    : duration;
};

export default function App() {
  const { locale, setLocale } = useLocale();
  const [projects, setProjects] = useState<ProjectSummary[]>([]),
    [project, setProject] = useState<Project | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [view, setView] = useState<View>("graph"),
    [selected, setSelected] = useState<string[]>([]),
    [edgeId, setEdgeId] = useState<string | null>(null),
    [scope, setScope] = useState<string | null>(null),
    [outline, setOutline] = useState(() => window.innerWidth >= 900),
    [inspector, setInspector] = useState(false),
    [activity, setActivity] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<NodeTab>("overview");
  const [dialog, setDialog] = useState<DialogState>(null),
    [projectMenu, setProjectMenu] = useState(false),
    [palette, setPalette] = useState(false),
    [query, setQuery] = useState(""),
    [toast, setToast] = useState(""),
    [busy, setBusy] = useState(false),
    [artifact, setArtifact] = useState<Artifact | null>(null),
    [history, setHistory] = useState<any[] | null>(null),
    [theme, setTheme] = useState(
      localStorage.getItem("exp-observer-theme") || "light",
    );
  const [motion, setMotion] = useState<Motion>(() => {
    const saved = localStorage.getItem("exp-observer-motion");
    return saved === "on" || saved === "off" ? saved : "system";
  });
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [boundaryIds, setBoundaryIds] = useState<string[]>([]);
  const [runtime, setRuntime] = useState<RuntimeSnapshot | null>(null);
  const [agentSetup, setAgentSetup] = useState<AgentSetup>();
  const [referenceFallback, setReferenceFallback] = useState("");
  const [headerToolsOpen, setHeaderToolsOpen] = useState(false);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CanvasData>>([]),
    [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const selectionRef = useRef(selected);
  selectionRef.current = selected;
  const pRef = useRef(project),
    busyRef = useRef(false),
    dragging = useRef(false),
    fileInput = useRef<HTMLInputElement>(null),
    loadedId = useRef("");
  const flow = useReactFlow();
  const fittedLayout = useRef("");
  const pendingNavigation = useRef<ReturnType<typeof nodeNavigation>>(null);
  const navigationSequence = useRef(0);
  const measuredSizes = useStore((state) =>
    JSON.stringify(
      state.nodes
        .filter((n) => !n.data.expanded && n.measured?.height)
        .map((n) => [n.id, n.measured!.width, n.measured!.height]),
    ),
  );
  const selectedNode = project?.nodes.find((n) => n.id === selected[0]);
  const selectedEdge = project?.edges.find((e) => e.id === edgeId);
  useEffect(() => {
    void api
      .agentSetup()
      .then(setAgentSetup)
      .catch(() => {});
  }, []);
  const copyReference = async (ids: string[] = selected) => {
    if (!project) return;
    const nodes = ids
      .map((id) => project.nodes.find((node) => node.id === id))
      .filter((node): node is NonNullable<typeof node> => !!node);
    if (!nodes.length) return;
    const text = nodeReference(
      project,
      nodes,
      window.location.origin,
      agentSetup,
    );
    try {
      await navigator.clipboard.writeText(text);
      setToast(t("节点引用已复制，粘贴到 Agent 对话即可"));
    } catch {
      setReferenceFallback(text);
    }
  };
  useEffect(() => {
    pRef.current = project;
  }, [project]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("exp-observer-theme", theme);
  }, [theme]);
  useEffect(() => {
    document.documentElement.dataset.motion = motion;
    localStorage.setItem("exp-observer-motion", motion);
  }, [motion]);
  useEffect(() => {
    const id = project?.id;
    setRuntime(null);
    if (!id) return;
    let cancelled = false,
      pending = false;
    let expiry: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      if (pending || document.hidden) return;
      pending = true;
      try {
        const snapshot = await api.runtime(id);
        if (!cancelled) {
          clearTimeout(expiry);
          expiry = setTimeout(() => setRuntime(null), 10000);
          setRuntime((previous) =>
            JSON.stringify(previous?.active) === JSON.stringify(snapshot.active)
              ? previous
              : snapshot,
          );
        }
      } catch {
        if (!cancelled) setRuntime(null);
      } finally {
        pending = false;
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 1800);
    return () => {
      cancelled = true;
      clearInterval(timer);
      clearTimeout(expiry);
    };
  }, [project?.id]);
  const notify = useCallback((message: string) => {
    setToast(message);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 4200);
    return () => clearTimeout(t);
  }, [toast]);
  const load = useCallback(
    async (id: string) => {
      loadedId.current = id;
      setLoading(true);
      try {
        const p = await api.project(id);
        if (loadedId.current !== id) return;
        pRef.current = p;
        setProject(p);
        setSelected([]);
        pendingNavigation.current = null;
        setScope(initialResearchScope(p));
        setExpandedIds(new Set());
        setBoundaryIds([]);
        setEdgeId(null);
        localStorage.setItem("exp-observer-project", id);
        setError("");
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [flow],
  );
  useEffect(() => {
    api
      .list()
      .then(({ projects: ps }) => {
        setProjects(ps);
        const saved = localStorage.getItem("exp-observer-project");
        if (ps.length)
          void load(ps.find((p) => p.id === saved)?.id || ps[0].id);
        else setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);
  useEffect(() => {
    const pollTimer = setInterval(async () => {
      if (busyRef.current || dragging.current || document.hidden) return;
      try {
        const { projects: ps } = await api.list();
        setProjects(ps);
        const p = pRef.current;
        const revision = ps.find((x) => x.id === p?.id)?.revision;
        if ((!p || revision === undefined) && ps.length) {
          const saved = localStorage.getItem("exp-observer-project");
          await load(
            ps.find((candidate) => candidate.id === saved)?.id || ps[0].id,
          );
        } else if (p && !ps.length) {
          loadedId.current = "";
          pRef.current = null;
          setProject(null);
          setNodes([]);
          setEdges([]);
          setSelected([]);
          setScope(null);
          setEdgeId(null);
          setInspector(false);
        } else if (p && revision !== undefined && revision !== p.revision) {
          const updated = await api.project(p.id);
          if (
            pRef.current?.id === p.id &&
            !busyRef.current &&
            !dragging.current
          ) {
            pRef.current = updated;
            setProject(updated);
          }
        }
        setError("");
      } catch {
        setError(t("连接中断，正在重连"));
      }
    }, 1800);
    return () => clearInterval(pollTimer);
  }, [load]);
  const mutate = useCallback(
    async (operations: Operation[]) => {
      const p = pRef.current;
      if (!p || busyRef.current) return false;
      busyRef.current = true;
      setBusy(true);
      try {
        const updated = await api.batch(p, operations);
        if (pRef.current?.id === updated.id) {
          pRef.current = updated;
          setProject(updated);
        }
        return true;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          const updated = await api.project(p.id);
          pRef.current = updated;
          setProject(updated);
          notify(t("记录已被更新，请重试这次修改"));
        } else notify((e as Error).message);
        return false;
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [notify],
  );
  useEffect(() => {
    if (project && scope && !project.nodes.some((node) => node.id === scope)) {
      setScope(null);
      setExpandedIds(new Set());
      setSelected([]);
      setBoundaryIds([]);
      setEdgeId(null);
      setInspector(false);
    }
  }, [project, scope]);
  const toggle = useCallback((id: string) => {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const enter = useCallback(
    (id: string) => {
      pendingNavigation.current = null;
      navigationSequence.current += 1;
      setScope(id);
      setExpandedIds(new Set());
      setBoundaryIds([]);
      setEdgeId(null);
      setInspector(false);
      setSelected([]);
      setTimeout(
        () => flow.fitView({ padding: 0.22, duration: motionDuration(350) }),
        100,
      );
    },
    [flow],
  );
  const inspectNode = useCallback((id: string, tab: NodeTab) => {
    setSelected([id]);
    setBoundaryIds([]);
    setEdgeId(null);
    setInspectorTab(tab);
    setInspector(true);
    setNodes((current) =>
      current.map((n) => ({ ...n, selected: n.id === id })),
    );
  }, []);
  useEffect(() => {
    if (!project) return;
    const canvas = toCanvas(
      {
        ...project,
        runtimeActivity:
          runtime?.projectId === project.id ? runtime.active : [],
      },
      scope,
      selectionRef.current,
      {
        onToggle: toggle,
        onEnter: enter,
        onInspect: inspectNode,
      },
      { expandedIds },
    );
    const measured = new Map<string, { width: number; height: number }>(
      (JSON.parse(measuredSizes) as [string, number, number][]).map(
        ([id, width, height]) => [id, { width, height }],
      ),
    );
    canvas.nodes = canvas.nodes.map((n) => ({
      ...n,
      measured: measured.get(n.id),
    }));
    let cancelled = false;
    void layoutCanvas(canvas)
      .then((arranged) => {
        if (cancelled || dragging.current) return;
        setNodes(
          arranged.nodes.map((n) => ({
            ...n,
            selected: selectionRef.current.includes(n.id),
          })),
        );
        setEdges(arranged.edges);
        const key = `${project.id}:${scope}`;
        const jump = pendingNavigation.current;
        if (
          jump?.projectId === project.id &&
          jump.scope === scope &&
          arranged.nodes.some((node) => node.id === jump.nodeId)
        ) {
          fittedLayout.current = key;
          const sequence = navigationSequence.current;
          const frame = () => {
            if (
              cancelled ||
              navigationSequence.current !== sequence ||
              pRef.current?.id !== project.id
            )
              return;
            const target = flow.getNode(jump.nodeId);
            if (!target) return;
            pendingNavigation.current = null;
            void flow.fitView({
              nodes: [target],
              padding: 0.65,
              duration: motionDuration(350),
              maxZoom: 1,
            });
          };
          // ReactFlow commits the ELK result before calculating node bounds.
          requestAnimationFrame(() => requestAnimationFrame(frame));
        } else if (!jump && fittedLayout.current !== key) {
          fittedLayout.current = key;
          setTimeout(() => {
            if (
              cancelled ||
              pendingNavigation.current ||
              pRef.current?.id !== project.id
            )
              return;
            const cards = arranged.nodes
              .filter((n) => !n.parentId)
              .sort((a, b) => a.position.y - b.position.y);
            const firstRows = [
              ...new Set(cards.map((n) => n.position.y)),
            ].slice(0, 3);
            void flow.fitView({
              nodes: cards.filter((n) => firstRows.includes(n.position.y)),
              padding: 0.18,
              maxZoom: 0.85,
              duration: motionDuration(300),
            });
          }, 120);
        }
      })
      .catch((e) => {
        if (!cancelled)
          notify(t("布局失败：{value0}", { value0: (e as Error).message }));
      });
    return () => {
      cancelled = true;
    };
  }, [
    project,
    runtime,
    scope,
    toggle,
    enter,
    inspectNode,
    flow,
    notify,
    measuredSizes,
    expandedIds,
    locale,
  ]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      // Native reading/delivery dialogs own keyboard input and Escape. Closing
      // one must preserve the selected research node underneath it.
      if (document.querySelector("dialog[open]")) return;
      const tag = (e.target as HTMLElement).tagName;
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPalette((v) => !v);
        return;
      }
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      if (e.key === "Escape") {
        setPalette(false);
        setDialog(null);
        setArtifact(null);
        setHistory(null);
        setSelected([]);
        setEdgeId(null);
      }
      if (e.key.toLowerCase() === "n" && !e.metaKey && !e.ctrlKey)
        setDialog({ type: "node", parentId: scope });
      if (e.key.toLowerCase() === "f")
        void flow.fitView({ padding: 0.18, duration: motionDuration(350) });
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "g") {
        e.preventDefault();
        if (selected.length) setDialog({ type: "group" });
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [scope, selected, flow]);
  const handleSelection = useCallback(
    ({ nodes }: { nodes: Node[] }) =>
      setSelected((prev) => {
        const next = nodes.map((n) => n.id);
        return next.join() === prev.join() ? prev : next;
      }),
    [],
  );
  const selectNode = (id: string) => {
    if (!project) return;
    const navigation = nodeNavigation(project, id);
    if (!navigation) return;
    pendingNavigation.current = navigation;
    navigationSequence.current += 1;
    if (window.innerWidth < 900) setOutline(false);
    setInspectorTab("overview");
    setScope(navigation.scope);
    setExpandedIds(new Set());
    setBoundaryIds([]);
    setSelected([id]);
    setNodes((current) =>
      current.map((item) => ({ ...item, selected: item.id === id })),
    );
    setEdgeId(null);
    setInspector(true);
    setView("graph");
    setPalette(false);
    setQuery("");
  };
  const onConnect = (c: Connection) => {
    if (c.source === c.target) return;
    void mutate([
      {
        op: "edge.add",
        data: {
          id: uid("edge"),
          source: c.source,
          target: c.target,
          relation: "leads_to",
          basis: "hypothesis",
        },
      },
    ]);
  };
  const saveDrag = (_: unknown, moved: Node, movedNodes: Node[]) => {
    dragging.current = false;
    const p = pRef.current;
    if (!p) return;
    const byId = new Map(flow.getNodes().map((n) => [n.id, n]));
    function absolute(n: Node): { x: number; y: number } {
      if (!n.parentId) return n.position;
      const parent = byId.get(n.parentId);
      const pp = parent ? absolute(parent) : { x: 0, y: 0 };
      return { x: pp.x + n.position.x, y: pp.y + n.position.y };
    }
    const moving = movedNodes?.length ? movedNodes : [moved];
    const movingIds = new Set(moving.map((n) => n.id));
    const roots = moving.filter(
      (n) =>
        !ancestry(p.nodes, n.id)
          .slice(0, -1)
          .some((a) => movingIds.has(a.id) && isResearchContainer(p.nodes, a)),
    );
    const changes = new Map<string, Operation>();
    for (const root of roots) {
      const original = p.nodes.find((n) => n.id === root.id);
      if (!original) continue;
      const pos = absolute(root);
      const dx = pos.x - original.position.x,
        dy = pos.y - original.position.y;
      for (const id of [
        root.id,
        ...(isResearchContainer(p.nodes, original)
          ? descendants(p.nodes, root.id)
          : []),
      ]) {
        const existing = p.nodes.find((n) => n.id === id)!;
        const rendered = byId.get(id);
        const finalPosition = rendered
          ? absolute(rendered)
          : {
              x: existing.position.x + dx,
              y: existing.position.y + dy,
            };
        changes.set(id, {
          op: "node.update",
          data: {
            id,
            position: {
              x: Math.round(finalPosition.x),
              y: Math.round(finalPosition.y),
            },
          },
        });
      }
    }
    void mutate([...changes.values()]);
  };
  const layout = async () => {
    if (!project) return;
    try {
      const arranged = await layoutCanvas(
        toCanvas(
          project,
          scope,
          selected,
          {
            onToggle: toggle,
            onEnter: enter,
            onInspect: inspectNode,
          },
          { expandedIds },
        ),
        { resetManual: true },
      );
      // Explicit relayout releases manual pins. Automatic view coordinates are
      // computed by the same ELK engine used on load and incoming updates.
      const visibleScope = new Set(arranged.nodes.map((node) => node.id));
      const ops = project.nodes
        .filter((n) => visibleScope.has(n.id))
        .map((n) => ({
          op: "node.update",
          data: {
            id: n.id,
            positionSource: "auto",
          },
        }));
      if (await mutate(ops)) {
        setNodes(arranged.nodes);
        setEdges(arranged.edges);
        setTimeout(
          () =>
            void flow.fitView({
              padding: 0.18,
              maxZoom: 1,
              duration: motionDuration(350),
            }),
          120,
        );
      }
    } catch (e) {
      notify(t("布局失败：{value0}", { value0: (e as Error).message }));
    }
  };
  const exportProject = () => {
    if (!project) return;
    const blob = new Blob([JSON.stringify(project, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${project.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const importProject = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const p = await api.import(JSON.parse(await file.text()));
      setProjects((await api.list()).projects);
      await load(p.id);
      notify(t("研究已导入"));
    } catch (e) {
      notify((e as Error).message);
    }
    e.target.value = "";
  };
  const openHistory = async () => {
    if (!project) return;
    try {
      const result = await api.history(project.id);
      setHistory(
        Array.isArray(result)
          ? result
          : result.history || result.revisions || [],
      );
    } catch (e) {
      notify((e as Error).message);
    }
  };
  const deleteSelected = async () => {
    const ops: Operation[] = edgeId
      ? [{ op: "edge.delete", data: { id: edgeId } }]
      : selected.map((id) => ({ op: "node.delete", data: { id } }));
    if (ops.length && (await mutate(ops))) {
      setSelected([]);
      setEdgeId(null);
      notify(t("已移除，可从历史版本恢复"));
    }
  };
  const graphCount = project?.nodes.length || 0;
  const running =
    project?.runs.filter((r) => r.status === "running").length || 0;
  const mainTabs: { id: View; label: string; icon: typeof Network }[] = [
    { id: "graph", label: t("研究图"), icon: Network },
    { id: "runs", label: t("运行"), icon: FlaskConical },
    { id: "compare", label: t("对比"), icon: LayoutGrid },
    { id: "evidence", label: t("证据"), icon: Files },
  ];

  return (
    <div className="app-shell">
      <div className="workspace">
        <header className="topbar">
          <div className="wordmark">
            <img
              className="app-icon"
              src="/assets/app-icon.svg"
              alt=""
              width="28"
              height="28"
            />
            ExpObserver
          </div>
          <span className="topbar-divider" />
          <div className="project-switcher">
            <button
              className="project-switch"
              onClick={() => setProjectMenu(!projectMenu)}
            >
              <FolderOpen size={15} />
              <span>{project?.name || t("选择研究项目")}</span>
              <ChevronDown size={13} />
            </button>
            {projectMenu && (
              <>
                <div
                  className="dismiss"
                  onClick={() => setProjectMenu(false)}
                />
                <div className="dropdown project-dropdown">
                  <div className="dropdown-caption">{t("研究项目")}</div>
                  {projects.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => {
                        void load(p.id);
                        setProjectMenu(false);
                      }}
                    >
                      <span className="project-dot" />
                      <span>{p.name}</span>
                      {p.id === project?.id && <Check size={14} />}
                    </button>
                  ))}
                  <div className="dropdown-line" />
                  <button
                    onClick={() => {
                      setDialog({ type: "project" });
                      setProjectMenu(false);
                    }}
                  >
                    <Plus size={15} />
                    {t("新建研究")}
                  </button>
                  <button
                    onClick={() => {
                      fileInput.current?.click();
                      setProjectMenu(false);
                    }}
                  >
                    <Upload size={15} />
                    {t("导入 JSON")}
                  </button>
                </div>
              </>
            )}
          </div>
          <nav className="top-nav" aria-label={t("研究视图")}>
            {mainTabs.map((t) => (
              <button
                key={t.id}
                aria-pressed={view === t.id}
                className={view === t.id ? "selected" : ""}
                onClick={() => setView(t.id)}
              >
                <t.icon size={15} />
                {t.label}
                {t.id === "runs" &&
                  !!project?.runs.filter(isExecutionRun).length && (
                    <span>{project.runs.filter(isExecutionRun).length}</span>
                  )}
              </button>
            ))}
          </nav>
          <div className="topbar-right">
            <DeliveryStatus projectId={project?.id} error={error} busy={busy} />
            <button
              className="search-trigger"
              aria-label={t("搜索")}
              title={t("搜索")}
              onClick={() => {
                setPalette(true);
                setQuery("");
              }}
            >
              <Search size={14} />
              <span>{t("搜索")}</span>
              <kbd>⌘ K</kbd>
            </button>
            <div
              className="topbar-tools"
              data-open={headerToolsOpen}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  setHeaderToolsOpen(false);
                  event.currentTarget
                    .querySelector<HTMLButtonElement>(".compact-tools-toggle")
                    ?.focus();
                }
              }}
            >
              <button
                className="icon-button compact-tools-toggle"
                aria-label={t("更多工具")}
                aria-expanded={headerToolsOpen}
                aria-controls="header-tools"
                onClick={() => setHeaderToolsOpen(!headerToolsOpen)}
              >
                <MoreHorizontal size={18} />
              </button>
              {headerToolsOpen && (
                <div
                  className="dismiss header-tools-dismiss"
                  onClick={() => setHeaderToolsOpen(false)}
                />
              )}
              <div className="topbar-tools-body" id="header-tools">
                <label className="language-control" title={t("界面语言")}>
                  <Languages size={15} aria-hidden="true" />
                  <select
                    aria-label={t("界面语言")}
                    value={locale}
                    onChange={(event) =>
                      setLocale(event.target.value as "en" | "zh-CN")
                    }
                  >
                    <option value="en">English</option>
                    <option value="zh-CN">简体中文</option>
                  </select>
                </label>
                <IconButton
                  label={t("连接 Agent")}
                  onClick={() => {
                    setHeaderToolsOpen(false);
                    setPalette(true);
                    setQuery(">skill");
                  }}
                >
                  <Terminal size={17} />
                  <span className="header-tool-label">{t("连接 Agent")}</span>
                </IconButton>
                <IconButton
                  label={theme === "dark" ? t("浅色外观") : t("深色外观")}
                  onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                >
                  {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
                  <span className="header-tool-label">
                    {theme === "dark" ? t("浅色外观") : t("深色外观")}
                  </span>
                </IconButton>
                <label className="motion-control" title={t("动画偏好")}>
                  <Activity size={14} aria-hidden="true" />
                  <select
                    aria-label={t("动画偏好")}
                    value={motion}
                    onChange={(e) => setMotion(e.target.value as Motion)}
                  >
                    <option value="system">{t("跟随系统")}</option>
                    <option value="on">{t("开启动画")}</option>
                    <option value="off">{t("关闭动画")}</option>
                  </select>
                </label>
                <IconButton
                  label={t("导出研究 JSON")}
                  onClick={() => {
                    setHeaderToolsOpen(false);
                    exportProject();
                  }}
                  disabled={!project}
                >
                  <Download size={17} />
                  <span className="header-tool-label">
                    {t("导出研究 JSON")}
                  </span>
                </IconButton>
                <IconButton
                  label={t("版本历史")}
                  onClick={() => {
                    setHeaderToolsOpen(false);
                    void openHistory();
                  }}
                  disabled={!project}
                >
                  <History size={17} />
                  <span className="header-tool-label">{t("版本历史")}</span>
                </IconButton>
              </div>
            </div>
          </div>
        </header>
        <div className="work-area">
          {outline && (
            <aside className="outline">
              <div className="outline-heading">
                <span>
                  {t("研究目录")}
                  <small>{graphCount}</small>
                </span>
                <IconButton
                  label={t("收起导航")}
                  onClick={() => setOutline(false)}
                >
                  <PanelLeftClose size={14} />
                </IconButton>
              </div>
              <button
                className="workspace-item selected"
                onClick={() => {
                  setScope(null);
                  setView("graph");
                  setTimeout(
                    () =>
                      flow.fitView({
                        padding: 0.2,
                        duration: motionDuration(300),
                      }),
                    100,
                  );
                }}
              >
                <Network size={15} />
                <span>{t("研究全景")}</span>
                <span className="count">{graphCount}</span>
              </button>
              <div className="outline-tree">
                {project && (
                  <OutlineTree
                    nodes={project.nodes}
                    parentId={null}
                    selected={selected[0]}
                    onSelect={selectNode}
                  />
                )}
              </div>
              <div className="outline-footer">
                <span className="tiny-dot accent" />
                <span>
                  {t("{count} 次运行", {
                    count: project?.runs.filter(isExecutionRun).length || 0,
                  })}
                </span>
                <span className="outline-footer-right">
                  {t("{count} 份证据", {
                    count: project?.artifacts.length || 0,
                  })}
                </span>
              </div>
            </aside>
          )}
          <main className="main-area">
            <div className="work-toolbar">
              <IconButton
                label={outline ? t("收起研究目录") : t("展开研究目录")}
                onClick={() => setOutline(!outline)}
              >
                <PanelLeftOpen size={16} />
              </IconButton>
              <h1>
                {view === "graph" && scope
                  ? project?.nodes.find((n) => n.id === scope)?.title
                  : mainTabs.find((t) => t.id === view)?.label}
              </h1>
              {view === "graph" && (
                <span className="toolbar-count">
                  {t("{count} 个节点", { count: nodes.length })}
                </span>
              )}
              {project?.id === "retrieval-demo" && (
                <span className="origin-tag">{t("模拟研究")}</span>
              )}
              <div className="view-tab-right">
                {project && (
                  <CurrentWork
                    project={project}
                    runtime={runtime}
                    onSelect={selectNode}
                  />
                )}
                {running > 0 && (
                  <span className="live-indicator">
                    <span />
                    {t("{count} 个运行中", { count: running })}
                  </span>
                )}
                {view === "graph" && (
                  <>
                    {selectedNode && (
                      <button
                        className="button"
                        aria-label={t("复制引用")}
                        title={t("复制引用")}
                        onClick={() => void copyReference()}
                      >
                        <Copy size={14} />
                        <span className="toolbar-action-label">
                          {t("复制引用")}
                        </span>
                        {selected.length > 1 ? ` · ${selected.length}` : ""}
                      </button>
                    )}
                    {scope && boundaryRelations(project!, scope).length > 0 && (
                      <button
                        className="button"
                        onClick={() => {
                          setBoundaryIds(
                            boundaryRelations(project!, scope).map(
                              (edge) => edge.id,
                            ),
                          );
                          setSelected([]);
                          setEdgeId(null);
                          setInspector(true);
                        }}
                      >
                        {t("边界关系 {count}", {
                          count: boundaryRelations(project!, scope).length,
                        })}
                      </button>
                    )}
                    {expandedIds.size > 0 && (
                      <button
                        className="button"
                        onClick={() => setExpandedIds(new Set())}
                      >
                        {t("收起容器")}
                      </button>
                    )}
                    <IconButton
                      label={t("自动布局")}
                      onClick={() => void layout()}
                      disabled={!project}
                    >
                      <LayoutGrid size={15} />
                    </IconButton>
                    <IconButton
                      label={t("切换详情面板")}
                      active={inspector}
                      onClick={() => setInspector(!inspector)}
                    >
                      <Settings2 size={15} />
                    </IconButton>
                  </>
                )}
                <button
                  className="button primary compact-add"
                  aria-label={project ? t("添加节点") : t("新建研究")}
                  title={project ? t("添加节点") : t("新建研究")}
                  onClick={() =>
                    setDialog(
                      project
                        ? { type: "node", parentId: scope }
                        : { type: "project" },
                    )
                  }
                >
                  <Plus size={14} />
                  <span className="toolbar-action-label">
                    {project ? t("添加节点") : t("新建研究")}
                  </span>
                </button>
              </div>
            </div>
            {error && !project ? (
              <div className="empty-state">
                <Network size={34} />
                <h2>{t("连接本地工作空间")}</h2>
                <p>{error}</p>
                <button className="button" onClick={() => location.reload()}>
                  <RefreshCw size={14} />
                  {t("重新连接")}
                </button>
              </div>
            ) : loading && !project ? (
              <div className="empty-state">
                <span className="spinner" />
                <p>{t("正在打开研究…")}</p>
              </div>
            ) : !project ? (
              <div className="empty-state">
                <Network size={38} />
                <h2>{t("从一个问题开始")}</h2>
                <button
                  className="button primary"
                  onClick={() => setDialog({ type: "project" })}
                >
                  <Plus size={15} />
                  {t("新建研究")}
                </button>
                <button
                  className="text-button"
                  onClick={() => fileInput.current?.click()}
                >
                  {t("导入已有研究")}
                </button>
              </div>
            ) : (
              <div className="view-body">
                {view === "graph" ? (
                  <>
                    <div className="graph-canvas">
                      <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        nodeTypes={nodeTypes}
                        edgeTypes={edgeTypes}
                        connectionMode={ConnectionMode.Loose}
                        onNodesChange={onNodesChange}
                        onEdgesChange={onEdgesChange}
                        onConnect={onConnect}
                        onSelectionChange={handleSelection}
                        onNodeClick={(_, n) => {
                          setBoundaryIds([]);
                          setInspectorTab("overview");
                          setSelected([n.id]);
                          setEdgeId(null);
                          setInspector(true);
                        }}
                        onEdgeClick={(_, e) => {
                          setSelected([]);
                          if (e.data?.boundary) {
                            setBoundaryIds(
                              (e.data.originals as Project["edges"]).map(
                                (edge) => edge.id,
                              ),
                            );
                            setEdgeId(null);
                          } else {
                            setBoundaryIds([]);
                            setEdgeId(e.id);
                          }
                          setInspector(true);
                        }}
                        onPaneClick={() => {
                          setEdgeId(null);
                        }}
                        onNodeDoubleClick={(_, n) => {
                          if (n.data.container) enter(n.id);
                        }}
                        onNodeDragStart={() => {
                          dragging.current = true;
                        }}
                        onNodeDragStop={saveDrag}
                        onMoveEnd={(_, viewport) =>
                          localStorage.setItem(
                            `exp-observer-viewport-${project.id}-${scope}`,
                            JSON.stringify(viewport),
                          )
                        }
                        defaultViewport={JSON.parse(
                          localStorage.getItem(
                            `exp-observer-viewport-${project.id}-${scope}`,
                          ) || '{"x":0,"y":0,"zoom":0.8}',
                        )}
                        fitView
                        fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
                        minZoom={0.15}
                        maxZoom={1.8}
                        selectionMode={SelectionMode.Partial}
                        selectionOnDrag
                        panOnDrag={[1, 2]}
                        panOnScroll
                        zoomOnScroll={false}
                        zoomOnDoubleClick={false}
                        deleteKeyCode={null}
                        colorMode={theme === "light" ? "light" : "dark"}
                        proOptions={{ hideAttribution: true }}
                        aria-label={t("研究图画布")}
                      >
                        <Background
                          variant={BackgroundVariant.Dots}
                          gap={22}
                          size={1}
                          color={theme === "light" ? "#d4d4d8" : "#303036"}
                        />
                        <MiniMap
                          pannable
                          zoomable
                          nodeColor={(n) =>
                            n.selected
                              ? "#2563eb"
                              : theme === "light"
                                ? "#a1a1aa"
                                : "#52525b"
                          }
                          maskColor={
                            theme === "light" ? "#fafafacc" : "#18181bcc"
                          }
                          style={{ background: "var(--panel)" }}
                        />
                      </ReactFlow>
                      <div className="canvas-top-left">
                        {scope ? (
                          <div className="canvas-crumb">
                            <button
                              onClick={() => {
                                setScope(null);
                                setExpandedIds(new Set());
                                setBoundaryIds([]);
                                setInspector(false);
                                setSelected([]);
                                setTimeout(
                                  () =>
                                    flow.fitView({
                                      padding: 0.2,
                                      duration: motionDuration(300),
                                    }),
                                  80,
                                );
                              }}
                            >
                              {t("研究脉络")}
                            </button>
                            {ancestry(project.nodes, scope).map((n) => (
                              <span key={n.id}>
                                <ChevronRight size={11} />
                                <button onClick={() => enter(n.id)}>
                                  {n.title}
                                </button>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="canvas-label">
                            <span className="tiny-dot accent" />
                            {t("主脉络")}
                          </span>
                        )}
                      </div>
                      {!nodes.length && (
                        <div className="canvas-empty">
                          <Plus size={24} />
                          <span>{t("添加第一个研究节点")}</span>
                          <button
                            className="button"
                            onClick={() =>
                              setDialog({ type: "node", parentId: scope })
                            }
                          >
                            {t("添加节点")}
                          </button>
                        </div>
                      )}
                      <div className="canvas-controls">
                        <IconButton
                          label={t("放大")}
                          onClick={() =>
                            flow.zoomIn({ duration: motionDuration(180) })
                          }
                        >
                          <ZoomIn size={16} />
                        </IconButton>
                        <IconButton
                          label={t("缩小")}
                          onClick={() =>
                            flow.zoomOut({ duration: motionDuration(180) })
                          }
                        >
                          <ZoomOut size={16} />
                        </IconButton>
                        <span className="control-divider" />
                        <IconButton
                          label={t("适应画布 · F")}
                          onClick={() =>
                            flow.fitView({
                              padding: 0.2,
                              duration: motionDuration(350),
                            })
                          }
                        >
                          <Maximize2 size={15} />
                        </IconButton>
                        <span className="control-divider" />
                        <button
                          className="activity-toggle"
                          onClick={() => setActivity(!activity)}
                        >
                          <Activity size={14} />
                          {t("动态")}
                          {project.activity?.length > 0 && (
                            <span>{project.activity.length}</span>
                          )}
                        </button>
                      </div>
                      {selected.length > 1 && (
                        <div className="selection-toolbar">
                          <span>
                            {t("已选择 {count} 个节点", {
                              count: selected.length,
                            })}
                          </span>
                          <button onClick={() => setDialog({ type: "group" })}>
                            <Layers size={14} />
                            {t("放入容器")}
                          </button>
                        </div>
                      )}
                    </div>
                    {inspector && (
                      <aside className="inspector">
                        {boundaryIds.length > 0 ? (
                          <BoundaryInspector
                            project={project}
                            edges={project.edges.filter((edge) =>
                              boundaryIds.includes(edge.id),
                            )}
                            onSelect={selectNode}
                            onClose={() => setInspector(false)}
                            onEdit={(id) => {
                              setBoundaryIds([]);
                              setEdgeId(id);
                            }}
                          />
                        ) : selectedNode ? (
                          <NodeInspector
                            key={selectedNode.id}
                            node={selectedNode}
                            project={project}
                            busy={busy}
                            tab={inspectorTab}
                            onTabChange={setInspectorTab}
                            onCopyReference={() =>
                              void copyReference([selectedNode.id])
                            }
                            mutate={mutate}
                            onClose={() => setInspector(false)}
                            onBranch={() =>
                              setDialog({
                                type: "branch",
                                source: selectedNode.id,
                                parentId: selectedNode.parentId,
                              })
                            }
                            onEnter={() => enter(selectedNode.id)}
                            onChild={() =>
                              setDialog({
                                type: "node",
                                parentId: selectedNode.id,
                              })
                            }
                            onDelete={() => void deleteSelected()}
                            onArtifact={setArtifact}
                            onSelect={selectNode}
                            onConnect={() =>
                              setDialog({
                                type: "connect",
                                source: selectedNode.id,
                              })
                            }
                          />
                        ) : selectedEdge ? (
                          <EdgeInspector
                            edge={selectedEdge}
                            mutate={mutate}
                            onDelete={() => void deleteSelected()}
                          />
                        ) : (
                          <ProjectInspector
                            project={project}
                            onAdd={() =>
                              setDialog({ type: "node", parentId: scope })
                            }
                            onSelect={selectNode}
                            onClose={() => setInspector(false)}
                          />
                        )}
                      </aside>
                    )}
                  </>
                ) : view === "runs" ? (
                  <RunsView
                    project={project}
                    onArtifact={setArtifact}
                    onNode={selectNode}
                  />
                ) : view === "compare" ? (
                  <CompareView project={project} />
                ) : (
                  <EvidenceView
                    project={project}
                    onOpen={setArtifact}
                    onAdd={() => setDialog({ type: "artifact" })}
                  />
                )}
              </div>
            )}
            {activity && project && (
              <div className="activity-drawer">
                <div className="drawer-heading">
                  <span>
                    <Activity size={14} />
                    {t("研究动态")}
                  </span>
                  <IconButton
                    label={t("关闭动态")}
                    onClick={() => setActivity(false)}
                  >
                    <X size={14} />
                  </IconButton>
                </div>
                <div className="activity-list">
                  {[...project.activity]
                    .reverse()
                    .slice(0, 40)
                    .map((a, i) => (
                      <div key={a.id || i}>
                        <span className="activity-dot" />
                        <time>{time(a.at)}</time>
                        <span>
                          {a.message ||
                            a.operations
                              ?.map(
                                (o) =>
                                  ({
                                    "node.add": t("新增节点"),
                                    "node.update": t("更新节点"),
                                    "run.add": t("开始运行"),
                                    "run.update": t("更新运行"),
                                    "run.event": t("运行事件"),
                                    "assessment.add": t("登记评估"),
                                    "edge.add": t("连接节点"),
                                    "decision.add": t("记录结论"),
                                    "project.update": t("更新项目"),
                                  })[o.op] || o.op,
                              )
                              .join(" · ") ||
                            a.type ||
                            t("研究已更新")}
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            )}
            <footer className="statusbar">
              <span>
                <span className="tiny-dot accent" />
                ExpObserver
              </span>
              <span>
                {project ? `r${project.revision}` : t("本地工作空间")}
              </span>
              <div />
              <span className="statusbar-hint">
                {t("拖动平移 · Shift 框选 · F 适应画布")}
              </span>
              <button
                onClick={() => {
                  setPalette(true);
                  setQuery(">skill");
                }}
              >
                <Terminal size={12} />
                {t("Agent 接入")}
                <ArrowUpRight size={11} />
              </button>
            </footer>
          </main>
        </div>
      </div>
      <input
        ref={fileInput}
        type="file"
        accept=".json,application/json"
        hidden
        onChange={importProject}
      />
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={16} />
          {toast}
          <button onClick={() => setToast("")}>
            <X size={13} />
          </button>
        </div>
      )}
      {referenceFallback && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setReferenceFallback("");
          }}
        >
          <div
            className="modal reference-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="reference-title"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.stopPropagation();
                setReferenceFallback("");
              }
            }}
          >
            <div className="modal-heading">
              <h2 id="reference-title">{t("复制节点引用")}</h2>
              <IconButton
                label={t("关闭引用")}
                onClick={() => setReferenceFallback("")}
              >
                <X size={16} />
              </IconButton>
            </div>
            <p>{t("自动复制未成功，请复制下方内容到 Agent 对话。")}</p>
            <textarea
              aria-label={t("节点引用内容")}
              readOnly
              autoFocus
              value={referenceFallback}
              onFocus={(event) => event.currentTarget.select()}
            />
            <button
              className="button wide"
              onClick={(event) => {
                event.currentTarget.parentElement
                  ?.querySelector("textarea")
                  ?.select();
              }}
            >
              {t("全选引用")}
            </button>
          </div>
        </div>
      )}
      {dialog && (
        <CreateDialog
          dialog={dialog}
          project={project}
          selected={selected}
          onClose={() => setDialog(null)}
          mutate={mutate}
          onCreated={async (p) => {
            setProjects((await api.list()).projects);
            await load(p.id);
          }}
          onNodeCreated={(id) => {
            setView("graph");
            setScope(
              pRef.current?.nodes.find((node) => node.id === id)?.parentId ||
                null,
            );
            setExpandedIds(new Set());
            setBoundaryIds([]);
            setEdgeId(null);
            setSelected([id]);
            setInspector(true);
          }}
          notify={notify}
          flowCenter={() =>
            flow.screenToFlowPosition({
              x: window.innerWidth / 2,
              y: window.innerHeight / 2,
            })
          }
        />
      )}
      {palette && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setPalette(false);
          }}
        >
          <div className="command-palette">
            <div className="palette-input">
              <Search size={18} />
              <input
                autoFocus
                placeholder={t("搜索节点、研究，或输入操作…")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <kbd onClick={() => setPalette(false)}>Esc</kbd>
            </div>
            {query.startsWith(">skill") ? (
              <SkillPanel project={project} notify={notify} />
            ) : (
              <div className="palette-results">
                {!query && (
                  <>
                    <button
                      onClick={() => {
                        setPalette(false);
                        setDialog({ type: "node", parentId: scope });
                      }}
                    >
                      <Plus size={16} />
                      {t("添加研究节点")}
                      <kbd>N</kbd>
                    </button>
                    <button
                      onClick={() => {
                        setPalette(false);
                        setDialog({ type: "project" });
                      }}
                    >
                      <FolderPlus size={16} />
                      {t("新建研究")}
                    </button>
                    <button onClick={() => setQuery(">skill")}>
                      <Terminal size={16} />
                      {t("连接 Agent 与 Skill")}
                    </button>
                    <div className="dropdown-caption">{t("研究节点")}</div>
                  </>
                )}
                {project?.nodes
                  .filter((n) =>
                    `${n.title} ${n.summary} ${n.tags.join(" ")}`
                      .toLowerCase()
                      .includes(query.toLowerCase()),
                  )
                  .slice(0, 12)
                  .map((n) => (
                    <button key={n.id} onClick={() => selectNode(n.id)}>
                      <span
                        className={`tiny-dot ${n.status === "active" ? "accent" : ""}`}
                      />
                      <span>{n.title}</span>
                      <small>{kinds[n.kind] || n.kind}</small>
                    </button>
                  ))}
                {query &&
                  projects
                    .filter((p) =>
                      p.name.toLowerCase().includes(query.toLowerCase()),
                    )
                    .map((p) => (
                      <button
                        key={p.id}
                        onClick={() => {
                          void load(p.id);
                          setPalette(false);
                        }}
                      >
                        <FolderOpen size={16} />
                        {p.name}
                      </button>
                    ))}
              </div>
            )}
          </div>
        </div>
      )}
      {artifact && project && (
        <ArtifactDialog
          artifact={artifact}
          project={project}
          onClose={() => setArtifact(null)}
        />
      )}
      {history && project && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setHistory(null);
          }}
        >
          <div className="modal history-modal">
            <div className="modal-heading">
              <h2>{t("版本历史")}</h2>
              <IconButton label={t("关闭")} onClick={() => setHistory(null)}>
                <X size={17} />
              </IconButton>
            </div>
            <div className="history-list">
              {[...history].reverse().map((h, i) => (
                <div key={i}>
                  <History size={16} />
                  <div>
                    <strong>
                      {t("版本 {revision}", { revision: h.revision })}
                    </strong>
                    <span>
                      {date(h.at || h.updatedAt || h.createdAt)}
                      {h.message ? ` · ${h.message}` : ""}
                    </span>
                  </div>
                  <button
                    className="button subtle"
                    disabled={h.revision === project.revision}
                    onClick={async () => {
                      try {
                        const p = await api.restore(project, h.revision);
                        pRef.current = p;
                        setProject(p);
                        setHistory(null);
                        notify(t("已恢复为新版本"));
                      } catch (e) {
                        notify((e as Error).message);
                      }
                    }}
                  >
                    {h.revision === project.revision
                      ? t("当前版本")
                      : t("恢复")}
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
