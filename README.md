# WAHA FastAPI WhatsApp Service

A FastAPI application that uses a Python client wrapper to interact with WAHA (WhatsApp HTTP API) for sending WhatsApp messages.

## Prerequisites

- Python 3.8+
- Docker (for running WAHA server)
- A WhatsApp account

## Setup

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Start WAHA Server

WAHA must be running before you can send messages. Start it using Docker:

```bash
docker run -it --rm --network=host --name waha devlikeapro/waha
```

Once running, visit `http://localhost:3000` in your browser to:
- Access the WAHA Swagger documentation
- Scan the QR code to pair your WhatsApp account
- Create and manage sessions

### 3. Configure Environment Variables (Optional)

The application uses the following environment variables (with defaults):

- `WAHA_BASE_URL`: WAHA server URL (default: `http://localhost:3000`)
- `WAHA_SESSION`: Default session name (default: `default`)
- `WAHA_API_KEY`: API key for authentication if WAHA requires it (default: `None`)
- `WAHA_AUTH_TYPE`: Authentication type - `X-Api-Key`, `Bearer`, or `none` (default: `X-Api-Key`)

You can set these in your environment or create a `.env` file in the project root:

**Option 1: Create a `.env` file** (recommended)

Create a `.env` file in the project root with the following content:

```bash
# WAHA Configuration
WAHA_BASE_URL=http://localhost:3000
WAHA_SESSION=default

# WAHA Authentication (REQUIRED if WAHA Docker container has WHATSAPP_API_KEY set)
# Get this value from your WAHA Docker container's WHATSAPP_API_KEY environment variable
WAHA_API_KEY=your_api_key_here
WAHA_AUTH_TYPE=X-Api-Key

# For Bearer token authentication, use:
# WAHA_AUTH_TYPE=Bearer
```

**Option 2: Set environment variables directly**

```bash
export WAHA_BASE_URL=http://localhost:3000
export WAHA_SESSION=default
export WAHA_API_KEY=your_api_key_here  # If WAHA requires authentication
export WAHA_AUTH_TYPE=X-API-Key  # or "Bearer" depending on WAHA configuration
```

**Important:** If you're getting 401 Unauthorized errors:

### Option 1: WAHA Started WITH Authentication (WHATSAPP_API_KEY set)

If you started WAHA Docker container WITH `WHATSAPP_API_KEY`:
```bash
docker run -it --rm --network=host -e WHATSAPP_API_KEY=my_secret_key --name waha devlikeapro/waha
```

Then in your `.env` file, set:
```bash
WAHA_API_KEY=my_secret_key
WAHA_AUTH_TYPE=X-Api-Key
```

### Option 2: WAHA Started WITHOUT Authentication (No WHATSAPP_API_KEY)

If you started WAHA Docker container WITHOUT `WHATSAPP_API_KEY`:
```bash
docker run -it --rm --network=host --name waha devlikeapro/waha
```

Then in your `.env` file, set:
```bash
WAHA_AUTH_TYPE=none
# Don't set WAHA_API_KEY or leave it empty
```

**Common Issue:** If WAHA was started WITHOUT `WHATSAPP_API_KEY` but you're sending `X-Api-Key` header, you'll get 401 errors. Set `WAHA_AUTH_TYPE=none` in this case.

### Debugging Steps:

1. **Check your WAHA Docker configuration:**
   ```bash
   docker inspect <waha_container_name> | grep WHATSAPP_API_KEY
   ```
   If this shows nothing, WAHA doesn't require authentication.

2. **Use the debug endpoint:**
   Visit `http://localhost:8002/debug/config` to see your current configuration.

3. **Check WAHA logs:**
   ```bash
   docker logs <waha_container_name>
   ```

4. **Test in WAHA Swagger:**
   Visit `http://localhost:3000/swagger` and check if there's an "Authorize" button. If there isn't one, WAHA doesn't require authentication.

### 4. Run the FastAPI Application

```bash
python main.py
```

Or using uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000`

## Usage

### API Endpoints

#### Health Check

```bash
curl http://localhost:8000/health
```

#### Send Message

```bash
curl -X POST "http://localhost:8000/send-message" \
     -H "Content-Type: application/json" \
     -d '{
       "chatId": "1234567890@c.us",
       "text": "Hello from FastAPI!",
       "session": "default"
     }'
```

**Request Body:**
- `chatId` (required): WhatsApp chat ID
  - Private chat: `1234567890@c.us` (phone number with country code, no + or spaces)
  - Group chat: `12345@g.us`
- `text` (required): Message text content
- `session` (optional): WAHA session name (defaults to configured session)

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "message_id",
    "timestamp": 1234567890
  }
}
```

### API Documentation

Once the server is running, you can access:
- Interactive API docs: `http://localhost:8000/docs`
- Alternative docs: `http://localhost:8000/redoc`

## Project Structure

```
finvarta-whatsapp-service/
├── main.py              # FastAPI application
├── waha_client.py       # WAHA client wrapper
├── config.py            # Configuration management
├── requirements.txt     # Python dependencies
└── README.md            # This file
```

## Troubleshooting

### Connection Errors

If you get connection errors, ensure:
1. WAHA server is running (`docker ps` to check)
2. WAHA is accessible at the configured `WAHA_BASE_URL`
3. Your WhatsApp account is paired (check WAHA dashboard)

### Session Errors

If you get session-related errors:
1. Ensure a session exists in WAHA (check `http://localhost:3000`)
2. Verify the session name matches your configuration
3. Make sure the session is authenticated (QR code scanned)

## Extending the Service

The service is designed to be easily extended. To add support for:
- **Images**: Add `send_image()` method to `WAHAClient` and corresponding endpoint
- **Files**: Add `send_file()` method to `WAHAClient` and corresponding endpoint
- **Webhooks**: Add webhook endpoint to receive incoming messages

## License

MIT
