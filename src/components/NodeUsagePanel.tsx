import { t } from "../i18n";
import { Clock3, Play, Square } from "lucide-react";
import {
  getNodeUsage,
  formatDuration,
  formatTokens,
  formatUsageTime,
} from "../usage";
import { uid, type Operation, type Project, type ResearchNode } from "../model";
import { UsageCollection } from "./UsageCollection";
import { NodeHostUsage } from "./HostUsage";

export function NodeUsagePanel({
  project,
  node,
  busy,
  mutate,
}: {
  project: Project;
  node: ResearchNode;
  busy: boolean;
  mutate: (operations: Operation[]) => Promise<boolean>;
}) {
  const usage = getNodeUsage(project, node.id);
  const ownRunning = usage.observations.filter(
    (o) => o.nodeId === node.id && o.status === "running",
  );
  const children = project.nodes.some((n) => n.parentId === node.id);
  return (
    <div className="node-usage-panel">
      <div className="usage-summary">
        <div>
          <span>{t("记录计时")}</span>
          <strong>
            {usage.elapsedMs === null
              ? t("未采集")
              : formatDuration(usage.elapsedMs)}
            {usage.elapsedPartial && usage.elapsedMs !== null ? "+" : ""}
          </strong>
        </div>
        <div>
          <span>{t("输入 Token")}</span>
          <strong>
            {usage.inputTokens === null
              ? t("未采集")
              : formatTokens(usage.inputTokens)}
          </strong>
        </div>
        <div>
          <span>{t("输出 Token")}</span>
          <strong>
            {usage.outputTokens === null
              ? t("未采集")
              : formatTokens(usage.outputTokens)}
          </strong>
        </div>
      </div>
      <p className="usage-scope">
        {usage.tokenScope === null
          ? t("暂无可归属用量")
          : usage.tokenScope === "execution"
            ? t("被测任务用量")
            : t("研究 Agent 用量")}
      </p>
      <div className="usage-scope">
        <span>
          {children
            ? t("含子节点，重叠计时已合并")
            : usage.isRunning
              ? t("计时中")
              : t("已记录用量")}
        </span>
        {usage.commandRunCount > 0 && (
          <span>
            {t("{count} 次运行 · 执行 {duration}", {
              count: usage.commandRunCount,
              duration:
                usage.runMs === null
                  ? t("未采集")
                  : formatDuration(usage.runMs),
            })}
          </span>
        )}
      </div>
      {usage.externalTaskCount > 0 && (
        <div className="usage-scope">
          <span>
            {t("{count} 个外部任务", { count: usage.externalTaskCount })}
          </span>
          <span>
            {t("任务起止跨度 {duration}", {
              duration: formatDuration(usage.externalTaskMs),
            })}
          </span>
          {usage.externalReportedMs !== null && (
            <span>
              {t("执行器报告耗时 {duration}", {
                duration: formatDuration(usage.externalReportedMs),
              })}
            </span>
          )}
          {usage.externalTaskRunning && <span>{t("外部任务运行中")}</span>}
        </div>
      )}
      {usage.tokensPartial && usage.totalTokens !== null && (
        <div className="usage-scope">{t("部分 Token 未采集")}</div>
      )}
      <button
        className="button wide"
        disabled={busy || ownRunning.length > 0}
        onClick={() =>
          void mutate([
            {
              op: "observation.start",
              data: { id: uid("obs"), nodeId: node.id, title: node.title },
            },
          ])
        }
      >
        <Play size={12} />
        {t("开始计时")}
      </button>
      {!usage.observations.length && !usage.hostUsage.length && (
        <div className="small-empty">
          {t("该节点尚无可确认归属的步骤计时或 Token 数据")}
        </div>
      )}
      <UsageCollection projectId={project.id} />
      <NodeHostUsage records={usage.hostUsage} />
      {usage.observations.map((o) => (
        <div className="observation-card" key={o.id}>
          <div className="observation-title">
            <Clock3 size={12} />
            <strong>{o.title}</strong>
            <span>
              {o.status === "running"
                ? t("计时中")
                : formatDuration(o.durationMs)}
            </span>
          </div>
          {o.nodeId !== node.id && (
            <div className="observation-node">
              {project.nodes.find((n) => n.id === o.nodeId)?.title}
            </div>
          )}
          <div className="observation-tokens">
            <span>
              {t("输入 {count}", { count: formatTokens(o.inputTokens) })}
            </span>
            <span>
              {t("输出 {count}", { count: formatTokens(o.outputTokens) })}
            </span>
          </div>
          <div className="observation-meta">
            <time>{formatUsageTime(o.startedAt)}</time>
            <span>{o.usageSource || t("Token 未采集")}</span>
            {o.usageRef && <span>{o.usageRef}</span>}
          </div>
          {o.nodeId === node.id && o.status === "running" && (
            <button
              className="button subtle wide"
              disabled={busy}
              onClick={() =>
                void mutate([{ op: "observation.finish", data: { id: o.id } }])
              }
            >
              <Square size={11} />
              {t("结束计时")}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
