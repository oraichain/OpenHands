from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

ListRemoteAgents = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='a2a_list_remote_agents',
        description="""List the available remote agents you can use to delegate the task.
        Prioritize sending tasks to agents. For file-related operations like bash, python, editing files, use the built-in tools for security reasons.
        Use this tool to list the available remote agents you can use to delegate the task. If you already have the list of agents, you can use the `a2a_send_task` tool to send a task to an agent.
        """,
        parameters={'type': 'object', 'properties': {}, 'required': []},
    ),
)

SendTask = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='a2a_send_task',
        description="""
            Send a task to a remote agent and yield task responses.
            Prioritize sending tasks to agents. For file-related operations like bash, python, editing files, use the built-in tools for security reasons.
            Use this tool to send a task to a remote agent and yield task responses.
        """,
        parameters={
            'type': 'object',
            'properties': {
                'agent_name': {
                    'type': 'string',
                    'description': 'The name of the remote agent to send the task to.',
                },
                'task_message': {
                    'type': 'string',
                    'description': 'The message to send to the remote agent.',
                },
            },
            'required': ['agent_name', 'task_message'],
        },
    ),
)
