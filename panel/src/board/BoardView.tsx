import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { Annotation, Board, BoardNode } from "../protocol";
import { LiveCaption } from "../components/Caption";
import { t, useT } from "../i18n";
import { useStore } from "../store";
import { NODE_W, computeLayout, type Positions } from "./layout";
import { provenanceStyle } from "./provenance";

interface WispData extends Record<string, unknown> {
  node: BoardNode;
  focused: boolean;
  annotations: Annotation[];
  vertical: boolean;
}

/** Text alternative of a node: what it is and how much to trust it (provenance is never colour or border only). */
export function nodeAriaLabel(n: BoardNode, annotations: Annotation[] = []): string {
  const prov = t(`board.aria.${n.provenance}`);
  const conf = n.confidence < 1 ? t("board.aria.confidence", { percent: Math.round(n.confidence * 100) }) : "";
  const notes = annotations.map((a) => t("board.aria.note", { text: a.text })).join("");
  return `${n.kind} ${n.label}, ${prov}${conf}${notes}`;
}

const WispNode = memo(function WispNode({ data }: NodeProps<Node<WispData>>) {
  const { node, focused, annotations, vertical } = data;
  const t = useT();
  const send = useStore((s) => s.send);
  const style = provenanceStyle(node.provenance);
  return (
    <div
      className={`wnode ${style.className}${focused ? " focused" : ""}`}
      style={{ width: NODE_W }}
      title={node.ref ?? node.id}
    >
      <Handle
        type="target"
        position={vertical ? Position.Top : Position.Left}
      />
      <div className="wnode-head">
        <span className="kind">{node.kind}</span>
        {style.eye ? (
          <span
            className="eye"
            role="img"
            aria-label={t("board.observedAria")}
            title={t("board.observedTitle")}
          >
            ◉
          </span>
        ) : (
          <span className="tag">{t(`board.tag.${node.provenance}`)}</span>
        )}
        {node.confidence < 1 && (
          <span className="conf" title={t("board.confidence")}>
            {Math.round(node.confidence * 100)}%
          </span>
        )}
      </div>
      <div className="wnode-label">{node.label}</div>
      {node.props_view.length > 0 && (
        <dl className="wnode-props">
          {node.props_view.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {annotations.map((a) => (
        <div key={a.id} className={`wnote ${a.provenance}`}>
          {a.text}
        </div>
      ))}
      <button
        className="why nodrag"
        aria-label={t("board.whyAria", { label: node.label })}
        onClick={(e) => {
          e.stopPropagation();
          send({ type: "board.ask_why", node_id: node.id });
        }}
      >
        {t("board.why")}
      </button>
      <Handle
        type="source"
        position={vertical ? Position.Bottom : Position.Right}
      />
    </div>
  );
});

const nodeTypes = { wisp: WispNode };

function Flow({ board }: { board: Board }) {
  const send = useStore((s) => s.send);
  const setSelected = useStore((s) => s.setSelected);
  const [positions, setPositions] = useState<Positions>({});
  const lastSent = useRef({ id: "", t: 0 });
  // Click and keyboard (Tab to a node, Enter or Space) both select; a click fires both events, so send once.
  const select = (id: string) => {
    const now = Date.now();
    if (lastSent.current.id === id && now - lastSent.current.t < 300) return;
    lastSent.current = { id, t: now };
    setSelected(id);
    send({ type: "board.select", node_id: id });
  };
  const { fitView } = useReactFlow();
  // Portrait (a narrow tool window): flows run top to bottom.
  const [portrait, setPortrait] = useState(
    () => window.innerHeight > window.innerWidth,
  );
  useEffect(() => {
    const on = () => setPortrait(window.innerHeight > window.innerWidth);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  const vertical =
    board.layout === "tree" || board.layout === "stack" || portrait;

  // The layout key ignores props_view text so that value updates do not re-run ELK.
  const layoutKey = JSON.stringify([
    board.layout,
    portrait,
    board.nodes.map((n) => [n.id, n.order, n.props_view.length]),
    board.edges.map((e) => e.id),
  ]);
  useEffect(() => {
    let alive = true;
    computeLayout(board, portrait).then((p) => {
      if (!alive) return;
      setPositions(p);
      setTimeout(
        () =>
          fitView({
            duration: matchMedia("(prefers-reduced-motion: reduce)").matches
              ? 0
              : 300,
            padding: 0.2,
          }),
        80,
      );
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey]);

  const nodes: Node<WispData>[] = useMemo(
    () =>
      board.nodes.map((n) => ({
        id: n.id,
        type: "wisp",
        position: positions[n.id] ?? { x: 0, y: 0 },
        ariaLabel: nodeAriaLabel(n, board.annotations.filter((a) => a.target === n.id)),
        ariaRole: "group" as const,
        data: {
          node: n,
          focused: board.focus.includes(n.id),
          annotations: board.annotations.filter((a) => a.target === n.id),
          vertical,
        },
        draggable: true,
      })),
    [board.nodes, board.focus, board.annotations, positions, vertical],
  );

  const edges: Edge[] = useMemo(() => {
    const real: Edge[] = board.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.kind === "contains" ? undefined : e.kind.replace(/_/g, " "),
      className: `wedge ${e.provenance}`,
      markerEnd: { type: MarkerType.ArrowClosed },
      animated: false,
    }));
    if (board.layout === "stack") {
      const ordered = board.nodes
        .filter((n) => n.order !== null)
        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
      for (let i = 0; i + 1 < ordered.length; i++) {
        const a = ordered[i];
        const b = ordered[i + 1];
        if (a && b)
          real.push({
            id: `order:${a.id}>${b.id}`,
            source: a.id,
            target: b.id,
            label: t("board.then"),
            className: "wedge order",
            markerEnd: { type: MarkerType.ArrowClosed },
          });
      }
    }
    return real;
  }, [board.edges, board.nodes, board.layout]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      minZoom={0.08}
      maxZoom={1.6}
      nodesConnectable={false}
      onNodeClick={(_, n) => select(n.id)}
      onKeyDown={(e) => {
        const el = e.target as HTMLElement;
        if ((e.key === "Enter" || e.key === " ") && el.classList.contains("react-flow__node") && el.dataset.id) {
          e.preventDefault();
          select(el.dataset.id);
        }
      }}
      onSelectionChange={({ nodes: sel }) => {
        const only = sel.length === 1 ? sel[0] : undefined;
        if (only) select(only.id);
      }}
      colorMode="dark"
    >
      <Background gap={24} color="#2a1766" />
      <Controls showInteractive={false} position="bottom-right" />
    </ReactFlow>
  );
}

function Legend() {
  const t = useT();
  return (
    <div className="legend" role="group" aria-label={t("board.legend")}>
      <span className="swatch observed" /> {t("board.legend.observed")}
      <span className="swatch inferred" /> {t("board.legend.inferred")}
      <span className="swatch illustrative" /> {t("board.legend.illustrative")}
    </div>
  );
}

function Steps({ board }: { board: Board }) {
  const t = useT();
  if (board.steps.length === 0) return null;
  const icon = { pending: "○", active: "◉", done: "✓", failed: "✕" } as const;
  return (
    <ol className="steps" aria-label={t("board.steps")}>
      {board.steps.map((s) => (
        <li key={s.id} className={s.status}>
          <span className="stepicon" aria-hidden>
            {icon[s.status]}
          </span>
          {s.text}
        </li>
      ))}
    </ol>
  );
}

export function BoardView() {
  const t = useT();
  const board = useStore((s) => s.board);
  return (
    <div className="boardwrap">
      {board.stale && (
        <div className="stale" role="status">
          {t("board.stale")}
        </div>
      )}
      {board.nodes.length === 0 ? (
        <div className="empty">
          <img
            className="mascot"
            src="/wysp-mark.png"
            alt=""
            width={96}
            height={96}
          />
          <p>{t("board.emptyTitle")}</p>
          <p className="muted">
            {t("board.emptyBody")}
          </p>
        </div>
      ) : (
        <ReactFlowProvider>
          <Flow board={board} />
        </ReactFlowProvider>
      )}
      <Steps board={board} />
      <div className="board-bottom">
        <LiveCaption />
        <Legend />
      </div>
    </div>
  );
}
