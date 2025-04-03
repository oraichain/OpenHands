from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

_DELEGATE_CODEACT_DESCRIPTION = """Delegate a code-related task to a specialized CodeAct agent.
* Only delegate after thoroughly thinking through the problem and exhausting other available methods.
* The CodeAct agent can analyze code, debug issues, implement features, and optimize performance.
* The CodeAct agent will return code snippets, explanations, or analysis results.
* Provide clear instructions about what code task needs to be performed.
* Consider if you can solve the task without delegation first.
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
                    'description': 'The code task instructions for the agent.',
                },
            },
            'required': ['task'],
        },
    ),
)
