import concurrent.futures
import threading
import asyncio
import serial
import sys
import time
from types import TracebackType
from typing import Any, List, Optional

import discord
import discord.types

import discordbot


def flush(iface: serial.Serial) -> None:
    print("Flushing serial...")
    while True:
        data = iface.read()
        sys.stdout.write(data.decode())
        if not data:
            break
    sys.stdout.write("\n")
    print("- End flush")


class SerialChannel(discord.TextChannel):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def send(self, content: Optional[str], **kwargs: None) -> None:  # type: ignore # This is a hack to make us minimally compatible.
        print(content)
        return None


# TODO: Inherit from MarBot instead, and handle hardware_guild_id and hardware_user
class SerialBot(discordbot.MarBot):
    def __init__(self) -> None:
        self.serial_user = "marauderiic"
        discord.utils.setup_logging(
            handler=discord.utils.MISSING,
            formatter=discord.utils.MISSING,
            level=discord.utils.MISSING,
            root=False,
        )

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.results: List[concurrent.futures.Future] = []  # type: ignore # There's only so much I can care about getting this typed

        self.thread = threading.Thread(target=serial_thread, args=[self, self.loop])

        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

    def handle_serial_message(self, serial_data: str) -> None:
        user = discord.utils.find(lambda m: m.name == self.serial_user, self.users)
        if user is None:
            print(f"Can't find serial user {self.serial_user}")
            return

        serial_data = serial_data.strip()

        # TODO: Add a special join-me action handling here
        # self.results.append(
        #     asyncio.run_coroutine_threadsafe(
        #         client.play_iface("serial-user", None, [data]), loop
        #     )
        # )

        self.results.append(
            asyncio.run_coroutine_threadsafe(
                self.handle_play(user, SerialChannel(), [serial_data]), self.loop
            )
        )

        # Prune outdated coroutines and their results.
        if len(self.results) > 5:
            for result in self.results[:5]:  # Cancel the first 5
                result.cancel()
            self.results = self.results[
                5:
            ]  # Continue waiting for everything after the first 5

    async def setup_hook(self) -> None:
        await super().setup_hook()
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
        discordbot.main(self, self.loop)

    def serial_bot_stop(self) -> None:
        global done
        done = True
        self.thread.join()
        self.loop.run_until_complete(self.loop.shutdown_asyncgens())
        self.loop.close()


done = False  # Setting this flag causes the main_serial thread to stop.


def serial_thread(client: SerialBot) -> None:
    """
    Poll for lines in the serial data
    """
    global done

    print("Serial waiting for discord bot to come online")
    while not done and not client.is_ready():
        time.sleep(0.1)

    print("Starting serial")
    try:
        with serial.Serial(port="COM3", baudrate=115200, timeout=1) as iface:
            flush(iface)
            data = ""
            while not done:
                # TODO: Handle serial.serialutil.SerialException here for when the soundboard is unplugged and plugged back in
                rx_data = iface.readline().decode()
                data += rx_data

                if (
                    done
                ):  # Handle any flag changes that happened while we were reading data
                    break  # type: ignore # This is reachable because 'done' is volatile.

                if not data:
                    continue

                print("serial rx:", data.strip())

                if "\n" in data:
                    client.handle_serial_message(data)
                    data = ""

    except KeyboardInterrupt:
        pass
    finally:
        for result in client.results:
            result.cancel()


if __name__ == "__main__":
    with SerialBot() as client:
        pass
