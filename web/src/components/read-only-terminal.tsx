"use client";

import type { Terminal as XtermTerminal } from "@xterm/xterm";
import { useEffect, useMemo, useRef } from "react";

const MAX_TERMINAL_CHARACTERS = 131_072;

export function sanitizeTerminalOutput(input: string): string {
  const withoutOsc = input
    .replaceAll("\r", "")
    .replace(/\u001B\][\s\S]*?(?:\u0007|\u001B\\)/g, "")
    .replace(/\u001B\][^\u0007]*(?:$|\u0007)/g, "");
  const withoutControls = withoutOsc
    .replace(/\u001B[P^_][\s\S]*?\u001B\\/g, "")
    .replace(/\u001B\[[0-?]*[ -/]*[@-~]/g, "")
    .replace(/\u001B[@-_]/g, "")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/g, "");
  if (withoutControls.length <= MAX_TERMINAL_CHARACTERS) return withoutControls;
  return `${withoutControls.slice(0, MAX_TERMINAL_CHARACTERS)}\n[output truncated]`;
}

export function ReadOnlyTerminal({
  label = "Read-only command output",
  output,
}: {
  label?: string;
  output: string;
}) {
  const terminalRoot = useRef<HTMLDivElement>(null);
  const safeOutput = useMemo(() => sanitizeTerminalOutput(output), [output]);

  useEffect(() => {
    if (!terminalRoot.current) return;
    const root = terminalRoot.current;
    let terminal: XtermTerminal | undefined;
    let disposed = false;
    void import("@xterm/xterm").then(({ Terminal }) => {
      if (disposed) return;
      terminal = new Terminal({
        convertEol: true,
        cursorBlink: false,
        disableStdin: true,
        rows: 8,
        screenReaderMode: true,
        theme: { background: "#071018", foreground: "#d8e8eb" },
      });
      terminal.open(root);
      if (terminal.textarea) terminal.textarea.tabIndex = -1;
      terminal.write(safeOutput.replaceAll("\n", "\r\n"));
    });
    return () => {
      disposed = true;
      terminal?.dispose();
    };
  }, [safeOutput]);

  return (
    <div className="terminal-frame" data-read-only="true">
      <div className="terminal-title">
        <span aria-hidden="true">›_</span>
        <span>{label}</span>
        <span className="terminal-mode">read only</span>
      </div>
      <div aria-hidden="true" className="terminal-surface" ref={terminalRoot} />
      <pre aria-label={label} className="sr-only" role="log">
        {safeOutput}
      </pre>
    </div>
  );
}
