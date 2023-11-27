
import discordbot
import threading
import asyncio
import serial
import sys
import time

def flush(iface: serial.Serial) -> None:
    print("Flushing serial...")
    while True:
        data = iface.read()
        sys.stdout.write(data.decode())
        if not data:
            break
    sys.stdout.write("\n")
    print("- End flush")


# TODO: Inherit from MarBot instead, and handle hardware_guild_id and hardware_user
class SerialBot(discordbot.MarBot):
    pass

done = False  # Setting this flag causes the main_serial thread to stop.
def main_serial(client: discordbot.MarBot, loop: asyncio.AbstractEventLoop) -> None:
    """
    Poll for lines in the serial data
    """
    global done
    results = []

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

                if done: # Handle any flag changes that happened while we were reading data
                    break  # type: ignore # This is reachable because 'done' is volatile.

                if not data:
                    continue

                print("serial rx:", data.strip())

                if "\n" in data:
                    # We got a complete line, massage the data, dispatch, and reset.
                    data = data.strip()
                    # TODO: Add a special join-me action handling here
                    results.append(asyncio.run_coroutine_threadsafe(client.play_iface("serial-user", None, [data]), loop))
                    data = ""

                if len(results) > 5:
                    for result in results[:5]:
                        result.cancel()
                    results = results[:5]

    except KeyboardInterrupt:
        pass
    finally:
        for result in results:
            result.cancel()

if __name__ == "__main__":
    client = discordbot.create()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    thread = threading.Thread(target=main_serial, args=[client, loop])

    orig_hook = client.setup_hook
    async def setup_hook() -> None:
        await orig_hook()
        thread.start()
    client.setup_hook = setup_hook  # type: ignore # mypy cant handle this

    try:
        discordbot.main(client, loop)
    finally:
        done = True
        thread.join()
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

