from abc import ABC
from typing import List, AsyncGenerator
import asyncio
import uuid

from openhands.a2a.common.types import Message, SendTaskResponse, SendTaskStreamingResponse, TextPart, TaskStatusUpdateEvent, Task
from openhands.a2a.client.card_resolver import A2ACardResolver
from openhands.a2a.client.client import A2AClient
from openhands.a2a.common.types import AgentCard, A2AClientHTTPError, A2AClientJSONError, TaskSendParams
from openhands.controller.state.state import State
from openhands.core.logger import openhands_logger as logger


class A2AManager(ABC): 
    async def get_agent_card(self, a2a_server_url: str):
        async with A2ACardResolver(a2a_server_url) as resolver:
            try:
                card = await resolver.get_agent_card()
                return card
            except (A2AClientHTTPError, A2AClientJSONError) as e:
                logger.error(f"Failed to fetch agent card from {a2a_server_url}: {str(e)}")
                return None
        
    async def list_remote_agents(self, a2a_server_urls: List[str]):
        """List the available remote agents you can use to delegate the task."""
        if not a2a_server_urls:
            return []
        remote_agent_info = []
        for a2a_server_url in a2a_server_urls:
            card = await self.get_agent_card(a2a_server_url)
            if card:
                remote_agent_info.append(
                    {"agent_name": card.name, "description": card.description, "agent_url": a2a_server_url}
                )
        return remote_agent_info
    
    async def send_task(self, agent_card: AgentCard, message: str, sid: str) -> AsyncGenerator[SendTaskStreamingResponse | SendTaskResponse, None]:
        """Send a task to a remote agent and yield task responses.
        
        Args:
            agent_name: Name of the remote agent
            message: Message to send to the agent
            sid: Session ID
            
        Yields:
            TaskStatusUpdateEvent or Task: Task response updates
        """
        client = A2AClient(agent_card)
        
        request: TaskSendParams = TaskSendParams(
            id=str(uuid.uuid4()),
            sessionId=sid,
            message=Message(
                role="user",
                parts=[TextPart(text=message)],
                metadata={},
            ),
            acceptedOutputModes=["text", "text/plain", "image/png"],
            metadata={'conversation_id': sid},
        )
        
        if agent_card.capabilities.streaming:
            async for response in client.send_task_streaming(request):
                yield response
        else:
            response = await client.send_task(request)
            yield response

    @classmethod
    def from_toml_config(cls, config: dict) -> 'A2AManager':
        a2a_manager = cls(config["a2a_server_url"])
        return a2a_manager