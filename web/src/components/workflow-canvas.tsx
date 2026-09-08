"use client";

import { useRef } from "react";

import {
  Background,
  Controls,
  ReactFlow,
  MarkerType,
  type Node,
  type Edge,
  type Connection,
} from "@xyflow/react";
import type {
  WorkflowIssue,
  WorkflowLayout,
  WorkflowSpec,
} from "@jarvis/contracts";

export type WorkflowSelection = { kind: "node" | "edge"; id: string } | null;
export function nodePosition(
  layout: WorkflowLayout,
  index: number,
  id: string,
) {
  return (
    layout.nodes?.[id] ?? {
      x: (index % 3) * 240,
      y: Math.floor(index / 3) * 150,
    }
  );
}

/** A presentation adapter only. Spec mutations go directly to the canonical document. */
export function WorkflowCanvas({
  spec,
  layout,
  readOnly,
  issues = [],
  selection,
  onSelect,
  onLayout,
  onConnect,
  onRemove,
  projection = {},
  transitions = [],
}: {
  spec: WorkflowSpec;
  layout: WorkflowLayout;
  readOnly: boolean;
  issues?: WorkflowIssue[];
  selection: WorkflowSelection;
  onSelect: (value: WorkflowSelection) => void;
  onLayout: (
    value: WorkflowLayout | ((current: WorkflowLayout) => WorkflowLayout),
  ) => void;
  onConnect: (connection: Connection) => void;
  onRemove: (nodeIds: string[], edgeIds: string[]) => void;
  /** Future event projections may annotate a read-only graph without advancing it. */
  projection?: Readonly<Record<string, string>>;
  transitions?: ReadonlyArray<{ from: string; to: string }>;
}) {
  const viewportControl = useRef(false);
  const nodes: Node[] = spec.nodes.map((node, index) => {
    const problems = issues.filter((issue) => issue.node_id === node.id);
    return {
      id: node.id,
      position: nodePosition(layout, index, node.id),
      type: node.type === "finalize" ? "output" : "default",
      selected: selection?.kind === "node" && selection.id === node.id,
      className: problems.length ? "workflow-node-invalid" : undefined,
      ariaLabel: `${node.label}, ${node.type}${problems.length ? `, ${problems.length} validation problems` : ""}`,
      data: {
        label: (
          <>
            <span className="workflow-node-kind">
              {node.type.replaceAll("_", " ")}
              {node.id === spec.entrypoint ? " · entry" : ""}
            </span>
            <strong>{node.label}</strong>
            {problems.length ? (
              <span className="workflow-node-problem">
                {problems.length} problem{problems.length === 1 ? "" : "s"}
              </span>
            ) : null}
            {projection[node.id] ? <span>{projection[node.id]}</span> : null}
          </>
        ),
      },
    };
  });
  const edges: Edge[] = spec.edges.map((edge) => ({
    id: edge.id,
    source: edge.from,
    target: edge.to,
    animated:
      transitions.at(-1)?.from === edge.from &&
      transitions.at(-1)?.to === edge.to,
    style: transitions.some((t) => t.from === edge.from && t.to === edge.to)
      ? { stroke: "var(--accent)", strokeWidth: 3 }
      : undefined,
    label: `${edge.kind}${edge.fallback ? " · fallback" : ""}`,
    selected: selection?.kind === "edge" && selection.id === edge.id,
    className: issues.some((issue) => issue.edge_id === edge.id)
      ? "workflow-edge-invalid"
      : undefined,
    ariaLabel: `${edge.from} to ${edge.to}, ${edge.kind}`,
    markerEnd: { type: MarkerType.ArrowClosed, color: "var(--text-muted)" },
  }));
  return (
    <div className="workflow-canvas" aria-label="Workflow graph" role="region">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        colorMode="dark"
        minZoom={0.1}
        maxZoom={4}
        defaultViewport={
          layout.viewport
            ? { ...layout.viewport, zoom: layout.viewport.zoom ?? 1 }
            : undefined
        }
        fitView={!layout.viewport}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        deleteKeyCode={readOnly ? null : ["Backspace", "Delete"]}
        onNodeClick={(_, node) => onSelect({ kind: "node", id: node.id })}
        onEdgeClick={(_, edge) => onSelect({ kind: "edge", id: edge.id })}
        onPaneClick={() => onSelect(null)}
        onNodesChange={(changes) => {
          const positions = changes.filter(
            (change) => change.type === "position" && change.position,
          );
          if (!readOnly && positions.length) {
            onLayout((current) => {
              const next = { ...current.nodes };
              for (const change of positions)
                if (change.type === "position" && change.position)
                  next[change.id] = {
                    x: Math.max(-100000, Math.min(100000, change.position.x)),
                    y: Math.max(-100000, Math.min(100000, change.position.y)),
                  };
              return { ...current, nodes: next };
            });
          }
          const selected = changes.find(
            (change) => change.type === "select" && change.selected,
          );
          if (selected && "id" in selected)
            onSelect({ kind: "node", id: selected.id });
        }}
        onEdgesChange={(changes) => {
          const selected = changes.find(
            (change) => change.type === "select" && change.selected,
          );
          if (selected && "id" in selected)
            onSelect({ kind: "edge", id: selected.id });
        }}
        onDelete={({ nodes: removedNodes, edges: removedEdges }) =>
          onRemove(
            removedNodes.map((n) => n.id),
            removedEdges.map((e) => e.id),
          )
        }
        onConnect={onConnect}
        onMoveEnd={(event, viewport) => {
          if (!readOnly && (event || viewportControl.current))
            onLayout((current) => ({ ...current, viewport }));
          viewportControl.current = false;
        }}
        proOptions={{ hideAttribution: false }}
      >
        <Background gap={24} />
        <div
          onClickCapture={() => {
            viewportControl.current = true;
          }}
        >
          <Controls showInteractive={false} />
        </div>
      </ReactFlow>
    </div>
  );
}
