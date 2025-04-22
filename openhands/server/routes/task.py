

from fastapi import APIRouter, Request, status, JSONResponse
from pydantic import BaseModel
from requests import Response

from openhands.core.logger import openhands_logger as logger
from openhands.server.thesis_auth import add_invite_code_to_user

app = APIRouter(prefix='/api')


@app.get('/root_task')
def get_root_task(request: Request):
    """
    Retrieve the root task of the current agent session.

    To get the root_task:
    ```sh
    curl -H "Authorization: Bearer <TOKEN>" http://localhost:3000/api/root_task
    ```

    Args:
        request (Request): The incoming request object.

    Returns:
        dict: The root task data if available.

    Raises:
        HTTPException: If the root task is not available.
    """
    controller = request.state.session.agent_session.controller
    if controller is not None:
        state = controller.get_state()
        if state:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=state.root_task.to_dict(),
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
