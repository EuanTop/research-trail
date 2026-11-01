import { t } from "../i18n";
import { ArrowRight, Link2, X } from "lucide-react";
import { ancestry, relations, type Project, type ResearchEdge } from "../model";
import { IconButton } from "./Primitives";

export function BoundaryInspector({
  project,
  edges,
  onSelect,
  onEdit,
  onClose,
}: {
  project: Project;
  edges: ResearchEdge[];
  onSelect: (id: string) => void;
  onEdit: (id: string) => void;
  onClose: () => void;
}) {
  const path = (id: string) =>
    ancestry(project.nodes, id)
      .map((n) => n.title)
      .join(" / ");
  return (
    <>
      <div className="inspector-header">
        <span>
          <Link2 size={14} /> {t("边界关系 · {count}", { count: edges.length })}
        </span>
        <IconButton label={t("关闭关系详情")} onClick={onClose}>
          <X size={15} />
        </IconButton>
      </div>
      <div className="inspector-scroll boundary-relations">
        {edges.map((edge) => (
          <article key={edge.id}>
            <button
              className="boundary-endpoint"
              onClick={() => onSelect(edge.source)}
            >
              {path(edge.source)}
            </button>
            <div className="boundary-relation">
              <ArrowRight size={13} />
              {relations[edge.relation]
                ? t(relations[edge.relation])
                : edge.relation}
              {edge.label && <span>{edge.label}</span>}
            </div>
            <button
              className="boundary-endpoint"
              onClick={() => onSelect(edge.target)}
            >
              {path(edge.target)}
            </button>
            <button className="text-button" onClick={() => onEdit(edge.id)}>
              {t("查看原始关系")}
            </button>
          </article>
        ))}
      </div>
    </>
  );
}
