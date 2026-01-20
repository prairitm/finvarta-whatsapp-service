"""FastAPI application for sending WhatsApp messages via WAHA."""
import json
import logging
from typing import Any, Optional

import httpx
from aiokafka import AIOKafkaConsumer
from aiokafka.structs import TopicPartition
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError

from config import settings
from recipients import get_recipients_file_path, load_recipients, number_to_chat_id
from waha_client import WAHAClient

logger = logging.getLogger(__name__)


app = FastAPI(
    title="WAHA WhatsApp Service",
    description="FastAPI service for sending WhatsApp messages via WAHA",
    version="1.0.0"
)

# Initialize WAHA client
waha_client = WAHAClient()


class SendMessageRequest(BaseModel):
    """Request model for sending a WhatsApp message."""
    chat_id: str = Field(..., alias="chatId", description="WhatsApp chat ID (e.g., '1234567890@c.us')")
    text: str = Field(..., description="Message text content")
    session: Optional[str] = Field(None, description="WAHA session name (defaults to configured session)")
    
    class Config:
        populate_by_name = True


class MessageResponse(BaseModel):
    """Response model for successful message send."""
    status: str = "success"
    data: dict


class ErrorResponse(BaseModel):
    """Error response model."""
    status: str = "error"
    detail: str


class SendBulkRequest(BaseModel):
    """Request model for bulk send to all recipients in recipients.txt."""
    text: str = Field(..., description="Message text to send to all recipients")
    session: Optional[str] = Field(None, description="WAHA session name (defaults to configured session)")


class BulkSendResultItem(BaseModel):
    """Per-recipient result for bulk send."""
    chat_id: str
    status: str  # "success" | "error"
    error: Optional[str] = None


class BulkSendResponse(BaseModel):
    """Response model for bulk send."""
    status: str = "success"
    sent: int
    failed: int
    results: list[BulkSendResultItem]


class NotificationPayload(BaseModel):
    """Kafka message from notification-payload topic."""
    company_name: Optional[str] = None
    pdf_url: Optional[str] = None
    summary: str
    number: str


class ConsumeResultItem(BaseModel):
    """Per-message result for consume-notifications."""
    number: str
    company_name: Optional[str] = None
    status: str  # "success" | "error" | "skipped"
    error: Optional[str] = None


class ConsumeNotificationsResponse(BaseModel):
    """Response model for consume-notifications."""
    status: str = "success"
    processed: int
    failed: int
    skipped: int
    results: list[ConsumeResultItem]


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "WAHA WhatsApp Service"}


@app.get("/debug/session-status")
async def check_session_status():
    """Check the status of the WAHA session."""
    try:
        session_status = await waha_client.check_session_status()
        return {
            "status": "success",
            "session_status": session_status,
            "note": "Session should be 'CONNECTED' and 'ready' to send messages"
        }
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error checking session: {str(e)}"
        )


@app.get("/debug/config")
async def debug_config():
    """Debug endpoint to check configuration (without exposing API key)."""
    from pathlib import Path
    from config import settings
    
    # Check what headers will actually be sent
    actual_headers = waha_client._get_headers()
    auth_header_present = any("key" in k.lower() or "auth" in k.lower() for k in actual_headers.keys())
    
    # Check .env file
    env_file_path = Path(__file__).parent / ".env"
    env_file_exists = env_file_path.exists()
    env_file_info = {}
    
    if env_file_exists:
        try:
            env_content = env_file_path.read_text(encoding="utf-8")
            env_file_info = {
                "env_file_path": str(env_file_path),
                "env_file_exists": True,
                "has_waha_api_key_line": any("WAHA_API_KEY" in line for line in env_content.split("\n")),
                "waha_api_key_line_preview": next(
                    (line.strip()[:50] + "..." if len(line.strip()) > 50 else line.strip())
                    for line in env_content.split("\n")
                    if "WAHA_API_KEY" in line and "=" in line
                ) if any("WAHA_API_KEY" in line for line in env_content.split("\n")) else None
            }
        except Exception as e:
            env_file_info = {"error_reading_env": str(e)}
    else:
        env_file_info = {
            "env_file_path": str(env_file_path),
            "env_file_exists": False,
            "note": "Create .env file in the project root directory"
        }
    
    return {
        "waha_base_url": settings.waha_base_url,
        "waha_session": settings.waha_session,
        "waha_api_key_configured": bool(settings.waha_api_key),
        "waha_api_key_length": len(settings.waha_api_key) if settings.waha_api_key else 0,
        "waha_api_key_preview": f"{settings.waha_api_key[:3]}..." if settings.waha_api_key and len(settings.waha_api_key) > 3 else "Not set",
        "waha_auth_type": settings.waha_auth_type,
        "auth_header_will_be_sent": auth_header_present,
        "actual_headers_keys": list(actual_headers.keys()),
        "diagnosis": "✅ Auth header will be sent" if auth_header_present else "❌ NO AUTH HEADER - WAHA requires authentication!",
        "env_file_info": env_file_info,
        "fix_required": "Set WAHA_API_KEY in .env file to match WHATSAPP_API_KEY in your WAHA Docker container" if not auth_header_present else None,
        "note": "WAHA is returning 401, which means it REQUIRES authentication. You must set WAHA_API_KEY in .env"
    }


@app.post("/debug/test-waha")
async def test_waha_connection():
    """Test endpoint to directly test WAHA API connection and see full request/response."""
    import httpx
    from config import settings
    
    url = f"{settings.waha_base_url}/api/sessions"
    headers = waha_client._get_headers()
    
    # Mask sensitive headers for logging
    debug_headers = {k: "***" if "key" in k.lower() or "auth" in k.lower() else v for k, v in headers.items()}
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            
            return {
                "status_code": response.status_code,
                "url": url,
                "headers_sent": debug_headers,
                "response_text": response.text[:500] if response.text else "No response body",
                "response_headers": dict(response.headers),
                "success": response.status_code < 400,
                "connection_status": "✅ Connected to WAHA server"
            }
    except httpx.ConnectError as e:
        return {
            "error": str(e),
            "url": url,
            "headers_sent": debug_headers,
            "type": type(e).__name__,
            "connection_status": "❌ Cannot connect to WAHA server",
            "troubleshooting": [
                "Check if WAHA is running: docker ps | grep waha",
                f"Try accessing {settings.waha_base_url} in your browser",
                "Verify WAHA is running on the correct port (default: 3000)",
                "Check if WAHA container is healthy: docker ps --format 'table {{.Names}}\t{{.Status}}'"
            ]
        }
    except httpx.TimeoutException as e:
        return {
            "error": str(e),
            "url": url,
            "headers_sent": debug_headers,
            "type": type(e).__name__,
            "connection_status": "❌ Request timed out",
            "troubleshooting": [
                "WAHA server may be overloaded or unresponsive",
                "Check WAHA logs: docker logs waha",
                "Try restarting WAHA: docker restart waha"
            ]
        }
    except Exception as e:
        return {
            "error": str(e),
            "url": url,
            "headers_sent": debug_headers,
            "type": type(e).__name__,
            "connection_status": "❌ Unexpected error"
        }


@app.post(
    "/send-message",
    response_model=MessageResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}
)
async def send_message(request: SendMessageRequest):
    """
    Send a WhatsApp text message via WAHA.
    
    - **chatId**: WhatsApp chat ID in format `1234567890@c.us` (private) or `12345@g.us` (group)
    - **text**: The message text to send
    - **session**: Optional WAHA session name (defaults to configured session)
    """
    try:
        response_data = await waha_client.send_text_message(
            chat_id=request.chat_id,
            text=request.text,
            session=request.session
        )
        return MessageResponse(status="success", data=response_data)
    except httpx.HTTPStatusError as e:
        # Include more details in error response
        error_detail = str(e)
        if e.response.text:
            error_detail += f"\nWAHA Response: {e.response.text}"
        if e.response.status_code == 401:
            error_detail += f"\n\nTroubleshooting: Check /debug/config endpoint to verify your authentication settings."
            error_detail += f"\nIf WAHA was started without WHATSAPP_API_KEY, set WAHA_AUTH_TYPE=none in .env"
        raise HTTPException(
            status_code=e.response.status_code,
            detail=error_detail
        )
    except httpx.RequestError as e:
        error_type = type(e).__name__
        error_detail = f"Failed to connect to WAHA server at {settings.waha_base_url}\n"
        error_detail += f"Error type: {error_type}\n"
        error_detail += f"Error message: {str(e)}\n\n"
        error_detail += "Possible causes:\n"
        error_detail += "1. WAHA server is not running - Check with: docker ps | grep waha\n"
        error_detail += f"2. WAHA server is not accessible at {settings.waha_base_url}\n"
        error_detail += "3. Network connectivity issue - Try accessing http://localhost:3000 in your browser\n"
        error_detail += "4. Wrong port - Verify WAHA is running on port 3000\n"
        raise HTTPException(
            status_code=503,
            detail=error_detail
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )


@app.get("/recipients")
async def get_recipients():
    """
    List recipients that would be used by POST /send-bulk.

    Returns parsed chat_ids from the recipients file. File missing or empty returns empty list.
    """
    path = get_recipients_file_path()
    recipients = load_recipients(path)
    return {"recipients": recipients, "count": len(recipients)}


@app.post(
    "/send-bulk",
    response_model=BulkSendResponse,
    responses={400: {"model": ErrorResponse}}
)
async def send_bulk(request: SendBulkRequest):
    """
    Send a WhatsApp text message to all recipients in recipients.txt.

    - **text**: The message to send to every number in the recipients file.
    - **session**: Optional WAHA session name (defaults to configured session).

    Recipients are loaded from the file configured by WAHA_RECIPIENTS_FILE (default: recipients.txt).
    Sends sequentially to reduce rate-limit risk.
    """
    path = get_recipients_file_path()
    chat_ids = load_recipients(path)
    if not chat_ids:
        raise HTTPException(
            status_code=400,
            detail="No valid recipients in recipients file. Add mobile numbers to recipients.txt (one per line, e.g. 919920906247 or +91 9920906247)."
        )
    results: list[BulkSendResultItem] = []
    sent = 0
    failed = 0
    for chat_id in chat_ids:
        try:
            await waha_client.send_text_message(
                chat_id=chat_id,
                text=request.text,
                session=request.session
            )
            results.append(BulkSendResultItem(chat_id=chat_id, status="success", error=None))
            sent += 1
        except Exception as e:
            results.append(BulkSendResultItem(chat_id=chat_id, status="error", error=str(e)))
            failed += 1
    return BulkSendResponse(status="success", sent=sent, failed=failed, results=results)


@app.post(
    "/consume-notifications",
    response_model=ConsumeNotificationsResponse,
    responses={503: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def consume_notifications(
    max_messages: Optional[int] = None,
    poll_timeout_ms: int = 5000,
):
    """
    Consume messages from Kafka topic notification-payload and send summary as WhatsApp text to number.

    - **max_messages**: Cap how many messages to process per call; None = no cap.
    - **poll_timeout_ms**: Timeout for getmany (ms). Only new messages (auto_offset_reset=latest).
    """
    bootstrap = settings.kafka_bootstrap_servers
    servers = [s.strip() for s in bootstrap.split(",")] if isinstance(bootstrap, str) else bootstrap
    consumer = AIOKafkaConsumer(
        settings.kafka_topic_notification_payload,
        bootstrap_servers=servers,
        group_id=settings.kafka_consumer_group,
        auto_offset_reset="latest",
        enable_auto_commit=False,
    )
    try:
        await consumer.start()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not connect to Kafka at {bootstrap}: {e}",
        )

    results: list[ConsumeResultItem] = []
    processed = 0
    failed = 0
    skipped = 0
    # For each tp, the next offset to read (we commit through last_committable - 1). Only advance on success/skip when contiguous.
    last_committable: dict[TopicPartition, int] = {}

    try:
        batch = await consumer.getmany(timeout_ms=poll_timeout_ms)
        recs: list[tuple[TopicPartition, Any]] = []
        for tp, lst in batch.items():
            for r in lst:
                recs.append((tp, r))
        recs.sort(key=lambda x: (x[0].topic, x[0].partition, x[1].offset))

        for tp, record in recs:
            if max_messages is not None and (processed + failed + skipped) >= max_messages:
                break

            raw = record.value
            if raw is None:
                logger.warning("consume-notifications: null value at %s offset %s", tp, record.offset)
                results.append(ConsumeResultItem(number="", company_name=None, status="skipped", error="null message value"))
                skipped += 1
                next_off = record.offset + 1
                if tp not in last_committable or record.offset == last_committable[tp]:
                    last_committable[tp] = next_off
                continue

            try:
                d = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            except Exception as e:
                logger.warning("consume-notifications: JSON parse error at %s offset %s: %s", tp, record.offset, e)
                results.append(ConsumeResultItem(number="", company_name=None, status="skipped", error=f"JSON parse error: {e}"))
                skipped += 1
                next_off = record.offset + 1
                if tp not in last_committable or record.offset == last_committable[tp]:
                    last_committable[tp] = next_off
                continue

            try:
                payload = NotificationPayload.model_validate(d)
            except ValidationError as e:
                logger.warning("consume-notifications: validation error at %s offset %s: %s", tp, record.offset, e)
                results.append(ConsumeResultItem(number=d.get("number") or "", company_name=d.get("company_name"), status="skipped", error=str(e)))
                skipped += 1
                next_off = record.offset + 1
                if tp not in last_committable or record.offset == last_committable[tp]:
                    last_committable[tp] = next_off
                continue

            if not (payload.summary or "").strip():
                logger.warning("consume-notifications: empty summary at %s offset %s number=%s", tp, record.offset, payload.number)
                results.append(ConsumeResultItem(number=payload.number, company_name=payload.company_name, status="skipped", error="empty summary"))
                skipped += 1
                next_off = record.offset + 1
                if tp not in last_committable or record.offset == last_committable[tp]:
                    last_committable[tp] = next_off
                continue

            chat_id = number_to_chat_id(payload.number)
            if chat_id is None:
                logger.warning("consume-notifications: invalid number at %s offset %s number=%s", tp, record.offset, payload.number)
                results.append(ConsumeResultItem(number=payload.number, company_name=payload.company_name, status="skipped", error="invalid number"))
                skipped += 1
                next_off = record.offset + 1
                if tp not in last_committable or record.offset == last_committable[tp]:
                    last_committable[tp] = next_off
                continue

            try:
                await waha_client.send_text_message(chat_id=chat_id, text=payload.summary, session=None)
            except Exception as e:
                logger.warning("consume-notifications: WAHA send failed at %s offset %s number=%s: %s", tp, record.offset, payload.number, e)
                results.append(ConsumeResultItem(number=payload.number, company_name=payload.company_name, status="error", error=str(e)))
                failed += 1
                continue

            results.append(ConsumeResultItem(number=payload.number, company_name=payload.company_name, status="success", error=None))
            processed += 1
            next_off = record.offset + 1
            if tp not in last_committable or record.offset == last_committable[tp]:
                last_committable[tp] = next_off

        if last_committable:
            await consumer.commit(offsets=last_committable)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
    finally:
        await consumer.stop()

    return ConsumeNotificationsResponse(status="success", processed=processed, failed=failed, skipped=skipped, results=results)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
