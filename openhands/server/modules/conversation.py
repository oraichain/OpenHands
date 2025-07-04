import asyncio
from datetime import datetime

from sqlalchemy import and_, desc, func, or_, select

from openhands.core.logger import openhands_logger as logger
from openhands.server.db import database
from openhands.server.models import (
    Conversation,
    ResearchTrending,
    ResearchView,
)
from openhands.server.static import SortBy


class ConversationModule:
    def get_view_count(self, conversation: dict, sort_by=None):
        if not sort_by:
            return 0
        if sort_by == SortBy.total_view_24h:
            value = conversation.get('total_view_24h')
            return 0 if value is None else value
        if sort_by == SortBy.total_view_7d:
            value = conversation.get('total_view_7d')
            return 0 if value is None else value
        if sort_by == SortBy.total_view_30d:
            value = conversation.get('total_view_30d')
            return 0 if value is None else value
        return 0

    async def _get_conversation_by_id(self, conversation_id: str):
        try:
            query = Conversation.select().where(
                Conversation.c.conversation_id == conversation_id
            )
            existing_record = await database.fetch_one(query)
            return existing_record
        except Exception as e:
            logger.error(f'Error getting conversation by id: {str(e)}')
            return None

    async def _update_title_conversation(self, conversation_id: str, title: str):
        try:
            await database.execute(
                Conversation.update()
                .where(Conversation.c.conversation_id == conversation_id)
                .values(title=title)
            )
        except Exception as e:
            logger.error(f'Error updating title conversation: {str(e)}')

    async def _update_research_view(self, conversation_id: str, ip_address: str = ''):
        try:
            await database.execute(
                ResearchView.insert().values(
                    conversation_id=conversation_id,
                    created_at=datetime.now(),
                    ip_address=ip_address,
                )
            )
        except Exception as e:
            logger.error(f'Error updating research view: {str(e)}')
            return False

    async def _get_conversation_visibility(self, conversation_id: str, user_id: str):
        try:
            query = Conversation.select().where(
                (Conversation.c.conversation_id == conversation_id)
                & (Conversation.c.user_id == user_id)
            )
            existing_record = await database.fetch_one(query)

            return {
                'is_published': existing_record.published if existing_record else False,
                'hidden_prompt': existing_record.configs.get('hidden_prompt', True)
                if existing_record
                else True,
                'thumbnail_url': existing_record.configs.get('thumbnail_url', None)
                if existing_record
                else None,
            }
        except Exception as e:
            logger.error(f'Error getting conversation visibility: {str(e)}')
            return {
                'is_published': False,
                'hidden_prompt': False,
                'thumbnail_url': None,
            }

    async def _update_conversation_visibility(
        self,
        conversation_id: str,
        is_published: bool,
        user_id: str,
        configs: dict,
        title: str,
        status: str = 'available',
    ):
        try:
            query = Conversation.select().where(
                (Conversation.c.conversation_id == conversation_id)
                & (Conversation.c.user_id == user_id)
            )
            existing_record = await database.fetch_one(query)

            if existing_record:
                await database.execute(
                    Conversation.update()
                    .where(
                        (Conversation.c.conversation_id == conversation_id)
                        & (Conversation.c.user_id == user_id)
                    )
                    .values(
                        published=is_published,
                        configs={**existing_record.configs, **configs},
                        title=title,
                        status=status,
                    )
                )
            else:
                await database.execute(
                    Conversation.insert().values(
                        conversation_id=conversation_id,
                        user_id=user_id,
                        published=is_published,
                        title=title,
                        configs=configs,
                    )
                )
            return True
        except Exception as e:
            logger.error(f'Error updating conversation visibility: {str(e)}')
            return False

    async def _get_conversation_visibility_info(self, conversation_id: str):
        """
        Check if the conversation is published and return the mnemonic of the user who owns the conversation
        """
        try:
            query = Conversation.select().where(
                Conversation.c.conversation_id == conversation_id
            )
            existing_record = await database.fetch_one(query)
            if not existing_record:
                return 'Conversation not found', None
            # if existing_record.status and existing_record.status == 'deleted':
            #     return 'Conversation deleted', None
            if not existing_record.published:
                return 'Conversation not published', {
                    'user_id': existing_record.user_id,
                    'hidden_prompt': existing_record.configs.get('hidden_prompt', True),
                    'space_id': existing_record.configs.get('space_id', None),
                    'thread_follow_up': existing_record.configs.get(
                        'thread_follow_up', None
                    ),
                    'research_mode': existing_record.configs.get('research_mode', None),
                    'raw_followup_conversation_id': existing_record.configs.get(
                        'raw_followup_conversation_id', None
                    ),
                }
            user_id = existing_record.user_id
            return None, {
                'user_id': user_id,
                'hidden_prompt': existing_record.configs.get('hidden_prompt', True),
                'space_id': existing_record.configs.get('space_id', None),
                'thread_follow_up': existing_record.configs.get(
                    'thread_follow_up', None
                ),
                'research_mode': existing_record.configs.get('research_mode', None),
                'raw_followup_conversation_id': existing_record.configs.get(
                    'raw_followup_conversation_id', None
                ),
            }
        except Exception as e:
            logger.error(f'Error getting conversation visibility by id: {str(e)}')
            return 'Error getting conversation visibility by id', None

    async def _delete_conversation(self, conversation_id: str, user_id: str):
        try:
            query = Conversation.select().where(
                (Conversation.c.conversation_id == conversation_id)
                & (Conversation.c.user_id == user_id)
            )
            existing_record = await database.fetch_one(query)
            if not existing_record:
                return 'Conversation not found', None
            await database.execute(
                Conversation.update()
                .where(
                    (Conversation.c.conversation_id == conversation_id)
                    & (Conversation.c.user_id == user_id)
                )
                .values(status='deleted')
            )
            return True
        except Exception as e:
            logger.error(f'Error deleting conversation: {str(e)}')
            return False

    async def _get_raw_conversation_info(self, conversation_id: str, user_id: str):
        from openhands.server.shared import (
            ConversationStoreImpl,
            config,
        )

        try:
            conversation_store = await ConversationStoreImpl.get_instance(
                config, user_id, None
            )
            metadata = await conversation_store.get_metadata(conversation_id)
            return {
                'conversation_id': metadata.conversation_id,
                'title': metadata.title,
            }
        except Exception as e:
            logger.error(f'Error getting conversation info: {str(e)}')
            return None

    async def _response_conversation(self, conversations: list[dict], sort_by=None):
        try:
            # Filter conversations without titles
            conversation_updated = [
                conversation
                for conversation in conversations
                if not conversation.get('title')
            ]

            if conversation_updated:
                # Get raw conversation info for those without titles
                tasks = [
                    self._get_raw_conversation_info(
                        conversation.get('conversation_id', ''),
                        conversation.get('user_id', ''),
                    )
                    for conversation in conversation_updated
                ]
                raw_conversations = await asyncio.gather(*tasks)

                raw_conversations_dict = {
                    conversation['conversation_id']: conversation['title']
                    for conversation in raw_conversations
                }

                # Create update tasks for conversations without titles
                update_tasks = []
                for conversation in conversation_updated:
                    if conversation.get('conversation_id') in raw_conversations_dict:
                        update_tasks.append(
                            database.execute(
                                Conversation.update()
                                .where(
                                    (
                                        Conversation.c.conversation_id
                                        == conversation.get('conversation_id')
                                    )
                                    & (
                                        Conversation.c.user_id
                                        == conversation.get('user_id')
                                    )
                                )
                                .values(
                                    title=raw_conversations_dict[
                                        conversation.get('conversation_id')
                                    ]
                                )
                            )
                        )

                # Execute all updates concurrently
                if update_tasks:
                    await asyncio.gather(*update_tasks)

                # Update the titles in our local conversation list
                for conversation in conversations:
                    if (
                        not conversation.get('title')
                        and conversation.get('conversation_id')
                        in raw_conversations_dict
                    ):
                        conversation['title'] = raw_conversations_dict[
                            conversation.get('conversation_id')
                        ]

            # Format and return all conversations
            return [
                {
                    'conversation_id': conversation.get('conversation_id'),
                    'title': conversation.get('title')
                    or 'Untitled Conversation',  # Fallback title
                    'short_description': conversation.get('short_description'),
                    'published': conversation.get('published'),
                    'view_count': self.get_view_count(conversation, sort_by),
                    'thumbnail_url': conversation.get('configs', {}).get(
                        'thumbnail_url', None
                    ),
                }
                for conversation in conversations
            ]

        except Exception as e:
            logger.error(f'Error processing conversations: {str(e)}')
            # Return basic format even if error occurs
            return [
                {
                    'conversation_id': conversation.get('conversation_id'),
                    'title': conversation.get('title') or 'Untitled Conversation',
                    'short_description': conversation.get('short_description'),
                    'published': conversation.get('published'),
                    'view_count': self.get_view_count(conversation, sort_by),
                    'thumbnail_url': conversation.get('configs', {}).get(
                        'thumbnail_url', None
                    ),
                }
                for conversation in conversations
            ]

    async def _get_list_conversations(self, **kwargs):
        try:
            page = kwargs.get('page', 1)
            limit = kwargs.get('limit', 10)
            offset = (page - 1) * limit
            published = kwargs.get('published')
            conversation_ids = kwargs.get('conversation_ids', [])
            prioritized_usecase_ids = kwargs.get('prioritized_usecase_ids', [])
            sort_by = kwargs.get('sort_by', None)
            if sort_by:
                query = (
                    select(
                        Conversation,
                        ResearchTrending.c.total_view_24h,
                        ResearchTrending.c.total_view_7d,
                        ResearchTrending.c.total_view_30d,
                    )
                    .select_from(
                        Conversation.outerjoin(
                            ResearchTrending,
                            Conversation.c.conversation_id
                            == ResearchTrending.c.conversation_id,
                        )
                    )
                    .where(
                        or_(
                            Conversation.c.status != 'deleted',
                            Conversation.c.status.is_(None),
                        )
                    )
                )
            else:
                query = select(Conversation).where(
                    or_(
                        Conversation.c.status != 'deleted',
                        Conversation.c.status.is_(None),
                    )
                )

            if published is not None:
                query = query.where(Conversation.c.published == published)
            if conversation_ids and len(conversation_ids) > 0:
                query = query.where(
                    Conversation.c.conversation_id.in_(conversation_ids)
                )

            if page == 1 and len(prioritized_usecase_ids) > 0:
                prioritized_query = query.where(
                    Conversation.c.conversation_id.in_(prioritized_usecase_ids)
                )
                prioritized_items = await database.fetch_all(prioritized_query)

                remaining_query = (
                    query.where(
                        ~Conversation.c.conversation_id.in_(prioritized_usecase_ids)
                    )
                    .offset(0)
                    .limit(limit - len(prioritized_items))
                )
                remaining_items = await database.fetch_all(remaining_query)

                items = [*prioritized_items, *remaining_items]
                items = [dict(row) for row in items]
                items = await self._response_conversation(items, str(sort_by))
                return {
                    'items': items,
                    'page': page,
                    'limit': limit,
                }

            if sort_by == SortBy.total_view_24h:
                query = query.order_by(
                    desc(func.coalesce(ResearchTrending.c.total_view_24h, 0))
                )
            elif sort_by == SortBy.total_view_7d:
                query = query.order_by(
                    desc(func.coalesce(ResearchTrending.c.total_view_7d, 0))
                )
            elif sort_by == SortBy.total_view_30d:
                query = query.order_by(
                    desc(func.coalesce(ResearchTrending.c.total_view_30d, 0))
                )

            # Normal pagination for other pages
            query = query.offset(offset).limit(limit)
            items = await database.fetch_all(query)
            items = [dict(row) for row in items]
            items = await self._response_conversation(items, sort_by)
            return {
                'items': items,
                'page': page,
                'limit': limit,
            }
        except Exception as e:
            logger.error(f'Error getting list conversations: {str(e)}')
            return []

    async def _get_conversation_visibility_by_user_id(
        self,
        user_id: str | None,
        page: int = 1,
        limit: int = 10,
        keyword: str | None = None,
    ):
        if not user_id:
            return []

        try:
            offset = (page - 1) * limit

            base_filter = or_(
                Conversation.c.status != 'deleted', Conversation.c.status.is_(None)
            )
            if keyword:
                base_filter = and_(
                    base_filter, Conversation.c.title.ilike(f'%{keyword}%')
                )

            query = (
                Conversation.select()
                .where(Conversation.c.user_id == user_id)
                .where(base_filter)
                .order_by(desc(Conversation.c.created_at))
                .offset(offset)
                .limit(limit)
            )
            items = await database.fetch_all(query)

            total_query = (
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.c.user_id == user_id)
                .where(base_filter)
            )
            total = await database.fetch_val(total_query)

            return {'total': total, 'items': items}

        except Exception as e:
            logger.error(f'Error getting conversation by user id: {str(e)}')
            return {'total': 0, 'items': []}

    async def update_empty_conversation_titles(self, config):
        try:
            # Get conversations with empty or null titles
            query = Conversation.select().where(
                or_(
                    Conversation.c.title.is_(None),
                    Conversation.c.title == '',
                    Conversation.c.title == 'Untitled Conversation',
                )
            )

            conversations = await database.fetch_all(query)

            if not conversations:
                return {
                    'updated': 0,
                    'message': 'No conversations with empty titles found',
                }

            # Process all conversations concurrently using gather
            async def process_conversation(conversation):
                try:
                    conversation_id = conversation.conversation_id
                    conversation_user_id = conversation.user_id
                    from openhands.server.shared import ConversationStoreImpl

                    # Get metadata from file store
                    conversation_store = await ConversationStoreImpl.get_instance(
                        config, conversation_user_id, None
                    )

                    try:
                        metadata = await conversation_store.get_metadata(
                            conversation_id
                        )
                    except FileNotFoundError:
                        metadata = None

                    if metadata and metadata.title:
                        # Use existing title from metadata
                        await database.execute(
                            Conversation.update()
                            .where(Conversation.c.conversation_id == conversation_id)
                            .values(title=metadata.title)
                        )

                    return {
                        'success': True,
                        'conversation_id': conversation_id,
                        'title': metadata.title if metadata else None,
                    }

                except Exception as e:
                    logger.error(
                        f'Error updating title for conversation {conversation.conversation_id}: {str(e)}'
                    )
                    return {
                        'success': False,
                        'conversation_id': conversation.conversation_id,
                        'error': str(e),
                    }

            # Process all conversations concurrently
            results = []

            for conv in conversations:
                result = await process_conversation(conv)
                results.append(result)

            updated_count = sum(1 for result in results if result['success'])
            errors = [
                f"Conversation {r['conversation_id']}: {r['error']}"
                for r in results
                if not r['success']
            ]

            result = {
                'updated': updated_count,
                'total_found': len(conversations),
                'message': f'Successfully updated {updated_count} out of {len(conversations)} conversations',
            }

            if errors:
                result['errors'] = errors

            return result

        except Exception as e:
            logger.error(f'Error in update_empty_conversation_titles: {str(e)}')
            return {'updated': 0, 'error': str(e)}


conversation_module = ConversationModule()
