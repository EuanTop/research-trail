import { t, useLocale } from "../i18n";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import {
  Activity,
  Box,
  ChevronDown,
  ChevronRight,
  Clock3,
  Layers,
  Minus,
} from "lucide-react";
import { kinds, type CanvasData } from "../model";
import type { NodePresentation } from "../node-presentation";
import { formatDuration, formatTokens } from "../usage";
import { originLabel } from "../question-origin";
import { Badge, kindIcon } from "./Primitives";

function UsageStats({ data }: { data: CanvasData }) {
  const usage = data.usage;
  const elapsed = usage?.isRunning
    ? t("计时中")
    : usage?.elapsedMs != null
      ? t("计时 {duration}", { duration: formatDuration(usage.elapsedMs) })
      : usage?.runMs != null
        ? t("执行 {duration}", { duration: formatDuration(usage.runMs) })
        : usage?.externalTaskMs != null
          ? t("任务跨度 {duration}", {
              duration: formatDuration(usage.externalTaskMs),
            })
          : usage?.externalReportedMs != null
            ? t("执行器 {duration}", {
                duration: formatDuration(usage.externalReportedMs),
              })
            : usage?.externalTaskRunning
              ? t("外部任务运行中")
              : t("计时 —");
  const tokens = `${usage?.tokenScope === "execution" ? t("执行 Token") : "Token"} ${formatTokens(usage?.totalTokens)}${usage?.totalTokens != null && usage.tokensPartial ? "+" : ""}`;
  return (
    <>
      <button
        className="node-stat nodrag"
        title={t("查看步骤计时与执行耗时")}
        onClick={(e) => {
          e.stopPropagation();
          data.onInspect?.(data.node.id, "usage");
        }}
      >
        <Clock3 size={10} />
        {elapsed}
      </button>
      <button
        className="node-stat nodrag"
        title={
          usage?.tokenScope === "execution"
            ? t("被测任务用量；查看输入与输出 Token 来源")
            : usage?.tokensPartial
              ? t("部分用量未采集；查看已记录的输入与输出 Token")
              : t("研究 Agent 用量；查看输入与输出 Token 来源")
        }
        onClick={(e) => {
          e.stopPropagation();
          data.onInspect?.(data.node.id, "usage");
        }}
      >
        {tokens}
      </button>
    </>
  );
}

export function ResearchCard({ data, selected }: NodeProps<Node<CanvasData>>) {
  useLocale();
  const { node: n, children, expanded } = data;
  const container = data.container === true;
  const Icon = container ? Layers : kindIcon[n.kind] || Box;
  const presentation: NodePresentation = data.presentation ?? {
    headline: n.title || t("未命名节点"),
    context: "",
    summary: n.summary || "",
    conclusion: "",
    source: "",
  };
  const processing = data.processing === true;
  const hasPause = !!(
    presentation.pauseReason ||
    presentation.resumeWhen ||
    presentation.nextAction
  );
  return (
    <div
      className={`research-node ${selected ? "is-selected" : ""} ${processing ? "is-processing" : ""} ${(container || !processing) && n.status === "failed" ? "state-failed" : ""} ${(container || !processing) && n.status === "paused" ? "state-paused" : ""} kind-${n.kind} ${expanded ? "container-expanded" : ""} ${container ? "is-container" : ""}`}
      aria-label={
        processing
          ? t("{title}，处理中", { title: presentation.headline })
          : undefined
      }
    >
      {processing && (
        <svg className="processing-outline" aria-hidden="true">
          <rect className="processing-outline-track" pathLength="100" />
          <rect className="processing-outline-blue" pathLength="100" />
          <rect className="processing-outline-green" pathLength="100" />
        </svg>
      )}
      {(
        [Position.Top, Position.Right, Position.Bottom, Position.Left] as const
      ).map((position) => (
        <Handle
          key={position}
          id={position}
          type="source"
          position={position}
        />
      ))}
      <div className="node-grip">
        <div className="node-type">
          <span className="node-kind-icon">
            <Icon size={13} />
          </span>
          {kinds[n.kind] ? t(kinds[n.kind]) : n.kind || t("研究节点")}
          {container && n.kind !== "group" ? t(" · 容器") : ""}
          {container && processing && (
            <span
              title={t("容器内有执行正在运行")}
              aria-label={t("内部执行中")}
            >
              <Activity size={12} />
            </span>
          )}
        </div>
        <Badge
          status={
            processing && !container ? "running" : n.status || t("未记录")
          }
        />
        {!expanded && container && children > 0 && (
          <button
            className="node-inline-expand nodrag"
            title={t("就地展开容器")}
            onClick={(e) => {
              e.stopPropagation();
              data.onToggle(n.id);
            }}
          >
            <ChevronDown size={13} />
          </button>
        )}
      </div>
      <div
        className={`node-content ${presentation.conclusion ? "has-conclusion" : ""} ${hasPause ? "has-pause" : ""}`}
      >
        <h3 title={presentation.headline}>{presentation.headline}</h3>
        {n.kind === "question" && !expanded && (
          <button
            className="node-origin-link nodrag"
            title={t("查看问题来源")}
            onClick={(event) => {
              event.stopPropagation();
              data.onInspect?.(n.id, "overview");
            }}
          >
            {t("来源")} · {originLabel(n)}
          </button>
        )}
        {!expanded && hasPause && (
          <div className="node-pause-details">
            {presentation.pauseReason && (
              <p title={presentation.pauseReason}>
                <span>{t("暂停：")}</span>
                {presentation.pauseReason}
              </p>
            )}
            {(presentation.resumeWhen || presentation.nextAction) && (
              <p title={presentation.resumeWhen || presentation.nextAction}>
                <span>
                  {presentation.resumeWhen ? t("恢复：") : t("下一步：")}
                </span>
                {presentation.resumeWhen || presentation.nextAction}
              </p>
            )}
          </div>
        )}
        {!expanded && presentation.summary && (
          <p title={presentation.summary}>{presentation.summary}</p>
        )}
        {!expanded && presentation.conclusion && (
          <p className="node-conclusion" title={presentation.conclusion}>
            {presentation.source || t("结论")}
            {t("：")}
            {presentation.conclusion}
          </p>
        )}
      </div>
      {expanded ? (
        <>
          <div className="container-actions nodrag">
            <span>{t("{count} 个节点", { count: children })}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                data.onToggle(n.id);
              }}
              title={t("折叠容器")}
            >
              <Minus size={12} />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                data.onEnter(n.id);
              }}
              title={t("进入容器")}
            >
              {t("进入")}
            </button>
          </div>
          <div className="container-usage">
            <UsageStats data={data} />
          </div>
        </>
      ) : (
        <div className="node-footer">
          {container ? (
            <button
              className="expand-link nodrag"
              onClick={(e) => {
                e.stopPropagation();
                data.onEnter(n.id);
              }}
            >
              <ChevronRight size={11} />
              {t("进入 · {count} 个节点", { count: children })}
            </button>
          ) : (
            <button
              className="node-stat nodrag"
              onClick={(e) => {
                e.stopPropagation();
                data.onInspect?.(n.id, "runs");
              }}
              title={
                data.usage?.externalTaskCount
                  ? t("查看命令执行与外部任务")
                  : t("查看平台捕获的命令执行")
              }
            >
              {(data.usage?.runCount ?? data.runs ?? 0) > 0
                ? t("{count} 次执行", {
                    count: data.usage?.runCount ?? data.runs ?? 0,
                  })
                : t("未采集执行")}
            </button>
          )}
          <UsageStats data={data} />
        </div>
      )}
    </div>
  );
}
