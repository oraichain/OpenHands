import { createSlice } from "@reduxjs/toolkit"
import { Task, TaskState } from "#/services/task-service"

export const taskSlice = createSlice({
  name: "task",
  initialState: {
    task: {
      id: "",
      goal: "",
      subtasks: [],
      state: TaskState.OPEN_STATE,
    } as Task,
  },
  reducers: {
    setRootTask: (state, action) => {
      state.task = action.payload as Task
    },
  },
})

export const { setRootTask } = taskSlice.actions

export default taskSlice.reducer
