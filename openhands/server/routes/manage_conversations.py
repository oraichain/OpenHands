import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Body,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from openhands.core.config.llm_config import LLMConfig
from openhands.core.logger import openhands_logger as logger
from openhands.core.schema.research import ResearchMode
from openhands.events.action.message import MessageAction
from openhands.events.event import EventSource
from openhands.events.stream import EventStream
from openhands.integrations.provider import (
    PROVIDER_TOKEN_TYPE,
)
from openhands.integrations.service_types import Repository
from openhands.server.auth import (
    get_github_user_id,
    get_provider_tokens,
    get_user_id,
)
from openhands.server.data_models.conversation_info import ConversationInfo
from openhands.server.data_models.conversation_info_result_set import (
    ConversationInfoResultSet,
)
from openhands.server.modules import conversation_module
from openhands.server.session.conversation_init_data import ConversationInitData
from openhands.server.shared import (
    ConversationStoreImpl,
    config,
    conversation_manager,
    file_store,
    s3_handler,
)
from openhands.server.thesis_auth import (
    change_thread_visibility,
    create_thread,
    delete_thread,
    get_thread_by_id,
)
from openhands.server.types import LLMAuthenticationError, MissingSettingsError
from openhands.storage.data_models.conversation_metadata import ConversationMetadata
from openhands.storage.data_models.conversation_status import ConversationStatus
from openhands.utils.async_utils import wait_all
from openhands.utils.conversation_summary import generate_conversation_title
from openhands.utils.get_user_setting import get_user_setting

app = APIRouter(prefix='/api')


class InitSessionRequest(BaseModel):
    selected_repository: Repository | None = None
    selected_branch: str | None = None
    initial_user_msg: str | None = None
    image_urls: list[str] | None = None
    replay_json: str | None = None
    system_prompt: str | None = None
    user_prompt: str | None = None
    mcp_disable: dict[str, bool] | None = None
    research_mode: str | None = None
    space_id: int | None = None
    thread_follow_up: int | None = None
    followup_discover_id: str | None = None


class ChangeVisibilityRequest(BaseModel):
    is_published: bool
    hidden_prompt: bool


class ConversationVisibility(BaseModel):
    is_published: bool
    hidden_prompt: bool


async def _create_new_conversation(
    user_id: str | None,
    git_provider_tokens: PROVIDER_TOKEN_TYPE | None,
    selected_repository: Repository | None,
    selected_branch: str | None,
    initial_user_msg: str | None,
    image_urls: list[str] | None,
    replay_json: str | None,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
    attach_convo_id: bool = False,
    mnemonic: str | None = None,
    mcp_disable: dict[str, bool] | None = None,
    research_mode: str | None = None,
    knowledge_base: list[dict] | None = None,
    space_id: int | None = None,
    thread_follow_up: int | None = None,
    raw_followup_conversation_id: str | None = None,
):
    logger.info(
        'Creating conversation',
        extra={'signal': 'create_conversation', 'user_id': user_id},
    )

    running_conversations = await conversation_manager.get_running_agent_loops(user_id)
    if (
        len(running_conversations) >= config.max_concurrent_conversations
        and os.getenv('RUN_MODE') == 'PROD'
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'You have reached the maximum limit of {config.max_concurrent_conversations} concurrent conversations.',
        )

    logger.info('Loading settings')
    settings = await get_user_setting(user_id)

    session_init_args: dict = {}
    if settings:
        session_init_args = {**settings.__dict__, **session_init_args}
        # We could use litellm.check_valid_key for a more accurate check,
        # but that would run a tiny inference.
        if (
            not settings.llm_api_key
            or settings.llm_api_key.get_secret_value().isspace()
        ):
            logger.warn(f'Missing api key for model {settings.llm_model}')
            raise LLMAuthenticationError(
                'Error authenticating with the LLM provider. Please check your API key'
            )

    else:
        logger.warn('Settings not present, not starting conversation')
        raise MissingSettingsError('Settings not found')

    session_init_args['git_provider_tokens'] = git_provider_tokens
    session_init_args['selected_repository'] = selected_repository
    session_init_args['selected_branch'] = selected_branch
    conversation_init_data = ConversationInitData(**session_init_args)
    logger.info('Loading conversation store')
    conversation_store = await ConversationStoreImpl.get_instance(config, user_id, None)
    logger.info('Conversation store loaded')

    conversation_id = uuid.uuid4().hex
    while await conversation_store.exists(conversation_id):
        logger.warning(f'Collision on conversation ID: {conversation_id}. Retrying...')
        conversation_id = uuid.uuid4().hex
    logger.info(
        f'New conversation ID: {conversation_id}',
        extra={'user_id': user_id, 'session_id': conversation_id},
    )

    conversation_title = get_default_conversation_title(conversation_id)

    logger.info(f'Saving metadata for conversation {conversation_id}')
    await conversation_store.save_metadata(
        ConversationMetadata(
            conversation_id=conversation_id,
            title=conversation_title,
            user_id=user_id,
            github_user_id=None,
            selected_repository=selected_repository.full_name
            if selected_repository
            else selected_repository,
            selected_branch=selected_branch,
        )
    )

    logger.info(
        f'Starting agent loop for conversation {conversation_id}',
        extra={'user_id': user_id, 'session_id': conversation_id},
    )
    initial_message_action = None
    if initial_user_msg or image_urls:
        user_msg = (
            initial_user_msg.format(conversation_id)
            if attach_convo_id and initial_user_msg
            else initial_user_msg
        )
        initial_message_action = MessageAction(
            content=user_msg or '',
            image_urls=image_urls or [],
            mode=research_mode,
        )

    await conversation_manager.maybe_start_agent_loop(
        conversation_id,
        conversation_init_data,
        user_id,
        initial_user_msg=initial_message_action,
        replay_json=replay_json,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        github_user_id=None,
        mnemonic=mnemonic,
        mcp_disable=mcp_disable,
        knowledge_base=knowledge_base,
        space_id=space_id,
        thread_follow_up=thread_follow_up,
        research_mode=research_mode,
        raw_followup_conversation_id=raw_followup_conversation_id,
    )
    logger.info(f'Finished initializing conversation {conversation_id}')

    return conversation_id, conversation_title


@app.post('/conversations')
async def new_conversation(request: Request, data: InitSessionRequest):
    """Initialize a new session or join an existing one.

    After successful initialization, the client should connect to the WebSocket
    using the returned conversation ID.
    """
    logger.info('Initializing new conversation')
    provider_tokens = get_provider_tokens(request)
    selected_repository = data.selected_repository
    selected_branch = data.selected_branch
    initial_user_msg = data.initial_user_msg
    image_urls = data.image_urls or []
    replay_json = data.replay_json
    system_prompt = data.system_prompt
    user_prompt = data.user_prompt
    user_id = get_user_id(request)
    mnemonic = request.state.user.mnemonic
    space_id = data.space_id
    thread_follow_up = data.thread_follow_up
    bearer_token = request.headers.get('Authorization')
    x_device_id = request.headers.get('x-device-id')
    followup_discover_id = data.followup_discover_id

    try:
        knowledge_base = None
        raw_followup_conversation_id = None
        # if space_id or thread_follow_up:
        #     knowledge_base = await search_knowledge(
        #         initial_user_msg, space_id, thread_follow_up, user_id
        # )
        # if knowledge and knowledge['data']['summary']:
        #     initial_user_msg = (
        #         f"Reference information:\n{knowledge['data']['summary']}\n\n"
        #         f"Question:\n{initial_user_msg}"
        #     )
        if thread_follow_up:
            threadData = await get_thread_by_id(thread_follow_up)
            if threadData:
                raw_followup_conversation_id = threadData['conversationId']
        start_time = time.time()
        conversation_id, conversation_title = await _create_new_conversation(
            user_id,
            provider_tokens,
            selected_repository,
            selected_branch,
            initial_user_msg,
            image_urls,
            replay_json,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            mnemonic=mnemonic,
            mcp_disable=data.mcp_disable,
            research_mode=data.research_mode,
            knowledge_base=knowledge_base,
            space_id=space_id,
            thread_follow_up=thread_follow_up,
            raw_followup_conversation_id=raw_followup_conversation_id,
        )

        end_time = time.time()
        logger.info(
            f'Time taken to create new conversation: {end_time - start_time} seconds'
        )
        if conversation_id and user_id is not None:
            start_time = time.time()
            await create_thread(
                space_id,
                thread_follow_up,
                conversation_id,
                data.initial_user_msg,
                bearer_token,
                x_device_id,
                followup_discover_id,
                data.research_mode,
            )
            end_time = time.time()
            logger.info(f'Time taken to create thread: {end_time - start_time} seconds')
            metadata: dict[str, Any] = {}
            metadata['hidden_prompt'] = True
            if space_id is not None:
                metadata['space_id'] = space_id
            if thread_follow_up is not None:
                metadata['thread_follow_up'] = thread_follow_up
            if raw_followup_conversation_id is not None:
                metadata['raw_followup_conversation_id'] = raw_followup_conversation_id
            if data.research_mode and data.research_mode == ResearchMode.FOLLOW_UP:
                metadata['research_mode'] = ResearchMode.FOLLOW_UP
            start_time = time.time()
            await conversation_module._update_conversation_visibility(
                conversation_id,
                False,
                user_id,
                metadata,
                conversation_title,
                'available',
            )
            end_time = time.time()
            logger.info(
                f'Time taken to update conversation visibility: {end_time - start_time} seconds'
            )
        return JSONResponse(
            content={'status': 'ok', 'conversation_id': conversation_id}
        )
    except MissingSettingsError as e:
        return JSONResponse(
            content={
                'status': 'error',
                'message': str(e),
                'msg_id': 'CONFIGURATION$SETTINGS_NOT_FOUND',
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    except LLMAuthenticationError as e:
        return JSONResponse(
            content={
                'status': 'error',
                'message': str(e),
                'msg_id': 'STATUS$ERROR_LLM_AUTHENTICATION',
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        return JSONResponse(
            content={
                'status': 'error',
                'detail': str(e.detail) if hasattr(e, 'detail') else str(e),
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@app.get('/conversations')
async def search_conversations(
    request: Request,
    page_id: str | None = None,
    limit: int = 20,
    page: int = 1,
    keyword: str | None = None,
) -> ConversationInfoResultSet:
    user_id = get_user_id(request)
    conversation_store = await ConversationStoreImpl.get_instance(
        config, user_id, get_github_user_id(request)
    )

    # get conversation visibility by user id
    visible_conversations = (
        await conversation_module._get_conversation_visibility_by_user_id(
            user_id, page, limit, keyword
        )
    )
    if len(visible_conversations['items']) == 0:
        return ConversationInfoResultSet(results=[], next_page_id=None)
    visible_conversation_ids = [
        conversation['conversation_id']
        for conversation in visible_conversations['items']
    ]

    conversation_metadata_result_set = await conversation_store.search(
        page_id, limit, filter_conversation_ids=visible_conversation_ids
    )
    # Filter out conversations older than max_age
    now = datetime.now(timezone.utc)
    max_age = config.conversation_max_age_seconds
    filtered_results = [
        conversation
        for conversation in conversation_metadata_result_set.results
        if hasattr(conversation, 'created_at')
        and (now - conversation.created_at.replace(tzinfo=timezone.utc)).total_seconds()
        <= max_age
    ]

    conversation_ids = set(
        conversation.conversation_id for conversation in filtered_results
    )
    running_conversations = await conversation_manager.get_running_agent_loops(
        get_user_id(request), set(conversation_ids)
    )
    result = ConversationInfoResultSet(
        results=await wait_all(
            _get_conversation_info(
                conversation=conversation,
                is_running=conversation.conversation_id in running_conversations,
            )
            for conversation in filtered_results
        ),
        next_page_id=conversation_metadata_result_set.next_page_id,
        total=visible_conversations['total'],
    )
    return result


@app.get('/conversations/{conversation_id}')
async def get_conversation(
    conversation_id: str, request: Request
) -> ConversationInfo | None:
    conversation_store = await ConversationStoreImpl.get_instance(
        config, get_user_id(request), get_github_user_id(request)
    )
    try:
        metadata = await conversation_store.get_metadata(conversation_id)
        is_running = await conversation_manager.is_agent_loop_running(conversation_id)
        conversation_info = await _get_conversation_info(metadata, is_running)
        # existed_conversation = await conversation_module._get_conversation_by_id(
        #     conversation_id, str(get_user_id(request))
        # )
        # if existed_conversation:
        #     conversation_info.research_mode = existed_conversation.configs.get('research_mode', None)
        return conversation_info
    except FileNotFoundError:
        return None


def get_default_conversation_title(conversation_id: str) -> str:
    """
    Generate a default title for a conversation based on its ID.

    Args:
        conversation_id: The ID of the conversation

    Returns:
        A default title string
    """
    return f'Research {conversation_id[:5]}'


async def auto_generate_title(conversation_id: str, user_id: str | None) -> str:
    """
    Auto-generate a title for a conversation based on the first user message.
    Uses LLM-based title generation if available, otherwise falls back to a simple truncation.

    Args:
        conversation_id: The ID of the conversation
        user_id: The ID of the user

    Returns:
        A generated title string
    """
    logger.info(f'Auto-generating title for conversation {conversation_id}')

    try:
        # Create an event stream for the conversation
        event_stream = EventStream(conversation_id, file_store, user_id)

        # Find the first user message
        first_user_message = None
        for event in event_stream.get_events():
            if (
                event.source == EventSource.USER
                and isinstance(event, MessageAction)
                and event.content
                and event.content.strip()
            ):
                first_user_message = event.content
                break

        if first_user_message:
            # Get LLM config from user settings
            try:
                settings = await get_user_setting(user_id)

                if settings and settings.llm_model:
                    # Create LLM config from settings
                    llm_config = LLMConfig(
                        model=settings.llm_model,
                        api_key=settings.llm_api_key,
                        base_url=settings.llm_base_url,
                    )

                    # Try to generate title using LLM
                    llm_title = await generate_conversation_title(
                        first_user_message, llm_config
                    )
                    if llm_title:
                        logger.info(f'Generated title using LLM: {llm_title}')
                        return llm_title
            except Exception as e:
                logger.error(f'Error using LLM for title generation: {e}')

            # Fall back to simple truncation if LLM generation fails or is unavailable
            first_user_message = first_user_message.strip()
            title = first_user_message[:30]
            if len(first_user_message) > 30:
                title += '...'
            logger.info(f'Generated title using truncation: {title}')
            return title
    except Exception as e:
        logger.error(f'Error generating title: {str(e)}')
    return ''


@app.patch('/conversations/{conversation_id}')
async def update_conversation(
    request: Request, conversation_id: str, title: str = Body(embed=True)
) -> bool:
    user_id = get_user_id(request)
    conversation_store = await ConversationStoreImpl.get_instance(
        config, user_id, get_github_user_id(request)
    )
    metadata = await conversation_store.get_metadata(conversation_id)
    if not metadata:
        return False

    # If title is empty or unspecified, auto-generate it
    if not title or title.isspace():
        title = await auto_generate_title(conversation_id, user_id)

        # If we still don't have a title, use the default
        if not title or title.isspace():
            title = get_default_conversation_title(conversation_id)

    metadata.title = title
    await conversation_store.save_metadata(metadata)
    await conversation_module._update_title_conversation(conversation_id, title)
    return True


@app.delete('/conversations/{conversation_id}')
async def delete_conversation(
    conversation_id: str,
    request: Request,
) -> bool:
    user_id = get_user_id(request)
    # conversation_store = await ConversationStoreImpl.get_instance(
    #     config, user_id, get_github_user_id(request)
    # )
    # try:
    #     await conversation_store.get_metadata(conversation_id)
    # except FileNotFoundError:
    #     return False
    is_running = await conversation_manager.is_agent_loop_running(conversation_id)
    if is_running:
        await conversation_manager.close_session(conversation_id)

    # disable delete conversation from runtime
    # runtime_cls = get_runtime_cls(config.runtime)
    # await runtime_cls.delete(conversation_id)
    # await conversation_store.delete_metadata(conversation_id)

    # delete conversation from databasedatab
    await delete_thread(
        conversation_id,
        request.headers.get('Authorization'),
        request.headers.get('x-device-id'),
    )
    await conversation_module._delete_conversation(conversation_id, str(user_id))

    return True


@app.patch('/conversations/{conversation_id}/change-visibility')
async def change_visibility(
    conversation_id: str,
    request: Request,
    is_published: bool = Form(...),
    hidden_prompt: bool = Form(...),
    file: Optional[UploadFile] = None,
) -> bool:
    user_id = get_user_id(request)
    conversation_store = await ConversationStoreImpl.get_instance(
        config, user_id, get_github_user_id(request)
    )
    metadata = await conversation_store.get_metadata(conversation_id)
    if not metadata:
        return False

    # Handle file upload if provided
    extra_data = {
        'hidden_prompt': hidden_prompt,
    }

    if file and s3_handler is not None:
        print('processing file:', file)
        folder_path = f'conversations/{conversation_id}'
        file_url = await s3_handler.upload_file(file, folder_path)
        if file_url:
            extra_data['thumbnail_url'] = file_url

    await change_thread_visibility(
        conversation_id,
        is_published,
        request.headers.get('Authorization'),
        request.headers.get('x-device-id'),
    )

    return await conversation_module._update_conversation_visibility(
        conversation_id,
        is_published,
        str(user_id),
        extra_data,
        metadata.title if metadata.title else '',
    )


@app.get(
    '/conversations/{conversation_id}/visibility', response_model=ConversationVisibility
)
async def get_conversation_visibility(
    conversation_id: str,
    request: Request,
) -> bool:
    user_id = get_user_id(request)
    return await conversation_module._get_conversation_visibility(
        conversation_id, str(user_id)
    )


async def _get_conversation_info(
    conversation: ConversationMetadata,
    is_running: bool,
) -> ConversationInfo | None:
    try:
        title = conversation.title
        if not title:
            title = get_default_conversation_title(conversation.conversation_id)
        return ConversationInfo(
            conversation_id=conversation.conversation_id,
            title=title,
            last_updated_at=conversation.last_updated_at,
            created_at=conversation.created_at,
            selected_repository=conversation.selected_repository,
            status=(
                ConversationStatus.RUNNING if is_running else ConversationStatus.STOPPED
            ),
        )
    except Exception as e:
        logger.error(
            f'Error loading conversation {conversation.conversation_id}: {str(e)}',
            extra={'session_id': conversation.conversation_id},
        )
        return None
