import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ReactFlowProvider } from "@xyflow/react";
import { afterEach, expect, it } from "vitest";
import { setLocale } from "./i18n";
import { toCanvas, type Project, type ResearchNode } from "./model";
import {
  originLabel,
  originSources,
  questionOrigin,
  safeOriginUrl,
} from "./question-origin";
import { QuestionOriginPanel } from "./components/QuestionOrigin";
import { BoundaryInspector } from "./components/BoundaryInspector";
import { NodeInspector } from "./components/Inspectors";
import { ResearchCard } from "./components/ResearchCard";

function node(id: string, parentId: string | null = null): ResearchNode {
  return {
    id,
    title: `Title of ${id}`,
    parentId,
    kind: "question",
    status: "paused",
    summary: "",
    notes: "",
    nextAction: "",
    tags: [],
    position: { x: 0, y: 0 },
    collapsed: true,
  };
}
function project(): Project {
  return {
    id: "study",
    name: "Study",
    description: "",
    revision: 1,
    createdAt: "",
    updatedAt: "",
    nodes: [
      node("goal"),
      node("question", "goal"),
      node("finding", "question"),
    ],
    edges: [
      {
        id: "goal-question",
        source: "goal",
        target: "question",
        relation: "branches",
        label: "Asset availability before replication",
      },
    ],
    runs: [],
    artifacts: [],
    assessments: [],
    decisions: [],
    activity: [],
  };
}
function renderOrigin(p: Project) {
  return renderToStaticMarkup(
    createElement(QuestionOriginPanel, {
      node: p.nodes[1],
      project: p,
      busy: false,
      mutate: async () => {
        throw Error("Rendering cannot rewrite provenance");
      },
      onSelect() {},
      onArtifact() {},
    }),
  );
}
afterEach(() => setLocale("en"));

it("keeps unknown provenance distinct from containment, existing links and explicit independent exploration", () => {
  const p = project();
  const before = JSON.stringify(p);
  expect(questionOrigin(p.nodes[1])).toBeNull();
  expect(originLabel(p.nodes[1])).toBe("Source not recorded");
  const unknown = renderOrigin(p);
  expect(unknown).toContain("Source not recorded");
  expect(unknown).toContain("Add origin");
  expect(unknown).not.toContain("Independent exploration");
  expect(JSON.stringify(p)).toBe(before);
  p.nodes[1].questionOrigin = {
    type: "independent",
    reason: "An unrelated hypothesis worth testing",
  };
  expect(renderOrigin(p)).toContain("Independent exploration");
  expect(renderOrigin(p)).toContain("An unrelated hypothesis worth testing");
});

it("resolves recorded ancestor and nested sources, preserves missing IDs, custom types and retrospective context", () => {
  const p = project();
  p.nodeAliases = { oldGoal: "goal" };
  p.nodes[1].questionOrigin = {
    type: "reproduction audit",
    nodeIds: ["oldGoal", "finding", "deleted-source", "oldGoal"],
    artifactIds: ["deleted-artifact"],
    reason: "Asset inventory from the original goal",
    retrospective: true,
    recordedAt: "2026-11-02T01:00:00Z",
    url: "https://example.org/paper",
  };
  const before = JSON.stringify(p);
  expect(
    originSources(p, p.nodes[1]).map((source) => [
      source.originalId,
      source.id,
      source.node?.title,
    ]),
  ).toEqual([
    ["oldGoal", "goal", "Title of goal"],
    ["finding", "finding", "Title of finding"],
    ["deleted-source", "deleted-source", undefined],
  ]);
  const html = renderOrigin(p);
  for (const label of [
    "Title of goal",
    "Title of finding",
    "Source unavailable",
    "deleted-source",
    "deleted-artifact",
    "Recorded retrospectively",
    "reproduction audit",
    "Asset inventory from the original goal",
    "Edit origin",
  ])
    expect(html).toContain(label);
  expect(html).toContain('href="https://example.org/paper"');
  expect(JSON.stringify(p)).toBe(before);
  setLocale("zh-CN");
  expect(renderOrigin(p)).toContain("事后补记");
});

it("does not turn arbitrary source links into executable links or translate custom names", () => {
  const p = project();
  p.nodes[1].questionOrigin = {
    type: "constructor",
    url: "javascript:alert(1)",
  };
  expect(originLabel(p.nodes[1])).toBe("constructor");
  expect(renderOrigin(p)).not.toContain('href="javascript:');
  expect(safeOriginUrl("https://example.org")).toBe("https://example.org/");
  expect(safeOriginUrl("file:///tmp/source")).toBeNull();
});

it("shows a compact question-card origin control rather than a warning on every node type", () => {
  const p = project();
  const renderCard = (index: number) => {
    const data = toCanvas(p, index === 0 ? null : "goal", [], {
      onToggle() {},
      onEnter() {},
      onInspect() {},
    }).nodes[0].data;
    return renderToStaticMarkup(
      createElement(
        ReactFlowProvider,
        null,
        createElement(ResearchCard, { data, selected: false } as Parameters<
          typeof ResearchCard
        >[0]),
      ),
    );
  };
  expect(renderCard(1)).toContain('title="View question origin"');
  expect(renderCard(1)).toContain("Origin · Source not recorded");
  p.nodes[1].kind = "finding";
  expect(renderCard(1)).not.toContain('title="View question origin"');
});

it("shows formal relation direction and type alongside the user's explanation", () => {
  const p = project();
  const boundary = renderToStaticMarkup(
    createElement(BoundaryInspector, {
      project: p,
      edges: p.edges,
      onSelect() {},
      onEdit() {},
      onClose() {},
    }),
  );
  expect(boundary).toContain("Branch");
  expect(boundary).toContain("Asset availability before replication");
  expect(boundary.indexOf("Title of goal")).toBeLessThan(
    boundary.indexOf("Title of question"),
  );
  const renderInspector = () =>
    renderToStaticMarkup(
      createElement(NodeInspector, {
        node: p.nodes[1],
        project: p,
        busy: false,
        tab: "overview",
        onTabChange() {},
        mutate: async () => true,
        onClose() {},
        onBranch() {},
        onChild() {},
        onEnter() {},
        onDelete() {},
        onArtifact() {},
        onSelect() {},
        onConnect() {},
        onCopyReference() {},
      }),
    );
  const html = renderInspector();
  expect(html).toContain("From · Branch");
  expect(html).toContain("Asset availability before replication");
  expect(html).toContain("Source not recorded");
  p.edges[0].relation = "replication-prerequisite";
  expect(renderInspector()).toContain("From · replication-prerequisite");
});
