import asyncio
import json
import logging.handlers
import re
import smtplib

import aiohttp
import async_timeout
import discord

# Setting up logging with the built in discord.py logger
logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)

# We load the log file depending on what log file filename the user has specified in the config
with open("config.json", mode="r", encoding="utf-8") as config_file:
    config = json.load(config_file)
    handler = logging.FileHandler(filename=config["logging"]["log_file_name"], encoding='utf-8', mode='a')

# Continuing the logger setup
handler.setFormatter(logging.Formatter('%(asctime)s: %(levelname)s: %(name)s: %(message)s'))
logger.addHandler(handler)

# We check if the user wants to use email to report errors
if config["log_config"]["use_email_notifications"]:
    # We create the SMTP loghandler with the proper settings from the config
    mail_notification_handler = logging.handlers.SMTPHandler((config["log_config"]["email_settings"]["smtp_server"],
                                                              config["log_config"]["email_settings"][
                                                                  "smtp_port"]),
                                                             config["log_config"]["email_settings"]["from_address"],
                                                             config["log_config"]["email_settings"]["send_to"],
                                                             config["log_config"]["email_settings"]["subject"],
                                                             credentials=(
                                                                 config["log_config"]["email_settings"]["username"],
                                                                 config["log_config"]["email_settings"]["password"]),
                                                             secure=())

    # We change the level so it only sends emails about warnings or errors
    mail_notification_handler.setLevel(logging.WARNING)
    # We change the formatter to the formatter we use in the file handler
    mail_notification_handler.setFormatter(handler.formatter)

    # We add the mail handler to the logger
    logger.addHandler(mail_notification_handler)

# We compile the regular expressions we will need, for performance
role_id_regex = re.compile(r'<@&\d+>')

# The client object
actual_client = discord.Client(cache_auth=False)


def write_config(config_temp: dict):
    """This function writes the passed dict out to the config file as json."""
    # We write the out to the file
    with open("config.json", mode="w", encoding="utf-8") as config_file_temp:
        json.dump(config_temp, config_file_temp, indent=2, sort_keys=False)


def get_formatted_duration_fromtime(duration_seconds_noformat):
    # How many weeks the duration is
    duration_weeks = duration_seconds_noformat // (7 * 24 * 3600)

    # Subtracting the weeks from the unformatted seconds
    duration_seconds_noformat %= (7 * 24 * 3600)

    # How many days duration is
    duration_days = duration_seconds_noformat // (24 * 3600)

    # Subtracting the days from the unformatted seconds
    duration_seconds_noformat %= (24 * 3600)

    # How many hours the duration is
    duration_hours = duration_seconds_noformat // (3600)

    # Subtracting the hours from the unformatted seconds
    duration_seconds_noformat %= 3600

    # How many minutes the duration is
    duration_minutes = duration_seconds_noformat // 60

    # Subtracting the minutes from the unformatted seconds
    duration_seconds_noformat %= 60

    # Creating the formatted duration string
    formatted_duration = "%i weeks, %i days, %i hours, %i minutes, and %i seconds" % (
        duration_weeks, duration_days, duration_hours, duration_minutes, duration_seconds_noformat)

    return formatted_duration


def log_text(text, level):
    print(text)
    try:
        logger.log(level, text)
    except smtplib.SMTPException as e:
        print("Got error when trying to send email notification, error message: {0}".format(str(e)))
    except Exception as e:
        print("Got error when trying to log, error message {0}.".format(str(e)))


def log_debug(text):
    log_text(text, 10)


def log_info(text):
    log_text(text, 20)


def log_warning(text):
    log_text(text, 30)


def log_error(text):
    log_text(text, 40)


def log_critical(text):
    log_text(text, 50)


def log_ob(dis_object) -> str:
    """This method returns a string that contains the passed object's name and id, in the format of '{0} ({1})'.format(object.name, object.id)."""
    return "{0} ({1})".format(dis_object.name, dis_object.id)


async def remove_roles(client: discord.Client, member: discord.Member, roles: list):
    """This function is used to remove all roles from a list from a user until the user does not have any of those roles, or the max retries have been attempted.
    This raises Forbidden if the client does not have permissions to remove roles from the target user.
    May also raise HTTPException if the network operations failed."""

    # We basically work with the assumption that local membership operations are a lot faster than discord network operations

    # The duration to wait between each batch of role removals
    role_removal_cooldown = 0.1

    # We remove the roles a user has. We do this multiple times or until the user no longer has any of the roles (as doing it once is not reliable)
    for i in range(5):

        # We check if the user has any of the roles (just so we don't need to issue a network operation)
        # We check if the two lists (the member's roles and the removal roles) share any elements
        if any(x in max(roles, member.roles, key=len) for x in
               min(roles, member.roles, key=len)):
            # We remove all the roles from the user
            for role in [x for x in roles if x in member.roles]:
                await client.remove_roles(member, role)

            # We wait so we don't get rate limited, and so we have time to receive the updated member
            await asyncio.sleep(role_removal_cooldown)

        else:
            # We have removed all the roles
            i -= 1
            break

    # We log how many retries it took to remove the roles from the user
    log_info(
        "Removing roles from user {0} took {1} retries.".format(log_ob(member), i))


def check_add_remove_roles(member: discord.Member, channel: discord.Channel) -> bool:
    """This method returns true if the currently logged in client can remove and add roles from the passed member in the passed channel."""

    return channel.permissions_for(
        channel.server.me).manage_roles and member.top_role.position < member.server.me.top_role.position


def remove_fluxx_mention(client: discord.Client, message):
    """This function is used to remove the first part of an fluxx message so that the command code can more easily parse the command"""

    # The weird mention for the bot user, the string manipulation is due to mention strings not being the same all the time
    client_mention = client.user.mention[:2] + "!" + client.user.mention[2:]

    # We check if the input is a message or just a string
    if isinstance(message, discord.Message):
        content = message.content
    else:
        content = message

    # We first check if discord is fucking with us by using the weird mention
    if content.lstrip().startswith(client_mention):
        # Removing the fluxx bot mention in the message so we can parse the arguments more easily
        cleaned_message = content.lstrip()[len(client_mention) + 1:]
    else:
        # Removing the fluxx bot mention in the message so we can parse the arguments more easily
        cleaned_message = content.lstrip()[len(client.user.mention) + 1:]

    return cleaned_message


def is_message_command(message: discord.Message, client: discord.Client):
    """This function is used to check whether a message is trying to issue an fluxx-bot command"""

    # The weird mention for the bot user, the string manipulation is due to mention strings not being the same all the time
    client_mention = client.user.mention[:2] + "!" + client.user.mention[2:]

    # We return if the message is a command or not
    return message.content.lower().strip().startswith(client_mention) or message.content.lower().strip().startswith(
        client.user.mention)


def remove_discord_formatting(*strings):
    """This method removes all discord formatting chars from all the passed strings, and returns them in a list ordered like they were passed to it."""

    return [x.replace("*", "").replace("_", "").replace("~", "") for x in strings]


def escape_code_formatting(*strings):
    """Replaces backticks (from for example code blocks) with escaped backticks 
    (placing zero width joiners between them so they don't register as proper formatting)."""
    return [s.replace("`", "`\u2060") for s in strings]


def get_role_from_mention(member: discord.Member, string: str):
    """This method returns a role from the member's server based on the role mention in string.
    Returns None if there isn't a matching role on the member's server."""

    string = string.strip()
    match = role_id_regex.search(string)

    # Role mentions are in the format <@&ROLE_ID>, so we try to extract the role id with a precompiled regex
    if match:
        # We check if the role id is in the server
        role_id_string = match.group(0)[3:-1]
        if role_id_string in [x.id for x in member.server.roles]:
            # We search the member's server's roles for the string role id
            return discord.utils.get(member.server.roles, id=role_id_string)


def is_member_fluxx_admin(member: discord.Member, passed_config: dict):
    """This method checks if a user is an fluxx-bot admin or not, returns True if they are, False otherwise."""
    return int(member.id) in passed_config["somewhat_weird_shit"]["admin_user_ids"]


def parse_quote_parameters(raw: str, number_params: int):
    """Parses and returns a list of parsed parameters that are enclosed in quotes in a string.
    Raises Assertionerror if the string isn't in the required format."""

    # We strip the raw string
    raw = raw.strip()

    # Assert it starts with "
    assert raw[0] == "\""
    # Assert that there are the proper number of "s (double the number of parameters)
    assert sum([1 for c in raw if c == "\""]) == number_params * 2

    parameters = []
    for i in range(number_params):
        # Remove the first ", and put the argument into query_parameters, and then remove the next "
        raw = raw[1:]
        parameters.append(raw[:raw.find("\"")])
        raw = raw[raw.find("\"") + 1:]
        raw = raw[raw.find("\""):]

    return parameters


async def send_long(client: discord.Client, message, channel: discord.Channel, prepend: str = "", append: str = ""):
    """This method is used to send long messages (longer than 2000 chars) without triggering rate-limiting. 
    message can be a string or a list of strings, it will be autodetected. If a string in a list is > 2000 chars, it will fail to send.
    Prepend is prepended to all messages, not to the whole message input.
    Append is appended to all messages, not to the whole message input."""

    # How long we wait between each message
    cooldown_time = 0.5

    # We don't let append and prepend increase the length of the message
    msg_part_length = 1999 - (len(prepend) + len(append))

    # We don't want some weird errors
    if msg_part_length <= 0:
        raise ValueError()

    # We check if the message is already split into parts
    if not isinstance(message, str):
        # We split the input message into 1999 char chunks
        message_parts = [(prepend + message[i:i + msg_part_length] + append) for i in
                         range(0, len(message), msg_part_length)]
    else:
        message_parts = [message]

    # We send the message in multiple messages to bypass the 2000 char limit, and we pause between each message to not get rate-limited
    for split_message in message_parts:
        # We wait for a bit to not get rate-limited
        await asyncio.sleep(cooldown_time)

        # We send the message part
        await client.send_message(channel, split_message)


async def mashape_json_api_request(passed_config: dict, *args, endpoint: str, timeout: float = 5., method: str = "get",
                                   return_json: bool = True, return_raw_response: bool = False,
                                   return_data_aswell: bool = False, **kwargs) -> aiohttp.ClientResponse:
    """Does a json api request to a mashape.com api. The endpoint is endpoint, the timeout is in seconds, method is the HTTP method to use, and *args and **kwargs are passed to the aiohttp call.
    This raises asyncio.TimeoutError if the request takes more than timeout seconds. 
    Returns the raw response if return_raw_response is True (defaults to False).
    If return_raw_response is True and return_data_aswell is True, it will return: await response.read(), response
    Returns data in json format if return_json is True (defaults to True).
    This automatically uses the configured mashape key from the passed_config dict."""

    # We configure the HTTP headers to send
    headers = {
        "X-Mashape-Key": passed_config["credentials"]["mashape_api_key"],
        "Accept": "application/json"
    }

    # We do the request
    try:
        # We create an aiohttp.Client, and fetch the json from the meow api
        with async_timeout.timeout(timeout):
            async with aiohttp.ClientSession(loop=actual_client.loop) as session:
                async with getattr(session, method)(endpoint, *args, headers=headers, **kwargs) as response:
                    if return_raw_response:
                        if return_data_aswell:
                            return await response.read(), response
                        else:
                            return response
                    if return_json:
                        result = json.loads(await response.text())
                    else:
                        result = await response.text()
                    return result
    except (asyncio.TimeoutError, json.JSONDecodeError):
        # We didn't succeed with loading the url
        log_info("Wasn't able to load mashape url {0}.".format(endpoint))
        raise
