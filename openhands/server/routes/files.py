import base64
import os
import re

import aiofiles  # type: ignore
import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern
from starlette.background import BackgroundTask

from openhands.core.exceptions import AgentRuntimeUnavailableError
from openhands.core.logger import openhands_logger as logger
from openhands.events.action import FileReadAction
from openhands.events.observation import ErrorObservation, FileReadObservation
from openhands.runtime.base import Runtime
from openhands.server.file_config import FILES_TO_IGNORE
from openhands.utils.async_utils import call_sync_from_async

app = APIRouter(prefix='/api/conversations/{conversation_id}')


@app.get('/list-files')
async def list_files(request: Request, path: str | None = None):
    """List files in the specified path.

    This function retrieves a list of files from the agent's runtime file store,
    excluding certain system and hidden files/directories.

    To list files:
    ```sh
    curl http://localhost:3000/api/conversations/{conversation_id}/list-files
    ```

    Args:
        request (Request): The incoming request object.
        path (str, optional): The path to list files from. Defaults to None.

    Returns:
        list: A list of file names in the specified path.

    Raises:
        HTTPException: If there's an error listing the files.
    """
    if not request.state.conversation.runtime:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={'error': 'Runtime not yet initialized'},
        )

    runtime: Runtime = request.state.conversation.runtime

    try:
        file_list = await call_sync_from_async(runtime.list_files, path)
    except AgentRuntimeUnavailableError as e:
        logger.error(f'Error listing files: {e}')
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={'error': f'Error listing files: {e}'},
        )
    if path:
        file_list = [os.path.join(path, f) for f in file_list]

    file_list = [f for f in file_list if f not in FILES_TO_IGNORE]

    async def filter_for_gitignore(file_list, base_path):
        gitignore_path = os.path.join(base_path, '.gitignore')
        try:
            read_action = FileReadAction(gitignore_path)
            observation = await call_sync_from_async(runtime.run_action, read_action)
            spec = PathSpec.from_lines(
                GitWildMatchPattern, observation.content.splitlines()
            )
        except Exception as e:
            logger.warning(e)
            return file_list
        file_list = [entry for entry in file_list if not spec.match_file(entry)]
        return file_list

    try:
        file_list = await filter_for_gitignore(file_list, '')
    except AgentRuntimeUnavailableError as e:
        logger.error(f'Error filtering files: {e}')
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={'error': f'Error filtering files: {e}'},
        )

    return file_list


@app.get('/select-file')
async def select_file(file: str, request: Request, is_base64_in_md: bool = True):
    """Retrieve the content of a specified file.

    To select a file:
    ```sh
    curl http://localhost:3000/api/conversations/{conversation_id}select-file?file=<file_path>
    ```

    Args:
        file (str): The path of the file to be retrieved.
            Expect path to be absolute inside the runtime.
        request (Request): The incoming request object.
        is_base64_in_md (bool, optional): Whether to convert base64. Defaults to True.

    Returns:
        dict: A dictionary containing the file content.

    Raises:
        HTTPException: If there's an error opening the file.
    """
    runtime: Runtime = request.state.conversation.runtime

    file_path = os.path.join(
        runtime.config.workspace_mount_path_in_sandbox + '/' + runtime.sid, file
    )
    read_action = FileReadAction(file_path)
    try:
        observation = await call_sync_from_async(runtime.run_action, read_action)
    except AgentRuntimeUnavailableError as e:
        logger.error(f'Error opening file {file_path}: {e}')
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={'error': f'Error opening file: {e}'},
        )

    async def fetch_image_base64(image_path: str) -> str:
        # Compose the API URL for select-file
        # Extract conversation_id from the request.url.path
        try:
            conversation_id = request.url.path.split('/')[3]
        except Exception:
            conversation_id = ''
        # Compose the URL
        api_url = f'{request.base_url}api/conversations/{conversation_id}/select-file?file={image_path}'
        headers = dict(request.headers)
        # Remove host header to avoid issues
        headers.pop('host', None)
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return data.get('code', '')
            return ''

    if isinstance(observation, FileReadObservation):
        content = observation.content
        if file.lower().endswith('.md'):
            if not is_base64_in_md:
                return {'code': content}
            # Find all markdown image links ![alt](src) and <img src="src">
            md_img_pattern = r'!\[[^\]]*\]\(([^)]+)\)'
            html_img_pattern = r'<img[^>]+src=["\']([^"\'>]+)["\']'
            matches = re.findall(md_img_pattern, content) + re.findall(
                html_img_pattern, content
            )
            # Only process static paths (not http/https)
            replacements = {}
            for img_src in matches:
                if img_src.startswith('http://') or img_src.startswith('https://'):
                    continue
                # Normalize path relative to the md file
                img_path = os.path.normpath(
                    os.path.join(os.path.dirname(file), img_src)
                )
                base64_data = await fetch_image_base64(img_path)
                if base64_data:
                    # Check if base64_data already has data URL prefix
                    if base64_data.startswith('data:'):
                        data_url = base64_data
                    else:
                        # Guess mime type from extension
                        ext = os.path.splitext(img_src)[1].lower()
                        if ext == '.png':
                            mime = 'image/png'
                        elif ext in ['.jpg', '.jpeg']:
                            mime = 'image/jpeg'
                        elif ext == '.gif':
                            mime = 'image/gif'
                        else:
                            mime = 'application/octet-stream'
                        data_url = f'data:{mime};base64,{base64_data}'
                    replacements[img_src] = data_url
            # Replace in markdown
            for src, data_url in replacements.items():
                # Replace in both markdown and html img tags
                content = re.sub(
                    r'(!\[[^\]]*\]\()' + re.escape(src) + r'(\))',
                    r'\1' + data_url + r'\2',
                    content,
                )
                content = re.sub(
                    r'(<img[^>]+src=["\'])' + re.escape(src) + r'(["\'])',
                    r'\1' + data_url + r'\2',
                    content,
                )
            return {'code': content}
        else:
            return {'code': content}
    elif isinstance(observation, ErrorObservation):
        logger.error(f'Error opening file {file_path}: {observation}')

        if 'ERROR_BINARY_FILE' in observation.message:
            try:
                async with aiofiles.open(file_path, 'rb') as f:
                    binary_data = await f.read()
                    base64_encoded = base64.b64encode(binary_data).decode('utf-8')
                    return {'code': base64_encoded}
            except Exception as e:
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={'error': f'Error reading binary file: {e}'},
                )
        else:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={'error': f'Error opening file: {observation}'},
            )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={'error': f'Error opening file: {observation}'},
    )


@app.get('/zip-directory')
def zip_current_workspace(request: Request):
    try:
        logger.debug('Zipping workspace')
        runtime: Runtime = request.state.conversation.runtime
        path = runtime.config.workspace_mount_path_in_sandbox
        try:
            zip_file_path = runtime.copy_from(path)
        except AgentRuntimeUnavailableError as e:
            logger.error(f'Error zipping workspace: {e}')
            return JSONResponse(
                status_code=500,
                content={'error': f'Error zipping workspace: {e}'},
            )
        return FileResponse(
            path=zip_file_path,
            filename='workspace.zip',
            media_type='application/zip',
            background=BackgroundTask(lambda: os.unlink(zip_file_path)),
        )
    except Exception as e:
        logger.error(f'Error zipping workspace: {e}')
        raise HTTPException(
            status_code=500,
            detail='Failed to zip workspace',
        )
