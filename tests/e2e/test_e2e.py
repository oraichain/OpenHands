import asyncio
import os
import time
from typing import List, Optional

import jwt
import requests
import socketio

# Configuration
JWT_SECRET = os.getenv('JWT_SECRET')
JWT_ALGORITHM = 'HS256'
API_BASE_URL = 'http://localhost:3000'

# Create a SocketIO client
sio = socketio.AsyncClient()


def create_jwt_token(public_address: str):
    """Create a JWT token for authentication"""
    payload = {
        'user': {'publicAddress': public_address},
        'exp': int(time.time()) + 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def join_conversation(conversation_id: str, public_address: str):
    # Generate JWT token
    jwt_token = create_jwt_token(public_address)

    # Create query string with parameters
    query_string = (
        f'conversation_id={conversation_id}'
        f'&auth={jwt_token}'
        f'&latest_event_id=-1'
        f'&mode=normal'
        f'&system_prompt=You are a helpful AI assistant.'
    )

    try:
        # Connect to the server with query string
        await sio.connect(
            f'{API_BASE_URL}?{query_string}',
            socketio_path='/socket.io',
            transports=['websocket'],
            namespaces='/',
        )
        print(f'Connected with sid: {sio.sid}')

        # Handle connection events
        @sio.event
        async def connect():
            print('Connection established')

        @sio.event
        async def disconnect():
            print('Disconnected from server')

        @sio.event
        async def oh_event(data):
            print(f'Received event: {data}')

        # Start the CLI input loop in a separate task
        async def cli_input_loop():
            while True:
                try:
                    # Use asyncio's event loop to run synchronous input in a non-blocking way
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input('Enter message (or Ctrl+C to exit): ')
                    )
                    if user_input.strip():  # Only emit non-empty messages
                        # Emit a custom SocketIO event with the user's message
                        await sio.emit(
                            'oh_user_action',
                            {
                                'action': 'message',
                                'args': {
                                    'content': user_input,
                                    'timestamp': time.time(),
                                },
                            },
                        )
                        print(f'Sent message: {user_input}')
                except KeyboardInterrupt:
                    print('\nReceived Ctrl+C, disconnecting...')
                    await sio.disconnect()
                    break
                except Exception as e:
                    print(f'Error in CLI input: {e}')

        # Run the CLI input loop concurrently with the SocketIO event loop
        input_task = asyncio.create_task(cli_input_loop())

        # Keep the connection alive and wait for the input task to complete
        await sio.wait()
        await input_task  # Ensure the input task is cleaned up

    except socketio.exceptions.ConnectionError as e:
        print(f'Connection failed: {e}')
    except Exception as e:
        print(f'Error: {e}')


# The create_conversation function remains unchanged
def create_conversation(
    initial_user_msg: Optional[str] = None,
    image_urls: Optional[List[str]] = None,
    selected_repository: Optional[dict] = None,
    selected_branch: Optional[str] = None,
    replay_json: Optional[str] = None,
    public_address: Optional[str] = None,
) -> dict:
    payload = {
        'initial_user_msg': initial_user_msg,
        'image_urls': image_urls or [],
        'selected_repository': selected_repository,
        'selected_branch': selected_branch,
        'replay_json': replay_json,
    }
    headers = {
        'Authorization': f'Bearer {public_address}',
        'Content-Type': 'application/json',
    }
    try:
        response = requests.post(
            f'{API_BASE_URL}/api/conversations', json=payload, headers=headers
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f'HTTP Error: {e.response.json()}')
        raise e
    except requests.exceptions.RequestException as e:
        print(f'Request Error: {e}')
        raise e


if __name__ == '__main__':
    try:
        public_address = '0x11A87E9d573597d5A4271272df09C1177F34bEbC'
        conversation_id = os.getenv('CONVERSATION_ID')
        if not conversation_id:
            new_conversation_response = create_conversation(
                initial_user_msg='Hello, world!',
                image_urls=[],
                selected_repository=None,
                selected_branch=None,
                replay_json=None,
                public_address=public_address,
            )
            conversation_id = new_conversation_response['conversation_id']
        print(f'Conversation created with ID: {conversation_id}')
        asyncio.run(
            join_conversation(
                conversation_id=conversation_id, public_address=public_address
            )
        )
    except Exception as e:
        print(f'Error: {e}')
