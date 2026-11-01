import { t } from "../i18n";
import {
  ArrowRight,
  ArrowUpRight,
  Box,
  CheckCircle2,
  ChevronRight,
  Copy,
  FileText,
  FlaskConical,
  GitBranch,
  Lightbulb,
  Link2,
  Plus,
  Target,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  descendants,
  isResearchContainer,
  kinds,
  isExecutionRun,
  relations,
  statuses,
  type Artifact,
  type Operation,
  type Project,
  type ResearchNode,
  type NodeTab,
} from "../model";

import { Badge, date, IconButton, kindIcon } from "./Primitives";
import { NodeUsagePanel } from "./NodeUsagePanel";
import { ResearchNotes } from "./ResearchMarkdown";
import { MetricDetails } from "./MetricDetails";
import { QuestionOriginPanel } from "./QuestionOrigin";
import { nodePresentation } from "../node-presentation";
import { ProjectHostUsage } from "./HostUsage";
import {
  openResearchNodes,
  researchProgression,
} from "../research-progression";
import "./research-progression.css";
export function ProjectInspector({
  project,
  onAdd,
  onSelect,
  onClose,
}: {
  project: Project;
  onAdd: () => void;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const active = openResearchNodes(project);
  const decisions = project.decisions;
  const progression = researchProgression(project);
  const [allProgression, setAllProgression] = useState(false);
  useEffect(() => setAllProgression(false), [project.id]);
  const visibleProgression = allProgression
    ? progression
    : progression.slice(-5);
  return (
    <>
      <div className="inspector-heading">
        <span>
          <Target size={14} />
          {t("研究概览")}
        </span>
        <IconButton label={t("关闭详情")} onClick={onClose}>
          <X size={15} />
        </IconButton>
      </div>
      <div className="inspector-scroll">
        <h2 className="inspector-title">{project.name}</h2>
        <p className="inspector-summary">{project.description}</p>
        <div className="project-stats">
          <div>
            <strong>{project.nodes.length}</strong>
            <span>{t("研究节点")}</span>
          </div>
          <div>
            <strong>{project.runs.filter(isExecutionRun).length}</strong>
            <span>{t("实验运行")}</span>
          </div>
          <div>
            <strong>{project.artifacts.length}</strong>
            <span>{t("原始证据")}</span>
          </div>
        </div>
        <div className="inspector-section-title">
          <span>{t("已记录的判断变化")}</span>
          <span>
            {t("跨容器查看")} · {progression.length}
          </span>
        </div>
        {!progression.length && (
          <div className="small-empty">{t("尚无判断记录")}</div>
        )}
        <ol className="research-progression-list">
          {visibleProgression.map(({ node, path, createdAt }) => (
            <li key={node.id}>
              <button
                className="research-progression-entry"
                onClick={() => onSelect(node.id)}
              >
                <span className="research-progression-path">
                  {path.join(" / ") || t("项目顶层")}
                </span>
                <strong>{node.title}</strong>
                {node.conclusion?.trim() &&
                  node.conclusion.trim() !== node.title.trim() && (
                    <p>{node.conclusion}</p>
                  )}
                <span className="research-progression-meta">
                  <span>{createdAt ? date(createdAt) : t("按记录顺序")}</span>
                  <span>
                    {kinds[node.kind] ? t(kinds[node.kind]) : node.kind}{" "}
                    <ChevronRight size={11} />
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ol>
        {progression.length > 5 && (
          <button
            className="button wide subtle"
            aria-expanded={allProgression}
            onClick={() => setAllProgression(!allProgression)}
          >
            {allProgression
              ? t("仅看最近五条")
              : t("查看全部 {count} 条", { count: progression.length })}
          </button>
        )}
        <div className="inspector-section-title">
          <span>{t("暂停与开放事项")}</span>
          <span>{active.length}</span>
        </div>
        {active.map((n) => (
          <button
            className="active-path"
            key={n.id}
            onClick={() => onSelect(n.id)}
          >
            <span className="path-icon">
              <GitBranch size={15} />
            </span>
            <span>
              <strong>{n.title}</strong>
              <span className="research-open-status">
                <Badge status={n.status} />
              </span>
              <small>{n.pauseReason || n.nextAction || n.summary}</small>
            </span>
            <ChevronRight size={14} />
          </button>
        ))}
        {decisions.length > 0 && (
          <>
            <div className="inspector-section-title">
              <span>{t("最近结论")}</span>
            </div>
            {decisions.slice(-2).map((d) => (
              <div className="finding-summary" key={d.id}>
                <Lightbulb size={16} />
                <strong>{d.title}</strong>
                <p>{d.conclusion}</p>
                {d.nextAction && (
                  <div>
                    <ArrowRight size={12} />
                    {d.nextAction}
                  </div>
                )}
              </div>
            ))}
          </>
        )}
        <ProjectHostUsage project={project} />
        <button className="button wide subtle" onClick={onAdd}>
          <Plus size={14} />
          {t("继续探索")}
        </button>
      </div>
      <div className="inspector-bottom">
        <span className="tiny-dot accent" />
        {t("记录持续保存在本地")}
        <span>r{project.revision}</span>
      </div>
    </>
  );
}

const editableNodeStatuses = [
  "proposed",
  "active",
  "completed",
  "paused",
  "rejected",
  "failed",
];

export function NodeInspector({
  node,
  project,
  busy,
  tab,
  onTabChange,
  mutate,
  onClose,
  onBranch,
  onChild,
  onEnter,
  onDelete,
  onArtifact,
  onSelect,
  onConnect,
  onCopyReference,
}: {
  node: ResearchNode;
  project: Project;
  busy: boolean;
  tab: NodeTab;
  onTabChange: (tab: NodeTab) => void;
  mutate: (ops: Operation[]) => Promise<boolean>;
  onClose: () => void;
  onBranch: () => void;
  onChild: () => void;
  onEnter: () => void;
  onDelete: () => void;
  onArtifact: (a: Artifact) => void;
  onSelect: (id: string) => void;
  onConnect: () => void;
  onCopyReference: () => void;
}) {
  const [editing, setEditing] = useState(false),
    [draft, setDraft] = useState({ ...node });
  useEffect(() => {
    if (!editing) setDraft({ ...node });
  }, [node]);
  const runs = project.runs.filter((r) => r.nodeId === node.id);
  const presentation = nodePresentation(project, node);
  const relatedArtifacts = project.artifacts.filter(
    (a) =>
      a.nodeId === node.id ||
      runs.some((r) => r.id === a.runId || r.artifactIds.includes(a.id)),
  );
  const children = project.nodes.filter((n) => n.parentId === node.id);
  const Icon = kindIcon[node.kind] || Box;
  const save = async () => {
    if (!draft.title.trim()) return;
    if (
      await mutate([
        {
          op: "node.update",
          data: {
            id: node.id,
            title: draft.title,
            summary: draft.summary,
            conclusion: draft.conclusion || "",
            notes: draft.notes,
            nextAction: draft.nextAction,
            parentId: draft.parentId,
            isContainer: draft.isContainer ?? draft.kind === "group",
            tags:
              typeof draft.tags === "string"
                ? (draft.tags as string).split(",")
                : draft.tags,
            pauseReason: draft.pauseReason || "",
            resumeWhen: draft.resumeWhen || "",
          },
        },
      ])
    )
      setEditing(false);
  };
  return (
    <>
      <div className="inspector-heading">
        <span>
          <Icon size={14} />
          {kinds[node.kind] ? t(kinds[node.kind]) : node.kind}
        </span>
        <div>
          <IconButton label={t("复制节点引用")} onClick={onCopyReference}>
            <Copy size={14} />
          </IconButton>
          <IconButton label={t("新增子节点")} onClick={onChild}>
            <Plus size={14} />
          </IconButton>
          <IconButton label={t("关闭详情")} onClick={onClose}>
            <X size={15} />
          </IconButton>
        </div>
      </div>
      <div className="inspector-scroll">
        <div className="node-detail-title">
          {editing ? (
            <input
              autoFocus
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            />
          ) : (
            <h2>{node.title}</h2>
          )}
          <select
            aria-label={t("节点状态")}
            disabled={busy || editing}
            value={node.status}
            className={`status-select status-${node.status}`}
            onChange={(e) =>
              void mutate([
                {
                  op: "node.update",
                  data: { id: node.id, status: e.target.value },
                },
              ])
            }
          >
            {!editableNodeStatuses.includes(node.status) && (
              <option value={node.status}>
                {Object.hasOwn(statuses, node.status)
                  ? t(statuses[node.status])
                  : node.status || t("未记录")}
              </option>
            )}
            {editableNodeStatuses.map((s) => (
              <option key={s} value={s}>
                {t(statuses[s])}
              </option>
            ))}
          </select>
          {isResearchContainer(project.nodes, node) && (
            <button className="button" onClick={onEnter}>
              {t("进入容器")}
              <ChevronRight size={13} />
            </button>
          )}
        </div>
        <div className="detail-tabs">
          {[
            ["overview", t("概览")],
            ["runs", t("记录 {count}", { count: runs.length })],
            ["evidence", t("证据 {count}", { count: relatedArtifacts.length })],
            ["usage", t("用量")],
          ].map(([id, label]) => (
            <button
              key={id}
              className={tab === id ? "selected" : ""}
              onClick={() => onTabChange(id as NodeTab)}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === "usage" ? (
          <NodeUsagePanel
            project={project}
            node={node}
            busy={busy}
            mutate={mutate}
          />
        ) : tab === "overview" ? (
          <>
            {node.kind === "question" && (
              <QuestionOriginPanel
                node={node}
                project={project}
                busy={busy || editing}
                mutate={mutate}
                onSelect={onSelect}
                onArtifact={onArtifact}
              />
            )}
            {editing ? (
              <div className="edit-fields">
                <label>
                  {t("显示方式")}
                  <select
                    value={
                      children.length > 0 ||
                      (draft.isContainer ?? draft.kind === "group")
                        ? "container"
                        : "node"
                    }
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        isContainer: e.target.value === "container",
                      })
                    }
                  >
                    <option value="node" disabled={children.length > 0}>
                      {t("普通节点")}
                    </option>
                    <option value="container">{t("容器分组")}</option>
                  </select>
                </label>
                {node.status === "paused" && (
                  <>
                    <label>
                      {t("挂起原因")}
                      <textarea
                        value={draft.pauseReason || ""}
                        onChange={(e) =>
                          setDraft({ ...draft, pauseReason: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      {t("恢复条件")}
                      <textarea
                        value={draft.resumeWhen || ""}
                        onChange={(e) =>
                          setDraft({ ...draft, resumeWhen: e.target.value })
                        }
                      />
                    </label>
                  </>
                )}
                <label>
                  {t("结论")}
                  <textarea
                    placeholder={t("用一句话说明这一步发现了什么")}
                    value={draft.conclusion || ""}
                    onChange={(e) =>
                      setDraft({ ...draft, conclusion: e.target.value })
                    }
                  />
                </label>
                <label>
                  {t("摘要")}
                  <textarea
                    value={draft.summary}
                    onChange={(e) =>
                      setDraft({ ...draft, summary: e.target.value })
                    }
                  />
                </label>
                <label>
                  {t("详细记录")}
                  <textarea
                    rows={5}
                    value={draft.notes || ""}
                    onChange={(e) =>
                      setDraft({ ...draft, notes: e.target.value })
                    }
                  />
                </label>
                <label>
                  {t("下一步")}
                  <textarea
                    value={draft.nextAction || ""}
                    onChange={(e) =>
                      setDraft({ ...draft, nextAction: e.target.value })
                    }
                  />
                </label>
                <label>
                  {t("所属容器")}
                  <select
                    value={draft.parentId || ""}
                    onChange={(e) =>
                      setDraft({ ...draft, parentId: e.target.value || null })
                    }
                  >
                    <option value="">{t("项目根目录")}</option>
                    {project.nodes
                      .filter(
                        (n) =>
                          n.id !== node.id &&
                          !descendants(project.nodes, node.id).includes(n.id),
                      )
                      .map((n) => (
                        <option key={n.id} value={n.id}>
                          {n.title}
                        </option>
                      ))}
                  </select>
                </label>
                <div className="form-actions">
                  <button
                    className="button subtle"
                    onClick={() => setEditing(false)}
                  >
                    {t("取消")}
                  </button>
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => void save()}
                  >
                    {t("保存")}
                  </button>
                </div>
              </div>
            ) : (
              <>
                {presentation.source && (
                  <div className="node-context-note">
                    <strong>{presentation.source}</strong>
                    <p>
                      {presentation.conclusion ||
                        node.conclusion ||
                        node.summary}
                    </p>
                  </div>
                )}
                <p className="inspector-summary">
                  {node.summary || t("暂无摘要")}
                </p>
                {node.status === "paused" &&
                  (node.pauseReason || node.resumeWhen) && (
                    <div className="node-context-note pause-note">
                      {node.pauseReason && (
                        <>
                          <strong>{t("挂起原因")}</strong>
                          <p>{node.pauseReason}</p>
                        </>
                      )}
                      {node.resumeWhen && (
                        <>
                          <strong>{t("恢复条件")}</strong>
                          <p>{node.resumeWhen}</p>
                        </>
                      )}
                    </div>
                  )}
                {node.tags?.length > 0 && (
                  <div className="tags">
                    {node.tags.map((t) => (
                      <span key={t}>{t}</span>
                    ))}
                  </div>
                )}
                {node.notes && (
                  <ResearchNotes
                    key={node.id}
                    text={node.notes}
                    title={node.title}
                  />
                )}
                {node.nextAction && (
                  <div className="next-action">
                    <span>
                      <ArrowUpRight size={14} />
                      {t("下一步")}
                    </span>
                    <p>{node.nextAction}</p>
                  </div>
                )}
                <button
                  className="text-button edit-link"
                  onClick={() => setEditing(true)}
                >
                  <FileText size={13} />
                  {t("编辑记录")}
                </button>
              </>
            )}
            {children.length > 0 && (
              <>
                <div className="inspector-section-title">
                  <span>{t("子节点")}</span>
                  <span>{children.length}</span>
                </div>
                {children.map((n) => (
                  <button
                    key={n.id}
                    className="related-row"
                    onClick={() => onSelect(n.id)}
                  >
                    <Box size={13} />
                    <span>{n.title}</span>
                    <ChevronRight size={12} />
                  </button>
                ))}
              </>
            )}
            <div className="inspector-section-title">
              <span>{t("研究关系")}</span>
              <button onClick={onConnect}>
                <Plus size={13} />
              </button>
            </div>
            {project.edges
              .filter((e) => e.source === node.id || e.target === node.id)
              .map((e) => {
                const other = project.nodes.find(
                  (n) => n.id === (e.source === node.id ? e.target : e.source),
                );
                return (
                  <button
                    className="related-row"
                    key={e.id}
                    onClick={() => other && onSelect(other.id)}
                  >
                    <ArrowRight
                      size={13}
                      style={
                        e.target === node.id
                          ? { transform: "rotate(180deg)" }
                          : undefined
                      }
                    />
                    <span>
                      {other?.title}
                      <small>{e.label}</small>
                    </span>
                    <small>
                      {t(e.target === node.id ? "来自" : "指向")} ·{" "}
                      {relations[e.relation]
                        ? t(relations[e.relation])
                        : e.relation}
                    </small>
                  </button>
                );
              })}
            {project.decisions
              .filter((d) => d.nodeId === node.id)
              .map((d) => (
                <div className="finding-summary" key={d.id}>
                  <CheckCircle2 size={16} />
                  <strong>{d.title}</strong>
                  <p>{d.conclusion}</p>
                  <small>{d.scope}</small>
                </div>
              ))}
          </>
        ) : tab === "runs" ? (
          <>
            {runs.length ? (
              runs.map((r) => (
                <div className="inspector-run" key={r.id}>
                  <div>
                    <FlaskConical size={14} />
                    <strong>{r.title}</strong>
                    {!isExecutionRun(r) && <small>{t("结果记录")}</small>}
                    <Badge status={r.status} />
                  </div>
                  <MetricDetails metrics={r.metrics || {}} />
                  {project.assessments
                    .filter((a) => a.runId === r.id)
                    .map((a) => (
                      <details className="raw-metrics" key={a.id}>
                        <summary>
                          {t("评估")} · {a.rubric}
                        </summary>
                        {a.conclusion && <p>{a.conclusion}</p>}
                        <MetricDetails metrics={a.metrics} />
                      </details>
                    ))}
                  {r.events?.slice(-3).map((e) => (
                    <div className="mini-event" key={e.id}>
                      <span className="tiny-dot" />
                      {e.message}
                    </div>
                  ))}
                </div>
              ))
            ) : (
              <div className="small-empty">{t("暂无运行记录")}</div>
            )}
          </>
        ) : (
          <>
            {relatedArtifacts.length ? (
              relatedArtifacts.map((a) => (
                <button
                  className="artifact-row"
                  key={a.id}
                  onClick={() => onArtifact(a)}
                >
                  <FileText size={17} />
                  <span>
                    <strong>{a.title}</strong>
                    <small>
                      {a.bytes} bytes · {a.mime}
                    </small>
                  </span>
                  <ArrowUpRight size={13} />
                </button>
              ))
            ) : (
              <div className="small-empty">{t("暂无关联证据")}</div>
            )}
          </>
        )}
        <div className="metadata">
          <span>{t("节点标识")}</span>
          <code>{node.id}</code>
          {node.createdAt && (
            <>
              <span>{t("创建时间")}</span>
              <span>{date(node.createdAt)}</span>
            </>
          )}
        </div>
      </div>
      <div className="inspector-actions">
        <button className="button primary" onClick={onBranch}>
          <GitBranch size={14} />
          {t("从此处分支")}
        </button>
        <IconButton label={t("移除节点，可从历史恢复")} onClick={onDelete}>
          <Trash2 size={15} />
        </IconButton>
      </div>
    </>
  );
}

export function EdgeInspector({
  edge,
  mutate,
  onDelete,
}: {
  edge: any;
  mutate: (ops: Operation[]) => Promise<boolean>;
  onDelete: () => void;
}) {
  const [draft, setDraft] = useState(edge);
  useEffect(() => setDraft(edge), [edge]);
  return (
    <>
      <div className="inspector-heading">
        <span>
          <Link2 size={14} />
          {t("研究关系")}
        </span>
      </div>
      <div className="inspector-scroll edit-fields">
        {edge.provenance?.mode === "retrospective" && (
          <div className="node-context-note">
            <strong>{t("事后补充的关系")}</strong>
            <p>{edge.provenance.note}</p>
          </div>
        )}
        <label>
          {t("关系")}
          <select
            value={draft.relation}
            onChange={(e) => setDraft({ ...draft, relation: e.target.value })}
          >
            {Object.entries(relations).map(([k, v]) => (
              <option key={k} value={k}>
                {t(v)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("说明")}
          <input
            value={draft.label || ""}
            onChange={(e) => setDraft({ ...draft, label: e.target.value })}
          />
        </label>
        <label>
          {t("依据")}
          <select
            value={draft.basis || "unknown"}
            onChange={(e) => setDraft({ ...draft, basis: e.target.value })}
          >
            <option value="observed">{t("有记录支持")}</option>
            <option value="hypothesis">{t("待验证")}</option>
            <option value="unknown">{t("未知")}</option>
          </select>
        </label>
        <button
          className="button primary"
          onClick={() => void mutate([{ op: "edge.update", data: draft }])}
        >
          {t("保存关系")}
        </button>
        <button className="button danger" onClick={onDelete}>
          <Trash2 size={14} />
          {t("移除关系")}
        </button>
      </div>
    </>
  );
}
