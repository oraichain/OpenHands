import React from "react";
import { TerminalLogViewer } from "#/components/features/terminal/terminal-log-viewer";
import TerminalComponent from "#/components/features/terminal/terminal";
import {
  ResizablePanel,
  Orientation,
} from "#/components/layout/resizable-panel";

export default function TerminalPage() {
  const secrets = React.useMemo(() => [], []);

  return (
    <div className="h-full">
      <TerminalLogViewer />
      <ResizablePanel
        orientation={Orientation.VERTICAL}
        className="h-full"
        initialSize={300}
        firstClassName="rounded-xl overflow-hidden bg-black"
        secondClassName="rounded-xl overflow-hidden bg-black"
        firstChild={<TerminalComponent secrets={secrets} />}
        secondChild={<TerminalLogViewer />}
      />
    </div>
  );
}
