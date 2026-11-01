import { beforeEach, describe, expect, it } from "vitest";
import { setLocale } from "./i18n";

beforeEach(() => setLocale("zh-CN"));
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NodeHostUsage } from "./components/HostUsage";
import { NodeUsagePanel } from "./components/NodeUsagePanel";
import type {
  HostUsageRecord,
  Observation,
  Project,
  ResearchNode,
  Run,
} from "./model";
import {
  formatDuration,
  formatTokens,
  formatUsageTime,
  getNodeUsage,
  getProjectHostUsage,
} from "./usage";

function node(
  id: string,
  parentId: string | null = null,
  status = "completed",
  kind = "experiment",
): ResearchNode {
  return {
    id,
    parentId,
    status,
    kind,
    title: id,
    summary: "",
    notes: "",
    nextAction: "",
    tags: [],
    position: { x: 0, y: 0 },
    collapsed: false,
  };
}
function observation(
  id: string,
  nodeId: string,
  start = 0,
  end = 1000,
  fields: Partial<Observation> = {},
): Observation {
  return {
    id,
    nodeId,
    title: id,
    status: "finished",
    startedAt: new Date(start).toISOString(),
    finishedAt: new Date(end).toISOString(),
    durationMs: end - start,
    inputTokens: 10,
    outputTokens: 5,
    usageSource: "provider",
    origin: "observed",
    ...fields,
  };
}
function run(id: string, nodeId: string, metrics: Run["metrics"]): Run {
  return {
    id,
    nodeId,
    title: id,
    status: "completed",
    configuration: {},
    metrics,
    startedAt: "",
    events: [],
    artifactIds: [],
    origin: "observed",
  };
}
function project(
  nodes: ResearchNode[],
  observations?: Observation[],
  runs: Run[] = [],
): Project {
  return {
    id: "study",
    name: "",
    description: "",
    revision: 0,
    createdAt: "",
    updatedAt: "",
    nodes,
    observations,
    runs,
    edges: [],
    artifacts: [],
    assessments: [],
    decisions: [],
    activity: [],
  };
}

function hostUsage(
  id: string,
  nodeId: string | null,
  fields: Partial<HostUsageRecord> = {},
): HostUsageRecord {
  return {
    id,
    nodeId,
    source: "host",
    sourceRef: id,
    provider: "provider",
    model: "model",
    inputTokens: 100,
    outputTokens: 20,
    cacheReadTokens: 80,
    cacheWriteTokens: 0,
    startedAt: new Date(0).toISOString(),
    finishedAt: new Date(1000).toISOString(),
    ...fields,
  };
}

describe("host usage attribution", () => {
  it("separates scopes even for the same provider/model and prefers agent counters including zero", () => {
    const p = project([node("a")]);
    p.usageRecords = [
      hostUsage("agent", "a", { inputTokens: 0, outputTokens: 0 }),
      hostUsage("execution", "a", {
        scope: "execution",
        inputTokens: 900,
        outputTokens: 50,
      }),
    ];
    expect(getNodeUsage(p, "a")).toMatchObject({
      tokenScope: "agent",
      totalTokens: 0,
      cacheReadTokens: 80,
      tokensPartial: false,
    });
    expect(getNodeUsage(p, "a").hostUsage).toHaveLength(2);
    expect(getProjectHostUsage(p)).toMatchObject({
      inputTokens: 0,
      outputTokens: 0,
      models: [
        { scope: "agent", inputTokens: 0, outputTokens: 0 },
        { scope: "execution", inputTokens: 900, outputTokens: 50 },
      ],
    });
  });

  it("uses execution counters only when no actual agent counters exist, and retains unknown model/time", () => {
    const p = project(
      [node("a")],
      [
        observation("timer", "a", 0, 1000, {
          inputTokens: null,
          outputTokens: null,
        }),
      ],
    );
    p.usageRecords = [
      hostUsage("exec", "a", {
        scope: "execution",
        model: "",
        startedAt: null,
        finishedAt: null,
      }),
    ];
    expect(getNodeUsage(p, "a")).toMatchObject({
      tokenScope: "execution",
      totalTokens: 120,
      tokensPartial: false,
      elapsedMs: 1000,
    });
    expect(getProjectHostUsage(p)).toMatchObject({
      inputTokens: null,
      outputTokens: null,
      models: [{ scope: "execution", model: "" }],
    });
    const html = renderToStaticMarkup(
      createElement(NodeHostUsage, { records: p.usageRecords }),
    );
    expect(html).toContain("被测任务用量");
    expect(html).toContain("未知模型");
    expect(html.match(/未提供/g)).toHaveLength(2);
    expect(html).toContain("exec");
    expect(html).toContain("缓存读取");
    expect(html).not.toContain("1970");
  });

  it("treats manual observations as agent and does not deduplicate against an execution source reference", () => {
    const p = project(
      [node("a")],
      [
        observation("manual", "a", 0, 1000, {
          usageSource: "host",
          usageRef: "same",
        }),
      ],
    );
    p.usageRecords = [
      hostUsage("exec", "a", { scope: "execution", sourceRef: "same" }),
    ];
    expect(getNodeUsage(p, "a")).toMatchObject({
      tokenScope: "agent",
      totalTokens: 15,
    });
    p.usageRecords.push(hostUsage("agent", "a", { sourceRef: "same" }));
    expect(getNodeUsage(p, "a")).toMatchObject({
      tokenScope: "agent",
      totalTokens: 120,
    });
    expect(getProjectHostUsage(p).recordCount).toBe(2);
  });
  it("keeps unassigned inferences in project totals and never distributes them to nodes", () => {
    const p = project([node("parent"), node("child", "parent"), node("other")]);
    p.usageRecords = [
      hostUsage("known", "child"),
      hostUsage("unassigned", null),
      hostUsage("external", "other"),
    ];
    expect(getNodeUsage(p, "parent")).toMatchObject({
      inputTokens: 100,
      outputTokens: 20,
      totalTokens: 120,
      cacheReadTokens: 80,
    });
    expect(getNodeUsage(p, "child").totalTokens).toBe(120);
    expect(getProjectHostUsage(p)).toMatchObject({
      inputTokens: 300,
      outputTokens: 60,
      cacheReadTokens: 240,
      unassignedCount: 1,
      recordCount: 3,
    });
    p.usageRecords = [hostUsage("unassigned", null)];
    expect(getNodeUsage(p, "child").totalTokens).toBeNull();
  });

  it("deduplicates host references and explicit observations of the same measurement", () => {
    const p = project(
      [node("a")],
      [
        observation("manual", "a", 0, 1000, {
          usageSource: "host",
          usageRef: "ref",
        }),
      ],
    );
    p.usageRecords = [
      hostUsage("old", "a", { sourceRef: "ref" }),
      hostUsage("new", "a", { sourceRef: "ref", inputTokens: 150 }),
    ];
    expect(getNodeUsage(p, "a")).toMatchObject({
      inputTokens: 150,
      outputTokens: 20,
      totalTokens: 170,
      elapsedMs: 1000,
    });
    expect(getProjectHostUsage(p)).toMatchObject({
      recordCount: 1,
      inputTokens: 150,
    });
  });

  it("keeps provider/model totals separate and unknown values partial", () => {
    const p = project([node("a")]);
    p.usageRecords = [
      hostUsage("one", "a"),
      hostUsage("two", "a", {
        model: "other",
        inputTokens: null,
        outputTokens: 5,
      }),
    ];
    expect(getProjectHostUsage(p).models.map((model) => model.model)).toEqual([
      "model",
      "other",
    ]);
    expect(getNodeUsage(p, "a")).toMatchObject({
      inputTokens: 100,
      outputTokens: 25,
      totalTokens: 125,
      tokensPartial: true,
    });
  });
});

describe("getNodeUsage", () => {
  it("does not count captured external results as executions or execution time", () => {
    const recorded = {
      ...run("result", "a", { wallTimeMs: 9000 }),
      startedAt: null,
      finishedAt: null,
      capturedAt: "2026-10-21T10:00:00Z",
      configuration: { capturedExternalResult: true },
    };
    const p = project(
      [node("a")],
      [],
      [run("actual", "a", { wallTimeMs: 20 }), recorded],
    );
    expect(getNodeUsage(p, "a")).toMatchObject({ runCount: 1, runMs: 20 });
    p.runs = [recorded];
    expect(getNodeUsage(p, "a")).toMatchObject({ runCount: 0, runMs: null });
  });
  it("aggregates containment, ignoring semantic links and reused decision runs", () => {
    const p = project(
      [
        node("parent"),
        node("child", "parent"),
        node("grandchild", "child"),
        node("external"),
      ],
      [
        observation("a", "parent"),
        observation("b", "grandchild", 2000, 3000),
        observation("c", "external", 0, 9000),
      ],
      [
        run("local", "child", { wallTimeMs: 20 }),
        run("external", "external", { wallTimeMs: 9000 }),
      ],
    );
    p.edges.push({
      id: "link",
      source: "parent",
      target: "external",
      relation: "uses",
    });
    p.decisions.push({
      id: "choice",
      nodeId: "parent",
      title: "",
      conclusion: "",
      scope: "",
      nextAction: "",
      runIds: ["external"],
      artifactIds: [],
    });
    expect(getNodeUsage(p, "parent")).toMatchObject({
      elapsedMs: 2000,
      runMs: 20,
      runCount: 1,
      inputTokens: 20,
      outputTokens: 10,
      totalTokens: 30,
    });
    expect(getNodeUsage(p, "child").observations.map((o) => o.id)).toEqual([
      "b",
    ]);
    expect(getNodeUsage(p, "external").elapsedMs).toBe(9000);
  });

  it("unions overlapping parent, nested and parallel observation windows", () => {
    const p = project(
      [node("parent"), node("child", "parent")],
      [
        observation("parent", "parent", 0, 10000, { durationMs: 999999 }),
        observation("nested", "child", 1000, 3000),
        observation("parallel", "child", 8000, 12000),
        observation("later", "child", 15000, 17000),
      ],
    );
    const result = getNodeUsage(p, "parent");
    expect(result.elapsedMs).toBe(14000);
    expect(result.observations.map((o) => o.id)).toEqual([
      "later",
      "parallel",
      "nested",
      "parent",
    ]);
  });

  it("unions independent parallel siblings and sums disjoint windows", () => {
    const p = project(
      [node("root"), node("left", "root"), node("right", "root")],
      [
        observation("a", "left", 0, 3000),
        observation("b", "right", 2000, 5000),
        observation("c", "left", 7000, 8000),
      ],
    );
    expect(getNodeUsage(p, "root").elapsedMs).toBe(6000);
  });

  it("preserves unknown counters/times and explicit zeros", () => {
    const empty = getNodeUsage(project([node("root")]), "root");
    expect(empty).toMatchObject({
      elapsedMs: null,
      runMs: null,
      inputTokens: null,
      outputTokens: null,
      totalTokens: null,
      tokensPartial: false,
    });
    const zero = getNodeUsage(
      project(
        [node("root")],
        [
          observation("zero", "root", 0, 0, {
            inputTokens: 0,
            outputTokens: 0,
          }),
        ],
        [run("zero", "root", { wallTimeMs: 0 })],
      ),
      "root",
    );
    expect(zero).toMatchObject({
      elapsedMs: 0,
      runMs: 0,
      inputTokens: 0,
      outputTokens: 0,
      totalTokens: 0,
      tokensPartial: false,
    });
    const unknown = getNodeUsage(
      project(
        [node("root")],
        [
          observation("unknown", "root", 0, 1000, {
            inputTokens: null,
            outputTokens: null,
          }),
        ],
      ),
      "root",
    );
    expect(unknown).toMatchObject({
      inputTokens: null,
      outputTokens: null,
      totalTokens: null,
      tokensPartial: true,
    });
  });

  it("marks missing token fields and worked leaves as partial, but not pure containers or proposed leaves", () => {
    const p = project(
      [
        node("root", null, "active", "group"),
        node("known", "root"),
        node("todo", "root", "proposed"),
        node("empty-group", "root", "active", "group"),
      ],
      [observation("a", "known", 0, 1000, { inputTokens: 0, outputTokens: 0 })],
    );
    expect(getNodeUsage(p, "root").tokensPartial).toBe(false);
    p.nodes.push(node("unobserved", "root", "paused"));
    expect(getNodeUsage(p, "root").tokensPartial).toBe(true);
    p.observations!.push(
      observation("b", "unobserved", 0, 1000, {
        inputTokens: null,
        outputTokens: 3,
      }),
    );
    expect(getNodeUsage(p, "root")).toMatchObject({
      inputTokens: 0,
      outputTokens: 3,
      totalTokens: 3,
      tokensPartial: true,
    });
  });

  it("does not count running observation windows, even when they have a finish value", () => {
    const p = project(
      [node("root")],
      [observation("running", "root", 0, 100000, { status: "running" })],
    );
    expect(getNodeUsage(p, "root")).toMatchObject({
      elapsedMs: null,
      isRunning: true,
      elapsedPartial: true,
    });
    p.observations!.push(observation("done", "root", 2000, 3000));
    expect(getNodeUsage(p, "root")).toMatchObject({
      elapsedMs: 1000,
      isRunning: true,
      elapsedPartial: true,
    });
  });

  it("deduplicates stable IDs, using their final representation", () => {
    const a = observation("same", "root", 0, 1000);
    const p = project(
      [node("root")],
      [a, a, { ...a, inputTokens: 2 }],
      [
        run("r", "root", { wallTimeMs: 3 }),
        run("r", "root", { wallTimeMs: 4 }),
      ],
    );
    expect(getNodeUsage(p, "root")).toMatchObject({
      elapsedMs: 1000,
      runCount: 1,
      runMs: 4,
      inputTokens: 2,
      outputTokens: 5,
      totalTokens: 7,
    });
    expect(getNodeUsage(p, "root").observations).toHaveLength(1);
  });

  it("keeps measured wall times separate from query latency and rejects malformed numeric values", () => {
    const p = project(
      [node("root")],
      [
        observation("a", "root", 0, 1000, {
          inputTokens: NaN,
          outputTokens: -1,
        }),
        observation("b", "root", 2000, 3000, {
          inputTokens: 1.5,
          outputTokens: 0,
        }),
      ],
      [
        run("query-only", "root", { latency_ms: 2, warmBatchMedianMs: 4 }),
        run("valid", "root", { wallTimeMs: 9 }),
        run("negative", "root", { wallTimeMs: -1 }),
        run("infinite", "root", { wallTimeMs: Infinity }),
        run("text", "root", { wallTimeMs: "20" }),
      ],
    );
    expect(getNodeUsage(p, "root")).toMatchObject({
      elapsedMs: 2000,
      runMs: 9,
      runCount: 5,
      inputTokens: null,
      outputTokens: 0,
      totalTokens: 0,
      tokensPartial: true,
    });
    expect(
      getNodeUsage(
        project(
          [node("root")],
          [],
          [run("query-only", "root", { latency_ms: 2 })],
        ),
        "root",
      ).runMs,
    ).toBeNull();
  });

  it("ignores invalid/reversed finished intervals and returns empty scope for missing nodes", () => {
    const p = project(
      [node("root")],
      [
        observation("bad", "root", 0, 1000, { startedAt: "bad" }),
        observation("reverse", "root", 2000, 1000),
        observation("missing", "root", 0, 1000, { finishedAt: null }),
      ],
    );
    expect(getNodeUsage(p, "root").elapsedMs).toBeNull();
    expect(getNodeUsage(p, "missing")).toMatchObject({
      elapsedMs: null,
      runCount: 0,
      observations: [],
      tokensPartial: false,
    });
  });
});

describe("external task time", () => {
  it("keeps remote lifecycle duration separate from captured commands and ongoing tasks unknown", () => {
    const p = project(
      [node("root")],
      [],
      [
        run("command", "root", { wallTimeMs: 2000 }),
        {
          ...run("remote", "root", { wallTimeMs: 999999 }),
          configuration: { externalTask: true, taskRef: "job-1" },
          status: "completed",
          startedAt: "2026-10-29T08:00:00Z",
          finishedAt: "2026-10-29T10:00:00Z",
        },
        {
          ...run("ongoing", "root", {}),
          configuration: { externalTask: true },
          status: "running",
          startedAt: "2026-10-29T10:01:00Z",
          finishedAt: null,
        },
      ],
    );
    expect(getNodeUsage(p, "root")).toMatchObject({
      runCount: 3,
      commandRunCount: 1,
      runMs: 2000,
      externalTaskCount: 2,
      externalTaskMs: 7200000,
      externalTaskRunning: true,
      elapsedMs: null,
    });
    p.runs = p.runs.slice(2);
    expect(getNodeUsage(p, "root")).toMatchObject({
      runCount: 1,
      commandRunCount: 0,
      runMs: null,
      externalTaskMs: null,
      externalTaskRunning: true,
    });
  });
});

it("retains executor time independently of timestamp rounding and renders both measurements", () => {
  setLocale("en");
  const p = project(
    [node("root")],
    [],
    [
      {
        ...run("remote", "root", {}),
        configuration: { externalTask: true, taskRef: "job-1" },
        status: "completed",
        startedAt: "2026-10-29T08:00:00Z",
        finishedAt: "2026-10-29T08:00:01Z",
        durationMs: 905,
      },
    ],
  );
  const before = JSON.stringify(p);
  const usage = getNodeUsage(p, "root");
  expect(usage).toMatchObject({
    externalTaskMs: 1000,
    externalReportedMs: 905,
    runMs: null,
  });
  const html = renderToStaticMarkup(
    createElement(NodeUsagePanel, {
      project: p,
      node: p.nodes[0],
      busy: false,
      mutate: async () => true,
    }),
  );
  expect(html).toContain("Task timestamp span 1 s");
  expect(html).toContain("Executor-reported time 905 ms");
  expect(JSON.stringify(p)).toBe(before);
});

describe("usage formatting", () => {
  it("keeps absent and invalid host timestamps unknown instead of inventing epoch times", () => {
    expect([null, undefined, "", "invalid"].map(formatUsageTime)).toEqual(
      Array(4).fill("未提供"),
    );
    expect(formatUsageTime("2026-10-21T10:00:00Z")).not.toBe("未提供");
  });
  it("formats measured duration with compact units and preserves zero", () => {
    expect([null, 0, 12.25, 1200, 90000, 5400000].map(formatDuration)).toEqual([
      "—",
      "0 ms",
      "12.3 ms",
      "1.2 s",
      "1.5 m",
      "1.5 h",
    ]);
    expect(formatDuration(NaN)).toBe("—");
    expect(formatDuration(-1)).toBe("—");
  });
  it("formats known integer tokens and keeps missing values distinct", () => {
    expect([null, 0, 999, 1200, 1250000, 2000000000].map(formatTokens)).toEqual(
      ["—", "0", "999", "1.2k", "1.3M", "2B"],
    );
    expect(formatTokens(Infinity)).toBe("—");
    expect(formatTokens(1.1)).toBe("—");
  });
});
