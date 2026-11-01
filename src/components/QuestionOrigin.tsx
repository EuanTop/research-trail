import { useEffect, useState } from "react";
import { ArrowUpRight, Link2 } from "lucide-react";
import { t } from "../i18n";
import type {
  Artifact,
  Operation,
  Project,
  QuestionOrigin,
  ResearchNode,
} from "../model";
import {
  originLabel,
  originSources,
  originTypes,
  questionOrigin,
  safeOriginUrl,
} from "../question-origin";
import "./question-origin.css";

export function QuestionOriginPanel({
  node,
  project,
  busy,
  mutate,
  onSelect,
  onArtifact,
}: {
  node: ResearchNode;
  project: Project;
  busy: boolean;
  mutate: (operations: Operation[]) => Promise<boolean>;
  onSelect: (id: string) => void;
  onArtifact: (artifact: Artifact) => void;
}) {
  const recorded = questionOrigin(node);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<QuestionOrigin>(recorded || { type: "" });
  const [error, setError] = useState("");
  const [customType, setCustomType] = useState(false);
  useEffect(() => {
    setEditing(false);
    setError("");
    setCustomType(false);
    setDraft(questionOrigin(node) || { type: "" });
  }, [node.id]);
  const sources = originSources(project, node);
  const url = safeOriginUrl(recorded?.url);
  return (
    <section className="question-origin" aria-label={t("问题来源")}>
      <div className="origin-heading">
        <strong>
          <Link2 size={13} />
          {t("问题来源")}
        </strong>
        {!editing && (
          <button
            className="text-button"
            disabled={busy}
            onClick={() => {
              setDraft(recorded || { type: "" });
              setCustomType(
                !!recorded && !Object.hasOwn(originTypes, recorded.type),
              );
              setEditing(true);
            }}
          >
            {t(recorded ? "编辑来源" : "补充来源")}
          </button>
        )}
      </div>
      {!editing ? (
        <>
          <div className="origin-state">
            <span>{originLabel(node)}</span>
            {recorded?.retrospective && <small>{t("事后补记")}</small>}
          </div>
          {recorded?.reason && <p>{recorded.reason}</p>}
          {sources.map(({ id, originalId, node: source }) =>
            source ? (
              <button
                className="origin-source"
                key={originalId}
                onClick={() => onSelect(id)}
              >
                <ArrowUpRight size={13} />
                <span>{source.title}</span>
              </button>
            ) : (
              <span className="origin-unresolved" key={originalId}>
                {t("来源暂不可用")} · {originalId}
              </span>
            ),
          )}
          {recorded?.artifactIds?.map((id) => {
            const artifact = project.artifacts.find(
              (candidate) => candidate.id === id,
            );
            return artifact ? (
              <button
                className="origin-source"
                key={id}
                onClick={() => onArtifact(artifact)}
              >
                {artifact.title || id}
              </button>
            ) : (
              <span className="origin-unresolved" key={id}>
                {t("来源暂不可用")} · {id}
              </span>
            );
          })}
          {url && (
            <a href={url} target="_blank" rel="noopener noreferrer">
              {t("打开来源链接")} <ArrowUpRight size={12} />
            </a>
          )}
          {recorded?.recordedAt && (
            <small className="origin-time">
              {t("来源记录于 {time}", {
                time: Number.isFinite(Date.parse(recorded.recordedAt))
                  ? new Date(recorded.recordedAt).toLocaleString()
                  : recorded.recordedAt,
              })}
            </small>
          )}
        </>
      ) : (
        <form
          className="origin-editor"
          onSubmit={(event) => {
            event.preventDefault();
            setError("");
            const value = draft.type.trim()
              ? {
                  ...draft,
                  type: draft.type.trim(),
                  recordedAt: new Date().toISOString(),
                }
              : null;
            if (!value && (!recorded || customType)) return;
            if (value && !value.url?.trim()) delete value.url;
            void mutate([
              {
                op: "node.update",
                data: { id: node.id, questionOrigin: value },
              },
            ])
              .then((saved) => {
                if (saved) setEditing(false);
                else setError(t("来源保存失败"));
              })
              .catch(() => setError(t("来源保存失败")));
          }}
        >
          <label>
            {t("来源类型")}
            <select
              value={customType ? "custom" : draft.type}
              onChange={(event) => {
                setCustomType(event.target.value === "custom");
                setDraft({
                  ...draft,
                  type:
                    event.target.value === "custom" ? "" : event.target.value,
                  nodeIds:
                    event.target.value === "independent" ? [] : draft.nodeIds,
                });
              }}
            >
              <option value="">{t("来源未记录")}</option>
              {Object.entries(originTypes).map(([type, label]) => (
                <option value={type} key={type}>
                  {t(label)}
                </option>
              ))}
              <option value="custom">{t("自定义来源")}</option>
            </select>
          </label>
          {customType && (
            <label>
              {t("自定义来源名称")}
              <input
                value={draft.type}
                onChange={(event) =>
                  setDraft({ ...draft, type: event.target.value })
                }
              />
            </label>
          )}
          {draft.type !== "independent" && (
            <label>
              {t("来源节点")}
              <select
                multiple
                size={4}
                value={draft.nodeIds || []}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    nodeIds: Array.from(event.target.selectedOptions).map(
                      (option) => option.value,
                    ),
                  })
                }
              >
                {(draft.nodeIds || [])
                  .filter(
                    (id) =>
                      !project.nodes.some((candidate) => candidate.id === id),
                  )
                  .map((id) => (
                    <option key={id} value={id}>
                      {t("来源暂不可用")} · {id}
                    </option>
                  ))}
                {project.nodes
                  .filter((candidate) => candidate.id !== node.id)
                  .map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {candidate.title}
                    </option>
                  ))}
              </select>
            </label>
          )}
          {(project.artifacts.length > 0 || !!draft.artifactIds?.length) && (
            <label>
              {t("来源证据")}
              <select
                multiple
                size={3}
                value={draft.artifactIds || []}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    artifactIds: Array.from(event.target.selectedOptions).map(
                      (option) => option.value,
                    ),
                  })
                }
              >
                {(draft.artifactIds || [])
                  .filter(
                    (id) =>
                      !project.artifacts.some(
                        (candidate) => candidate.id === id,
                      ),
                  )
                  .map((id) => (
                    <option key={id} value={id}>
                      {t("来源暂不可用")} · {id}
                    </option>
                  ))}
                {project.artifacts.map((artifact) => (
                  <option key={artifact.id} value={artifact.id}>
                    {artifact.title || artifact.id}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            {t("提出理由")}
            <textarea
              rows={2}
              value={draft.reason || ""}
              onChange={(event) =>
                setDraft({ ...draft, reason: event.target.value })
              }
            />
          </label>
          <label>
            {t("来源链接")}
            <input
              type="url"
              value={draft.url || ""}
              onChange={(event) =>
                setDraft({ ...draft, url: event.target.value })
              }
            />
          </label>
          <label className="origin-checkbox">
            <input
              type="checkbox"
              checked={draft.retrospective || false}
              onChange={(event) =>
                setDraft({ ...draft, retrospective: event.target.checked })
              }
            />
            {t("事后补记")}
          </label>
          {error && <p role="alert">{error}</p>}
          <div className="form-actions">
            <button
              className="button subtle"
              type="button"
              onClick={() => setEditing(false)}
            >
              {t("取消")}
            </button>
            <button
              className="button primary"
              disabled={
                busy || (!draft.type.trim() && (!recorded || customType))
              }
              type="submit"
            >
              {t("保存来源")}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
