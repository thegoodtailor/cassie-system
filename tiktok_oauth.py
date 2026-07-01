#!/usr/bin/env python3
"""TikTok OAuth callback — run once to get initial tokens.

Usage:
    1. Start this server:  python tiktok_oauth.py
    2. Visit the auth URL it prints
    3. Authorize in browser → redirects back → tokens saved
    4. Stop the server (Ctrl+C)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

CLIENT_KEY = os.getenv("TIKTOK_CLIENT_KEY", "aw5cotryrtm6kiav")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "JNOpL3TpcPz9uwS4kW9NENPyOoiDoFzw")
REDIRECT_URI = "https://news.tanazur.org/tiktok-callback"
TOKEN_FILE = Path(__file__).parent / "data" / "tiktok_tokens.json"
API_BASE = "https://open.tiktokapis.com"

AUTH_URL = (
    f"https://www.tiktok.com/v2/auth/authorize/"
    f"?client_key={CLIENT_KEY}"
    f"&scope=user.info.basic,video.publish"
    f"&response_type=code"
    f"&redirect_uri={REDIRECT_URI}"
    f"&state=cassie_oauth"
)


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" not in params:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No auth code received")
            return

        code = params["code"][0]
        print(f"\nAuth code received: {code[:20]}...")

        # Exchange code for tokens
        resp = httpx.post(
            f"{API_BASE}/v2/oauth/token/",
            data={
                "client_key": CLIENT_KEY,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )

        data = resp.json()
        if "access_token" in data:
            tokens = {
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
                "open_id": data.get("open_id", ""),
                "scope": data.get("scope", ""),
                "created_at": datetime.now().isoformat(),
                "refreshed_at": datetime.now().isoformat(),
            }
            TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
            print(f"\nTokens saved to {TOKEN_FILE}")
            print(f"  access_token: {data['access_token'][:20]}...")
            print(f"  refresh_token: {data['refresh_token'][:20]}...")
            print(f"  open_id: {data.get('open_id', '')}")

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Cassie TikTok OAuth Complete</h1><p>Tokens saved. You can close this tab.</p>")
        else:
            print(f"\nToken exchange failed: {data}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Token exchange failed: {json.dumps(data)}".encode())

    def log_message(self, format, *args):
        pass  # Suppress default logging


if __name__ == "__main__":
    print("=" * 60)
    print("  TikTok OAuth Setup for Cassie")
    print("=" * 60)
    print(f"\n  1. Visit this URL in your browser:\n")
    print(f"  {AUTH_URL}\n")
    print(f"  2. Authorize the app")
    print(f"  3. You'll be redirected back and tokens will be saved\n")
    print(f"  Listening on port 7871...")
    print(f"  (nginx proxies /tiktok-callback → localhost:7871)")

    server = HTTPServer(("127.0.0.1", 7871), CallbackHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDone.")
