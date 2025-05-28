# Binary Content Control and S3 Upload Guide

This guide explains how to control binary content and upload it to S3 in the OpenHands system.

## Overview

The system provides multiple ways to handle binary content and upload it to S3:

1. **Direct Binary Upload** - For raw binary data
2. **Base64 Encoded Upload** - For base64 encoded content
3. **File Upload** - For FastAPI UploadFile objects

## S3 Handler Methods

### 1. `upload_raw_file()` - Primary Method for Binary Content

```python
async def upload_raw_file(
    self,
    file_content: bytes,
    folder_path: str,
    filename: str,
    content_type: Optional[str] = None,
    metadata: Optional[dict] = None
):
```

**Parameters:**
- `file_content`: Raw binary data as bytes
- `folder_path`: S3 folder path (e.g., "workspace/session_id")
- `filename`: Target filename in S3
- `content_type`: MIME type (auto-detected if not provided)
- `metadata`: Optional metadata dictionary

**Example Usage:**
```python
# Upload binary image data
binary_data = b'\x89PNG\r\n\x1a\n...'  # Your binary content
s3_url = await s3_handler.upload_raw_file(
    file_content=binary_data,
    folder_path="workspace/abc123",
    filename="image.png",
    content_type="image/png",
    metadata={"source": "user_upload", "size": str(len(binary_data))}
)
```

### 2. Content Type Detection

The system automatically detects content types based on file extensions:

```python
def _get_content_type(self, filename: str) -> str:
    # Supported types:
    '.png': 'image/png'
    '.jpg': 'image/jpeg'
    '.jpeg': 'image/jpeg'
    '.gif': 'image/gif'
    '.webp': 'image/webp'
    '.pdf': 'application/pdf'
    '.mp4': 'video/mp4'
    '.txt': 'text/plain'
    '.json': 'application/json'
    '.zip': 'application/zip'
    # Default: 'application/octet-stream'
```

## Binary Content Processing Patterns

### Pattern 1: Base64 Data URL Format
```python
# Input: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..."
if file_content.startswith('data:image/'):
    base64_part = file_content.split(',', 1)[1]
    binary_data = safe_base64_decode(base64_part)
```

### Pattern 2: Plain Base64 String
```python
# Input: "iVBORw0KGgoAAAANSUhEUgAA..."
try:
    binary_data = safe_base64_decode(file_content)
except ValueError:
    # Not base64, treat as raw text/binary
    binary_data = file_content.encode('utf-8')
```

### Pattern 3: Direct Binary File Reading
```python
async with aiofiles.open(file_path, 'rb') as f:
    binary_data = await f.read()
```

## Complete Upload Flow Example

```python
async def upload_binary_content(binary_data: bytes, filename: str, session_id: str):
    """Complete example of uploading binary content to S3."""

    # 1. Validate file type
    ext = os.path.splitext(filename)[1].lower()
    allowed_types = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf']
    if ext not in allowed_types:
        raise ValueError(f"Unsupported file type: {ext}")

    # 2. Prepare upload parameters
    folder_path = f"workspace/{session_id}"
    content_type = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.pdf': 'application/pdf',
    }.get(ext, 'application/octet-stream')

    # 3. Add metadata
    metadata = {
        'original_filename': filename,
        'file_size': str(len(binary_data)),
        'upload_timestamp': str(int(time.time())),
        'session_id': session_id,
    }

    # 4. Upload to S3
    s3_url = await s3_handler.upload_raw_file(
        file_content=binary_data,
        folder_path=folder_path,
        filename=filename,
        content_type=content_type,
        metadata=metadata
    )

    if s3_url:
        logger.info(f"Successfully uploaded {filename} to {s3_url}")
        return {
            'success': True,
            'url': s3_url,
            'content_type': content_type,
            'file_size': len(binary_data)
        }
    else:
        raise Exception("Failed to upload to S3")
```

## Error Handling Best Practices

### 1. Base64 Decoding with Safe Padding
```python
def safe_base64_decode(data: str) -> bytes:
    try:
        # Remove whitespace and newlines
        data = data.strip().replace('\n', '').replace('\r', '')

        # Add padding if necessary
        missing_padding = len(data) % 4
        if missing_padding:
            data += '=' * (4 - missing_padding)

        return base64.b64decode(data)
    except Exception as e:
        raise ValueError(f'Invalid base64 data: {e}')
```

### 2. Comprehensive Error Handling
```python
try:
    s3_url = await s3_handler.upload_raw_file(binary_data, folder_path, filename)
    if not s3_url:
        return JSONResponse(
            status_code=500,
            content={'error': 'S3 upload failed - no URL returned'}
        )
except ClientError as e:
    logger.error(f'AWS S3 error: {e}')
    return JSONResponse(
        status_code=500,
        content={'error': f'S3 service error: {e}'}
    )
except Exception as e:
    logger.error(f'Unexpected error: {e}')
    return JSONResponse(
        status_code=500,
        content={'error': f'Upload failed: {e}'}
    )
```

## Environment Configuration

Ensure these environment variables are set:

```bash
S3_ACCESS_KEY_ID=your_access_key
S3_SECRET_ACCESS_KEY=your_secret_key
S3_BUCKET=your_bucket_name
S3_REGION=your_region  # defaults to ap-southeast-1
```

## Testing Binary Uploads

### Test with curl:
```bash
# Upload an image file
curl -X POST "http://localhost:3000/api/conversations/{conversation_id}/upload-image-file" \
  -H "Content-Type: application/json" \
  -d '{"file": "path/to/your/image.png"}'
```

### Test with Python:
```python
import base64
import requests

# Read binary file
with open('image.png', 'rb') as f:
    binary_data = f.read()

# Convert to base64
base64_data = base64.b64encode(binary_data).decode('utf-8')

# Upload via API
response = requests.post(
    f"http://localhost:3000/api/conversations/{conversation_id}/upload-image-file",
    json={"file": "image.png"}
)
```

## Key Benefits of This Approach

1. **Automatic Content-Type Detection** - Proper MIME types for better browser compatibility
2. **Metadata Support** - Track file information and upload details
3. **Comprehensive Error Handling** - Better debugging and user feedback
4. **Base64 Padding Safety** - Handles malformed base64 data gracefully
5. **Flexible Input Formats** - Supports data URLs, plain base64, and raw binary
6. **Detailed Logging** - Track upload progress and debug issues

## Common Use Cases

1. **Image Uploads** - PNG, JPEG, GIF, WebP files
2. **Document Uploads** - PDF files
3. **Video Uploads** - MP4, WebM files
4. **Archive Uploads** - ZIP files
5. **Text Files** - JSON, TXT files

This system provides robust control over binary content handling and ensures reliable uploads to S3 with proper metadata and error handling.
