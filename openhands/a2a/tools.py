from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk


ListRemoteAgents = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='a2a_list_remote_agents',
        description="""List the available remote agents you can use to delegate the task. Call this tool only once, when you need to list the available remote agents.""",
        parameters={
            'type': 'object',
            'properties': {},
            'required': []
        },
    ),
)

SendTask = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='a2a_send_task',
        description="""
            Send a task to a remote agent and yield task responses. Use this tool to delegate the task to a remote agent when you don't have the resources to complete the task. When the task is complete, the tool will yield the task response.
            The task can be long running and you can stream the task response back to the user.
        """,
        parameters={
            'type': 'object',
            'properties': {
                'agent_url': {'type': 'string', 'description': 'The URL of the remote agent to send the task to. The URL format is: http(s)://<host>:<port>. There must be no path in the URL.'},
                'agent_name': {'type': 'string', 'description': 'The name of the remote agent to send the task to.'},
                'task_message': {'type': 'string', 'description': 'The message to send to the remote agent. This message could be your current thoughts, a question, or a request for information. It could also be a user message that you want to delegate to the remote agent.'},
            },
            'required': ['agent_url', 'agent_name', 'task_message']
        },
    ),
)


