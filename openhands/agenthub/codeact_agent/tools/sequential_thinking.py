from litellm import ChatCompletionToolParam, ChatCompletionToolParamFunctionChunk

_SEQUENTIAL_THINKING_DESCRIPTION = """A specialized tool for structured, sequential problem-solving through ordered steps.
This tool helps break down complex problems into clear, linear steps that follow a logical progression.
Each step builds directly on the previous ones to create a complete solution path.

When to use this tool:
- Breaking down complex problems into sequential steps
- Creating methodical, step-by-step plans
- Tasks requiring linear progression
- Problems that benefit from clear, ordered thinking
- Debugging or troubleshooting that needs systematic analysis
- Teaching or explaining processes in a structured way
- Situations where each step must be completed before the next begins

Key features:
- Enforces a clear beginning, middle, and end to the thinking process
- Maintains strict sequential order of steps
- Each step directly builds on previous steps
- Progress is tracked through numbered steps
- Focuses on completion of each step before moving to the next
- Prevents branching or parallel thinking paths
- Ensures logical connection between consecutive steps
- Provides a final conclusion that summarizes the sequential analysis

Parameters explained:
- currentStep: The current step in your sequential thinking process
- stepNumber: Current position in the sequence
- totalSteps: Total number of steps in the complete sequence
- nextStepNeeded: True if more steps are needed to complete the thinking process
- isComplete: True only when the final step and conclusion have been reached
- stepSummary: Brief summary of what was accomplished in this step

You should:
1. Start by defining the total number of steps needed (can be adjusted if necessary)
2. Ensure each step follows directly from the previous one
3. Complete each step fully before moving to the next
4. Maintain clear connections between consecutive steps
5. Avoid branching or parallel thinking paths
6. Track progress through step numbers
7. Provide a conclusion in the final step
8. Only mark isComplete as true when the entire sequence is finished"""

SequentialThinkingTool = ChatCompletionToolParam(
    type='function',
    function=ChatCompletionToolParamFunctionChunk(
        name='sequential_thinking',
        description=_SEQUENTIAL_THINKING_DESCRIPTION,
        parameters={
            'type': 'object',
            'properties': {
                'currentStep': {
                    'type': 'string',
                    'description': 'The current step in your sequential thinking process',
                },
                'stepNumber': {
                    'type': 'integer',
                    'description': 'Current position in the sequence',
                    'minimum': 1,
                },
                'totalSteps': {
                    'type': 'integer',
                    'description': 'Total number of steps in the complete sequence',
                    'minimum': 1,
                },
                'nextStepNeeded': {
                    'type': 'boolean',
                    'description': 'Whether another step is needed to complete the thinking process',
                },
                'isComplete': {
                    'type': 'boolean',
                    'description': 'Whether the sequential thinking process is complete',
                },
                'stepSummary': {
                    'type': 'string',
                    'description': 'Brief summary of what was accomplished in this step',
                },
            },
            'required': [
                'currentStep',
                'stepNumber',
                'totalSteps',
                'nextStepNeeded',
                'isComplete',
            ],
        },
    ),
)
