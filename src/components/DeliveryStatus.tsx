import {
  Check,
  CircleHelp,
  CheckCircle2,
  CloudUpload,
  RefreshCw,
  TriangleAlert,
  X,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type DeliverySnapshot } from "../api";
import { formatUsageTime } from "../usage";
import { t, useLocale } from "../i18n";
import "./delivery-status.css";

type Indicator = "blocked" | "pending" | "unknown" | "synced";
export function deliveryIndicator(
  snapshot: DeliverySnapshot | null,
  failed = false,
): Indicator {
  if (
    snapshot?.available &&
    (snapshot.blockedCount > 0 || snapshot.interruptedCount > 0)
  )
    return "blocked";
  if (snapshot?.available && snapshot.pendingCount > 0) return "pending";
  if (
    failed ||
    !snapshot?.available ||
    snapshot.discoveryComplete !== true ||
    snapshot.state !== "synced"
  )
    return "unknown";
  return "synced";
}
const labels: Record<Indicator, string> = {
  blocked: "记录待处理",
  pending: "记录待同步",
  unknown: "同步状态未知",
  synced: "Agent 记录已同步",
};
const itemLabels = {
  pending: "待同步",
  blocked: "同步失败",
  interrupted: "记录未完成",
};

export function DeliveryDetails({
  snapshot,
  fetchError,
  workspaceError,
  busy,
  retrying,
  retryError,
  onRetry,
  onRefresh,
}: {
  snapshot: DeliverySnapshot | null;
  fetchError: string;
  workspaceError: string;
  busy: boolean;
  retrying: string | null;
  retryError: string;
  onRetry: (taskId?: string) => void;
  onRefresh: () => void;
}) {
  const retryable = snapshot?.items.some(
    (item) => item.state === "pending" || item.state === "blocked",
  );
  return (
    <>
      <div className="delivery-workspace">
        <strong>{t("页面保存")}</strong>
        <span>
          {workspaceError
            ? t("页面连接异常")
            : busy
              ? t("保存中")
              : t("页面已保存")}
        </span>
        {workspaceError && <p role="alert">{workspaceError}</p>}
      </div>
      <section className="delivery-agent">
        <div className="delivery-section-heading">
          <h3>{t("Agent 记录送达")}</h3>
          <button
            className="icon-button"
            onClick={onRefresh}
            aria-label={t("刷新同步状态")}
            title={t("刷新同步状态")}
          >
            <RefreshCw size={14} />
          </button>
        </div>
        <p className="delivery-scope">{t("已连接的工作目录")}</p>
        {fetchError && (
          <p className="delivery-error" role="alert">
            {t("无法检查记录送达状态")} · {fetchError}
          </p>
        )}
        {!fetchError &&
          (!snapshot?.available || snapshot.discoveryComplete !== true) && (
            <p className="delivery-scope">{t("尚未完成工作目录检查")}</p>
          )}
        {snapshot?.available && (
          <>
            <dl className="delivery-counts">
              <div>
                <dt>{t("待同步")}</dt>
                <dd>{snapshot.pendingCount}</dd>
              </div>
              <div>
                <dt>{t("同步失败")}</dt>
                <dd>{snapshot.blockedCount}</dd>
              </div>
              <div>
                <dt>{t("记录未完成")}</dt>
                <dd>{snapshot.interruptedCount}</dd>
              </div>
            </dl>
            {deliveryIndicator(snapshot, !!fetchError) === "synced" && (
              <p className="delivery-clear">
                <Check size={14} />
                {t("已连接工作目录的记录均已送达")}
              </p>
            )}
          </>
        )}
        {retryError && (
          <p className="delivery-error" role="alert">
            {retryError}
          </p>
        )}
        {snapshot?.items.map((item) => (
          <article
            className={`delivery-item delivery-item-${item.state}`}
            key={item.taskId}
          >
            <div>
              <strong>{item.title || item.nodeId || item.taskId}</strong>
              <span>
                {t(
                  item.retryable === false
                    ? "需要修复"
                    : itemLabels[item.state],
                )}
              </span>
            </div>
            {!!item.waitingFor?.length && (
              <div className="delivery-dependencies">
                <span>{t("等待前置记录")}</span>
                {item.waitingFor.map((dependency) => (
                  <div key={dependency.taskId}>
                    <strong>{dependency.title || t("前置研究记录")}</strong>
                    <button
                      className="button subtle"
                      disabled={retrying !== null}
                      onClick={() => onRetry(dependency.taskId)}
                    >
                      {retrying === dependency.taskId
                        ? t("重试中")
                        : t("送达前置记录")}
                    </button>
                  </div>
                ))}
              </div>
            )}
            {item.lastError && (
              <p className="delivery-error">
                <code>{item.lastError.code}</code> {item.lastError.message}
              </p>
            )}
            <div className="delivery-item-footer">
              <small>
                {t("已尝试 {count} 次", { count: item.attempts })}
                {item.retryable !== false &&
                  item.nextAttemptAt &&
                  Number.isFinite(Date.parse(item.nextAttemptAt)) && (
                    <span>
                      {t("下次重试 {time}", {
                        time: formatUsageTime(item.nextAttemptAt),
                      })}
                    </span>
                  )}
              </small>
              {item.state !== "interrupted" && (
                <button
                  className="button subtle"
                  disabled={retrying !== null}
                  onClick={() => onRetry(item.taskId)}
                >
                  {retrying === item.taskId
                    ? t("重试中")
                    : t(item.retryable === false ? "重新检查送达" : "重试送达")}
                </button>
              )}
            </div>
          </article>
        ))}
        {retryable && (
          <button
            className="button primary delivery-retry-all"
            disabled={retrying !== null}
            onClick={() => onRetry()}
          >
            <RefreshCw size={13} />
            {retrying === "*" ? t("重试中") : t("重试待送达记录")}
          </button>
        )}
        {retryable && (
          <p className="delivery-scope">
            {t("仅重新发送已冻结的记录，不重新运行实验。")}
          </p>
        )}
      </section>
    </>
  );
}

function DeliveryDialog({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useId();
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return createPortal(
    <dialog
      ref={dialog}
      className="delivery-dialog"
      aria-labelledby={heading}
      onKeyDown={(event) => event.stopPropagation()}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header>
        <h2 id={heading}>{t("保存与同步")}</h2>
        <button
          autoFocus
          className="icon-button"
          aria-label={t("关闭同步详情")}
          onClick={onClose}
        >
          <X size={17} />
        </button>
      </header>
      <div className="delivery-dialog-body">{children}</div>
    </dialog>,
    document.body,
  );
}

type State = {
  projectId: string;
  snapshot: DeliverySnapshot | null;
  error: string;
};
export function DeliveryStatus({
  projectId,
  error,
  busy,
}: {
  projectId?: string;
  error: string;
  busy: boolean;
}) {
  useLocale();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<State>({
    projectId: "",
    snapshot: null,
    error: "",
  });
  const [refresh, setRefresh] = useState(0);
  const [retry, setRetry] = useState<{
    projectId: string;
    taskId: string | null;
    error: string;
  }>({ projectId: "", taskId: null, error: "" });
  const generation = useRef(0);
  const currentProject = useRef(projectId);
  currentProject.current = projectId;
  const retryController = useRef<AbortController | null>(null);
  useEffect(() => {
    const version = ++generation.current;
    let controller: AbortController | null = null;
    let pending = false;
    setState({ projectId: projectId || "", snapshot: null, error: "" });
    setRetry({ projectId: projectId || "", taskId: null, error: "" });
    const poll = async () => {
      if (!projectId || pending || document.hidden) return;
      pending = true;
      controller = new AbortController();
      try {
        const snapshot = await api.deliveryStatus(projectId, controller.signal);
        if (version === generation.current && snapshot.projectId === projectId)
          setState({ projectId, snapshot, error: "" });
      } catch (caught) {
        if (version === generation.current && !controller.signal.aborted)
          setState((previous) => ({
            projectId,
            snapshot:
              previous.projectId === projectId ? previous.snapshot : null,
            error: (caught as Error).message,
          }));
      } finally {
        pending = false;
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 15000);
    const visible = () => {
      if (!document.hidden) void poll();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      generation.current++;
      controller?.abort();
      retryController.current?.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [projectId, refresh]);
  const snapshot = state.projectId === projectId ? state.snapshot : null;
  const fetchError = state.projectId === projectId ? state.error : "";
  const retrying = retry.projectId === projectId ? retry.taskId : null;
  const retryError = retry.projectId === projectId ? retry.error : "";
  const runRetry = async (taskId?: string) => {
    if (!projectId || retrying !== null) return;
    const target = projectId;
    const version = generation.current;
    const controller = new AbortController();
    retryController.current = controller;
    setRetry({ projectId: target, taskId: taskId || "*", error: "" });
    try {
      await api.retryDelivery(target, taskId, controller.signal);
      if (
        !controller.signal.aborted &&
        currentProject.current === target &&
        version === generation.current
      )
        setRefresh((value) => value + 1);
    } catch (caught) {
      if (
        !controller.signal.aborted &&
        currentProject.current === target &&
        version === generation.current
      )
        setRetry({
          projectId: target,
          taskId: null,
          error: (caught as Error).message,
        });
    }
  };
  const indicator = deliveryIndicator(snapshot, !!fetchError);
  const attention = indicator === "blocked" || indicator === "pending";
  const label = attention
    ? labels[indicator]
    : error
      ? "页面连接异常"
      : busy
        ? "保存中"
        : labels[indicator];
  const Icon =
    indicator === "blocked" || (!attention && !!error)
      ? TriangleAlert
      : indicator === "pending"
        ? CloudUpload
        : indicator === "synced"
          ? CheckCircle2
          : CircleHelp;
  const count =
    (snapshot?.blockedCount || 0) +
    (snapshot?.pendingCount || 0) +
    (snapshot?.interruptedCount || 0);
  return (
    <>
      <button
        className={`delivery-trigger delivery-${indicator}`}
        onClick={() => setOpen(true)}
        aria-label={t(label)}
        title={t(label)}
      >
        <Icon size={14} />
        <span className="delivery-trigger-label">{t(label)}</span>
        {count > 0 && <span className="delivery-trigger-count">{count}</span>}
      </button>
      {open && (
        <DeliveryDialog onClose={() => setOpen(false)}>
          <DeliveryDetails
            snapshot={snapshot}
            fetchError={fetchError}
            workspaceError={error}
            busy={busy}
            retrying={retrying}
            retryError={retryError}
            onRetry={(taskId) => void runRetry(taskId)}
            onRefresh={() => setRefresh((value) => value + 1)}
          />
        </DeliveryDialog>
      )}
    </>
  );
}
