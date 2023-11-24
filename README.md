# discordbot
A discord bot providing soundboard functionality with customizable commands, designed to run on the same machine that the soundboard files are hosted on.

I use it personally but maybe you'll get some use out of it.

This is written in the Python 3 programming language, which you can download from [here](https://python.org). Download and install the newest version of Python 3; this was tested on Python 3.12.0. Check the box to add python to your `PATH`. If it asks to add `py` to your path, set that too.

I use this on Windows, but it'll probably work on Linux with little-to-no changes. It uses the Python discord library (documentation is [here](https://discordpy.readthedocs.io/), but you don't need to read it to use this bot). It has a few awkward parts since it was started in 2017 with an earlier discordpy version. To get the necessary libraries to run the bot:

On Windows, you have to do some stuff on the command line:
* Download all the files from this GitHub repository to their own folder (i.e. make a new folder called `DiscordBot` somewhere)
* Use your Windows Start menu -> Run (App) -> `cmd.exe`. This will start a command prompt window.
* `<the drive letter that you downloaded these files to>:` (e.g. `d:`)
* `cd "<the folder that you downloaded these files to>"` (e.g. `cd "Users\John Doe\Downloads\DiscordBot"`)
* `py -3 -m venv venv`
* `venv\Scripts\python.exe -m pip install -r requirements.txt`

On Linux:
* Download all the files from this github repository to their own folder (i.e. make a new folder called `DiscordBot` somewhere)
* Open a terminal window
* `cd <the folder that you downloaded these files to>` (e.g. `cd ~/Downloads/DiscordBot`)
* `python3 -m venv venv`
* `venv/bin/python -m pip install -r requirements.txt`

All platforms:
* Update `config.ini`
* Run the bot:
  * Windows: `venv\Scripts\python.exe -m discordbot`
  * Linux: `venv/bin/python -m discordbot`

Unlike cloud-hosted bots, you need your _own_ discord bot account, and the bot is only designed to connect to a single server at a time, but maybe it'll work on multiple servers, I dunno. See [discordpy's instructions](https://discordpy.readthedocs.io/en/stable/discord.html#discord-intro) for more on this. Hey, free software gonna free, but it's easy!

Invite the bot to your server following discordpy's instructions.

To get started, move `config.ini.template` to `config.ini`. Update the `admins` and `token` lines at a minimum. `admins` should be set to your discord username. `token` should be set to your bot token from the `TOKEN` subheading under discord's `Build-A-Bot` header.

## limitations

The bot only accepts commands in channels that have "bot" somewhere in the channel name, because I haven't made that configurable yet.

## configuring the bot

Copy `config.ini.template` to `config.ini` in the same folder as `discordbot.py`.

The `config.ini` has a few headings and is read like a ini file (specifically it uses Python's ConfigParser built-in library):
* `[config]`: The global bot configuration.
  * `path` is the path that the bot looks for soundboard files in.
  * `prefix` is the prefix for all of the bot's commands.
  * `token` is the path to a text file containing the bot's login token.
* `[admins]`: The administrator configuration. Contains a single line:
  * `admins = comma,separated,administrator,usernames`
  * Administrators have access to some privileged bot commands.
* `[files]`: Every line is of the form `play_argument = soundboard_file`. This is the fun part.
* `[commands]`: Associates the bot's commands with the actual commands that you want users to use for them. Any user can run the commands. Valid bot commands are:
  * `d20`: Rolls a 20-sided die using pseudo-randomness.
  * `play <argument>`: Play the sound file that's associated with the given `play_argument` from the `files` header.
  * `playlist`: Print the `files` to the channel.
  * `show-admins`: Prints all the `admins` usernames.
  * `stop`: Stops playing the current sound.
  * `join-me`: Brings the bot user into the same voice channel as the person that issued the command.
  * `leave-voice`: Disconnect from the current voice channel
  * `help`: Print all the helps.

So, if you want users to have to type `!roll` instead of `!d20` to get a random number between 1 and 20 inclusive, put `d20 = roll` under the `[commands]` header. If you want users to have to type `?roll` instead, set `prefix = ?` in the `[config]` header, and set `d20 = roll` in the `[commands]` header.

* `[priv_commands]`: Commands that only admins can issue.
  * `reconfig`: Reload the config.ini file. This is helpful for adding new soundboard files.
  * `restart`: Kill the bot and restart it. This is helpful if you have updated the bot's code.
  * `maintenance`: Toggle whether or not only administrators can issue commands.
  * `set-spam-timer`: I think that this sets the minimum time between user commands, but I don't really remember.
  * `dump-spam-timers`: Output how much time is left until each user can issue a command.
* `[helps]`: Associates the bot's commands with the help text to output for them. Helpful for localizations, I guess, but I have no idea if it works right with non-ASCII.

## using the bot

By default I have `play` set to `!play`, `!p`, and `!!` in the `[commands]` heading. So to play the `c:/path/to/soundboard/files/directory/mlg-airhorn.mp3` file:

### one-time setup
* Create an mp3 file containing the sound effect, either by recording yourself with your microphone or finding a sound effect on youtube and using a youtube-to-mp3 converter.
* Create a bot account using the linked instructions above.
* Create a text file containing your bot's token, like `discordtoken.txt`. Use something like `notepad.exe` for this (`nano` on Linux).
* Copy `config.ini.template` to `config.ini`
* Using notepad, edit `config.ini` so that `token =` has the path to `discordtoken.txt`
* Invite your bot account to your server using the linked instructions above.
* Create a text channel on your server that contains the word `bot`, like `#bot-spam`. You probably want to configure this channel to never send notifications.

### every time you close the bot
* Start the discordbot.py file using the instructions above. The bot should show up on your server. The command prompt window will stay open while the bot is running - you can minimize it though.

### every time you want to hear a sound and the bot isn't in a voice channel yet
* Join a voice channel as yourself
* In `#bot-spam`, issue `!join-me`. The bot should join your voice channel.

### every time you want to hear a sound
* In `#bot-spam`, issue `!!air` because `!!` is set to the `play` command and `air` is the argument associated with `mlg-airhorn.mp3`. You should hear the mlg-airhorn sound effect -- if that's what you put in mlg-airhorn.mp3 anyway :)

### to close the bot
* In the `cmd.exe` window (or, on Linux, the terminal) that is running the bot (you should see a bunch of output), hold `CTRL` on your keyboard and press `c`. To close the command prompt, type `exit` and press enter.