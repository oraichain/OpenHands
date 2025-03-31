import React from "react";
import { useWsClient } from "#/context/ws-client-provider";
import { TerminalDataEvent } from "#/types/core/events";

const isTerminalDataEvent = (event: unknown): event is TerminalDataEvent => {
  if (!event || typeof event !== "object") return false;
  const e = event as Record<string, unknown>;
  return (
    "type" in e &&
    e.type === "terminal_data" &&
    "source" in e &&
    e.source === "terminal" &&
    "data" in e &&
    typeof e.data === "string" &&
    "id" in e &&
    typeof e.id === "number" &&
    "timestamp" in e &&
    typeof e.timestamp === "string"
  );
};

export function TerminalLogViewer() {
  const { events } = useWsClient();
  const logContainerRef = React.useRef<HTMLDivElement>(null);
  const [terminalLogs, setTerminalLogs] = React.useState<TerminalDataEvent[]>(
    [],
  );
  const [autoScroll, setAutoScroll] = React.useState(true);

  // Handle new events
  React.useEffect(() => {
    if (!events.length) return;

    setTerminalLogs((prev) => [
      ...prev,
      ...events.filter((e) => isTerminalDataEvent(e)),
    ]);
  }, [events.length]);

  // Auto-scroll to bottom when new logs arrive
  React.useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [terminalLogs, autoScroll]);

  // Handle scroll events to toggle auto-scroll
  const handleScroll = React.useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const element = e.currentTarget;
    const isAtBottom =
      Math.abs(
        element.scrollHeight - element.scrollTop - element.clientHeight,
      ) < 10;
    setAutoScroll(isAtBottom);
  }, []);

  return (
    <div className="flex flex-col h-full">
      <div className="flex justify-between items-center p-2 bg-gray-800 text-white">
        <h3 className="text-sm font-semibold">Terminal Logs</h3>
        <button
          onClick={() => setAutoScroll(true)}
          className="px-2 py-1 text-xs rounded bg-green-600"
        >
          Auto-scroll {autoScroll ? "ON" : "OFF"}
        </button>
      </div>
      <div
        ref={logContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-auto bg-black text-white font-mono text-sm p-4"
      >
        {terminalLogs.map((log, index) => (
          <div key={log.id || index} className="whitespace-pre-wrap mb-1">
            <span className="text-gray-500">
              [{new Date(log.timestamp).toLocaleTimeString()}]
            </span>{" "}
            {log.data}
          </div>
        ))}
        {!terminalLogs.length && (
          <div className="text-gray-500 italic">No logs available...</div>
        )}
      </div>
    </div>
  );
}
