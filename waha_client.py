"""WAHA (WhatsApp HTTP API) client wrapper."""
import httpx
from typing import Optional, Dict, Any
from config import settings


class WAHAClient:
    """Client wrapper for WAHA REST API."""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        default_session: Optional[str] = None,
        api_key: Optional[str] = None,
        auth_type: Optional[str] = None
    ):
        """
        Initialize WAHA client.
        
        Args:
            base_url: WAHA server base URL (defaults to settings.waha_base_url)
            default_session: Default session name (defaults to settings.waha_session)
            api_key: API key for authentication (defaults to settings.waha_api_key)
            auth_type: Authentication type - "X-API-Key", "Bearer", or "none" (defaults to settings.waha_auth_type)
        """
        self.base_url = base_url or settings.waha_base_url
        self.default_session = default_session or settings.waha_session
        self.api_key = api_key or settings.waha_api_key
        self.auth_type = auth_type or settings.waha_auth_type
        self.api_base = f"{self.base_url}/api"
    
    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers including authentication if configured."""
        headers = {"Content-Type": "application/json"}
        # Only add auth header if API key is provided and not set to "none"
        if self.api_key and self.auth_type != "none" and self.api_key.strip():
            if self.auth_type == "Bearer":
                headers["Authorization"] = f"Bearer {self.api_key.strip()}"
            elif self.auth_type == "X-Api-Key":
                # WAHA uses X-Api-Key (lowercase 'i' in Api)
                headers["X-Api-Key"] = self.api_key.strip()
        return headers
    
    async def send_text_message(
        self,
        chat_id: str,
        text: str,
        session: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a text message via WAHA API.
        
        Args:
            chat_id: WhatsApp chat ID (format: "1234567890@c.us" for private or "12345@g.us" for groups)
            text: Message text content
            session: Session name (defaults to default_session)
            
        Returns:
            Dict containing the response from WAHA API
            
        Raises:
            httpx.HTTPStatusError: If the HTTP request fails
            httpx.RequestError: If there's a network error
        """
        session_name = session or self.default_session
        
        # Check session status to ensure it's ready
        try:
            session_status = await self.check_session_status(session_name)
            
            # Check if session is ready - WAHA requires ready=true or status=CONNECTED to send messages
            # Some WAHA versions use "WORKING" status when connected but not fully ready
            session_status_value = session_status.get("status", "").upper()
            is_ready = session_status.get("ready", False)
            is_connected = session_status.get("connected", False)
            has_me_field = bool(session_status.get("me"))  # "me" field indicates WhatsApp connection
            
            # Allow CONNECTED, ready=true, or WORKING status with "me" field to proceed
            if session_status_value == "CONNECTED" or is_ready:
                # Session is ready, proceed
                pass
            elif session_status_value == "WORKING" and has_me_field:
                # WORKING status with "me" field - allow to proceed
                pass
            else:
                # Session is not ready
                error_msg = f"Session '{session_name}' is not ready to send messages. "
                error_msg += f"Status: {session_status.get('status', 'unknown')}, "
                error_msg += f"Ready: {is_ready}, Connected: {is_connected}. "
                if not has_me_field:
                    error_msg += "WhatsApp connection not established (no 'me' field). "
                error_msg += "Please ensure the session is fully connected and ready in the WAHA dashboard."
                raise httpx.HTTPStatusError(
                    message=error_msg,
                    request=None,
                    response=httpx.Response(400, text=error_msg)
                )
        except httpx.HTTPStatusError:
            raise  # Re-raise HTTPStatusError as-is
        except Exception as e:
            # If we can't check status, fail fast to prevent timeout
            raise httpx.RequestError(
                f"Failed to check session '{session_name}' status: {str(e)}. Cannot verify session is ready. Please check WAHA server.",
                request=None
            ) from e
        
        url = f"{self.api_base}/sendText"
        
        payload = {
            "chatId": chat_id,
            "text": text,
            "session": session_name
        }
        
        headers = self._get_headers()
        
        # Use a longer timeout for sendText, but also add connection timeout
        # WAHA may take time if session is not fully ready, so we validate that first
        timeout_config = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout_config) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
            except httpx.ConnectError as e:
                raise httpx.RequestError(
                    f"Could not connect to WAHA server at {self.base_url}. "
                    f"Is WAHA running? Check with: docker ps | grep waha",
                    request=e.request
                ) from e
            except httpx.TimeoutException as e:
                raise httpx.RequestError(
                    f"Request to WAHA server timed out after 60 seconds. "
                    f"This may indicate:\n"
                    f"1. Session '{session_name}' is not connected or ready\n"
                    f"2. WhatsApp connection is slow or unstable\n"
                    f"3. The chatId '{chat_id}' is invalid\n"
                    f"Check WAHA logs: docker logs waha",
                    request=e.request
                ) from e
            
            # Handle cases where WAHA aborts the request (statusCode null in logs)
            # This often happens when the session is not ready or chatId is invalid
            if response.status_code == 0 or (response.status_code >= 500 and response.text and "aborted" in response.text.lower()):
                error_msg = f"WAHA request was aborted. This usually means:\n"
                error_msg += f"1. Session '{session_name}' is not connected - Check WAHA dashboard\n"
                error_msg += f"2. Session is not ready - Ensure QR code is scanned\n"
                error_msg += f"3. Invalid chatId '{chat_id}' - Verify the format (e.g., '1234567890@c.us')\n"
                error_msg += f"4. WhatsApp connection issue - Check WAHA logs: docker logs waha\n"
                raise httpx.HTTPStatusError(
                    message=error_msg,
                    request=response.request,
                    response=response
                )
            
            # Provide better error messages for 401 errors
            if response.status_code == 401:
                error_msg = "WAHA authentication failed (401 Unauthorized).\n"
                error_msg += f"URL: {url}\n"
                
                if not self.api_key or not self.api_key.strip():
                    error_msg += "\nPossible causes:\n"
                    error_msg += "1. No API key configured. If WAHA was started WITHOUT WHATSAPP_API_KEY, remove WAHA_API_KEY from .env\n"
                    error_msg += "2. If WAHA requires authentication, set WAHA_API_KEY in .env to match WHATSAPP_API_KEY in Docker\n"
                else:
                    error_msg += f"\nAPI key is configured (length: {len(self.api_key)} chars)\n"
                    error_msg += "Possible causes:\n"
                    error_msg += "1. API key mismatch - verify WAHA_API_KEY matches WHATSAPP_API_KEY in Docker\n"
                    error_msg += "2. WAHA was started without WHATSAPP_API_KEY - remove WAHA_API_KEY from .env\n"
                    error_msg += "3. Check for extra spaces or special characters in the key\n"
                
                error_msg += f"\nWAHA Response: {response.text}"
                
                # Create a custom error with better message
                raise httpx.HTTPStatusError(
                    message=error_msg,
                    request=response.request,
                    response=response
                )
            
            # Check for other error status codes
            if response.status_code >= 400:
                error_msg = f"WAHA API returned error {response.status_code}\n"
                error_msg += f"URL: {url}\n"
                error_msg += f"Session: {session_name}\n"
                error_msg += f"ChatId: {chat_id}\n"
                
                if response.status_code == 400:
                    error_msg += "\nPossible causes:\n"
                    error_msg += "1. Invalid chatId format - Use '1234567890@c.us' for private chats\n"
                    error_msg += "2. Session not found or not ready\n"
                    error_msg += "3. Invalid message content\n"
                elif response.status_code == 404:
                    error_msg += "\nPossible causes:\n"
                    error_msg += f"1. Session '{session_name}' does not exist\n"
                    error_msg += "2. Endpoint not found - Check WAHA version\n"
                elif response.status_code >= 500:
                    error_msg += "\nPossible causes:\n"
                    error_msg += "1. WAHA server error - Check logs: docker logs waha\n"
                    error_msg += "2. WhatsApp connection issue\n"
                    error_msg += "3. Session disconnected\n"
                
                error_msg += f"\nWAHA Response: {response.text}"
                raise httpx.HTTPStatusError(
                    message=error_msg,
                    request=response.request,
                    response=response
                )
            
            response.raise_for_status()
            return response.json()
    
    async def check_session_status(self, session: Optional[str] = None) -> Dict[str, Any]:
        """
        Check the status of a WAHA session.
        
        Args:
            session: Session name (defaults to default_session)
            
        Returns:
            Dict containing session status information
        """
        session_name = session or self.default_session
        url = f"{self.api_base}/sessions/{session_name}"
        headers = self._get_headers()
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise httpx.HTTPStatusError(
                        message=f"Session '{session_name}' not found. Create it in WAHA dashboard first.",
                        request=e.request,
                        response=e.response
                    )
                raise