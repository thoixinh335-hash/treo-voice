#!/usr/bin/env python3
"""
Discord Voice 24/7 - Raw Gateway WebSocket
Không dùng discord.py-self
Dùng websockets + curl_cffi (chỉ cho REST API)
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Load .env từ thư mục chứa script
SCRIPT_DIR = Path(__file__).resolve().parent
dotenv_path = SCRIPT_DIR / ".env"
load_dotenv(dotenv_path)
if not dotenv_path.exists():
    print(f"[WARNING] Không tìm thấy {dotenv_path}")

from curl_cffi.requests import AsyncSession
import websockets

# ============================================================
# CONFIG
# ============================================================
TOKENS = [t.strip() for t in os.getenv("DISCORD_TOKENS", "").split(",") if t.strip()]
VOICE_IDS = [int(c.strip()) for c in os.getenv("VOICE_CHANNEL_IDS", "").split(",") if c.strip()]
SELF_MUTE = os.getenv("SELF_MUTE", "true").lower() == "true"
SELF_DEAF = os.getenv("SELF_DEAF", "false").lower() == "true"
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "10"))

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("treo")

# ============================================================
# FAKE BROWSER HEADERS
# ============================================================
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"

WS_HEADERS = {
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": "https://discord.com",
    "User-Agent": UA,
}


# ============================================================
# ACCOUNT - Raw Gateway
# ============================================================
class Account:
    def __init__(self, token: str, channel_id: int, index: int):
        self.token = token
        self.channel_id = channel_id
        self.index = index
        self.name = f"ACC#{index}"
        self.guild_id = None
        self.in_voice = False
        self.seq = None
        self._hb_interval = 0
        self._keep_alive = True
        self._user_id = None

    async def run(self):
        self._keep_alive = True
        while self._keep_alive:
            try:
                await self._connect_gateway()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"[{self.name}] ❌ Gateway error: {type(e).__name__}: {e}")

            if self._keep_alive:
                log.info(f"[{self.name}] Reconnect sau {RECONNECT_DELAY}s...")
                await asyncio.sleep(RECONNECT_DELAY)

    async def _get_gateway(self) -> str:
        """Lấy gateway URL từ Discord REST API."""
        headers = {
            "authorization": self.token,
            "user-agent": UA,
            "origin": "https://discord.com",
        }
        async with AsyncSession(headers=headers, impersonate="chrome142") as s:
            resp = await s.get("https://discord.com/api/v9/gateway")
            if resp.status_code == 401:
                log.error(f"[{self.name}] ❌ TOKEN SAI! (status 401)")
                self._keep_alive = False
                return None
            if resp.status_code == 403:
                log.error(f"[{self.name}] ❌ TOKEN BỊ LOCK! (status 403)")
                self._keep_alive = False
                return None
            if resp.status_code == 429:
                log.error(f"[{self.name}] ❌ Rate limited!")
                return None
            if resp.status_code != 200:
                log.error(f"[{self.name}] ❌ Gateway API: status {resp.status_code}")
                return None
            data = resp.json()
            log.info(f"[{self.name}] ✅ Token hợp lệ, lấy gateway: {data.get('url')[:30]}...")
            return data.get("url")

    async def _connect_gateway(self):
        """Kết nối Discord Gateway qua websockets library."""
        gateway_url = await self._get_gateway()
        if not gateway_url:
            return

        ws_url = f"{gateway_url}/?v=10&encoding=json"
        log.info(f"[{self.name}] Đang kết nối Gateway...")

        try:
            async with websockets.connect(
                ws_url,
                additional_headers=WS_HEADERS,
                max_size=2**24,  # 16MB
                ping_interval=None,  # Tự quản lý heartbeat
                ping_timeout=None,
                close_timeout=5,
            ) as ws:

                log.info(f"[{self.name}] ✅ WebSocket connected")
                self.ws = ws

                # Đợi op 10 Hello
                msg = await ws.recv()
                data = json.loads(msg)
                if data.get("op") != 10:
                    log.error(f"[{self.name}] ❌ Không nhận được Hello (op={data.get('op')})")
                    return

                self._hb_interval = data["d"]["heartbeat_interval"] / 1000
                log.info(f"[{self.name}] ✅ Gateway hello (heartbeat: {self._hb_interval:.1f}s)")

                # Bắt đầu heartbeat loop
                hb_task = asyncio.create_task(self._heartbeat_loop(ws))

                try:
                    # Gửi Identify
                    await self._identify(ws)

                    # Vòng lặp đọc message
                    await self._read_loop(ws)
                finally:
                    hb_task.cancel()
                    try:
                        await hb_task
                    except asyncio.CancelledError:
                        pass

                self.in_voice = False

        except websockets.WebSocketException as e:
            log.warning(f"[{self.name}] 📡 WebSocket lỗi: {e}")
        except OSError as e:
            log.warning(f"[{self.name}] 📡 Socket lỗi: {e}")

    async def _heartbeat_loop(self, ws):
        """Gửi heartbeat mỗi heartbeat_interval giây."""
        while True:
            await asyncio.sleep(self._hb_interval)
            try:
                await ws.send(json.dumps({"op": 1, "d": self.seq}))
            except Exception:
                break

    async def _identify(self, ws):
        """Gửi op 2 Identify."""
        payload = {
            "op": 2,
            "d": {
                "token": self.token,
                "capabilities": 4093,
                "properties": {
                    "os": "Windows",
                    "browser": "Chrome",
                    "device": "",
                    "system_locale": "en-US",
                    "browser_user_agent": UA,
                    "browser_version": "142.0.0.0",
                    "os_version": "10",
                    "referrer": "https://discord.com/",
                    "referring_domain": "discord.com",
                    "referrer_current": "https://discord.com/",
                    "referring_domain_current": "discord.com",
                    "release_channel": "stable",
                    "client_build_number": 580004,
                    "client_event_source": None,
                },
                "presence": {
                    "status": "online",
                    "since": 0,
                    "activities": [],
                    "afk": False,
                },
                "compress": False,
                "client_state": {
                    "guild_hashes": {},
                    "highest_last_message_id": "0",
                    "read_state_version": 0,
                    "user_guild_settings_version": -1,
                    "user_settings_version": -1,
                },
            },
        }
        await ws.send(json.dumps(payload))
        log.info(f"[{self.name}] 📤 Sent Identify")

    async def _read_loop(self, ws):
        """Đọc và xử lý message từ Gateway."""
        while self._keep_alive:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=60)
                if isinstance(msg, bytes):
                    msg = msg.decode()
            except asyncio.TimeoutError:
                # Không có message trong 60s -> gửi heartbeat để test
                try:
                    await ws.send(json.dumps({"op": 1, "d": self.seq}))
                except Exception:
                    break
                continue
            except websockets.WebSocketException as e:
                log.warning(f"[{self.name}] 📡 WebSocket mất kết nối: {e}")
                break

            data = json.loads(msg)
            op = data.get("op")

            if op == 0:  # Dispatch
                self.seq = data.get("s")
                t = data.get("t")

                if t == "READY":
                    user = data["d"]["user"]
                    self._user_id = str(user["id"])
                    log.info(f"[{self.name}] ✅ LOGIN: {user['username']} (ID: {self._user_id})")
                    await self._find_and_join()

                elif t == "VOICE_STATE_UPDATE":
                    vs = data["d"]
                    if vs.get("user_id") == self._user_id:
                        if vs.get("channel_id"):
                            if not self.in_voice:
                                self.in_voice = True
                                log.info(f"[{self.name}] 🎤 ĐÃ VÀO VOICE!")
                        else:
                            if self.in_voice:
                                self.in_voice = False
                                log.warning(f"[{self.name}] 🔌 Mất voice state")

                elif t == "VOICE_SERVER_UPDATE":
                    pass

                elif t == "RESUMED":
                    log.info(f"[{self.name}] 🔄 Session resumed")

            elif op == 1:  # Heartbeat request
                try:
                    await ws.send(json.dumps({"op": 1, "d": self.seq}))
                except Exception:
                    break

            elif op == 7:  # Reconnect
                log.warning(f"[{self.name}] 🔄 Gateway yêu cầu reconnect")
                break

            elif op == 9:  # Invalid Session
                log.error(f"[{self.name}] ❌ Invalid session! Token hết hạn hoặc sai.")
                self._keep_alive = False
                break

    async def _find_and_join(self):
        """Tìm guild từ channel_id và gửi voice state."""
        headers = {
            "authorization": self.token,
            "user-agent": UA,
            "origin": "https://discord.com",
        }
        async with AsyncSession(headers=headers, impersonate="chrome142") as s:
            resp = await s.get(f"https://discord.com/api/v9/channels/{self.channel_id}")
            if resp.status_code != 200:
                log.error(f"[{self.name}] ❌ Fetch channel failed: status {resp.status_code}")
                if resp.status_code in (401, 403):
                    self._keep_alive = False
                return
            ch = resp.json()

        if ch.get("type") != 2:
            log.error(f"[{self.name}] ❌ ID {self.channel_id} không phải voice channel!")
            return

        self.guild_id = str(ch["guild_id"])
        log.info(f"[{self.name}] Tìm thấy: {ch['name']} (guild={self.guild_id})")

        await self._send_voice_state()

    async def _send_voice_state(self):
        """Gửi op 4 VOICE_STATE_UPDATE."""
        if not hasattr(self, 'ws') or not self.ws or not self.guild_id:
            return

        payload = {
            "op": 4,
            "d": {
                "guild_id": self.guild_id,
                "channel_id": str(self.channel_id),
                "self_mute": SELF_MUTE,
                "self_deaf": SELF_DEAF,
            },
        }
        try:
            await self.ws.send(json.dumps(payload))
            log.info(f"[{self.name}] 📤 Voice State → {self.channel_id}")
        except Exception as e:
            log.error(f"[{self.name}] ❌ Gửi voice state thất bại: {e}")

    async def stop(self):
        self._keep_alive = False
        if hasattr(self, 'ws') and self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass


# ============================================================
# MAIN
# ============================================================
async def main():
    if not TOKENS:
        log.error("❌ Thiếu DISCORD_TOKENS trong .env!")
        sys.exit(1)
    if not VOICE_IDS:
        log.error("❌ Thiếu VOICE_CHANNEL_IDS trong .env!")
        sys.exit(1)

    log.info(f"🚀 Khởi động {len(TOKENS)} acc | Channels: {VOICE_IDS}")
    log.info(f"   Mute={SELF_MUTE} Deaf={SELF_DEAF} Reconnect={RECONNECT_DELAY}s")
    log.info(f"   Phương pháp: websockets + curl_cffi (REST)")
    log.info("=" * 40)

    accounts = [Account(t, VOICE_IDS[i % len(VOICE_IDS)], i + 1)
                for i, t in enumerate(TOKENS)]

    tasks = [asyncio.create_task(acc.run()) for acc in accounts]

    async def monitor():
        last_online = -1
        while True:
            await asyncio.sleep(30)
            online = sum(1 for a in accounts if a.in_voice)
            if online != last_online:
                log.info(f"📊 Status: {online}/{len(accounts)} trong voice")
                last_online = online

    monitor_task = asyncio.create_task(monitor())

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        monitor_task.cancel()
        for a in accounts:
            await a.stop()
        await asyncio.sleep(0.5)
        log.info("Đã dừng.")


if __name__ == "__main__":
    print(r"""
  _____              __      ___
 /__   \_ __ ___  __ \ \    / /(_)___ ___  ___
   / /\/ '__/ _ \/ _ \ \ \  / / / __/ _ \/ __|
  / /  | | |  __/  __/  \ \/ /| | (_|  __/\__ \
  \/   |_|  \___|\___|   \__/ |_|\___\___||___/
         Discord Voice 24/7 Self-Bot
    """)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bye!")
