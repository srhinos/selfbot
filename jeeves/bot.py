import asyncio
import collections
import inspect
import json
import logging
import random
import re
import shlex
import sys
import textwrap
import traceback
import zlib
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from random import randint

import aiohttp
import discord
from discord.http import HTTPClient, Route

import coloredlogs
import verboselogs
from TwitterAPI import TwitterAPI

from .constants import prefix
from .exceptions import CommandError
from .googl import shorten_url
from .utils import (MemberConverter, UserConverter, _get_variable,
                    clean_bad_pings, clean_string, cleanup_blocks,
                    cleanup_code, datetime_to_utc_ts, doc_string, load_json,
                    snowflake_time, strfdelta, timestamp_to_seconds,
                    write_json)

verboselogs.install()

### Code from this line till my next comment line is literal warcrimes, someone stop me pls
# To explain, I want colored logs. Colored logs use a handler. I also want clean non repeating logs. That uses a handler too.
# These handlers conflict. I decided to monkey patch the monkey patch so I can isolate all the bullshit just here.


def monkey_init(self, level=logging.NOTSET):
    logging.Handler.__init__(self, level)
    self.last_record = ""
    self.last_message = ""
    self.count = 1
    self.regex = re.compile(r"(.*[0-9][0-9]:[0-9][0-9]:[0-9][0-9] )(.*)")
    self.ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def monkey_emit(self, record):
    try:
        msg = self.format(record)
        match = self.regex.match(self.ansi_escape.sub("", msg))
        content = match.group(2)
        stream = self.stream
        if content == self.last_record and "\n" not in msg:
            self.count += 1
            msg = f"{msg} x {self.count}"
            stream.write(f"\r{msg}")
            self.last_message = msg
        else:
            self.last_record = content
            if self.count > 1 or "\n" not in self.last_message:
                stream.write(f"\n{msg}")
                self.last_message = msg
            else:
                stream.write(f"{msg}")
                self.last_message = msg
            self.count = 1
        self.flush()
    except RecursionError:
        raise
    except Exception:
        self.handleError(record)


coloredlogs.StandardErrorHandler.__init__ = monkey_init
coloredlogs.StandardErrorHandler.emit = monkey_emit
coloredlogs.StandardErrorHandler.terminator = ""

rootLogger = logging.getLogger(__name__)
rootLogger.setLevel(logging.DEBUG)

# logger = logging.getLogger('discord')
# logger.setLevel(logging.INFO)
# handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
# handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
# logger.addHandler(handler)

coloredlogs.install(
    fmt="[%(levelname)8s] %(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    field_styles={
        "asctime": {"color": "magenta", "bright": True},
        "hostname": {"color": "magenta"},
        "levelname": {"color": "black", "bold": True},
        "name": {"color": "blue"},
        "programname": {"color": "cyan"},
    },
    level="DEBUG",
    logger=rootLogger,
)


def format_console(msg):

    this = list(msg.split())
    new_this = [this[0]]
    for elem in this[1:]:
        if len(new_this[-1]) + len(elem) < 100:
            new_this[-1] = new_this[-1] + " " + elem
        else:
            new_this.append(elem)
    return "%s" % "\n\t\t     ".join(new_this)


class Response:
    def __init__(self, content, reply=False, delete_after=0, send_message=False):
        self.content = content
        self.send_message = send_message
        self.reply = reply
        self.delete_after = delete_after


class Jeeves(discord.Client):
    def __init__(self):
        super().__init__(fetch_offline_members=True)
        self.prefix = "!"
        self.avatars = [
            "http://i.imgur.com/5cREXtw.png",
            "http://i.imgur.com/Kz3Ndng.png",
            "http://i.imgur.com/86BR273.png",
            "http://i.imgur.com/hhRNuKJ.png",
        ]
        self.token = "ENTER YOUR TOKEN HERE"
        self.email = "ENTER EMAIL HERE"
        self.password = "ENTER PASSWORD HERE"
        self.bot_token = "ENTER A BOT TOKEN HERE IF WANTED"
        self.tags = load_json("tags.json")
        # self.shilllist = load_json('shilllist.json')
        # self.ignorelist = load_json('ignorelist.json')
        # self.shittext = load_file('16713.txt')

        self.reaction_list = []

        self.server_whitelist = load_json("server_whitelist.json")

        self.mention_dict = {}
        self.reset_period = 10  # in seconds
        self.max_mentions = 5
        self.action_on_detection = 2  # 0 = Delete Message
        # 1 = Delete Message+Kick
        # 2 = Delete Message+Mute (role created on the spot for mutes)
        # 3 = Delete Message+Ban

        self.run_bans = False

        self._last_result = None

        self.raw_bytes = 0
        self.last_timestamp = None

        self.session_id = None
        self.sequence = None
        self._zlib = zlib.decompressobj()
        self._buffer = bytearray()

        self.change_avi = False

        self.timed_events_debug = False

        self.bot_http = HTTPClient(
            None, proxy=None, proxy_auth=None, loop=asyncio.get_event_loop()
        )

        self.has_initiallized_bot = False

        self.sombra_percent = 7.4006
        self.sombra_time = None

        self.fm_bot_watcher = "180141263067021313"
        self.now_playing = None
        self.since_id = {"PlayOverwatch": 760694134902579204}
        self.twitAPI = TwitterAPI(
            "TWITTER CONSUMER KEY",
            "TWITTER CONSUMER SECRET",
            "TWITTER TOKEN KEY",
            "TWITTER TOKEN SECRET",
        )
        rootLogger.critical("init\n")

    # noinspection PyMethodOverriding
    def run(self):
        try:
            loop = asyncio.get_event_loop()
            # loop.create_task(self.banana())
            # loop.create_task(self.shitpost())
            # loop.create_task(self.sombra_check())
            loop.create_task(self.get_tweets())
            loop.run_until_complete(
                self.start(
                    self.token,
                    bot=False,
                )
            )
            loop.run_until_complete(self.connect())
        except Exception as e:
            rootLogger.debug(str(e) + "\n")
            traceback.print_exc()
            loop.run_until_complete(self.close())
        finally:
            loop.close()

    async def get_tweets(self):
        await self.wait_until_ready()
        # r = self.twitAPI.request('statuses/user_timeline', {'screen_name': 'PlayOverwatch',
        # 'exclude_replies': True,
        # 'count': 1})
        # for item in r.get_iterator():
        # print('setting ID')
        # self.since_id['PlayOverwatch'] = item['id']
        # while not self.is_closed:
        # try:
        # r = self.twitAPI.request('statuses/user_timeline', {'screen_name': 'PlayOverwatch',
        # 'exclude_replies': True,
        # 'count': 1})
        # for item in r.get_iterator():
        # if 'text' in item and item['id'] > self.since_id['PlayOverwatch']:
        # self.since_id['PlayOverwatch'] = item['id']
        # await self.send_message(discord.Object(id='94882524378968064'),
        # '***{}*** tweeted - \"*{}*\"\n***https://twitter.com/{}/status/{}***'.format(
        # item["user"]['name'], item['text'], item["user"]['screen_name'], item['id']
        # ))
        # await asyncio.sleep(6)
        # except:
        # print('error handled, fuck twitter API')

    # async def shitpost(self):
    # await self.wait_until_ready()
    # while not self.is_closed():
    # for item in self.shittext:
    # await asyncio.sleep(1.5)
    # await self.safe_send_message(discord.utils.get(self.get_all_channels(), id=290136694592765952), item)

    # async def banana(self):
    # await self.wait_until_ready()
    # while not self.is_closed():
    # if self.timed_events_debug: rootLogger.debug('at start\n')
    # initial = randint(1, 1799)
    # if self.timed_events_debug: rootLogger.debug('initial sleep of %s seconds' % initial)
    # await asyncio.sleep(initial)
    # stats_channel = discord.utils.get(self.get_all_channels(), id=154957001091186688)
    # #stats
    # if self.timed_events_debug: rootLogger.debug('starting stats\n')
    # msg1 = await self.safe_send_message(stats_channel, '!!stats')
    # await asyncio.sleep(5)
    # msg2 = await self.safe_send_message(stats_channel, 'xd')
    # await self.safe_delete_message(msg1)
    # await self.safe_delete_message(msg2)
    # if self.timed_events_debug: rootLogger.debug('cleared\n')

    # if self.timed_events_debug: rootLogger.debug('sleeping for %s seconds' % (1799-initial))
    # await asyncio.sleep(1799-initial)

    async def on_ready(self):
        if not self.has_initiallized_bot:
            rootLogger.success("Connected!\n")
            await self.bot_http.static_login(self.bot_token, bot=True)
            self.has_initiallized_bot = True
            rootLogger.success("~\n")

    async def _wait_delete_msg(self, message, after):
        await asyncio.sleep(after)
        await self.safe_delete_message(message)

    async def safe_send_message(
        self,
        dest,
        *,
        content=None,
        tts=False,
        embed=None,
        file=None,
        files=None,
        expire_in=None,
        nonce=None,
        quiet=None,
    ):
        msg = None
        try:
            msg = await dest.send(
                content=content, tts=tts, embed=embed, file=file, files=files
            )
            # if embed:
            # print(f'Embed send time: "{time_after - time_before}"')
            if msg and expire_in:
                asyncio.ensure_future(self._wait_delete_msg(msg, expire_in))

        except discord.Forbidden:
            if not quiet:
                print("Error: Cannot send message to %s, no permission" % dest.name)
        except discord.NotFound:
            if not quiet:
                print(
                    "Warning: Cannot send message to %s, invalid channel?" % dest.name
                )
        finally:
            if msg:
                return msg

    async def safe_delete_message(self, message, *, quiet=False):
        try:
            return await message.delete()

        except discord.Forbidden:
            if not quiet:
                print(
                    'Error: Cannot delete message "%s", no permission'
                    % message.clean_content
                )
        except discord.NotFound:
            if not quiet:
                print(
                    'Warning: Cannot delete message "%s", message not found'
                    % message.clean_content
                )

    async def safe_edit_message(
        self,
        message,
        *,
        new_content=None,
        expire_in=0,
        send_if_fail=False,
        quiet=False,
        embed=None,
    ):
        msg = None
        try:
            if not embed:
                await message.edit(content=new_content)
                msg = message
            else:
                await message.edit(content=new_content, embed=embed)
                msg = message

            if msg and expire_in:
                asyncio.ensure_future(self._wait_delete_msg(msg, expire_in))

        except discord.NotFound:
            if not quiet:
                print(
                    'Warning: Cannot edit message "%s", message not found'
                    % message.clean_content
                )
            if send_if_fail:
                if not quiet:
                    print("Sending instead")
                msg = await self.safe_send_message(message.channel, content=new)
        finally:
            if msg:
                return msg

    async def do_search(self, guild_id, **kwargs):
        search_args = {}
        search_args["author_id"] = kwargs.pop("author_id", None)
        search_args["mentions"] = kwargs.pop("mentions", None)
        search_args["has"] = kwargs.pop("has", None)
        search_args["max_id"] = kwargs.pop("max_id", None)
        search_args["min_id"] = kwargs.pop("min_id", None)
        search_args["channel_id"] = kwargs.pop("channel_id", None)
        search_args["content"] = kwargs.pop("content", None)
        string_query = ""
        for param, value in search_args.items():
            if value:
                string_query = (
                    string_query + f"&{param}={value}"
                    if string_query
                    else f"?{param}={value}"
                )
        return await self.http.request(
            Route("GET", f"/guilds/{guild_id}/messages/search{string_query}")
        )

    async def cmd_eval(
        self,
        author,
        guild,
        message,
        channel,
        mentions,
        eval_content,
        is_origin_tag=False,
    ):
        """
        Usage: {command_prefix}eval "evaluation string"
        runs a command thru the eval param for testing
        """
        env = {
            "self": self,
            "channel": channel,
            "author": author,
            "guild": guild,
            "message": message,
            "mentions": mentions,
            "_": self._last_result,
        }

        env.update(globals())

        code = cleanup_code(eval_content)
        stdout = StringIO()

        to_compile = f'async def func():\n{textwrap.indent(code, "  ")}'

        try:
            exec(to_compile, env)
        except Exception as e:
            traceback.print_exc()
            return Response(f"```py\n{e.__class__.__name__}: {e}\n```")

        func = env["func"]
        try:
            with redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            value = stdout.getvalue()
            await self.safe_send_message(
                channel, content=f"```py\n{value}{traceback.format_exc()}\n```"
            )
        else:
            value = stdout.getvalue()
            try:
                if is_origin_tag == False:
                    await message.add_reaction("\u2705")
            except:
                pass

            if ret is None:
                if value:
                    await self.safe_send_message(
                        channel, content=f"```py\n{value}\n```"
                    )
            else:
                self._last_result = ret
                await self.safe_send_message(
                    channel, content=f"```py\n{value}{ret}\n```"
                )

    # async def cmd_exec(self, author, guild, message, channel, mentions, code):
    # """
    # Usage: {command_prefix}eval "evaluation string"
    # runs a command thru the eval param for testing
    # """
    # return await self.cmd_eval(author, guild, message, channel, mentions, code)

    # async def cmd_runbans(self):
    # if self.run_bans:
    # self.run_bans = False
    # else:
    # self.run_bans = True

    async def cmd_downloademotes(self, server_id):
        """
        Usage: {command_prefix}forcebackup
        Forces a back up of all server configs
        """
        server_emotes = discord.utils.get(self.guilds, id=server_id).emojis
        for emote in server_emotes:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(emote.url) as r:
                    data = await r.read()
                    with open("emotes\%s.png" % emote.name, "wb") as f:
                        f.write(data)
        return Response(":thumbsup:", reply=True)

    async def cmd_forceban(self, guild, this_id):
        """
        Usage: {command_prefix}forcebackup
        Forces a back up of all server configs
        """
        await self.http.ban(
            this_id, guild.id, delete_message_days=0, reason="force ban"
        )
        return Response(":thumbsup:", reply=True)

    # async def cmd_whitelistserver(self, author, server_id):
    # """
    # Usage: {command_prefix}whitelistserver server_id
    # Adds a server's id to the whitelist!
    # """
    # if server_id not in self.server_whitelist:
    # self.server_whitelist.append(server_id)
    # write_json('server_whitelist.json', self.server_whitelist)
    # return Response(':thumbsup:', reply=True)

    # async def cmd_kek2(self, guild):
    # """
    # Usage: {command_prefix}forcebackup
    # Forces a back up of all server configs
    # """
    # for member in guild.members:
    # if not member.id == 80351110224678912:
    # list = []
    # list.append(discord.utils.get(guild.roles, id=298781003051302912))
    # await member.add_roles(*list, reason='didnt have everynone')
    # return Response(':thumbsup:', reply=True)

    # async def cmd_kek(self, guild):
    # """
    # Usage: {command_prefix}forcebackup
    # Forces a back up of all server configs
    # """
    # for member in guild.members:
    # if not member.id == 80351110224678912:
    # list = []
    # list.append(discord.utils.get(guild.roles, id=260520774388023297))
    # await member.add_roles(*list, reason='didnt have everynone')
    # return Response(':thumbsup:', reply=True)

    async def cmd_changename(self, author, string_name):
        """
        Usage: {command_prefix}changegame ["new game name"]
        Changes the "Now Playinfg..." game on Discord!
        """

        await self.user.edit(password=self.password, username=string_name)
        return Response(":thumbsup:", reply=True)

    # async def cmd_fw(self, message, leftover_args):
    # string = ' '.join(leftover_args)
    # roman_text = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!"#$%&()*+,-./:;<=>?@[]^_`{|}~'
    # fw_text = 'ï¼ï¼‘ï¼’ï¼“ï¼”ï¼•ï¼–ï¼—ï¼˜ï¼™ï½ï½‚ï½ƒï½„ï½…ï½†ï½‡ï½ˆï½‰ï½Šï½‹ï½Œï½ï½Žï½ï½ï½‘ï½’ï½“ï½”ï½•ï½–ï½—ï½˜ï½™ï½šï¼¡ï¼¢ï¼£ï¼¤ï¼¥ï¼¦ï¼§ï¼¨ï¼©ï¼ªï¼«ï¼¬ï¼­ï¼®ï¼¯ï¼°ï¼±ï¼²ï¼³ï¼´ï¼µï¼¶ï¼·ï¼¸ï¼¹ï¼ºï¼"ï¼ƒï¼„ï¼…ï¼†ï¼ˆï¼‰ï¼Šï¼‹ï¼Œï¼ï¼Žï¼ï¼šï¼›<ï¼>ï¼Ÿï¼ []^_`{|}~'
    # final = string.translate(str.maketrans(roman_text, fw_text))
    # return Response(final)

    async def cmd_outputlogs(self, channel, message, count):
        output = ""
        try:
            count = int(count)
        except ValueError:
            raise CommandError("Invalid message count found : {}".format(count))
        async for msg in channel.history(limit=count, before=message):
            output += "{}#{} ({}) - {}\n{}\n\n".format(
                msg.author.name,
                msg.author.discriminator,
                msg.author.id,
                msg.created_at.strftime("%H:%M:%S on %a %b %d"),
                msg.clean_content,
            )
        write_file(
            datetime.utcnow().strftime("%H_%M_%S_%a_%b_%d"),
            [output.encode("ascii", "ignore").decode("ascii")],
        )
        return Response(":thumbsup:", reply=True)

    async def cmd_steal(
        self, string_avi, emoji_name="stolen-emote", server_id=298778712709529603
    ):
        """
        Usage: {command_prefix}changegame ["new game name"]
        Changes the "Now Playing..." game on Discord!
        """

        server_to_up = discord.utils.get(self.guilds, id=server_id)
        async with aiohttp.ClientSession() as sess:
            async with sess.get(string_avi) as r:
                data = await r.read()
                await server_to_up.create_custom_emoji(name=emoji_name, image=data)
        return Response(":thumbsup:", reply=True)

    async def cmd_changeavi(self, author, string_avi):
        """
        Usage: {command_prefix}changegame ["new game name"]
        Changes the "Now Playing..." game on Discord!
        """
        async with aiohttp.ClientSession() as sess:
            async with sess.get(string_avi) as r:
                data = await r.read()
                await self.user.edit(password=self.password, avatar=data)
        return Response(":thumbsup:", reply=True)

    async def cmd_cls(self, message, channel):
        """
        Usage: {command_prefix}eval "evaluation string"
        runs a command thru the eval param for testing
        """
        async for msg in channel.history(500, before=message).filter(
            lambda m: m.author == self.user
        ):
            await asyncio.sleep(0.21)
            await self.safe_delete_message(msg)
        return Response(":thumbsup:", reply=True, delete_after=2)

    # async def cmd_toggleavi(self):
    # """
    # Usage: {command_prefix}eval "evaluation string"
    # runs a command thru the eval param for testing
    # """
    # self.change_avi ^= True
    # return Response(':thumbsup:', reply=True)

    # async def cmd_changegame(self, option, string_game):
    # """
    # Usage: {command_prefix}changegame ["new game name"]
    # Changes the "Now Playing..." game on Discord!
    # """
    # if option not in ['+', 'true', '-', 'false']:
    # return Response('ðŸ–• bad input you ass', reply=True)
    # if option in ['+', 'true']:
    # await self.change_status(game=discord.Game(name=string_game,
    # url='https://www.twitch.tv/s3xualrhinoceros',
    # type=1))
    # else:
    # await self.change_status(game=discord.Game(name=string_game))
    # return Response(':thumbsup:', reply=True)

    # async def cmd_promote(self, author, string_game):
    # """
    # Usage: {command_prefix}changegame ["new game name"]
    # Changes the "Now Playing..." game on Discord!
    # """
    # await self.change_status(game=discord.Game(name='CHECK THIS OUT',
    # url=string_game,
    # type=1))
    # return Response(':thumbsup:', reply=True)

    # async def cmd_addignore(self, message, mentions):
    # """
    # Usage: {command_prefix}changegame ["new game name"]
    # Changes the "Now Playing..." game on Discord!
    # """
    # for user in mentions:
    # self.ignorelist.append(user.id)
    # write_json('ignorelist.json', self.ignorelist)

    # async def cmd_deleteemotes(self, guild):
    # """
    # Usage: {command_prefix}changegame ["new game name"]
    # Changes the "Now Playing..." game on Discord!
    # """
    # for emote in guild.emojis:
    # emoji = await emote.delete()
    # return Response(':thumbsup:', reply=True)

    # async def cmd_moveemotes(self, guild):
    # """
    # Usage: {command_prefix}changegame ["new game name"]
    # Changes the "Now Playing..." game on Discord!
    # """
    # rootLogger.info('starting \n')
    # old_guild = discord.utils.get(self.guilds, id=159915737480298496)
    # for emote in old_guild.emojis:
    # try:
    # rootLogger.info('trying '+emote.name + '\n')
    # async with aiohttp.ClientSession() as sess:
    # async with sess.get(emote.url) as r:
    # data = await r.read()
    # await guild.create_custom_emoji(name=emote.name, image=data)
    # rootLogger.info('moving '+emote.name + '\n')
    # emoji = await emote.delete()
    # rootLogger.info('deleting '+emoji.name + '\n')
    # except:
    # pass
    # for x in range(50):
    # try:
    # async with aiohttp.ClientSession() as sess:
    # async with sess.get('https://cdn.discordapp.com/attachments/298778712709529603/298789783734321153/fckb1nzy_.png') as r:
    # data = await r.read()
    # await old_guild.create_custom_emoji(name='fuckb1nzy', image=data)
    # rootLogger.info(x + '\n')
    # except:
    # pass

    async def cmd_everynone(self, message, guild, leftover_args):
        """
        Usage: {command_prefix}changegame ["new game name"]
        Changes the "Now Playing..." game on Discord!
        """
        role = discord.utils.get(guild.roles, id=260520774388023297)
        if not role:
            role = discord.utils.get(guild.roles, id=298781003051302912)
        await role.edit(mentionable=True)
        return_string = "{} {}".format(role.mention, " ".join(leftover_args))
        await self.safe_send_message(message.channel, content=return_string)
        await self.safe_delete_message(message)
        await role.edit(mentionable=False)
        rootLogger.success("everynoned \n")

    async def cmd_everyone(self, message, guild, raw_leftover_args):
        """
        Usage: {command_prefix}changegame ["new game name"]
        Changes the "Now Playing..." game on Discord!
        """
        role = discord.utils.get(guild.roles, id=406756256309575680)
        await role.edit(mentionable=False)
        return_string = "@everyone {}".format(" ".join(raw_leftover_args))
        await self.safe_send_message(message.channel, content=return_string)
        await self.safe_delete_message(message)
        await role.edit(mentionable=True)
        rootLogger.success("everyoned \n")

    # async def cmd_testregex(self, content):
    # """
    # Usage: {command_prefix}changegame ["new game name"]
    # Changes the "Now Playing..." game on Discord!
    # """
    # import re
    # emoji_symbols_pictograms = re.compile(u'[\U0001f300-\U0001f5fF]')
    # emoji_emoticons = re.compile(u'[\U0001f600-\U0001f64F]')
    # emoji_transport_maps = re.compile(u'[\U0001f680-\U0001f6FF]')
    # emoji_symbols = re.compile(u'[\U00002600-\U000026FF]')
    # emoji_dingbats = re.compile(u'[\U00002700-\U000027BF]')
    # emoji_flags = re.compile(u'[\U0001F1E6-\U0001F1FF]')
    # emoji_numbers = re.compile(u'[\U00000023-\U00000039]\U000020E3|\U0001F51F')
    # emojis = re.findall(emoji_symbols_pictograms, content) + re.findall(emoji_emoticons, content) + re.findall(emoji_transport_maps, content) + re.findall(emoji_symbols, content) + re.findall(emoji_dingbats, content) + re.findall(emoji_flags, content) + re.findall(emoji_numbers, content)
    # if emojis:
    # return Response(emojis)
    # else:
    # rootLogger.critical('nope \n')

    async def cmd_changetracker(self, message, mentions):
        """
        Usage: {command_prefix}changegame ["new game name"]
        Changes the "Now Playing..." game on Discord!
        """
        if not mentions:
            return
        self.fm_bot_watcher = mentions[0].id
        if mentions[0].game:
            this = mentions[0].game.name.encode("ascii", "ignore").decode("ascii")
        write_file(
            "nowplaying.txt", ["{0}{1}{0}".format(" " * (len(this) + 200), this)]
        )

    async def cmd_userinfo(
        self, guild, channel, message, author, mentions, raw_leftover_args
    ):
        """
        Usage {command_prefix}userinfo [@mention OR User ID]
        Gathers info on a user and posts it in one easily consumable embed
        """
        converter = UserConverter()
        user = None

        if mentions:
            user = mentions[0]
            try:
                raw_leftover_args.remove(mentions[0].mention)
            except:
                raw_leftover_args.remove(f"<@!{mentions[0].id}>")

        else:
            temp = " " if len(list(raw_leftover_args)) > 1 else ""
            temp = temp.join(list(raw_leftover_args)).strip()
            print(f"'{temp}'")
            try:
                user = await converter.convert(message, self, temp)
            except:
                traceback.print_exc()
                pass

        if not user:
            user = author

        member = discord.utils.get(guild.members, id=user.id)

        if member:
            em = discord.Embed(colour=member.color)
            em.add_field(
                name="Full Name:",
                value=f"{user.name}#{user.discriminator}",
                inline=False,
            )
            em.add_field(name="ID:", value=f"{user.id}", inline=False)
            if not member.joined_at:
                em.add_field(
                    name="Joined On:", value="ERROR: Cannot fetch", inline=False
                )
            else:
                em.add_field(
                    name="Joined On:",
                    value="{} ({} ago)".format(
                        member.joined_at.strftime("%c"),
                        strfdelta(datetime.utcnow() - member.joined_at),
                    ),
                    inline=False,
                )
            em.add_field(
                name="Created On:",
                value="{} ({} ago)".format(
                    user.created_at.strftime("%c"),
                    strfdelta(datetime.utcnow() - user.created_at),
                ),
                inline=False,
            )
            member_search = await self.do_search(guild_id=guild.id, author_id=user.id)
            em.add_field(
                name="Messages in Server:",
                value="{}".format(member_search["total_results"]),
                inline=False,
            )
            em.add_field(
                name="Roles:",
                value="{}".format(
                    ", ".join([f"<@&{role.id}>" for role in member.roles])
                ),
                inline=False,
            )
            member_profile = await self.fetch_user_profile(member.id)
            em.add_field(
                name="Nitro Since:",
                value="{} ({} ago)".format(
                    member_profile.premium_since,
                    strfdelta(datetime.utcnow() - member_profile.premium_since),
                )
                if member_profile.premium
                else "-Not Subscribed-",
                inline=False,
            )
            if member_profile.hypesquad:
                em.add_field(
                    name="User In HypeSquad",
                    value="<:r6hype:420535089898848266> ",
                    inline=True,
                )
            if member_profile.partner:
                em.add_field(
                    name="User Is a Partner",
                    value="<:r6partner:420535152117284865>",
                    inline=True,
                )
            if member_profile.staff:
                em.add_field(
                    name="User Is Staff",
                    value="<:r6staff:420535209398763520>",
                    inline=True,
                )
            connection_txt = "\n".join(
                [
                    "{}{}: {}".format(
                        "{}".format(con["type"]).rjust(9),
                        "\u2705" if con["verified"] else "\U0001F6AB",
                        con["name"],
                    )
                    for con in member_profile.connected_accounts
                ]
            )
            if not connection_txt:
                connection_txt = "None"
            em.add_field(
                name="Connections:",
                value="```{}```".format(connection_txt),
                inline=False,
            )

            em.set_author(
                name=f"{'%s AKA %s' % (member.nick, user.name) if member.nick else user.name}",
                icon_url="https://i.imgur.com/FSGlsOR.png",
            )
        else:
            em = discord.Embed(colour=discord.Colour(0xFFFF00))
            em.add_field(name="Full Name:", value=f"{user.name}", inline=False)
            em.add_field(name="ID:", value=f"{user.id}", inline=False)
            em.add_field(
                name="Created On:",
                value="{} ({} ago)".format(
                    user.created_at.strftime("%c"),
                    strfdelta(datetime.utcnow() - user.created_at),
                ),
                inline=False,
            )
            em.set_author(name=user.name, icon_url="https://i.imgur.com/FSGlsOR.png")
            member_search = await self.do_search(guild_id=guild.id, author_id=user.id)
            em.add_field(
                name="Messages in Server:",
                value="{}".format(member_search["total_results"]),
                inline=False,
            )
            em.add_field(
                name="Voice Channel Activity:", value=f"{vc_string}", inline=False
            )
            try:
                bans = await guild.get_ban(user)
                reason = bans.reason
                if not reason:
                    history_items = []

                    search_in_actions = (
                        await self.do_search(
                            guild_id=guild.id,
                            channel_id=CHANS["actions"],
                            content=user.id,
                        )
                    )["messages"]
                    for message_block in search_in_actions:
                        for msg in message_block:
                            if (
                                str(user.id) in msg["content"]
                                and "Banned user" in msg["content"]
                                and msg["content"] not in history_items
                            ):
                                history_items.append(msg["content"])
                    reason = (cleanup_blocks(history_items[-1]).strip().split("\n"))[2][
                        7:
                    ]
                if not reason:
                    em.add_field(
                        name="User Banned from Server:",
                        value=f"Reason: {reason}",
                        inline=False,
                    )
                else:
                    em.add_field(
                        name="User Banned from Server:",
                        value=f"-Reason Unknown-",
                        inline=False,
                    )

            except discord.NotFound:
                pass

        em.set_thumbnail(url=user.avatar_url)
        await self.safe_send_message(channel, embed=em)
    async def cmd_tag(
        self, message, guild, author, channel, mentions, leftover_args, eval_content
    ):
        """
        Usage {command_prefix}tag tag name
        Gets a tag from the database of tags and returns it in chat for all to see.
        
        Usage {command_prefix}tag list
        Sends you a PM listing all tags in the tag database
        
        Usage {command_prefix}tag [+, add, -, remove,  blacklist]
        Mod only commands, ask rhino if you dont know the full syntax
        """
        if not leftover_args:
            raise CommandError("Please specify a tag!")
        switch = leftover_args.pop(0).lower()
        if switch in ["+", "add", "-", "remove", "list", "blacklist"]:
            if switch in ["+", "add"]:
                if len(leftover_args) == 2:
                    if len(leftover_args[0]) > 200 or len(leftover_args[1]) > 1750:
                        raise CommandError("Tag length too long")
                    self.tags[leftover_args[0].lower()] = [False, leftover_args[1]]
                    write_json("tags.json", self.tags)
                    return Response(
                        'Tag "%s" created' % clean_bad_pings(leftover_args[0]),
                        delete_after=15,
                    )
                else:
                    flags = leftover_args[0].split()
                    final_args = []
                    eval_override = False
                    for flag in flags:
                        if flag.isdigit() and guild.get_channel(int(flag)):
                            final_args.append(flag)
                        elif flag == "image":
                            eval_content = f'```\nem = discord.Embed(colour=discord.Colour(0x36393F))\nem.set_image(url="{leftover_args[2]}")\nawait self.safe_edit_message(channel, embed=em, send_if_fail=True)\n\n```'
                            final_args.append("eval")
                            eval_override = True
                        elif flag == "eval":
                            final_args.append("eval")
                            eval_override = True

                    if not final_args:
                        raise CommandError("Bad input")

                    final_str = " ".join(final_args)
                    if len(leftover_args[1]) > 200:
                        raise CommandError("Tag length too long")
                    self.tags[leftover_args[1].lower()] = [
                        final_str,
                        leftover_args[2]
                        if not eval_override
                        else cleanup_code(eval_content),
                    ]
                    write_json("tags.json", self.tags)
                    return Response(
                        'Tag "%s" created' % clean_bad_pings(leftover_args[1]),
                        delete_after=15,
                    )

            elif switch == "list":
                this = sorted(list(self.tags.keys()), key=str.lower)
                new_this = [this[0]]
                for elem in this[1:]:
                    if len(new_this[-1]) + len(elem) < 70:
                        new_this[-1] = new_this[-1] + ", " + elem
                    else:
                        new_this.append(elem)
                final = "%s" % "\n".join(new_this)
                print(final)
            else:
                try:
                    del self.tags[" ".join(leftover_args)]
                    write_json("tags.json", self.tags)
                    return Response(
                        'Tag "%s" removed' % clean_bad_pings(" ".join(leftover_args)),
                        delete_after=10,
                        delete_invoking=True,
                    )
                except:
                    raise CommandError("Tag doesn't exist to be removed")
        else:
            msg = False
            if leftover_args:
                tag_name = "{} {}".format(switch, " ".join(leftover_args))
            else:
                tag_name = switch
            for tag in self.tags:
                if tag_name.lower() == tag.lower():
                    if self.tags[tag][0]:
                        tag_flags = self.tags[tag][0].split()
                        # Eval Checking
                        if "eval" in tag_flags:
                            resp = await self.cmd_eval(
                                author,
                                guild,
                                message,
                                channel,
                                mentions,
                                self.tags[tag][1],
                                is_origin_tag=True,
                            )
                            if resp:
                                await self.safe_edit_message(
                                    channel,
                                    content=clean_bad_pings(resp),
                                    send_if_fail=True,
                                )
                            return
                    return Response(clean_bad_pings(self.tags[tag][1]))
            raise CommandError("Tag doesn't exist")

    async def on_raw_reaction_add(self, payload):
        if payload.user_id in [294882584201003009, 651627261782523926]:
            rootLogger.info(
                f"found giveaway on {self.get_guild(payload.guild_id).name}. Will react if >10 votes in 360s...\n"
            )
            for x in range(360):
                await asyncio.sleep(1)

                msg = discord.utils.get(
                    self._connection._messages, id=payload.message_id
                )
                if msg and msg.reactions and msg.reactions[0].count > 10:
                    await self.http.add_reaction(
                        payload.message_id,
                        payload.channel_id,
                        payload.emoji._as_reaction(),
                    )
                    rootLogger.info(
                        f"Reaction added to giveaway on {self.get_guild(payload.guild_id).name} after {x} seconds.\n"
                    )
                    return
            rootLogger.debug(
                f"giveaway on {self.get_guild(payload.guild_id).name} didnt reach minimum votes for reaction."
                + "\n"
            )

    async def on_member_update(self, before, after):
        if (
            before.id == self.fm_bot_watcher
            and before.game != after.game
            and after.game
        ):
            this = after.game.name.encode("ascii", "ignore").decode("ascii")
            self.now_playing = this
            write_file(
                "nowplaying.txt", "{0}{1}{0}".format(" " * (len(this) + 600), this)
            )

    async def on_message_delete(self, message):
        if isinstance(message.channel, discord.abc.PrivateChannel):
            final = format_console(
                '\npm deleted with %s(%s)\n\t"%s"\n'
                % (message.author.name, message.author.id, message.clean_content)
            )
            rootLogger.notice(final + "\n")
        if message.author == self.user and message.guild.id not in [142667827025805312]:
            final = format_console(
                'message deleted on %s(%s)\n"%s"\n'
                % (message.guild.name, message.guild.id, message.clean_content)
            )
            rootLogger.notice(final + "\n")

    async def on_member_update(self, before, after):
        if before.id == self.user.id:
            if before.nick != after.nick:
                rootLogger.notice(
                    'nickname changed on %s(%s)\nB:"%s"\tA:"%s"\n'
                    % (before.guild.name, before.guild.id, before.nick, after.nick)
                    + "\n"
                )

    async def on_member_ban(self, guild, user):
        if user.id == self.user.id:
            rootLogger.notice("banned on %s(%s)\n" % (guild.name, guild.id) + "\n")

    async def on_guild_remove(self, guild):
        rootLogger.notice("removed from %s(%s)\n" % (guild.name, guild.id) + "\n")

    async def on_message_edit(self, before, after):
        await self.on_message(after, edit=True)

    async def on_message(self, message, edit=False):
        if isinstance(message.channel, discord.DMChannel):
            if message.author != self.user:
                if not (
                    self.user.get_relationship(message.author.id)
                    and self.user.get_relationship(message.author.id).type
                    == discord.RelationshipType.friend
                ):

                    important_guilds = {
                        "rhinos place 3": 77514836912644096,
                        "Discord Partners": 132251458665054209,
                        "Epic Reddit Comms": 388758109671129088,
                        "Fortnite Sub Shit": 327913868758351882,
                        "Globogym": 321440727965892609,
                        "Legends Of Today": 261004672230359050,
                        "R6 Mods": 128496410428571648,
                        "Anthem Sub Mod Discord": 237153448678653952,
                        "CKC": 207943928018632705,
                        "/r/discord_app": 475782045310648325,
                        "Goose Nest": 78117785145716736,
                        "DMD": 147862229029486593,
                        "SiegeGG": 375860641510195202,
                        "RoadToSI": 666217090708930560,
                        "Partnered Games Servers": 571368315113701378,
                        "Softlocke": 198538845598253057,
                        "Discord Mod Server": 667560445975986187,
                    }

                    if not any(
                        guild in list(important_guilds.values())
                        for guild in [
                            guild.id
                            for guild in self.guilds
                            if message.author.id
                            in [member.id for member in guild.members]
                        ]
                    ):
                        await self.http.ack_message(message.channel.id, message.id)
                        rootLogger.info(
                            f"DM from {message.author.name}, not friend so acking"
                        )
                    else:
                        rootLogger.info(
                            f"DM from {message.author.name}, not friend but in acceptable server so not acking"
                        )
                else:
                    rootLogger.info(f"DM from {message.author.name}")
                dm_tracking_channel = discord.utils.get(
                    self.get_all_channels(), id=398966481406263297
                )
                self.divider_content = "__                                                                                                          __\n\n"
                jump_embed = discord.Embed(
                    colour=discord.Colour(0x36393F),
                    description=f"[click to jump]({message.jump_url})",
                )
                if message.attachments:
                    if not message.content:
                        msg_content = "-No content-"
                    else:
                        msg_content = message.clean_content

                    if edit:
                        await self.safe_send_message(
                            dm_tracking_channel,
                            embed=jump_embed,
                            content=f'{self.divider_content}**EDITED MSG From:** *{message.author.mention}*:\n```{msg_content}```\n~Attachments: {", ".join([attachment.url for attachment in message.attachments])}\nID: `{message.author.id}`',
                        )
                    else:
                        await self.safe_send_message(
                            dm_tracking_channel,
                            embed=jump_embed,
                            content=f'{self.divider_content}**From:** *{message.author.mention}*:\n```{msg_content}```\n~Attachments: {", ".join([attachment.url for attachment in message.attachments])}\nID: `{message.author.id}`',
                        )

                else:
                    if edit:
                        await self.safe_send_message(
                            dm_tracking_channel,
                            embed=jump_embed,
                            content=f"{self.divider_content}**EDITED MSG From:** *{message.author.mention}*:\n```{message.clean_content}```\nID: `{message.author.id}`",
                        )
                    else:
                        await self.safe_send_message(
                            dm_tracking_channel,
                            embed=jump_embed,
                            content=f"{self.divider_content}**From:** *{message.author.mention}*:\n```{message.clean_content}```\nID: `{message.author.id}`",
                        )
                return
        elif isinstance(message.channel, discord.GroupChannel):
            if message.author != self.user:
                rootLogger.info(f"DM in {message.channel.name}")

                dm_tracking_channel = discord.utils.get(
                    self.get_all_channels(), id=398966481406263297
                )
                self.divider_content = "__                                                                                                          __\n\n"
                jump_embed = discord.Embed(
                    colour=discord.Colour(0x36393F),
                    description=f"[click to jump]({message.jump_url})",
                )
                if message.attachments:
                    if not message.content:
                        msg_content = "-No content-"
                    else:
                        msg_content = message.clean_content

                    if edit:
                        await self.safe_send_message(
                            dm_tracking_channel,
                            embed=jump_embed,
                            content=f'{self.divider_content}**EDITED MSG From:** *{message.author.mention}* in Group DM {message.channel.name}:\n```{message.clean_content}```\n~Attachments: {", ".join([attachment.url for attachment in message.attachments])}\nID: `{message.author.id}`',
                        )
                    else:
                        await self.safe_send_message(
                            dm_tracking_channel,
                            embed=jump_embed,
                            content=f'{self.divider_content}**From:** *{message.author.mention}* in Group DM {message.channel.name}:\n```{message.clean_content}```\n~Attachments: {", ".join([attachment.url for attachment in message.attachments])}\nID: `{message.author.id}`',
                        )

                else:
                    if edit:
                        await self.safe_send_message(
                            dm_tracking_channel,
                            embed=jump_embed,
                            content=f"{self.divider_content}**EDITED MSG From:** *{message.author.mention}* in Group DM {message.channel.name}:\n```{message.clean_content}```\nID: `{message.author.id}`",
                        )
                    else:
                        await self.safe_send_message(
                            dm_tracking_channel,
                            embed=jump_embed,
                            content=f"{self.divider_content}**From:** *{message.author.mention}* in Group DM {message.channel.name}:\n```{message.clean_content}```\nID: `{message.author.id}`",
                        )
                return
        else:
            if edit:
                return
            if message.author != self.user:
                if (
                    not message.author.id in [135288293548883969, 77511942717046784]
                    and not message.author.bot
                ):
                    # for x in range(0x070):
                    # if chr(0x900+x) in message.content:
                    # await self.safe_send_message(discord.utils.get(self.get_all_channels(), id=304046409185755146), '__**CRASH SPAM ON %s(%s) IN <#%s> BY %s (%s)**)__' % (message.guild.name, message.guild.id, message.channel.id, message.author.mention, message.author.id))
                    # try:
                    # await self.safe_delete_message(message)
                    # except:
                    # print('Couldnt delete crash spam...  Pls refer to logs in discord channel')
                    msg = None
                    if (
                        message.guild.me in message.mentions
                        or (
                            message.mention_everyone
                            and message.guild.id != 298778712709529603
                        )
                        or (
                            set(message.guild.me.roles).intersection(
                                message.role_mentions
                            )
                            and message.guild.id != 298778712709529603
                        )
                    ):
                        jump_embed = discord.Embed(
                            colour=discord.Colour(0x36393F),
                            description=f"[click to jump]({message.jump_url})",
                        )
                        if not message.mention_everyone:
                            await self.safe_send_message(
                                discord.utils.get(
                                    self.get_all_channels(), id=304046409185755146
                                ),
                                embed=jump_embed,
                                content="\nmentioned on %s(%s) in <#%s> by %s (%s)```%s```"
                                % (
                                    message.guild.name,
                                    message.guild.id,
                                    message.channel.id,
                                    message.author.mention,
                                    message.author.id,
                                    message.clean_content,
                                ),
                            )
                        msg = f'mentioned on \x1b[1;35m{message.guild.name}\x1b[0m(\x1b[0;37m{message.guild.id}\x1b[0m) \x1b[0;32mby\n\t\t    \x1b[1;31m{message.author.name}\x1b[0m(\x1b[0;37m{message.author.id}\x1b[0m) in \x1b[0;36m#{message.channel.name}\x1b[0m - \n\t\t    \x1b[0;34m"{format_console(message.clean_content)}"\x1b[0m'

                    else:
                        if message.guild.id not in ["298778712709529603"]:
                            regex = r"(?<![\w])(rhino|sexualrhino|sexualrhinoceros|rhinoceros|sexrhino)(?![\w])"
                            if re.search(regex, message.clean_content, re.IGNORECASE):
                                jump_embed = discord.Embed(
                                    colour=discord.Colour(0x36393F),
                                    description=f"[click to jump]({message.jump_url})",
                                )
                                await self.safe_send_message(
                                    discord.utils.get(
                                        self.get_all_channels(), id=304046409185755146
                                    ),
                                    embed=jump_embed,
                                    content="\nmentioned on %s(%s) in <#%s> by %s (%s)```%s```"
                                    % (
                                        message.guild.name,
                                        message.guild.id,
                                        message.channel.id,
                                        message.author.mention,
                                        message.author.id,
                                        message.clean_content,
                                    ),
                                )
                                shortened_jump = await shorten_url(message.jump_url)
                                msg = f'mentioned on \x1b[1;35m{message.guild.name}\x1b[0m(\x1b[0;37m{message.guild.id}\x1b[0m) \x1b[0;32mby\n\t\t    \x1b[1;31m{message.author.name}\x1b[0m(\x1b[0;37m{message.author.id}\x1b[0m) in \x1b[0;36m#{message.channel.name}\x1b[0m - \n\t\t    \x1b[0;34m"{format_console(message.clean_content)}"\x1b[0m\n\t\t     {shortened_jump}'
                    if msg:
                        rootLogger.debug(msg + "\n")
                return
        if edit:
            return
        if message.channel.id == "227595844088627200":
            this = message.content.encode("ascii", "ignore").decode("ascii")
            if message.author.id == self.fm_bot_watcher and this != self.now_playing:
                self.now_playing = this
                write_file(
                    "nowplaying.txt",
                    ["{0}{1}{0}".format(" " * (len(this) + 200), this)],
                )
        if message.author == self.user:

            message_content = message.content.strip()

            if message_content.startswith(prefix):
                try:
                    _, *raw_args = message_content.split()
                    command, *args = shlex.split(message_content)
                except ValueError as e:
                    command, *args = message_content.split()
                command = command[len(prefix) :].lower().strip()

                handler = getattr(self, "cmd_%s" % command, None)
                if not handler:

                    tag_name = message.content.strip()[1:].lower()
                    if tag_name in self.tags:
                        if self.tags[tag_name][0]:
                            tag_flags = self.tags[tag_name][0].split()

                            # Eval Checking
                            if "eval" in tag_flags:
                                resp = await self.cmd_eval(
                                    message.author,
                                    message.guild,
                                    message,
                                    message.channel,
                                    message.mentions,
                                    self.tags[tag_name][1],
                                    is_origin_tag=True,
                                )
                                if resp:
                                    await self.safe_edit_message(
                                        message.channel,
                                        content=clean_bad_pings(resp),
                                        send_if_fail=True,
                                    )
                                return

                        await self.safe_edit_message(
                            message.channel,
                            content=clean_bad_pings(self.tags[tag_name][1]),
                            send_if_fail=True,
                        )

                        print(
                            "[Command] {0.id}/{0.name} ({1})".format(
                                message.author, message_content
                            )
                        )
                    return

                else:
                    argspec = inspect.signature(handler)
                    params = argspec.parameters.copy()

                    # noinspection PyBroadException
                    try:
                        handler_kwargs = {}
                        if params.pop("message", None):
                            handler_kwargs["message"] = message

                        if params.pop("channel", None):
                            handler_kwargs["channel"] = message.channel

                        if params.pop("author", None):
                            handler_kwargs["author"] = message.author

                        if params.pop("guild", None):
                            handler_kwargs["guild"] = message.guild

                        if params.pop("mentions", None):
                            handler_kwargs["mentions"] = message.mentions

                        if params.pop("leftover_args", None):
                            handler_kwargs["leftover_args"] = args

                        if params.pop("raw_leftover_args", None):
                            handler_kwargs["raw_leftover_args"] = raw_args

                        if params.pop("eval_content", None):
                            handler_kwargs["eval_content"] = message.content

                        args_expected = []
                        for key, param in list(params.items()):
                            doc_key = (
                                "[%s=%s]" % (key, param.default)
                                if param.default is not inspect.Parameter.empty
                                else key
                            )
                            args_expected.append(doc_key)

                            if (
                                not args
                                and param.default is not inspect.Parameter.empty
                            ):
                                params.pop(key)
                                continue

                            if args:
                                arg_value = args.pop(0)
                                if arg_value.startswith("<@") or arg_value.startswith(
                                    "<#"
                                ):
                                    pass
                                else:
                                    if re.fullmatch(r"[0-9]{17,18}", arg_value):
                                        arg_value = int(arg_value)

                                    handler_kwargs[key] = arg_value
                                    params.pop(key)

                        if params:
                            docs = getattr(handler, "__doc__", None)
                            if not docs:
                                docs = "Usage: {}{} {}".format(
                                    self.prefix, command, " ".join(args_expected)
                                )

                            docs = "\n".join(l.strip() for l in docs.split("\n"))
                            await self.safe_send_message(
                                message.channel,
                                content="```\n%s\n```"
                                % docs.format(command_prefix=self.prefix),
                                expire_in=15,
                            )
                            return

                        response = await handler(**handler_kwargs)
                        if response and isinstance(response, Response):
                            content = response.content
                            if len(content) > 2000:
                                split = [
                                    content[i : i + 2000]
                                    for i in range(0, len(content), 2000)
                                ]
                                for x in split:
                                    await self.safe_send_message(
                                        message.channel, content=x
                                    )
                                await self.safe_delete_message(message)
                            elif response.send_message:
                                if response.reply:
                                    content = "**(╭ರ_•)**-%s" % content
                                await self.safe_send_message(
                                    message.channel,
                                    content=content,
                                    expire_in=response.delete_after,
                                )
                            else:
                                if response.reply:
                                    content = "**(╭ರ_•)**-%s" % content
                                await self.safe_edit_message(
                                    message,
                                    new_content=content,
                                    expire_in=response.delete_after,
                                    send_if_fail=True,
                                )

                    except Exception as e:
                        await self.safe_send_message(
                            message.channel,
                            content="```\n%s\n```" % traceback.format_exc(),
                        )
                        traceback.print_exc()


if __name__ == "__main__":
    bot = Jeeves()
    bot.run()
