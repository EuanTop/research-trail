import { describe, expect, it } from "vitest";
import {
  descendants,
  boundaryRelations,
  effectiveAssessments,
  toCanvas,
  validateProject,
  NODE_SIZE,
  type Project,
  type ResearchNode,
} from "./model";
const n = (
  id: string,
  parentId: string | null = null,
  collapsed = false,
): ResearchNode => ({
  id,
  title: id,
  kind: "group",
  status: "active",
  parentId,
  summary: "",
  notes: "",
  nextAction: "",
  tags: [],
  position: { x: 10, y: 10 },
  collapsed,
});
const p = (nodes: ResearchNode[], edges: any[] = []): Project => ({
  id: "p",
  name: "p",
  description: "",
  revision: 1,
  createdAt: "",
  updatedAt: "",
  nodes,
  edges,
  runs: [],
  artifacts: [],
  assessments: [],
  decisions: [],
  activity: [],
});
const actions = { onToggle: () => {}, onEnter: () => {} };
describe("nested research graph", () => {
  it("treats existing logical parents as closed containers without changing research records", () => {
    const question = { ...n("q"), kind: "question", isContainer: false };
    const finding = { ...n("f", "q"), kind: "finding" };
    const project = p([question, finding]);
    const canvas = toCanvas(project, null, [], actions);
    expect(canvas.nodes.map((n) => n.id)).toEqual(["q"]);
    expect(canvas.nodes[0].data).toMatchObject({
      container: true,
      expanded: false,
      children: 1,
    });
    expect(canvas.nodes[0].style?.width).toBe(NODE_SIZE.w);
    expect(toCanvas(project, "q", [], actions).nodes.map((n) => n.id)).toEqual([
      "f",
    ]);
    expect(question.isContainer).toBe(false);
    expect(project.nodes[1].parentId).toBe("q");
  });
  it("opens only the requested nesting level and preserves custom node kinds", () => {
    const project = p([
      { ...n("group"), kind: "question", isContainer: true },
      { ...n("q", "group"), kind: "custom-analysis" },
      { ...n("f", "q"), kind: "finding" },
    ]);
    const canvas = toCanvas(project, null, [], actions, {
      expandedIds: new Set(["group"]),
    });
    expect(canvas.nodes.map((n) => n.id)).toEqual(["group", "q"]);
    expect(canvas.nodes[0].data.expanded).toBe(true);
    expect(canvas.nodes[1].parentId).toBe("group");
    expect(canvas.nodes[1].data.node.kind).toBe("custom-analysis");
    expect(canvas.nodes[1].data.expanded).toBe(false);
    expect(
      toCanvas(project, null, [], actions, {
        expandedIds: new Set(["group", "q"]),
      }).nodes.map((n) => n.id),
    ).toEqual(["group", "q", "f"]);
  });
  it("keeps capture order faint and unlabelled without inventing scientific relationships", () => {
    const project = p(
      [n("a"), n("b")],
      [
        {
          id: "order",
          source: "a",
          target: "b",
          relation: "recorded_after",
          label: "记录顺序",
          basis: "observed",
        },
      ],
    );
    const edge = toCanvas(project, null, [], actions).edges[0];
    expect(edge.label).toBe("");
    expect(edge.style?.opacity).toBeLessThan(0.5);
    expect(edge.data?.orderOnly).toBe(true);
    expect(project.edges[0].relation).toBe("recorded_after");
  });
  it("folds descendants while preserving cross-boundary relationships", () => {
    const project = p(
      [n("a", null, true), n("b", "a"), n("c", "b"), n("d")],
      [{ id: "e", source: "c", target: "d", relation: "supports" }],
    );
    const canvas = toCanvas(project, null, [], actions);
    expect(canvas.nodes.map((n) => n.id)).toEqual(["a", "d"]);
    expect(canvas.edges[0].source).toBe("a");
    expect(canvas.edges[0].target).toBe("d");
  });
  it("exposes scope-parent relations without inventing links between its children", () => {
    const edges = [
      {
        id: "goal-a",
        source: "goal",
        target: "a",
        relation: "branches",
        label: "Asset audit",
      },
      { id: "goal-b", source: "goal", target: "b", relation: "branches" },
      { id: "a-finding", source: "a", target: "finding", relation: "leads_to" },
      {
        id: "external-goal",
        source: "external",
        target: "goal",
        relation: "motivates",
      },
      {
        id: "finding-outside",
        source: "finding",
        target: "external",
        relation: "supports",
      },
    ];
    const project = p(
      [
        n("goal"),
        n("a", "goal"),
        n("b", "goal"),
        n("finding", "a"),
        n("external"),
      ],
      edges,
    );
    const before = JSON.stringify(project);
    const canvas = toCanvas(project, "goal", [], actions);
    expect(canvas.nodes.map((node) => node.id)).toEqual(["a", "b"]);
    expect(canvas.edges).toEqual([]);
    expect(boundaryRelations(project, "goal").map((edge) => edge.id)).toEqual([
      "goal-a",
      "goal-b",
      "external-goal",
      "finding-outside",
    ]);
    expect(boundaryRelations(project, "goal")[0]).toBe(edges[0]);
    expect(boundaryRelations(project, "a").map((edge) => edge.id)).toEqual([
      "goal-a",
      "a-finding",
      "finding-outside",
    ]);
    expect(JSON.stringify(project)).toBe(before);
  });
  it("shows descendants when entering a collapsed container", () => {
    const project = p([n("a", null, true), n("b", "a"), n("c", "b")]);
    expect(toCanvas(project, "a", [], actions).nodes.map((n) => n.id)).toEqual([
      "b",
    ]);
    expect(toCanvas(project, "b", [], actions).nodes.map((n) => n.id)).toEqual([
      "c",
    ]);
  });
  it("keeps arbitrary containment independent of semantic cycles", () => {
    const project = p(
      [n("a"), n("b", "a"), n("c", "b")],
      [
        { id: "ab", source: "a", target: "c", relation: "tests" },
        { id: "ca", source: "c", target: "a", relation: "revisits" },
      ],
    );
    expect(validateProject(project)).toEqual([]);
    expect(descendants(project.nodes, "a")).toEqual(["b", "c"]);
  });
  it("rejects containment cycles", () => {
    expect(
      validateProject(p([n("a", "b"), n("b", "a")])).length,
    ).toBeGreaterThan(0);
  });
  it("does not count re-evaluation as a new execution", () => {
    const project = p([]);
    project.assessments = [
      {
        id: "v1",
        runId: "r",
        rubric: "q",
        metrics: {},
        conclusion: "",
        limitations: "",
      },
      {
        id: "v2",
        runId: "r",
        rubric: "q",
        metrics: {},
        conclusion: "",
        limitations: "",
        supersedes: "v1",
      },
    ];
    expect(effectiveAssessments(project).map((a) => a.id)).toEqual(["v2"]);
    expect(project.runs).toHaveLength(0);
  });
  it("assigns separate reciprocal lanes after collapsing hidden endpoints", () => {
    const project = p(
      [n("a", null, true), n("child", "a"), n("b")],
      [
        { id: "out", source: "child", target: "b", relation: "supports" },
        { id: "back", source: "b", target: "child", relation: "revisits" },
      ],
    );
    const { edges } = toCanvas(project, null, [], actions);
    expect(edges.map((edge) => [edge.source, edge.target])).toEqual([
      ["a", "b"],
      ["b", "a"],
    ]);
    expect(edges[0].data?.lane).not.toBe(edges[1].data?.lane);
  });
});
