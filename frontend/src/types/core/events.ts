export interface TerminalDataEvent {
  id: number;
  timestamp: string;
  source: "terminal";
  data: string;
  type: "terminal_data";
}
