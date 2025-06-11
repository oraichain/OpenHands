from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from openhands.server.modules import conversation_module

app = APIRouter(prefix='/share')


@app.get('/{conversation_id}')
async def get_share_conversation(conversation_id: str):
    conversation = await conversation_module._get_conversation_by_id(conversation_id)
    if not conversation or not conversation.published:
        raise HTTPException(status_code=404, detail='Conversation not found')

    # Extract data from conversation
    title = conversation.title or 'OpenHands Conversation'
    description = 'Thesis.io is an agentic workspace that helps investors develop evidence-backed DeFi strategies.'
    thumbnail_url = (
        conversation.configs.get(
            'thumbnail_url', 'https://app.thesis.io/preview-image.jpg'
        )
        if conversation.configs
        else 'https://app.thesis.io/preview-image.jpg'
    )
    share_url = 'http://app.thesis.io'

    # HTML template with variable substitution
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <!-- Open Graph -->
  <meta property="og:title" content="{title}" />
  <meta property="og:description" content="{description}" />
  <meta property="og:image" content="{thumbnail_url}" />
  <meta property="og:url" content="{share_url}" />
  <meta property="og:type" content="article" />
  <!-- Twitter Card -->
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="{title}" />
  <meta name="twitter:description" content="{description}" />
  <meta name="twitter:image" content="{thumbnail_url}" />
</head>
<body>
  <h1>{title}</h1>
  <br />
  <p>{description}</p>
</body>
</html>"""

    return HTMLResponse(content=html_content, status_code=200)
