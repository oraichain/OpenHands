import { AgentState } from "#/types/agent-state";
import { createSlice } from "@reduxjs/toolkit";

export const agentSlice = createSlice({
  name: "agent",
  initialState: {
    curAgentState: AgentState.LOADING,
    currentTask: {
      args: {
        task_content: "",
      },
    },
  },
  reducers: {
    setCurrentAgentState: (state, action) => {
      state.curAgentState = action.payload;
    },
    setCurrentTask: (state, action) => {
      state.currentTask = action.payload;
    },
  },
});

export const { setCurrentAgentState, setCurrentTask } = agentSlice.actions;

export default agentSlice.reducer;
