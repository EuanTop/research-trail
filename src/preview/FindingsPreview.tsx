import { useCallback, useState } from "react";
import {
  Background,
  BaseEdge,
  ConnectionMode,
  EdgeLabelRenderer,
  MarkerType,
  ReactFlow,
  getSmoothStepPath,
  useNodesState,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
} from "@xyflow/react";
import { ChevronRight, Maximize2, Minus, Plus, X } from "lucide-react";
import { ResearchCard } from "../components/ResearchCard";
import { type CanvasData } from "../model";
import { formatDuration, formatTokens, type NodeUsage } from "../usage";
import "./findings-preview.css";

type Finding = {
  title: string;
  approach: string;
  takeaway: string;
  conclusion: string;
  evidence: string;
  limitation: string;
};
type FindingNode = Node<CanvasData>;

// Fixed presentation examples, independent of any current experiment. All
// status/usage metadata is simulated; this page never requests or mutates data.
const findings: Record<string, Finding> = {
  perturbation: {
    title: "微小修改会打乱字体轮廓序列吗？",
    approach: "保留完整曲线，施加微扰并比较起点与子路径排序。",
    takeaway: "发现：形状变化很小，序列却会明显换序。",
    conclusion: "最小尺度的微扰也会触发大量离散换序，序列变化远大于几何变化。",
    evidence:
      "278 / 1,152 对发生序列结构变化，涉及 32 个字形中的 11 个。Arial H 的来源对齐 RMSE 仅 0.00000688 em，同位置 RMSE 却达到 0.38057 em。",
    limitation:
      "样本来自两套字体、16 个特意选择的字符。这里衡量的是序列变化，不能等同于几何信息丢失。",
  },
  tolerance: {
    title: "加入容差，能减少微扰换序吗？",
    approach: "因微扰触发换序，比较不同容差与扰动尺度。",
    takeaway: "发现：本样本小尺度未再换序，较大扰动仍会换序。",
    conclusion:
      "相对容差网格将本样本最小尺度的突变降至零；扰动增大后，收益会下降。",
    evidence:
      "在 0.001 / 0.003 em 扰动下，0.002 em 网格仍有 36 / 155 次突变，各有 1,152 对样本。0.008 em 网格在最大尺度仍有 15 次突变。",
    limitation:
      "网格只用于排序决策，不修改几何坐标。本次没有确定通用最优容差，也不能把样本内零突变解释为连续稳定。",
  },
  boundary: {
    title: "容差收益可靠吗，额外代价有多大？",
    approach: "针对稳定性与开销，寻找换序边界并核对优化实现。",
    takeaway: "发现：边界仍在；加速有效，但仍慢于简单排序。",
    conclusion:
      "容差扩大了稳定区域，也把不连续边界移到了其他位置，并未消除边界。",
    evidence:
      "定向二分找到的两侧形状仅相差约 4.47×10⁻¹¹ em，仍有 30.30% 的线段来源位置改变。等价快实现的 18,432 次比较零差异，较直接网格实现约快 16 倍。",
    limitation:
      "这是刻意寻找的反例，不能估计发生频率。快实现每字形约 0.165 ms，仍约慢于 lex 37 倍；计时不是严格微基准。",
  },
  fidelity: {
    title: "改进排序后，曲线与孔洞还完整吗？",
    approach: "为排除信息丢失，核对完整曲线和孔洞。",
    takeaway: "发现：本次未见丢失，栅格噪声需单独归因。",
    conclusion:
      "本次规范化保留了完整曲线，不能把栅格微孔计数变化归因于规范化丢失信息。",
    evidence:
      "73,728 次精确曲线检查全部通过；32 个字形的独立原字体解码一致，96 次直接曲线绕数栅格比较完全相同。2048 像素下剩余差异来自 1–2 像素微孔。",
    limitation:
      "未实现通用的精确拓扑判定，也未证明所有局部扰动都保持向量拓扑。证据只覆盖本次字形和规则。",
  },
};

function FindingEdge(props: EdgeProps) {
  const [path, x, y] = getSmoothStepPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
    borderRadius: 6,
    offset: 28,
  });
  return (
    <>
      <BaseEdge
        id={props.id}
        path={path}
        markerEnd={props.markerEnd}
        style={{ stroke: "#9aa6b5", strokeWidth: 1.25 }}
      />
      <EdgeLabelRenderer>
        <span
          className="pv-edge-label"
          style={{
            transform: `translate(-50%, -50%) translate(${x}px, ${y}px)`,
          }}
        >
          {props.label}
        </span>
      </EdgeLabelRenderer>
    </>
  );
}

const nodeTypes = { finding: ResearchCard };
const edgeTypes = { finding: FindingEdge };
const positions = {
  perturbation: { x: 500, y: 20 },
  tolerance: { x: 500, y: 300 },
  boundary: { x: 220, y: 600 },
  fidelity: { x: 780, y: 600 },
};
const links = [
  ["perturbation", "tolerance", "bottom", "top", "发现微扰换序，尝试容差"],
  ["tolerance", "boundary", "bottom", "top", "样本零换序，追查边界"],
  ["boundary", "tolerance", "left", "left", "反例限定稳定性结论"],
  ["tolerance", "fidelity", "bottom", "top", "稳定之外，还需核对完整性"],
  ["fidelity", "tolerance", "right", "right", "核验支持信息保留"],
];
const edges: Edge[] = links.map(
  ([source, target, sourceHandle, targetHandle, label], i) => ({
    id: `preview-${i}`,
    source,
    target,
    sourceHandle,
    targetHandle,
    label,
    type: "finding",
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 13,
      height: 13,
      color: "#9aa6b5",
    },
  }),
);

const mockUsage: NodeUsage = {
  tokenScope: "agent",
  elapsedMs: 42_000,
  elapsedPartial: false,
  isRunning: false,
  runMs: 1_200,
  runCount: 2,
  commandRunCount: 2,
  externalTaskCount: 0,
  externalTaskMs: null,
  externalReportedMs: null,
  externalTaskRunning: false,
  inputTokens: 3_000,
  outputTokens: 600,
  totalTokens: 3_600,
  tokensPartial: false,
  observations: [],
  hostUsage: [],
  cacheReadTokens: null,
  cacheWriteTokens: null,
};

export function FindingsPreview() {
  const [detail, setDetail] = useState<string | null>(null);
  const [demoProcessing, setDemoProcessing] = useState(true);
  const open = useCallback((id: string) => setDetail(id), []);
  const [nodes, , onNodesChange] = useNodesState<FindingNode>(
    Object.entries(findings).map(([id, finding]) => ({
      id,
      type: "finding",
      position: positions[id as keyof typeof positions],
      style: { width: 368, height: 210 },
      dragHandle: ".node-grip",
      data: {
        node: {
          id,
          title: finding.title,
          kind:
            id === "perturbation"
              ? "question"
              : id === "fidelity"
                ? "finding"
                : "experiment",
          status: "completed",
          parentId: null,
          summary: "",
          notes: "",
          nextAction: "",
          tags: [],
          position: positions[id as keyof typeof positions],
          collapsed: false,
        },
        presentation: {
          headline: finding.title,
          context: "",
          source: "",
          summary: `${finding.approach}\n${finding.takeaway}`,
        },
        children: 0,
        runs: mockUsage.runCount,
        expanded: false,
        usage: { ...mockUsage },
        onInspect: () => open(id),
        onToggle: () => {},
        onEnter: () => {},
      },
    })),
  );
  const flow = useReactFlow();
  const selected = detail ? findings[detail] : null;
  const previewNodes = nodes.map((node) => ({
    ...node,
    data: {
      ...node.data,
      processing: demoProcessing && node.id === "tolerance",
      node: {
        ...node.data.node,
        status:
          demoProcessing && node.id === "tolerance" ? "active" : "completed",
      },
      usage: {
        ...mockUsage,
        isRunning: demoProcessing && node.id === "tolerance",
      },
    },
    ariaLabel:
      demoProcessing && node.id === "tolerance"
        ? `${node.data.node.title}，Agent 正在处理（模拟）`
        : node.data.node.title,
  }));
  const selectedUsage = previewNodes.find((node) => node.id === detail)?.data
    .usage;
  return (
    <div className="pv-app">
      <header className="pv-header">
        <a className="pv-brand" href="/">
          ExpObserver
        </a>
        <ChevronRight size={14} />
        <span>字体轮廓规范化 · 演示</span>
        <div className="pv-header-end">
          <button
            className="pv-processing-toggle"
            role="switch"
            aria-label="模拟 Agent 处理中"
            aria-checked={demoProcessing}
            onClick={() => setDemoProcessing((value) => !value)}
          >
            <span />
            模拟处理中
          </button>
          <span>演示预览 · 元数据为模拟</span>
          <a href="/">
            返回研究 <ChevronRight size={13} />
          </a>
        </div>
      </header>
      <main className="pv-main">
        <div className="pv-heading">
          <h1>研究脉络</h1>
          <span>字体轻微变化后，如何保持序列稳定与曲线完整？</span>
        </div>
        <ReactFlow
          nodes={previewNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onNodeClick={(_, node) => setDetail(node.id)}
          onPaneClick={() => setDetail(null)}
          connectionMode={ConnectionMode.Loose}
          nodesConnectable={false}
          edgesFocusable={false}
          fitView
          fitViewOptions={{ padding: 0.1, maxZoom: 1.1 }}
          minZoom={0.35}
          maxZoom={1.6}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#dfe4eb" gap={24} size={0.75} />
        </ReactFlow>
        <div className="pv-controls">
          <button
            aria-label="放大"
            onClick={() => void flow.zoomIn({ duration: 200 })}
          >
            <Plus size={16} />
          </button>
          <button
            aria-label="缩小"
            onClick={() => void flow.zoomOut({ duration: 200 })}
          >
            <Minus size={16} />
          </button>
          <i />
          <button
            aria-label="适应画布"
            onClick={() =>
              void flow.fitView({ padding: 0.1, maxZoom: 1.1, duration: 300 })
            }
          >
            <Maximize2 size={15} />
          </button>
        </div>
        <div className="pv-hint">演示内容 · 点击节点查看完整依据与适用边界</div>
        {selected && (
          <aside className="pv-detail" aria-label="发现详情">
            <div className="pv-detail-top">
              <span>发现详情</span>
              <button aria-label="关闭详情" onClick={() => setDetail(null)}>
                <X size={17} />
              </button>
            </div>
            <h2>{selected.title}</h2>
            <div className="pv-detail-meta" aria-label="模拟运行元数据">
              <span>
                {selectedUsage ? `${selectedUsage.runCount} 次运行` : "运行 —"}
              </span>
              <span>执行 {formatDuration(selectedUsage?.runMs)}</span>
              <span>Token {formatTokens(selectedUsage?.totalTokens)}</span>
            </div>
            <section>
              <h3>研究内容</h3>
              <p>{selected.approach}</p>
            </section>
            <section>
              <h3>发现</h3>
              <p>{selected.conclusion}</p>
            </section>
            <section>
              <h3>依据</h3>
              <p>{selected.evidence}</p>
            </section>
            <section>
              <h3>适用边界</h3>
              <p>{selected.limitation}</p>
            </section>
          </aside>
        )}
      </main>
    </div>
  );
}
