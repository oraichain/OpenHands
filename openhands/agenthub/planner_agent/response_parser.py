from openhands.agenthub.codeact_agent.function_calling import combine_thought
from openhands.controller.action_parser import ResponseParser
from openhands.core.exceptions import FunctionCallNotExistsError
from openhands.events.action.mcp import McpAction
from openhands.events.tool import ToolCallMetadata
from openhands.io import json
from openhands.events.action import (
    Action,
)
from openhands.events.serialization.action import action_from_dict
from litellm import ModelResponse

from openhands.mcp.tool import MCPClientTool


class PlannerResponseParser(ResponseParser):
    def __init__(self):
        super().__init__()

    def parse_response(self, response) -> str:
        pass

    def parse(self, response: ModelResponse) -> str:

        actions: list[Action] = []
        assert len(response.choices) == 1, 'Only one choice is supported for now'
        choice = response.choices[0]
        assistant_msg = choice.message
        if hasattr(assistant_msg, 'tool_calls') and assistant_msg.tool_calls:

            # Check if there's assistant_msg.content. If so, add it to the thought
            thought = ''
            if isinstance(assistant_msg.content, str):
                thought = assistant_msg.content
            elif isinstance(assistant_msg.content, list):
                for msg in assistant_msg.content:
                    if msg['type'] == 'text':
                        thought += msg['text']

            for i, tool_call in enumerate(assistant_msg.tool_calls):

                arguments = tool_call.function.arguments

                # ================================================
                # McpAction (MCP)
                # ================================================
                if tool_call.function.name.endswith(MCPClientTool.postfix()):
                    original_action_name = tool_call.function.name.replace(
                        MCPClientTool.postfix(), ''
                    )
                    print(f'Original action name: {original_action_name}')
                    action = McpAction(
                        name=original_action_name,
                        arguments=arguments,
                    )
                else:
                    raise FunctionCallNotExistsError(
                        f'Tool {tool_call.function.name} is not registered. (arguments: {arguments}). Please check the tool name and retry with an existing tool.'
                    )

                # We only add thought to the first action
                if i == 0:
                    action = combine_thought(action, thought)
                # Add metadata for tool calling
                action.tool_call_metadata = ToolCallMetadata(
                    tool_call_id=tool_call.id,
                    function_name=tool_call.function.name,
                    model_response=response,
                    total_calls_in_response=len(assistant_msg.tool_calls),
                )
                actions.append(action)
        else:
            # get the next action from the response
            action_str = choice['message']['content']
            actions.append(self.parse_action(action_str))

        return actions

    def parse_action(self, action_str: str) -> Action:
        """Parses a string to find an action within it

        Parameters:
        - response (str): The string to be parsed

        Returns:
        - Action: The action that was found in the response string
        """
        # attempt to load the JSON dict from the response
        action_dict = json.loads(action_str)

        if 'content' in action_dict:
            # The LLM gets confused here. Might as well be robust
            action_dict['contents'] = action_dict.pop('content')

        return action_from_dict(action_dict)
