import { useWsClient } from "#/context/ws-client-provider";
import { getTerminalCommand } from "#/services/terminal-service";
import { Command } from "#/state/command-slice";
import { parseTerminalOutput } from "#/utils/parse-terminal-output";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import React from "react";
// import { useLocation } from "react-router";

/*
  NOTE: Tests for this hook are indirectly covered by the tests for the XTermTerminal component.
  The reason for this is that the hook exposes a ref that requires a DOM element to be rendered.
*/

interface UseTerminalConfig {
  commands: Command[];
  secrets: string[];
  disabled: boolean;
}

const DEFAULT_TERMINAL_CONFIG: UseTerminalConfig = {
  commands: [],
  secrets: [],
  disabled: false,
};

export const useTerminal = ({
  commands,
  secrets,
  disabled,
}: UseTerminalConfig = DEFAULT_TERMINAL_CONFIG) => {
  const { send } = useWsClient();
  const terminal = React.useRef<Terminal | null>(null);
  const fitAddon = React.useRef<FitAddon | null>(null);
  const ref = React.useRef<HTMLDivElement>(null);
  const lastCommandIndex = React.useRef(0);
  const keyEventDisposable = React.useRef<{ dispose: () => void } | null>(null);
  // const location = useLocation();
  // const pathname = location.pathname;

  // Reset lastCommandIndex when commands array is empty
  React.useEffect(() => {
    if (commands.length === 0) {
      lastCommandIndex.current = 0;
    }
  }, [commands]);

  // Cleanup function to properly dispose terminal
  const cleanup = React.useCallback(() => {
    if (keyEventDisposable.current) {
      keyEventDisposable.current.dispose();
      keyEventDisposable.current = null;
    }
    if (terminal.current) {
      terminal.current.dispose();
      terminal.current = null;
    }
    lastCommandIndex.current = 0;
  }, []);

  const createTerminal = () =>
    new Terminal({
      fontFamily: "Menlo, Monaco, 'Courier New', monospace",
      fontSize: 14,
      theme: {
        // TODO: check light mode and dark mode
        // background: "#0F0F0F",
        background: "#F5F5F5",
        foreground: "#292929",
        selectionBackground: "#A7C6ED",
        selectionForeground: "#292929",
      },
    });

  const initializeTerminal = () => {
    if (terminal.current) {
      if (fitAddon.current) terminal.current.loadAddon(fitAddon.current);
      if (ref.current) terminal.current.open(ref.current);
    }
  };

  const copySelection = (selection: string) => {
    const clipboardItem = new ClipboardItem({
      "text/plain": new Blob([selection], { type: "text/plain" }),
    });

    navigator.clipboard.write([clipboardItem]);
  };

  const pasteSelection = (callback: (text: string) => void) => {
    navigator.clipboard.readText().then(callback);
  };

  const pasteHandler = (event: KeyboardEvent, cb: (text: string) => void) => {
    const isControlOrMetaPressed =
      event.type === "keydown" && (event.ctrlKey || event.metaKey);

    if (isControlOrMetaPressed) {
      if (event.code === "KeyV") {
        pasteSelection((text: string) => {
          terminal.current?.write(text);
          cb(text);
        });
      }

      if (event.code === "KeyC") {
        const selection = terminal.current?.getSelection();
        if (selection) copySelection(selection);
      }
    }

    return true;
  };

  const handleEnter = (command: string) => {
    terminal.current?.write("\r\n");
    send(getTerminalCommand(command));
  };

  const handleBackspace = (command: string) => {
    terminal.current?.write("\b \b");
    return command.slice(0, -1);
  };

  // Initialize terminal
  React.useEffect(() => {
    cleanup(); // Clean up existing terminal before creating new one

    terminal.current = createTerminal();
    fitAddon.current = new FitAddon();

    let resizeObserver: ResizeObserver | null = null;
    if (ref.current) {
      initializeTerminal();
      terminal.current.write("$ ");

      resizeObserver = new ResizeObserver(() => {
        fitAddon.current?.fit();
      });
      resizeObserver.observe(ref.current);
    }

    return () => {
      cleanup();
      resizeObserver?.disconnect();
    };
  }, []); // Keep this as empty dependency array

  // Handle commands updates
  React.useEffect(() => {
    if (!terminal.current || commands.length === 0) return;

    // Write all commands when switching tabs
    for (let i = lastCommandIndex.current; i < commands.length; i += 1) {
      let { content } = commands[i];
      const { type } = commands[i];

      secrets.forEach((secret) => {
        content = content.replaceAll(secret, "*".repeat(10));
      });

      terminal.current.writeln(
        parseTerminalOutput(content.replaceAll("\n", "\r\n").trim()),
      );

      if (type === "output") {
        terminal.current.write("\n$ ");
      }
    }

    lastCommandIndex.current = commands.length;
    fitAddon.current?.fit(); // Ensure terminal fits after writing commands
  }, [commands, secrets]);

  React.useEffect(() => {
    if (terminal.current) {
      // Dispose of existing listeners if they exist
      if (keyEventDisposable.current) {
        keyEventDisposable.current.dispose();
        keyEventDisposable.current = null;
      }

      let commandBuffer = "";

      if (!disabled) {
        // Add new key event listener and store the disposable
        keyEventDisposable.current = terminal.current.onKey(
          ({ key, domEvent }) => {
            if (domEvent.key === "Enter") {
              handleEnter(commandBuffer);
              commandBuffer = "";
            } else if (domEvent.key === "Backspace") {
              if (commandBuffer.length > 0) {
                commandBuffer = handleBackspace(commandBuffer);
              }
            } else {
              // Ignore paste event
              if (key.charCodeAt(0) === 22) {
                return;
              }
              commandBuffer += key;
              terminal.current?.write(key);
            }
          },
        );

        // Add custom key handler and store the disposable
        terminal.current.attachCustomKeyEventHandler((event) =>
          pasteHandler(event, (text) => {
            commandBuffer += text;
          }),
        );
      } else {
        // Add a noop handler when disabled
        keyEventDisposable.current = terminal.current.onKey((e) => {
          e.domEvent.preventDefault();
          e.domEvent.stopPropagation();
        });
      }
    }

    return () => {
      if (keyEventDisposable.current) {
        keyEventDisposable.current.dispose();
        keyEventDisposable.current = null;
      }
    };
  }, [disabled]);

  return ref;
};
