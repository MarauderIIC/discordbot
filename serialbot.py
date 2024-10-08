import concurrent.futures
import logging
import threading
import asyncio
import sys
import time
from types import TracebackType
from typing import Any, List, Optional

import discord
import discord.types
import serial
import serial.serialutil

import discordbot

_log = logging.getLogger()


class SerialChannel(discord.TextChannel):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def send(self, content: Optional[str], **kwargs: None) -> None:  # type: ignore # Wrong return is a hack to make us minimally compatible.
        print(content)
        return None


class SerialMember(discord.Member):
    def __init__(self, discord_member: discord.Member) -> None:
        self.discord_member = discord_member

    @property
    def mention(self) -> str:
        return f"<@display={self.display_name} user={self.name} id={self.id}>"

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.discord_member, attr)


class SerialBot(discordbot.MarBot):
    def __init__(self, port: str, baud: int) -> None:
        discord.utils.setup_logging(
            handler=discord.utils.MISSING,
            formatter=discord.utils.MISSING,
            level=discord.utils.MISSING,
            root=True,
        )

        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        # TODO: Handle hardware_user config instead of hardcoding it into serial_user.
        self.serial_user = "marauderiic"
        self.results: List[concurrent.futures.Future] = []  # type: ignore # There's only so much I can care about getting this typed

        self.thread_done = (
            False  # Setting this flag to True tells thread_serial to stop.
        )
        self.thread = threading.Thread(target=thread_serial, args=[self, port, baud])

    def thread_handle_serial_message(
        self, serial_data: str, loop: asyncio.AbstractEventLoop
    ) -> None:
        """
        Handle a serial command. Right now this means join the soundboard user's voice channel and play a sound.

        :param serial_data: Raw serial string that represents a complete command
        :param loop: The asyncio loop used to submit commands to the main MarBot task.
        """
        if not self.is_ready():
            _log.warning(
                f"Discord not connected; not ready to handle serial data: '{serial_data}'"
            )
            return

        if loop is None:
            raise ValueError("No asyncio event loop")
        
        if serial_data == "QUIT_NOW":
            return

        user = None
        for guild in self.guilds:
            for member in guild.members:
                if (
                    member.name == self.serial_user
                    and member.voice
                    and member.voice.channel
                ):
                    user = member
                    break

        if user is None or user.voice is None or user.voice.channel is None:
            _log.warning(
                f"Can't find serial user {self.serial_user} in a voice channel in any server"
            )
            return

        if not self.voice_client or (
            self.voice_client and self.voice_client.channel != user.voice.channel
        ):
            self.results.append(
                asyncio.run_coroutine_threadsafe(
                    self.handle_join_user(user, SerialChannel(), []), loop
                )
            )
            # TODO: Surely there's a callback for this.
            timeout = time.time() + 5
            while time.time() < timeout:
                if (
                    self.voice_client
                    and self.voice_client.is_connected()
                    and self.voice_client.channel == user.voice.channel
                ):
                    break
                time.sleep(0.1)
            else:
                _log.warning(
                    "Voice connection did not complete in timeout, try again when the bot joins"
                )
                return

        serial_data = serial_data.strip()

        self.results.append(
            asyncio.run_coroutine_threadsafe(
                self.handle_play(SerialMember(user), SerialChannel(), [serial_data]),
                loop,
            )
        )

        # Prune outdated coroutines and their results.
        if len(self.results) > 5:
            for result in self.results[:5]:  # Cancel the first 5 - an arbitrary number
                result.cancel()
            # Continue waiting for everything else
            self.results = self.results[5:]

    async def setup_hook(self) -> None:
        await super().setup_hook()
        _log.debug("Starting serial thread")
        self.thread.start()

    def __enter__(self) -> "SerialBot":
        self.serial_bot_start()
        return self

    def __exit__(
        self,
        unused_exc_type: Optional[type[BaseException]],
        unused_exc_value: Optional[BaseException],
        unused_exc_tb: Optional[TracebackType],
    ) -> None:
        self.serial_bot_stop()

    def serial_bot_start(self) -> None:
        discordbot.main(self, loop)

    def serial_bot_stop(self) -> None:
        self.thread_done = True
        self.thread.join()
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


def thread_serial(client: SerialBot, port: str, baud: int = 115200) -> None:
    """
    Poll for lines in the serial data
    """
    global loop  # Putting this into SerialBot causes things to break... maybe the variable name overlaps with something?

    #_log.setLevel(logging.DEBUG)
    _log.info("Serial waiting for discord bot to come online")
    # TODO: Use on_ready instead.
    while not client.thread_done and not client.is_ready():
        time.sleep(0.1)

    warned = False  # Don't warn consecutively about reconnecting.
    last_upload_at = 0
    state = 0
    while not client.thread_done:
        try:
            if not warned:
                _log.info("Connecting to serial %s...", port)
            with serial.Serial(port=port, baudrate=baud, timeout=1) as iface:
                iface.reset_input_buffer()  # Clear boot info
                data = ""
                warned = False
                while not client.thread_done:
                    # TODO: Handle serial.serialutil.SerialException here for when the soundboard is unplugged and plugged back in
                    rx_data = iface.readline().decode(errors="replace")
                    data += rx_data

                    # Handle any flag changes that happened while we were reading data
                    if client.thread_done:
                        break  # type: ignore # This is reachable because thread_done is volatile

                    if not data:
                        continue

                    if data.startswith("~WARNING"):
                        _log.warning("Serial rx: %s", data.strip())
                    elif data.startswith("~ERROR"):
                        _log.error("Serial rx: %s", data.strip())
                    else:
                        _log.debug("state %d, serial rx: '%s'", state, data)

                    if "\n" in data:  # No matter what state we're in, clear the data if we got a full line.
                        data = data.strip()
                        if data == "~Waiting for sounds":
                            if time.time() - last_upload_at < 5:
                                _log.error("Sound board boot loop detected, bailing!")
                                client.thread_done = True
                                break

                            serial_sounds = "\n".join(x for x in client.files.keys()).encode(encoding="ascii") + b"\n"
                            iface.write((str(len(client.files.keys())) + "\n").encode(encoding="ascii"))
                            _log.debug("Sent %s", (str(len(serial_sounds)) + "\n").encode(encoding="ascii"))
                            iface.write(serial_sounds)
                            _log.debug("Sent %s", serial_sounds)
                            _log.info("Serial ready!")
                            last_upload_at = time.time()
                            iface.reset_input_buffer()  # Maybe we got boot info again
                            state = 1
                        elif data == "~Soundboard ready":
                            if state == 0:
                                _log.info("Soundboard is already ready! Be sure to restart it if your local sound files have changed.")
                            state = 2

                        if not data.startswith("~"):
                            client.thread_handle_serial_message(data, loop)
                        data = ""

        except serial.serialutil.SerialException as exc:
            if not warned:
                _log.warning("Can't talk to serial device. Retrying...")
                warned = True
            timeout = time.time() + 5
            while time.time() < timeout and not client.thread_done:
                time.sleep(0.5)


if __name__ == "__main__":
    global loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    try:
        with SerialBot(port="COM3", baud=115200) as client:
            pass
    except KeyboardInterrupt:
        pass
