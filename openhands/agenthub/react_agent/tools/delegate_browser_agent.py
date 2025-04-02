from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

_DELEGATE_BROWSER_DESCRIPTION = """Delegate a web browsing task to a specialized browsing agent.
* The browsing agent can perform web searches, visit websites, and extract information.
* The browsing agent will return the requested information or a summary of its findings.
* Provide clear instructions about what information to find or what browsing actions to take.
"""

DelegateBrowserTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='delegate_to_browsing_agent',
        description=_DELEGATE_BROWSER_DESCRIPTION,
        parameters={
            'type': 'object',
            'properties': {
                'task': {
                    'type': 'string',
                    'description': 'The search query or browsing instructions for the agent.',
                },
            },
            'required': ['query'],
        },
    ),
)
