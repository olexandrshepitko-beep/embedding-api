#!/usr/bin/env python3
"""
TDLib Telegram Auth Service for Railway.
Генерирует QR код для входа → сохраняет сессию → отдаёт по HTTP.
"""
import json
import ctypes
import ctypes.util
import base64
import io
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

API_ID = 21983805
API_HASH = "7561534ca4d06db50b00fdcae88890e2"
SESSION_PATH = "/app/tdlib_session.json"

# Global state
client = None
auth_state = {"status": "waiting_qr", "qr_url": None, "session_saved": False}


class TDLibClient:
    """Minimal TDLib JSON client."""
    
    def __init__(self):
        # Find tdjson library
        lib_path = ctypes.util.find_library("tdjson")
        if not lib_path:
            lib_path = "/usr/local/lib/libtdjson.so"
        self._lib = ctypes.cdll.LoadLibrary(lib_path)
        
        # Setup function signatures
        self._lib.td_json_client_create.restype = ctypes.c_void_p
        self._lib.td_json_client_receive.argtypes = [ctypes.c_void_p, ctypes.c_double]
        self._lib.td_json_client_receive.restype = ctypes.c_char_p
        self._lib.td_json_client_send.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self._lib.td_json_client_execute.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self._lib.td_json_client_execute.restype = ctypes.c_char_p
        self._lib.td_json_client_destroy.argtypes = [ctypes.c_void_p]
        
        self._client = self._lib.td_json_client_create()
        
        # Set TDLib parameters
        self._send({
            "@type": "setLogVerbosityLevel",
            "new_verbosity_level": 0
        })
        self._send({
            "@type": "setLogStream",
            "log_stream": {"@type": "logStreamFile", "path": "/app/tdlib.log", "max_file_size": 1024}
        })
        
    def _send(self, query):
        self._lib.td_json_client_send(self._client, json.dumps(query).encode('utf-8'))
    
    def _receive(self, timeout=10.0):
        result = self._lib.td_json_client_receive(self._client, ctypes.c_double(timeout))
        if result:
            return json.loads(result.decode('utf-8'))
        return None
    
    def execute(self, query):
        result = self._lib.td_json_client_execute(self._client, json.dumps(query).encode('utf-8'))
        if result:
            return json.loads(result.decode('utf-8'))
        return None
    
    def send(self, query):
        self._send(query)
    
    def receive(self, timeout=10.0):
        return self._receive(timeout)
    
    def close(self):
        self._lib.td_json_client_destroy(self._client)


def auth_loop(client):
    """Handle TDLib authentication."""
    global auth_state
    
    # Set TDLib parameters
    client.send({
        "@type": "setTdlibParameters",
        "use_test_dc": False,
        "database_directory": "/app/tdlib_db",
        "files_directory": "/app/tdlib_files",
        "use_file_database": False,
        "use_chat_info_database": False,
        "use_message_database": False,
        "use_secret_chats": False,
        "api_id": API_ID,
        "api_hash": API_HASH,
        "system_language_code": "en",
        "device_model": "Railway",
        "system_version": "Linux",
        "application_version": "1.0.0",
    })
    
    while True:
        event = client.receive(30.0)
        if not event:
            continue
        
        ev_type = event.get("@type")
        
        if ev_type == "updateAuthorizationState":
            auth_state_type = event.get("authorization_state", {}).get("@type", "")
            
            if auth_state_type == "authorizationStateWaitTdlibParameters":
                # Already handled above
                pass
            
            elif auth_state_type == "authorizationStateWaitPhoneNumber":
                # Set phone number to trigger QR
                client.send({
                    "@type": "setAuthenticationPhoneNumber",
                    "phone_number": "+380689727174",
                    "settings": {
                        "@type": "phoneNumberAuthenticationSettings",
                        "allow_flash_call": False,
                        "is_current_phone_number": True,
                        "allow_sms_retriever_api": False
                    }
                })
            
            elif auth_state_type == "authorizationStateWaitCode":
                print("NEED_CODE: Код не пришёл автоматически. Ждём QR...")
                # Fallback: request QR
                client.send({"@type": "requestQrCode"})
            
            elif auth_state_type == "authorizationStateWaitOtherDeviceConfirmation":
                qr_url = event.get("link", "")
                auth_state["status"] = "scan_qr"
                auth_state["qr_url"] = qr_url
                print(f"QR_URL={qr_url}")
                print("QR_GENERATED — сканируй")
            
            elif auth_state_type == "authorizationStateWaitPassword":
                print("NEED_2FA: Требуется облачный пароль")
                auth_state["status"] = "need_2fa"
                # Для теста — без пароля не пройдём, но сохраним прогресс
                client.send({"@type": "checkAuthenticationPassword", "password": ""})
            
            elif auth_state_type == "authorizationStateReady":
                print("AUTHORIZED!")
                auth_state["status"] = "authorized"
                # Get user info
                client.send({"@type": "getMe"})
            
            elif auth_state_type == "authorizationStateClosed":
                print("CLOSED")
                break
        
        elif ev_type == "user":
            print(f"USER: {event.get('first_name', '?')} @{event.get('username', '?')}")
            # Save session
            save_session(client)
            auth_state["session_saved"] = True
            auth_state["status"] = "done"
            print("SESSION_SAVED")
            break
        
        elif ev_type == "error":
            err_msg = event.get("message", "")
            print(f"ERROR: {event.get('code', '?')} {err_msg}")
            if "phone number" in err_msg.lower():
                # Phone issues, try QR directly
                client.send({"@type": "requestQrCode"})
            elif "password" in err_msg.lower():
                auth_state["status"] = "need_2fa"
                print("NEED_2FA_PASSWORD")


def save_session(client):
    """Get session string and save."""
    # Export session
    client.send({
        "@type": "getAuthorizationState"
    })
    # TDLib handles session automatically via database_directory
    # We just need to keep the tdlib_db/ folder
    print("Session preserved in /app/tdlib_db/")


def serve_qr():
    """HTTP server to serve QR URL for scanning."""
    class QRHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            
            if auth_state["qr_url"]:
                html = f"""
                <html><body style="background:#000;color:#fff;font-family:sans-serif;text-align:center;padding:50px">
                <h1>Telegram Auth</h1>
                <p>Status: {auth_state['status']}</p>
                <p>Отсканируй QR в Telegram:</p>
                <p><b>Settings → Devices → Scan QR</b></p>
                <p><a href="{auth_state['qr_url']}" style="color:#0af;font-size:18px">Нажми если на телефоне</a></p>
                <p style="color:#888">Или открой ссылку в Telegram:</p>
                <code style="font-size:12px;word-break:break-all">{auth_state['qr_url']}</code>
                </body></html>
                """
            else:
                html = f"<html><body style='background:#000;color:#fff;padding:50px'><h1>Status: {auth_state['status']}</h1><p>Waiting for QR...</p></body></html>"
            
            self.wfile.write(html.encode())
    
    server = HTTPServer(("0.0.0.0", 8080), QRHandler)
    print(f"HTTP server on port 8080, auth status: {auth_state['status']}")
    server.serve_forever()


def main():
    global client
    
    print("=== TDLib Telegram Auth Service ===")
    
    # Start HTTP server in thread
    http_thread = threading.Thread(target=serve_qr, daemon=True)
    http_thread.start()
    
    # Start TDLib
    client = TDLibClient()
    
    try:
        if os.path.exists(SESSION_PATH):
            print(f"Found existing session at {SESSION_PATH}, loading...")
            # TDLib will auto-load if database_directory exists
        
        auth_loop(client)
    finally:
        if client:
            client.close()
    
    print(f"Final status: {auth_state['status']}")
    
    # Keep running for QR serving
    while auth_state["status"] not in ("done", "authorized"):
        time.sleep(1)
    
    print("Session ready! Service will keep running for 5 minutes...")
    time.sleep(300)


if __name__ == "__main__":
    main()
