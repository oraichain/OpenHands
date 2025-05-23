from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

ExecutePlanTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='execute_plan',
        description='Update the progress of the plan and delegate the next speaker',
        parameters={
            'type': 'object',
            'properties': {
                'is_request_satisfied': {
                    'type': 'object',
                    'description': 'Whether the request is satisfied',
                    'properties': {
                        'reason': {
                            'type': 'string',
                            'description': 'The reason for the decision',
                        },
                        'answer': {
                            'type': 'boolean',
                            'description': 'Whether the request is satisfied',
                        },
                    },
                },
                'is_in_loop': {
                    'type': 'object',
                    'description': 'Whether the request is in a loop',
                    'properties': {
                        'reason': {
                            'type': 'string',
                            'description': 'The reason for the decision',
                        },
                        'answer': {
                            'type': 'boolean',
                            'description': 'Whether the request is in a loop',
                        },
                    },
                },
                'is_progress_being_made': {
                    'type': 'object',
                    'description': 'Whether the request is making progress',
                    'properties': {
                        'reason': {
                            'type': 'string',
                            'description': 'The reason for the decision',
                        },
                        'answer': {
                            'type': 'boolean',
                            'description': 'Whether the request is making progress',
                        },
                    },
                },
                'next_speaker': {
                    'type': 'object',
                    'description': 'The next speaker',
                    'properties': {
                        'reason': {
                            'type': 'string',
                            'description': 'The reason for the decision',
                        },
                        'answer': {'type': 'string', 'description': 'The next speaker'},
                    },
                },
                'instruction_or_question': {
                    'type': 'object',
                    'description': 'The instruction or question',
                    'properties': {
                        'reason': {
                            'type': 'string',
                            'description': 'The reason for the decision',
                        },
                        'answer': {
                            'type': 'string',
                            'description': 'The instruction or question',
                        },
                    },
                },
            },
        },
    ),
)
