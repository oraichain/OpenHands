import json

import pytest

from openhands.storage.conversation.file_conversation_store import FileConversationStore
from openhands.storage.data_models.conversation_metadata import ConversationMetadata
from openhands.storage.locations import get_conversation_metadata_filename
from openhands.storage.memory import InMemoryFileStore


@pytest.mark.asyncio
async def test_load_store():
    store = FileConversationStore(InMemoryFileStore({}))
    expected = ConversationMetadata(
        conversation_id='some-conversation-id',
        user_id='some-user-id',
        github_user_id='12345',
        selected_repository='some-repo',
        title="Let's talk about trains",
    )
    await store.save_metadata(expected)
    found = await store.get_metadata('some-conversation-id')
    assert expected == found


@pytest.mark.asyncio
async def test_load_int_user_id():
    store = FileConversationStore(
        InMemoryFileStore(
            {
                get_conversation_metadata_filename(
                    'some-conversation-id', '67890'
                ): json.dumps(
                    {
                        'conversation_id': 'some-conversation-id',
                        'github_user_id': 12345,
                        'user_id': '67890',
                        'selected_repository': 'some-repo',
                        'title': "Let's talk about trains",
                        'created_at': '2025-01-16T19:51:04.886331Z',
                    }
                )
            }
        ),
        user_id='67890',
    )
    found = await store.get_metadata('some-conversation-id')
    assert found.github_user_id == '12345'
    assert found.user_id == '67890'


@pytest.mark.asyncio
async def test_search_empty():
    store = FileConversationStore(InMemoryFileStore({}))
    result = await store.search()
    assert len(result.results) == 0
    assert result.next_page_id is None


@pytest.mark.asyncio
async def test_search_basic():
    # Create test data with 3 conversations at different dates
    store = FileConversationStore(
        InMemoryFileStore(
            {
                get_conversation_metadata_filename('conv1', '123'): json.dumps(
                    {
                        'conversation_id': 'conv1',
                        'github_user_id': '123',
                        'user_id': '123',
                        'selected_repository': 'repo1',
                        'title': 'First conversation',
                        'created_at': '2025-01-16T19:51:04Z',
                    }
                ),
                get_conversation_metadata_filename('conv2', '123'): json.dumps(
                    {
                        'conversation_id': 'conv2',
                        'github_user_id': '123',
                        'user_id': '123',
                        'selected_repository': 'repo1',
                        'title': 'Second conversation',
                        'created_at': '2025-01-17T19:51:04Z',
                    }
                ),
                get_conversation_metadata_filename('conv3', '123'): json.dumps(
                    {
                        'conversation_id': 'conv3',
                        'github_user_id': '123',
                        'user_id': '123',
                        'selected_repository': 'repo1',
                        'title': 'Third conversation',
                        'created_at': '2025-01-15T19:51:04Z',
                    }
                ),
            }
        ),
        user_id='123',
    )

    result = await store.search()
    assert len(result.results) == 3
    # Should be sorted by date, newest first
    assert result.results[0].conversation_id == 'conv2'
    assert result.results[1].conversation_id == 'conv1'
    assert result.results[2].conversation_id == 'conv3'
    assert result.next_page_id is None


@pytest.mark.asyncio
async def test_search_pagination():
    # Create test data with 5 conversations
    store = FileConversationStore(
        InMemoryFileStore(
            {
                get_conversation_metadata_filename(f'conv{i}', '123'): json.dumps(
                    {
                        'conversation_id': f'conv{i}',
                        'github_user_id': '123',
                        'user_id': '123',
                        'selected_repository': 'repo1',
                        'title': f'Conversation {i}',
                        'created_at': f'2025-01-{15+i}T19:51:04Z',
                    }
                )
                for i in range(1, 6)
            }
        ),
        user_id='123',
    )

    # Test with limit of 2
    result = await store.search(limit=2)
    assert len(result.results) == 2
    assert result.results[0].conversation_id == 'conv5'  # newest first
    assert result.results[1].conversation_id == 'conv4'
    assert result.next_page_id is not None

    # Get next page using the next_page_id
    result2 = await store.search(page_id=result.next_page_id, limit=2)
    assert len(result2.results) == 2
    assert result2.results[0].conversation_id == 'conv3'
    assert result2.results[1].conversation_id == 'conv2'
    assert result2.next_page_id is not None

    # Get last page
    result3 = await store.search(page_id=result2.next_page_id, limit=2)
    assert len(result3.results) == 1
    assert result3.results[0].conversation_id == 'conv1'
    assert result3.next_page_id is None


@pytest.mark.asyncio
async def test_search_with_invalid_conversation():
    # Test handling of invalid conversation data
    store = FileConversationStore(
        InMemoryFileStore(
            {
                get_conversation_metadata_filename('conv1', '123'): json.dumps(
                    {
                        'conversation_id': 'conv1',
                        'github_user_id': '123',
                        'user_id': '123',
                        'selected_repository': 'repo1',
                        'title': 'Valid conversation',
                        'created_at': '2025-01-16T19:51:04Z',
                    }
                ),
                get_conversation_metadata_filename(
                    'conv2', '123'
                ): 'invalid json',  # Invalid conversation
            }
        ),
        user_id='123',
    )

    result = await store.search()
    # Should return only the valid conversation
    assert len(result.results) == 1
    assert result.results[0].conversation_id == 'conv1'
    assert result.next_page_id is None


@pytest.mark.asyncio
async def test_get_all_metadata():
    store = FileConversationStore(
        InMemoryFileStore(
            {
                get_conversation_metadata_filename('conv1', '123'): json.dumps(
                    {
                        'conversation_id': 'conv1',
                        'github_user_id': '123',
                        'user_id': '123',
                        'selected_repository': 'repo1',
                        'title': 'First conversation',
                        'created_at': '2025-01-16T19:51:04Z',
                    }
                ),
                get_conversation_metadata_filename('conv2', '123'): json.dumps(
                    {
                        'conversation_id': 'conv2',
                        'github_user_id': '123',
                        'user_id': '123',
                        'selected_repository': 'repo1',
                        'title': 'Second conversation',
                        'created_at': '2025-01-17T19:51:04Z',
                    }
                ),
            }
        ),
        user_id='123',
    )

    results = await store.get_all_metadata(['conv1', 'conv2'])
    assert len(results) == 2
    assert results[0].conversation_id == 'conv1'
    assert results[0].title == 'First conversation'
    assert results[1].conversation_id == 'conv2'
    assert results[1].title == 'Second conversation'
