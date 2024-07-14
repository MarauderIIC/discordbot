#!/usr/bin/env python3

import asyncio
import configparser
import logging
import discord
import os
import pprint
import random
import shutil
import sys
import traceback
import time

from pathlib import Path
from typing import Any, cast, Coroutine, List, Dict, Optional, Callable, Union

import psutil


class TooManyMatches(KeyError):
    def __init__(self, matches: List[str]) -> None:
        self.matches = matches
        super().__init__()

class LoggedInError(Exception):
    """ Not logged in """

_log = logging.getLogger()

TypeUserAnywhere = Union[discord.Member, discord.User]

TypeHandlerWithArgs = Callable[
    [TypeUserAnywhere, discord.TextChannel, List[str]], Coroutine[Any, Any, None]
]


class MarBot(discord.Client):
    # The magic string used to disable a command in the configuration file.
    CMD_DISABLED = "DISABLED"

    def __init__(
        self, config: Path = Path("config.ini"), **kwargs: discord.Intents
    ) -> None:
        """
        Create a new bot instance.

        :param config: The path to the configuration file.
        """
        super().__init__(**kwargs)

        self.config = config
        self.voice_client: Optional[discord.VoiceClient] = None
        self.token = ""
        # Map the actual command names to handlers
        self.HANDLERS: Dict[str, TypeHandlerWithArgs] = {
            "d20": self.handle_d20,
            "play": self.handle_play,
            "playlist": self.handle_playlist,
            "stop": self.handle_stop,
            "reconfig": self.handle_reload_config,
            "join-me": self.handle_join_user,
            "leave-voice": self.handle_leave_voice,
            "restart": self.handle_restart,
            "add": self.handle_add,
            "help": self.handle_help,
            "maintenance": self.handle_maintenance,
            "set-spam-timer": self.handle_set_spam_timer,
            "dump-spam-status": self.handle_dump_spam_status,
            "show-admins": self.handle_show_admins,
        }
        # Map the command aliases to handlers
        self.commands: Dict[
            str, TypeHandlerWithArgs
        ] = {}
        # Map the command names to help strings
        self.helps: Dict[str, str] = {}
        # Map the privileged command names in the .ini file's keys to handlers
        self.priv_commands = self.HANDLERS.copy()
        # Map user names to the next time that they can execute a command
        self.spam_protect: Dict[TypeUserAnywhere, float] = {}
        # Map user names to the amount of time to add to their spam timer
        self.spam_timers: Dict[TypeUserAnywhere, float] = {}
        # When a user is spam blocked, don't notify them that they can execute commands again more often than this
        self.SPAM_NOTIFICATION_THRESHOLD = 30
        # Only administrators can execute commands
        self.in_maintenance_mode = False
        # List of administrator user names
        self.admins: List[str] = []

        self.reload_config(load_token=True)

        print("Initialized")

    def reload_config(
        self, config: Optional[str] = None, load_token: bool = False
    ) -> None:
        """
        Reload the configuration file.

        :param config: The name of the configuration file; use previously-loaded config if None.
        :param load_token: If True, load the token from the config. Usually False when reloading while running.
        """
        _config: str = config or str(self.config)

        parser = configparser.ConfigParser()
        parser.read(_config)

        try:
            new_files = dict(parser["files"])
            new_commands = dict(parser["commands"])
            new_helps = dict(parser["helps"])
            new_priv_commands = dict(parser["priv_commands"])
            new_path = Path(parser["config"]["path"])
            new_add_path = new_path / "to_add"
            new_prefix = parser["config"]["prefix"]
            new_token = parser["config"]["token"]
            new_admins = parser["admins"]["admins"]
        except KeyError as exc:
            raise KeyError(
                f"Missing ini configuration section or configuration key '{exc.args[0]}'"
            )

        for key in new_commands:
            if key in new_priv_commands:
                raise KeyError(
                    f"Command key {key} is present in both commands and priv_commands"
                )

        for key in self.HANDLERS.keys():
            if key not in new_commands.keys() and key not in new_priv_commands.keys():
                raise KeyError(
                    f"Missing expected command key '{key}'. "
                    f"If you meant to disable it, use '{key} = {MarBot.CMD_DISABLED}'"
                )

        for key in list(new_commands.keys()) + list(new_priv_commands.keys()):
            if key not in self.HANDLERS.keys():
                raise KeyError(
                    f"Unexpected command key '{key}'. Remove it or check its spelling."
                )

        self.prefix, self.files, self.sound_directory, self.helps, self.add_path = (
            new_prefix,
            new_files,
            new_path,
            new_helps,
            new_add_path,
        )
        self.admins = new_admins.split(",")
        print(f"Admins: {', '.join(self.admins)}")
        print("Files:", self.files)
        if load_token:
            with open(new_token, "r") as f:
                self.token = f.read().strip()
            print(f"New token from {new_token}")

        self.priv_commands = {}
        self.commands = {}

        def manage_command(
            new_config: Dict[str, str],
            cmd_dest: Dict[str, TypeHandlerWithArgs],
            cmd_name: str,
            cmd_handler: TypeHandlerWithArgs,
        ) -> None:
            """
            Check the incoming command and add it to the destination command dictionary as appropriate.
            Commands can have aliases by adding commas.

            :param new_config: The incoming configuration dictionary
            :param cmd_dest: The destination dictionary to add the command/handler to, if it's not disabled.
            :param cmd_name: The internal name of the command to manage.
            :param cmd_handler: The handler to associate with the internal name of the command.
            """
            if new_config[cmd] == MarBot.CMD_DISABLED:
                print(f"Disabled command {cmd}")
                return
            for alias in new_config[cmd].split(","):
                cmd_dest[alias.strip()] = handler

        for cmd, handler in self.HANDLERS.items():
            # Give precedence to privileged commands
            if cmd in new_priv_commands:
                manage_command(new_priv_commands, self.priv_commands, cmd, handler)
            elif cmd in new_commands:
                manage_command(new_commands, self.commands, cmd, handler)

        if self.handle_restart not in list(self.priv_commands.values()) + list(
            self.commands.values()
        ):
            print("Re-adding restart command to privileged commands to avoid lockout")
            self.priv_commands["restart"] = self.handle_restart

        print("Privileged command mapping")
        pprint.pprint(
            {key: value.__name__ for key, value in self.priv_commands.items()}
        )
        print("Command mapping")
        pprint.pprint({key: value.__name__ for key, value in self.commands.items()})

        print(f"Loaded {_config}")

    def run(self, *args: Any, **kwargs: Any) -> None:
        """
        Start the bot with the token loaded from the configuration file.
        """
        super().run(self.token, *args, **kwargs)

    def are_equivalent_commands(self, candidates: List[str]) -> bool:
        if not candidates:
            return False
        return all(
            self.commands.get(x) == self.commands.get(candidates[0]) for x in candidates
        )

    def get_all_aliases_for(self, command: str) -> List[str]:
        if not command:
            return []

        candidates = [
            x
            for x in self.commands
            if self.commands.get(x) == self.commands.get(command)
        ]
        return candidates

    async def handle_reload_config(
        self, user: TypeUserAnywhere, channel: discord.TextChannel, unused_args: List[str]
    ) -> None:
        """
        Reload the configuration via a chat command.

        :param user: The user that sent the command.
        :param channel: The channel to respond to (usually the one it was sent on).
        :param unused_args: Unused.
        """
        try:
            self.reload_config()
        except:
            traceback.print_exc()
            await channel.send("Unable to reload config")
        else:
            await channel.send(f"{user.mention}, config reloaded")

    async def handle_d20(
        self, user: TypeUserAnywhere, channel: discord.TextChannel, unused_args: List[str]
    ) -> None:
        """
        Roll a d20 and send the result to the chat.

        :param user: The user that sent the command.
        :param channel: The channel to respond to (usually the one it was sent on).
        :param unused_args: Unused.
        """
        msg = f"{user.mention} rolled a d20 and got {random.randint(1, 20)}"
        await channel.send(msg)

    async def handle_dump_spam_status(
        self, user: TypeUserAnywhere, channel: discord.TextChannel, args: List[str]
    ) -> None:
        printable = pprint.pformat(
            {str(k): str(v) for k, v in self.spam_protect.items()}
        )
        await channel.send(
            f"Current time: {int(time.time())} Current spam protection status:\n{printable}"
        )

    async def handle_help(
        self,
        user: TypeUserAnywhere,
        channel: discord.TextChannel,
        args: List[str],
    ) -> None:
        """
        Send help to the chat.

        :param user: The user that sent the command.
        :param channel: The channel to respond to (usually the one it was sent on).
        :param args: Command to get help for, or empty list.
        """

        # Get first arg, if there is one
        keyword = next(iter(args), None)

        if not keyword:
            msg = f"All commands must be prefixed with {self.prefix}.\nCommands: {', '.join(self.prefix + cmd for cmd in self.commands)}.\n"
            msg += f"Admin commands: {', '.join(self.prefix + cmd for cmd in self.priv_commands)}"
            if self.helps.get("help"):
                msg += "\n" + self.helps["help"].format(
                    cmd=f"{self.prefix}help"
                )  # only add a new line if help command help is present
            await channel.send(msg)
            return

        if keyword not in self.commands:
            await channel.send(f"No such user command {keyword}")
            return

        aliases = self.get_all_aliases_for(keyword)
        for alias in aliases:
            if alias in self.helps:
                await channel.send(
                    self.helps[alias].format(
                        cmd=", ".join(
                            [
                                self.prefix + alias
                                for alias in self.get_all_aliases_for(keyword)
                            ]
                        )
                    )
                )
                return

        await channel.send(f"No help for {keyword}")

    async def handle_join_user(
        self, user: TypeUserAnywhere, channel: discord.TextChannel, unused_args: List[str]
    ) -> bool:
        """
        Join the sender's voice channel.

        :param user: The user that sent the command.
        :param channel: The channel to respond to (usually the one it was sent on).
        :param unused_args: Unused.
        """
        if not isinstance(user, discord.Member):
            await channel.send(f"{user.mention}, you must be in a server")
            return False
        
        if not user.voice or not user.voice.channel:
            await channel.send(f"{user.mention}, you must be in a voice channel")
            return False

        for member in self.get_all_members():
            permissions = user.voice.channel.permissions_for(member)
            print(
                f"{member} - Join request for {user.voice.channel} - Connect: {permissions.connect} - Speak: {permissions.speak}"
            )
            if permissions.connect and permissions.speak:
                break
        else:
            await channel.send(
                f"{user.mention}, I am missing connect or speak permission for your channel"
            )
            return False

        if not self.voice_client:
            self.voice_client = cast(discord.VoiceClient, await user.voice.channel.connect())

        await self.voice_client.move_to(user.voice.channel)

        timeout = time.time() + 10
        while self.voice_client.channel != user.voice.channel or not self.voice_client.is_connected():
            time.sleep(0.1)
            if time.time() >= timeout:
                print("Timed out")
                return False
        print("Connected")
        return True

    async def handle_leave_voice(
        self, user: TypeUserAnywhere, channel: discord.TextChannel, unused_args: List[str]
    ) -> None:
        """
        Leave the current voice channel.

        :param user: The user that sent the command.
        :param channel: The channel to respond to (usually the one it was sent on).
        :param unused_args: Unused.
        """

        if not self.voice_client:
            await channel.send(f"{user.mention}, I'm not connected to voice")
            # Try anyway

        try:
            await self.voice_client.disconnect()    # type: ignore # eafp
        except AttributeError:
            print("Tried to disconnect, but no client to use")
            traceback.print_exc()
            return
        except discord.errors.ClientException:
            await channel.send(f"{user.mention}, I'm not in a voice channel")
            print("...but I thought I was!")
            traceback.print_exc()
            return

    async def handle_maintenance(
        self, user: TypeUserAnywhere, channel: discord.TextChannel, args: List[str]
    ) -> None:
        """
        Enable or disable "only admins can issue commands" mode.
        """
        if not len(args):
            await channel.send(f"Maintenance mode: {self.in_maintenance_mode}")
        elif args[0].lower() in ("on", "true", "1"):
            self.in_maintenance_mode = True
            await channel.send("Maintenance mode on")
        elif args[0].lower() in ("off", "false", "0"):
            self.in_maintenance_mode = False
            await channel.send("Maintenance mode off")

    async def optional_send(self, channel: Optional[Union[discord.TextChannel, discord.DMChannel]], msg: str) -> None:
        """
        Send message 
        """
        if channel is None:
            print(msg)
        else:
            await channel.send(msg)

    async def handle_play(
        self, user: TypeUserAnywhere, channel: discord.TextChannel, args: List[str]
    ) -> None:
        """
        Play audio to the current voice channel.

        :param user: The user that sent the command.
        :param channel: The channel to respond to (usually the one it was sent on).
        :param args: The first entry is the pre-configured key for the sound effect
            to send to voice. Excess arguments result in an error.
        """
        await self.play_iface(user, channel, args)

    async def play_iface(self, user: TypeUserAnywhere, channel: Optional[discord.TextChannel], args: List[str]) -> None:

        if not self.voice_client:
            print("No voice client")
            if channel:
                # Try to join the user automatically
                if not await self.handle_join_user(user, channel, []) or not self.voice_client:
                    await self.optional_send(channel,
                        f"{user.mention} I'm not in a voice channel (try !leave-voice and !join-me?)"
                    )
                    return
            else:
                await self.optional_send(channel,
                    f"{user.mention} I'm not in a voice channel (try !leave-voice and !join-me?)"
                )
                return

        if len(args) > 1:
            await self.optional_send(channel,
                f"{user.mention} I'm only expecting a single word to follow that command."
            )
            return

        # Get first arg, if there is one
        keyword = next(iter(args), None)

        if not keyword:
            await self.optional_send(channel, f"{user.mention} Did you specify something to play?")
            return

        try:
            play_file = self.sound_directory / self.files[keyword]
        except KeyError:
            await self.optional_send(channel, f"{user.mention} No file for {keyword}")
            return

        print(f"Play '{keyword}' ==> {play_file}")
        play_me = discord.FFmpegPCMAudio(play_file.resolve().as_posix())

        if self.voice_client.is_playing():
            return

        try:
            # Compare current channel to requestor's channel?
            self.voice_client.play(play_me)
        except discord.errors.ClientException:
            await self.optional_send(channel, f"{user.mention} I'm not in a voice channel")
            print("...but I thought I was!")
            self.voice_client = None

    async def handle_playlist(
        self, user: TypeUserAnywhere, channel: discord.TextChannel, unused_args: List[str]
    ) -> None:
        """
        Send the configured sound keys to the channel, as well as the files they correspond to.

        :param user: The user that sent the command.
        :param channel: The channel to respond to (usually the one it was sent on).
        :param unused_args: Unused.
        """
        play_cmd = ""
        play_cmds = self.get_all_aliases_for("play")
        try:
            play_cmd = play_cmds[0]
        except IndexError:
            await channel.send(f"{user.mention}: The play command is not available")
            return

        await channel.send(
            f"{user.mention} Here are the files for {self.prefix}{play_cmd}:"
        )
        printable = pprint.pformat(self.files)

        printable = printable.replace(".mp3", "")
        printable = printable.replace("\n '", "\n")  # 'key': 'value', -> key': 'value',
        printable = printable.replace("': ", ": ")  # key': 'value' -> key: 'value',
        printable = printable.replace(": '", ": ")  # key: 'value' -> key: value',
        printable = printable.replace("',", ",")  # key: value', -> key: value,
        printable = printable.replace(
            '"', ""
        )  # Values with apostrophes in them wind up quoted - remove those too
        printable = printable.replace("{'", "")
        printable = printable.replace('{"', "")
        printable = printable.replace("'}", "")
        printable = printable.replace('"}', "")

        if len(printable) > 2000:
            sendable = ""
            for line in printable.splitlines():
                if len(sendable + line) > 2000:
                    await channel.send(f"{sendable}")
                    sendable = ""
                sendable += line + "\n"
            await channel.send(sendable)
            return

        try:
            await channel.send(f"{printable}")
        except discord.errors.HTTPException:
            print("Unable to send the following message of length:", len(printable))
            print(printable)
            raise

    async def handle_restart(
        self,
        unused_user: TypeUserAnywhere,
        unused_channel: discord.TextChannel,
        unused_args: List[str],
    ) -> None:
        """
        Restart this python process entirely.

        :param user: The user that sent the command.
        :param channel: The channel to respond to (usually the one it was sent on).
        :param unused_args: Unused.
        """
        print(f"Restarting- {sys.executable}")
        print(f"Args: {sys.argv} -- {os.path.abspath(__file__)}")
        await self.close()
        print("Self closed OK")
        self.do_restart()

    def do_restart(self) -> None:
        p = psutil.Process(os.getpid())
        # Don't leave dangling file handles
        for handler in p.open_files() + p.connections():
            try:
                if handler.fd not in [
                    -1,  # fds from psutil are always -1 on Windows
                    sys.stdout.fileno,
                    sys.stderr.fileno,
                    sys.stdin.fileno,
                ]:
                    print("Closing", handler.fd)
                    os.close(handler.fd)
            except:
                # Continue even if we can't close something.
                print("Error during handle restart:")
                traceback.print_exc()

        # Replace the current python process with an identical one, assuming
        # that argv is trustworthy.
        python = sys.executable
        os.execl(python, python, os.path.abspath(__file__))

    async def handle_set_spam_timer(
        self, user: TypeUserAnywhere, channel: discord.TextChannel, args: List[str]
    ) -> None:
        return

    async def handle_show_admins(
        self, user: TypeUserAnywhere, channel: discord.TextChannel, unused_args: List[str]
    ) -> None:
        """Dump the admin list"""
        await channel.send(f"{', '.join(self.admins)}")

    async def handle_stop(
        self, user: TypeUserAnywhere, channel: discord.TextChannel, unused_args: List[str]
    ) -> None:
        """
        Stop any currently-playing sounds.

        :param user: The user that sent the command.
        :param channel: The channel to respond to (usually the one it was sent on).
        :param unused_args: Unused.
        """
        if self.voice_client:
            self.voice_client.stop()

    async def handle_add(self, user: TypeUserAnywhere, channel: discord.TextChannel, args: List[str]) -> None:
        """
        Handle remotely adding a new sound to the soundboard.

        :param user: The user that sent the command.
        :param channel: The channel to respond to (usually the one it was sent on).
        :param args: The sound command to add.
        """

        # A lot of these messages are in-the-weeds; maybe I should DM the responses? It's awkward though because
        # the user can't respond in DM.
        
        if len(args) != 1:
            await self.optional_send(channel, f"{user.mention} Expected a single argument")
            return

        keyword = args[0]
        keyword_fname = keyword + ".txt"

        def is_in_add_path(fname):
            test_path = (self.add_path / fname).resolve()
            return test_path.parent == self.add_path.resolve()
        
        if not keyword.isalnum():
            await self.optional_send(channel, f"{user.mention} The file named for the command must be alphanumeric only")
            return
        
        if not is_in_add_path(keyword_fname):
            await self.optional_send(channel, f"{user.mention} file to add must be in the add subdir")
            return
        
        # Make sure the sound name isn't in use already.
        if keyword in self.files:
            await self.optional_send(channel, f"{user.mention} the keyword {keyword} is already taken")
            return
        
        # Search the to_add subfolder for the mp3 to add and its accompanying text file that says what playlist name to use for it.
        try:
            with open((self.add_path / keyword_fname).resolve(), "rt") as fh:
                mp3_fname = fh.readlines()[0].strip()
        except FileNotFoundError:
            await self.optional_send(channel, f"{user.mention} file to add must be in the add subdir")
            return

        if not is_in_add_path(mp3_fname):
            await self.optional_send(channel, f"{user.mention} sound to add must be in the add subdir")
            return
        
        self.files[keyword] = mp3_fname
        try:
            os.symlink((self.add_path / mp3_fname).resolve(), (self.sound_directory / mp3_fname).resolve())
        except FileExistsError:
            await self.optional_send(channel, f"{user.mention} that sound file already exists. I'm assigning {keyword} to it.")
        else:
            await self.optional_send(channel, f"{user.mention} sound added")

    def is_user_admin(self, user: Union[discord.User, discord.Member]) -> bool:
        """
        Determine if the given user can access privileged commands.

        :param user: The user to verify.
        :param channel: The channel to respond to (usually the one it was sent on).
        """
        if str(user) not in self.admins:
            return False
        return True

    @staticmethod
    def is_channel_authorized(channel: discord.abc.Messageable) -> bool:
        return "bot" in str(channel)

    def is_user_spam_blocked(self, user: TypeUserAnywhere) -> bool:
        try:
            # The user executed commands too fast. Increase the time until they can try again.
            if self.spam_protect[user] > time.time():
                self.spam_timers[user] = 1 + self.spam_timers[user] * 2
                self.spam_protect[user] += self.spam_timers[user]
                return True
            if self.spam_protect[user] == -1:
                return True
        except KeyError:
            pass

        # The user is no longer under spam block or was never spam blocked.
        # Set the time until that user can execute another command to the default.
        # An improvement would be "x commands over y time" instead of "1 command per y time"
        to_add = 3
        self.spam_protect[user] = time.time() + to_add
        self.spam_timers[user] = to_add
        return False

    async def on_ready(self) -> None:
        """
        Notify when the bot is logged into discord.
        """
        if self.user is None:
            raise LoggedInError("Not logged in, but discord is reporting ready")
        
        print("Logged in as %s %s" % (self.user.name, self.user.id))

    async def on_message(self, message: discord.Message) -> None:
        """
        Manage a chat message.

        :param message: The incoming text channel message.
        """

        if message.author == self.user:
            return

        channel = message.channel
        author = message.author
        content = message.content
        command = None

        if not isinstance(channel, discord.TextChannel):
            await author.send(f"{author.mention}, I can't receive commands in {channel} because it's not a text channel")
            return

        if content.startswith(self.prefix):
            command = content[len(self.prefix) :]

        if not command:
            return

        # Avoid log spam by only getting the first line
        command = command.lower().splitlines()[0]
        # Avoid log spam by only getting the first hundred characters
        command = command[:100]

        unsplit_command = command
        args = command.split()[1:]
        command = command.split()[0]
        log_content = "\\n".join(content.splitlines())

        print(f"{author}@{channel}: {log_content} ==> {command}")

        if not self.is_channel_authorized(channel):
            await author.send(
                f"{author.mention} I can't receive commands in channel {channel}"
            )
            return

        try:
            if command in self.priv_commands:
                if self.is_user_admin(author):
                    function = self.priv_commands[command]
                    # Do the function now to prevent accidental lockout.
                    print("\tPrivileged command, running immediately")
                    await function(author, channel, args)
                    return
                else:
                    raise PermissionError("No permission")
            else:
                # If we can't get an exact match, try space-less matching instead, to support commands like "!!<sound name>"
                print("Trying startswith for", command)
                try:
                    function = self.commands[command]
                except KeyError as exc:
                    candidates = []
                    for candidate in self.commands:
                        #print(candidate, "vs", unsplit_command)
                        if unsplit_command.startswith(candidate):
                            candidates.append(candidate)

                    if len(candidates) > 1:
                        if not self.are_equivalent_commands(candidates):
                            raise TooManyMatches(candidates) from exc
                    elif len(candidates) == 0:
                        raise KeyError("No candidates") from exc
                    candidate = candidates[0]

                    print(
                        f"Splitting {unsplit_command} at {candidate}: {unsplit_command.split(candidate)}"
                    )
                    args = unsplit_command.split(candidate)[1:]
                    command = candidate
                    print(f"{command}: {args}")
                    function = self.commands[command]

        except TooManyMatches as exc:
            await channel.send(
                f"{author.mention}, which of {' '.join(exc.matches)} do you mean?"
            )
            return
        except (KeyError, PermissionError):
            await channel.send(f"{author.mention}, no such command '{command}'")
            return

        print("\tGot", function.__name__)
        if self.is_user_admin(author):
            # Use maintenance mode to simulate regular user permissions
            if not self.in_maintenance_mode:
                print("\tAllow: user is admin")
                await function(author, channel, args)
                return
        if not self.is_user_admin(author) and self.in_maintenance_mode:
            print("\tDisallow: In maintenance mode and user is not admin")
            return
        if self.is_user_spam_blocked(author):
            print("\tDisallow: User is spam blocked")
            print(f"{author} is spam blocked")
            if self.spam_timers[author] <= self.SPAM_NOTIFICATION_THRESHOLD:
                await author.send(
                    f"Spam protection - I can't respond to your messages for approximately {int(self.spam_protect[author] - time.time())} seconds"
                )
            return
        print("\tAllow: Default reason")
        await function(author, channel, args)

def create() -> MarBot:
    """
    Create a basic MarBot and set up the discord logging.
    """

    # Since we can't use run and await self.close() successfully, we have to set up logging ourselves.
    discord.utils.setup_logging(
        handler=discord.utils.MISSING,
        formatter=discord.utils.MISSING,
        level=discord.utils.MISSING,
        root=False,
    )

    intents = discord.Intents.default()
    intents.message_content = True
    client = MarBot(intents=intents)
    # client.run()
    return client

def main(client: Optional[MarBot] = None, loop = None) -> None:

    if client is None:
        client = create()

    async def main_task() -> None:
        await client.start(client.token)

    debug = False
    loop_owner = False
    # Work around `await self.close()` crashing somewhere without giving a traceback.
    if loop is None:
        loop_owner = True
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop = asyncio.get_event_loop()
    futures = [asyncio.ensure_future(main_task())]
    try:
        loop.run_until_complete(asyncio.gather(*futures, return_exceptions=debug))
        print("Try done")
    except:
        future_logout = [asyncio.ensure_future(client.close())]
        loop.run_until_complete(asyncio.gather(*future_logout, return_exceptions=debug))
        print("Closing")
    finally:
        if loop_owner:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
    print("Done")


if __name__ == "__main__":
    main()
