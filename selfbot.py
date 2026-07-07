#!/usr/bin/env python3
"""
Discord Self-Bot Treo Voice 24/7
Hỗ trợ: Multi-account, Auto-reconnect, Voice stay-alive

Chiến lược: Gửi Voice State Update trực tiếp qua Gateway (op 4)
→ Không cần Voice WebSocket → Không bị lỗi DAVE/E2EE
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import discord

# ============================================================
# CONFIG
# ============================================================
TOKENS = [t.strip() for t in os.getenv("DISCORD_TOKENS", "").split(",") if t.strip()]
VOICE_IDS = [int(c.strip()) for c in os.getenv("VOICE_CHANNEL_IDS", "").split(",") if c.strip()]
SELF_MUTE = os.getenv("SELF_MUTE", "true").lower() == "true"
SELF_DEAF = os.getenv("SELF_DEAF", "false").lower() == "true"

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("treo")

# Giảm noise
for name in ["discord", "discord.gateway", "discord.voice_state",
             "discord.voice_client", "discord.client", "discord.http", "discord.state"]:
    logging.getLogger(name).setLevel(logging.WARNING)


# ============================================================
# SINGLE ACCOUNT
# ============================================================
class Account:
    def __init__(self, token: str, channel_id: int, index: int):
        self.token = token
        self.channel_id = channel_id
        self.index = index
        self.name = f"ACC#{index}"
        self.client = None
        self.guild_id = None  # Sẽ được set sau khi join
        self.in_voice = False
        self.ready = False

    async def run(self):
        self.client = discord.Client()

        @self.client.event
        async def on_ready():
            user = self.client.user
            log.info(f"[{self.name}] ✅ LOGIN: {user} (ID: {user.id})")
            self.ready = True

            # Tìm guild_id từ channel_id
            await self._find_guild_and_join()

        @self.client.event
        async def on_voice_state_update(member, before, after):
            if member != self.client.user:
                return

            if before.channel and not after.channel:
                self.in_voice = False
                log.warning(f"[{self.name}] 🔌 Mất voice state, sẽ gửi lại...")
                # Gửi lại voice state ngay
                if self.ready and self.guild_id:
                    await self._send_voice_state()

            elif not before.channel and after.channel:
                self.in_voice = True
                log.info(f"[{self.name}] 🎤 ĐÃ VÀO VOICE: {after.channel.name} "
                         f"({after.channel.guild.name}) | Mute={SELF_MUTE}")

        @self.client.event
        async def on_disconnect():
            log.warning(f"[{self.name}] WebSocket mất kết nối...")

        log.info(f"[{self.name}] Đang kết nối...")
        try:
            await self.client.start(self.token, reconnect=True)
        except discord.LoginFailure:
            log.error(f"[{self.name}] ❌ TOKEN SAI!")
            return
        except Exception as e:
            log.error(f"[{self.name}] ❌ {type(e).__name__}: {e}")
            return

    async def _find_guild_and_join(self):
        """Tìm guild_id từ voice channel và gửi voice state update."""
        # Thử lấy channel từ cache trước
        channel = self.client.get_channel(self.channel_id)

        if channel is None:
            # Fetch channel để lấy guild_id
            try:
                channel = await self.client.fetch_channel(self.channel_id)
            except Exception as e:
                log.error(f"[{self.name}] ❌ Không fetch được channel: {e}")
                return

        if channel is None:
            log.error(f"[{self.name}] ❌ Channel ID={self.channel_id} không tồn tại!")
            return

        if not isinstance(channel, discord.VoiceChannel):
            log.error(f"[{self.name}] ❌ ID={self.channel_id} không phải VoiceChannel!")
            return

        self.guild_id = channel.guild.id
        log.info(f"[{self.name}] Tìm thấy: {channel.name} trong {channel.guild.name} "
                 f"(guild_id={self.guild_id})")

        # Gửi Voice State Update qua Gateway (không cần Voice WebSocket)
        await self._send_voice_state()

    async def _send_voice_state(self):
        """Gửi VOICE_STATE_UPDATE (op 4) qua Gateway WebSocket."""
        if not self.client or not self.client.ws:
            return

        payload = {
            "op": 4,
            "d": {
                "guild_id": str(self.guild_id),
                "channel_id": str(self.channel_id),
                "self_mute": SELF_MUTE,
                "self_deaf": SELF_DEAF,
            }
        }

        try:
            await self.client.ws.send_as_json(payload)
            log.info(f"[{self.name}] 📤 Đã gửi VOICE_STATE_UPDATE → channel {self.channel_id}")
        except Exception as e:
            log.error(f"[{self.name}] ❌ Gửi voice state thất bại: {e}")


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
    log.info(f"   Mute={SELF_MUTE} Deaf={SELF_DEAF}")
    log.info(f"   Phương pháp: Gateway Voice State (không Voice WS)")
    log.info("=" * 40)

    accounts = [Account(t, VOICE_IDS[i % len(VOICE_IDS)], i + 1)
                for i, t in enumerate(TOKENS)]

    tasks = [asyncio.create_task(acc.run()) for acc in accounts]

    # Đợi kết nối
    await asyncio.sleep(10)

    online = sum(1 for a in accounts if a.in_voice)
    log.info(f">>> {online}/{len(accounts)} acc trong voice <<<")

    if online == 0:
        log.warning("⚠ Chưa acc nào vào voice. Kiểm tra:")
        log.warning("   1. Token còn hạn không?")
        log.warning("   2. Channel ID đúng không?")
        log.warning("   3. Acc có trong server đó không?")

    log.info("Bot đang chạy... Ctrl+C để dừng.\n")

    # Monitor mỗi 60s - gửi lại voice state nếu mất
    async def monitor():
        while True:
            await asyncio.sleep(60)
            for a in accounts:
                if a.ready and a.guild_id and not a.in_voice:
                    log.info(f"[{a.name}] Gửi lại voice state...")
                    await a._send_voice_state()
            online = sum(1 for a in accounts if a.in_voice)
            if online < len(accounts):
                log.info(f"📊 Status: {online}/{len(accounts)} online")

    monitor_task = asyncio.create_task(monitor())

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        monitor_task.cancel()
        for a in accounts:
            try:
                if a.client:
                    await a.client.close()
            except Exception:
                pass
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
