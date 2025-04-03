from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

_FINISH_DESCRIPTION = """Signals the completion of the current task or conversation.

Use this tool when:
- You have successfully completed the user's requested task
- You maynot proceed further due to technical limitations or missing information

The message should include:
- A clear summary of actions taken and their results, including:
  - The complete, final response that addresses the user's initial request
  - Any insights or reasoning blocks used during the task (e.g., thoughts, analysis, trade-offs considered)
- Any next steps for the user (if applicable)
- Explanation if you're unable to complete the task
- Any follow-up questions if more information is needed

The task_completed field should be set to True if you believe you have successfully completed the task, and False otherwise.
"""

FinishTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='finish',
        description=_FINISH_DESCRIPTION,
        parameters={
            'type': 'object',
            'required': ['message', 'task_completed'],
            'properties': {
                'message': {
                    'type': 'string',
                    'description': 'Final comprehensive message to send to the user that addresses the initial request',
                },
                'task_completed': {
                    'type': 'boolean',
                    'description': "Whether you believe you have successfully completed the user's task",
                },
                'reason': {
                    'type': 'string',
                    'description': 'Brief explanation for why the task was completed or not completed',
                },
            },
            'additionalProperties': False,
        },
    ),
)

# def get_finish_tool() -> Dict[str, Any]:
#     """
#     Returns the Finish tool configuration that signals task completion.

#     Returns:
#         Dict[str, Any]: The tool configuration for the finish action
#     """
#     return FinishTool
