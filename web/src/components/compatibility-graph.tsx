"use client";

import {
  Background,
  ReactFlow,
  type Edge,
  type Node,
  type OnInit,
} from "@xyflow/react";

const nodes: Node[] = [
  {
    id: "organizer",
    position: { x: 0, y: 0 },
    data: { label: "Organizer" },
    type: "input",
  },
  {
    id: "finalize",
    position: { x: 220, y: 0 },
    data: { label: "Finalize" },
    type: "output",
  },
];

const edges: Edge[] = [
  { id: "organizer-finalize", source: "organizer", target: "finalize" },
];

interface CompatibilityGraphProps {
  onInit?: OnInit;
}

export function CompatibilityGraph({ onInit }: CompatibilityGraphProps) {
  return (
    <div aria-label="Workflow compatibility graph" className="h-64 w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodesDraggable={false}
        nodesConnectable={false}
        onInit={onInit}
      >
        <Background />
      </ReactFlow>
    </div>
  );
}
