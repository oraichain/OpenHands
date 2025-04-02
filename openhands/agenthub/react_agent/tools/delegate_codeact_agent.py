from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

_DELEGATE_CODEACT_DESCRIPTION = """Delegate a code-related task to a specialized CodeAct agent.
* The CodeAct agent can analyze code, debug issues, implement features, and optimize performance.
* The CodeAct agent will return code snippets, explanations, or analysis results.
* Provide clear instructions about what code task needs to be performed.
"""

DelegateCodeActTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='delegate_to_codeact_agent',
        description=_DELEGATE_CODEACT_DESCRIPTION,
        parameters={
            'type': 'object',
            'properties': {
                'task': {
                    'type': 'string',
                    'description': 'The search query or browsing instructions for the agent.',
                },
            },
            'required': ['task'],
        },
    ),
)
