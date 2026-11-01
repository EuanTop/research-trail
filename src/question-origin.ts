import { t } from "./i18n";
import type { Project, QuestionOrigin, ResearchNode } from "./model";

export const originTypes: Record<string, string> = {
  goal: "目标拆解",
  finding: "发现引出",
  literature: "文献",
  user: "用户建议",
  independent: "独立探索",
};
export function questionOrigin(node: ResearchNode): QuestionOrigin | null {
  const origin = node.questionOrigin;
  return origin &&
    typeof origin === "object" &&
    typeof origin.type === "string" &&
    origin.type.trim()
    ? origin
    : null;
}
export function originLabel(node: ResearchNode) {
  const origin = questionOrigin(node);
  return origin
    ? Object.hasOwn(originTypes, origin.type)
      ? t(originTypes[origin.type])
      : origin.type
    : t("来源未记录");
}
export function originSources(project: Project, node: ResearchNode) {
  const origin = questionOrigin(node);
  const aliases = (project.nodeAliases ?? {}) as Record<string, string>;
  return [...new Set(origin?.nodeIds ?? [])].map((originalId) => {
    const id = aliases[originalId] || originalId;
    const source = project.nodes.find((candidate) => candidate.id === id);
    return { id, originalId, node: source };
  });
}
export function safeOriginUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}
