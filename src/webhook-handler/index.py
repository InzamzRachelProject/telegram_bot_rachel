# -*- coding: utf8 -*-
from cgitb import text
from http import client
import json
import time
import telebot
import os
import redis
import traceback
import requests
import re
import base64
from pymongo import MongoClient
from typing import Tuple, List
from modules.ask_ai import pic_generator, askgpt
from modules.card_maker import send_quote_pic_to_telegram

SUPPORT_MODULES = [
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-0301",
    "gpt-3.5-turbo-0613",
    "gpt-3.5-turbo-16k",
    "gpt-3.5-turbo-16k-0613",
    "gpt-3.5-turbo-1106",
    "o1-preview",
    "o1-mini",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4",
    "gpt-4-0314",
    "gpt-4-0613",
    "gpt-4-1106-preview",
    "gpt-4-vision-preview",
    "gpt-4-32k",
    "gpt-4-32k-0314",
    "gpt-4-32k-0613",
    "gpt-3.5-turbo-instruct",
    "gpt-3.5-turbo-instruct-0914",
    "text-davinci-003",
    "text-davinci-002",
    "text-curie-001",
    "text-babbage-001",
    "text-ada-001",
    "text-embedding-ada-002",
    "text-search-ada-doc-001",
    "dall-e",
    "dall-e-2",
    "dall-e-3",
    "text-davinci-edit-001",
    "code-davinci-edit-001",
    "whisper-1",
    "tts-1",
    "tts-1-hd",
    "tts-1-1106",
    "tts-1-hd-1106",
    "text-moderation-latest",
    "text-moderation-stable",
    "midjourney",
    "claude-2-web",
    "claude-2",
    "claude-instant-1",
    "palm-2-chat-bison",
    "palm-2-chat-bison-32k",
    "gemini-pro",
    "gemini-pro-vision",
]

r = redis.from_url(os.getenv("REDIS_URL"))

def get_character_link(speaker: str) -> str:
    client = MongoClient(os.getenv("MONGODB_ATLAS_URI"))
    db = client.get_database("CharacterProfiles")
    default_collection = db.get_collection("default")
    speaker_info = default_collection.find_one(
        {"name": speaker},
    )
    if speaker_info == None:
        return ""
    return speaker_info.get("card_url", "")


def main_handler(event, context):
    # 对 webhook 进行鉴权
    if event["headers"]["x-telegram-bot-api-secret-token"] != os.getenv(
        "telegram_bot_api_secret_token"
    ):
        return "Api auth failed"
    print("Received event: " + json.dumps(event))
    tele_token = os.getenv("tele_token")

    if not tele_token:
        return "No tele_token found"

    bot = telebot.TeleBot(tele_token)
    update = json.loads(event["body"].replace('"', '"'))
    # print("Received message: " + json.dumps(update, indent = 2))
    message = update.get("message", {})
    forward_from_chat = message.get("forward_from_chat", {})
    forward_from_chat_id = forward_from_chat.get("id", None)
    forward_from_message_id = message.get("forward_from_message_id", None)

    chat_group = message.get("chat", {}).get("id", None)
    chat_group_message_id = message.get("message_id", None)
    text = message.get("text", "").strip()
    utf8_text = text.encode("utf-8").decode("utf-8")
    print(
        "chat_group: {}, chat_group_message_id: {}, forward_from_chat_id: {}, message: {}".format(
            chat_group, chat_group_message_id, forward_from_chat_id, utf8_text
        ),
        flush=True,
    )
    while (
        chat_group != None
        and chat_group_message_id != None
        and forward_from_message_id != None
        and os.getenv("report_channel", None) == str(forward_from_chat_id)
    ):
        MongoDbUri = os.getenv("MONGODB_ATLAS_URI", None)
        if MongoDbUri == None:
            break
        client = MongoClient(MongoDbUri)
        db = client.get_database("BooksNotes")
        msg_config = db.get_collection("MsgToBookname")
        if msg_config == None:
            break
        print("forward_from_message_id: ", forward_from_message_id, flush=True)
        for x in msg_config.find():
            print(x, flush=True)
        book_info = msg_config.find_one({"channel_message_id": forward_from_message_id})
        if book_info == None:
            break
        print("book_info: ", book_info, flush=True)
        book_name = book_info.get("book_name", None)
        if book_name == None:
            break
        if book_info.get("reply_msg_info", None) == None:
            msg_config.update_one(
                {"channel_message_id": forward_from_message_id},
                {"$set": {"reply_msg_info": {}}},
            )
        reply_msg_info = msg_config.find_one(
            {"channel_message_id": forward_from_message_id}
        )["reply_msg_info"]
        print(f"book_name: {book_name}, reply_msg_info: ", reply_msg_info, flush=True)
        dbBooksNotes = client.get_database("BooksNotes")

        collections = dbBooksNotes.get_collection(book_name)
        # print("collections {}".format(collections), flush=True)

        content_hash_list = []
        for note in collections.find():
            # print(note, flush=True)
            preview_url = None
            content_hash_list.append(note["hash"])
            if note["hash"] in reply_msg_info.keys():
                print("match hash: ", note["hash"], flush=True)
                continue
            text_parts = [f"📚 {note['content']}"]
            if note.get("speaker", None) != None:
                speaker_charactor_link = get_character_link(note["speaker"])
                print("speaker_charactor_link: ", speaker_charactor_link)
                text_parts.append(f"🎙️ {note['speaker']}")
                if speaker_charactor_link != "":
                    preview_url = speaker_charactor_link
            if note.get("character_comment", None) != None:
                comment_character_link = get_character_link(note["character_comment"])
                print("comment_character_link: ", comment_character_link)
                text_parts.append(f"⚖️ {note['character_comment']}")
                if comment_character_link != "":
                    preview_url = comment_character_link
            if note.get("note", None) != None and note["note"].strip() != "":
                text_parts.append(f"💬 {note['note']}")
            text = "\n".join(text_parts).replace("&", "&amp;")
            print("preview_url: ", preview_url, flush=True)
            if note["hash"] in reply_msg_info.keys():
                print("edit_message_text: ", edit_message_text)
                bot.edit_message_text(
                    text,
                    chat_group,
                    reply_msg_info[note["hash"]],
                    parse_mode="HTML",
                    link_preview_options=telebot.types.LinkPreviewOptions(
                        url=preview_url,
                        prefer_small_media=True,
                        show_above_text=True,
                    ),
                )
                time.sleep(1)
            else:
                ret = bot.send_message(
                    chat_group,
                    text,
                    reply_to_message_id=chat_group_message_id,
                    parse_mode="HTML",
                    link_preview_options=telebot.types.LinkPreviewOptions(
                        url=preview_url,
                        prefer_small_media=True,
                        show_above_text=True,
                    ),
                )
                print("ret: ", ret, flush=True)
                reply_msg_info[note["hash"]] = ret.message_id
                time.sleep(1)
                print("reply_msg_info after update: ", reply_msg_info, flush=True)
            msg_config.update_one(
                {"channel_message_id": forward_from_message_id},
                {"$set": {"reply_msg_info": reply_msg_info}},
            )
        reply_msg_info = msg_config.find_one(
            {"channel_message_id": forward_from_message_id}
        )["reply_msg_info"]
        for content_hash in reply_msg_info.keys():
            if content_hash not in content_hash_list:
                bot.delete_message(chat_group, reply_msg_info[content_hash])
                msg_config.update_one(
                    {"channel_message_id": forward_from_message_id},
                    {"$unset": {"reply_msg_info." + content_hash: ""}},
                )
        break

    # 命令处理器
    if bot and "text" in message and message["text"].startswith("/"):
        bot = telebot.TeleBot(tele_token)
        ret, msg = command_handler(message, bot)
        if ret == 0:
            return msg
        print(bot.get_me())

    # 处理图片相关的命令
    if (
        bot
        and "photo" in message
        and "caption" in message
        and message["caption"].startswith("/")
    ):
        bot = telebot.TeleBot(tele_token)
        ret, msg = photo_cmd_handler(message, bot)
        if ret == 0:
            return msg
        print(bot.get_me())

    # 处理新加的 /pic[dall-e-3] 命令
    if (
        bot
        and "text" in message
        and "entities" in message
        and message["text"].startswith("/pic")
    ):
        bot = telebot.TeleBot(tele_token)
        command_args: list = message["text"].split(" ")
        model = parse_command_module(command_args, "/pic", "dall-e-3")
        prompt = message["text"][len(command_args[0]) :].strip()
        resp = bot.send_message(
            message["chat"]["id"],
            f"🤖 {model} generating",
            reply_to_message_id=message["message_id"],
        )
        ret, pic_url = pic_generator(model, prompt, return_type="url")
        if ret != 0:
            bot.edit_message_text(
                f"🤖 {model} generating failed",
                message["chat"]["id"],
                resp.message_id,
                parse_mode="MarkdownV2",
            )
            return msg
        bot.delete_message(message["chat"]["id"], resp.message_id)
        bot.send_photo(
            chat_id=message["chat"]["id"],
            photo=pic_url,
            reply_to_message_id=message["message_id"],
        )

    return "Received message: " + json.dumps(message, indent=2)


def command_handler(message: dict, bot: telebot.TeleBot) -> Tuple[int, str]:
    command_args: list = message["text"].split(" ")
    if command_args[0] == "/echo":
        if len(message["text"][6:]) > 0:
            bot.send_message(
                message["chat"]["id"],
                message["text"][6:],
                reply_to_message_id=message["message_id"],
            )
        return 0, "Echo command exec success"
    if command_args[0].startswith("/askgptclear"):
        r.delete(f'{message["from"]["id"]}_context')
    elif command_args[0].startswith("/askgpt"):
        try:
            module = parse_command_module(
                command_args, "/askgpt", os.getenv("OPENAI_MODEL")
            )
            # 判断模型是否支持
            if module not in SUPPORT_MODULES:
                bot.send_message(
                    message["chat"]["id"],
                    f"🤖 {module} is not supported",
                    reply_to_message_id=message["message_id"],
                )
                return 0, "Askgpt command exec success"
            # 发送消息,生成成功后再替换文本
            resp = bot.send_message(
                message["chat"]["id"],
                f"🤖 {module} Generating...",
                reply_to_message_id=message["message_id"],
            )
            answer = f"🤖 {module} \n\n" + askgpt(
                message["text"][len(command_args[0]) :], module, str(message["from"]["id"]),
            )
            bot.edit_message_text(
                escape_markdown_v2(answer),
                message["chat"]["id"],
                resp.message_id,
                parse_mode="MarkdownV2",
            )
        except Exception as e:
            # Error handling code
            bot.send_message(
                message["chat"]["id"], "Error:\n==========\n" + str(e.args)
            )
            # Rest of the error handling code...
            return 1, "Askgpt command exec error, traceback send to admin"
        else:
            return 0, "Askgpt command exec success"

    if command_args[0] == "/random_quote":
        send_quote_pic_to_telegram(message)
        return 0, "Random quote command exec success"

    # 检查是否是 /rss 命令
    if command_args[0] == "/rss":
        # 检查是否是管理员
        if str(message["from"]["id"]) != os.getenv("tg_admin"):
            bot.send_message(
                message["chat"]["id"],
                "Only administrators are allowed to use /rss commands.",
                reply_to_message_id=message["message_id"],
            )
            return 1, "Only administrators are allowed to use /rss commands."

        # 处理 /rss 命令的子命令
        if len(command_args) < 2:
            bot.send_message(
                message["chat"]["id"],
                "Invalid usage of /rss. Please use /rss subscribe, /rss list, /rss unsubscribe, or /rss help.",
                reply_to_message_id=message["message_id"],
            )
            return (
                1,
                "Invalid usage of /rss. Please use /rss subscribe, /rss list, /rss unsubscribe, or /rss help.",
            )

        sub_command = command_args[1].lower()

        # 处理 subscribe 子命令
        if sub_command == "subscribe":
            if len(command_args) < 3:
                bot.send_message(
                    message["chat"]["id"],
                    "Invalid usage of /rss subscribe. Please provide at least one RSS link.",
                    reply_to_message_id=message["message_id"],
                )
                return (
                    1,
                    "Invalid usage of /rss subscribe. Please provide at least one RSS link.",
                )

            rss_links = command_args[2:]
            result = subscribe_rss_links(message["chat"]["id"], rss_links)
            bot.send_message(
                message["chat"]["id"],
                result[1],
                reply_to_message_id=message["message_id"],
            )
            return result

        # 处理 unsubscribe 子命令
        elif sub_command == "unsubscribe":
            if len(command_args) < 3:
                bot.send_message(
                    message["chat"]["id"],
                    "Invalid usage of /rss unsubscribe. Please provide at least one RSS link.",
                    reply_to_message_id=message["message_id"],
                )
                return (
                    1,
                    "Invalid usage of /rss unsubscribe. Please provide at least one RSS link.",
                )

            rss_links = command_args[2:]
            result = unsubscribe_rss_links(message["chat"]["id"], rss_links)
            bot.send_message(
                message["chat"]["id"],
                result[1],
                reply_to_message_id=message["message_id"],
            )
            return result

        # 处理 list 子命令
        elif sub_command == "list":
            result = list_subscribed_rss_links(message["chat"]["id"])
            bot.send_message(
                message["chat"]["id"],
                result[1] if result[1] else "No RSS links subscribed.",
                reply_to_message_id=message["message_id"],
            )
            return result

        # 处理其他子命令
        else:
            bot.send_message(
                message["chat"]["id"],
                "Usage:\n/rss subscribe [rss_link1] [rss_link2] ... - Subscribe to RSS feeds.\n/rss unsubscribe [rss_link] - Unsubscribe from RSS feeds.\n/rss list - List subscribed RSS feeds.\n/rss help - Show this help message.",
                reply_to_message_id=message["message_id"],
            )
            return (
                0,
                "Usage:\n/rss subscribe [rss_link1] [rss_link2] ... - Subscribe to RSS feeds.\n/rss unsubscribe [rss_link] - Unsubscribe from RSS feeds.\n/rss list - List subscribed RSS feeds.\n/rss help - Show this help message.",
            )

    return 1, "No command is matched"


def photo_cmd_handler(message: dict, bot: telebot.TeleBot) -> Tuple[int, str]:
    command_args: list = message["caption"].split(" ")
    if command_args[0].startswith("/askgpt"):
        try:
            module = parse_command_module(
                command_args, "/askgpt", os.getenv("OPENAI_MODEL")
            )
            if module not in ["gpt-4-vision-preview", "gemini-pro-vision"]:
                module = os.getenv("OPENAI_VISION_MODEL")
            resp = bot.send_message(
                message["chat"]["id"],
                f"🤖 {module} Thinking...",
                reply_to_message_id=message["message_id"],
            )
            file_id = message["photo"][-1]["file_id"]
            photo_url = (
                f"https://api.telegram.org/bot{bot.token}/getFile?file_id={file_id}"
            )
            response = requests.get(photo_url)
            file_info = response.json()["result"]
            file_path = file_info["file_path"]
            photo_url = f"https://api.telegram.org/file/bot{bot.token}/{file_path}"
            photo_response = requests.get(photo_url)

            # Parse module and get answer
            prompt = message["caption"][
                len(command_args[0]) :
            ].strip()  # Extract prompt from the caption
            prompt = (
                prompt if prompt else ""
            )  # Set prompt to an empty string if it's not provided
            base64_image = base64.b64encode(photo_response.content).decode("utf-8")
            answer = f"🤖 {module}\n\n" + askgpt(
                prompt, module, message["from"]["id"],
                base64_image=base64_image,
            )

            # Change the answer
            bot.edit_message_text(
                escape_markdown_v2(answer),
                message["chat"]["id"],
                resp.message_id,
                parse_mode="MarkdownV2",
            )
        except Exception as e:
            # Handle exceptions
            error_message = "Error:\n==========\n" + str(e.args)
            bot.send_message(message["chat"]["id"], error_message)
            ret = bot.forward_message(
                os.getenv("tg_admin"), message["chat"]["id"], message["message_id"]
            )
            tg_admin: str | None = os.getenv("tg_admin")
            if tg_admin:
                bot.send_message(
                    tg_admin,
                    error_message
                    + "\n\nTraceback:\n==========\n"
                    + traceback.format_exc(),
                    reply_to_message_id=ret.message_id,
                )
            print(
                error_message + "\n\nTraceback:\n==========\n" + traceback.format_exc()
            )
            return 1, "Askgpt command exec error, traceback sent to admin"
        else:
            return 0, "Askgpt command exec success"


def parse_command_module(
    command_args: List[str], prefix: str, default_model: str
) -> Tuple[str, str]:
    # CMD Example: /askgpt[gpt-4-1106-preview] prompt

    # Default values
    module = default_model

    if command_args[0].startswith(prefix):
        # Remove the '/askgpt' prefix
        command_str = command_args[0][len(prefix) :]

        # Find positions of square brackets and parentheses
        module_start = command_str.find("[")
        module_end = command_str.rfind("]")

        # Extract module and voice if brackets are present
        if module_start != -1 and module_end != -1:
            module = command_str[module_start + 1 : module_end]

    return module


def subscribe_rss_links(chat_id: int, rss_links: list[str]) -> Tuple[int, str]:
    # 连接 MongoDB
    mongo_uri = os.environ.get("MONGO_URI")
    database_name = os.environ.get("MONGO_DATABASE_NAME", "TelegramBot")
    collection_name = os.environ.get("MONGO_CONFIG_COLLECTION_NAME", "config")

    # 连接 MongoDB
    client = MongoClient(mongo_uri)
    db = client[database_name]
    collection = db[collection_name]

    try:
        # 获取现有的订阅配置
        config_document = collection.find_one({"type": "rss"})
        subscribe_info = config_document.get("subscribe_info", {})
        chat_subscribe = subscribe_info.get(str(chat_id), [])

        # 检查是否有重复的订阅链接
        duplicate_links = set(rss_links) & set(chat_subscribe)
        info_messages = []
        if duplicate_links:
            info_messages.append(
                f"INFO: These RSS links are already subscribed: {', '.join(duplicate_links)}"
            )

        # 更新订阅配置
        new_rss_urls = list(set(chat_subscribe).union(rss_links))
        collection.update_one(
            {"type": "rss"},
            {"$set": {"subscribe_info.{}".format(chat_id): new_rss_urls}},
            upsert=True,
        )

        rss_urls_added = set(new_rss_urls).difference(set(chat_subscribe))
        if rss_urls_added:
            success_message = f"Subscribed to RSS links: {', '.join(rss_urls_added)}"
            info_messages.append(success_message)

        return 0, "\n".join(info_messages)

    except Exception as e:
        error_message = f"Error subscribing to RSS links: {str(e)}"
        return 1, error_message

    finally:
        # 关闭 MongoDB 连接
        client.close()


def unsubscribe_rss_links(chat_id: int, links: List[str]) -> Tuple[int, str]:
    # 获取 MongoDB 相关配置
    mongo_uri = os.environ.get("MONGO_URI")
    database_name = os.environ.get("MONGO_DATABASE_NAME", "TelegramBot")
    collection_name = os.environ.get("MONGO_CONFIG_COLLECTION_NAME", "config")

    # 连接 MongoDB
    client = MongoClient(mongo_uri)
    db = client[database_name]
    collection = db[collection_name]

    try:
        # 查找当前配置文档
        config_document = collection.find_one({"type": "rss"})
        subscribe_info = config_document.get("subscribe_info", {})

        if not subscribe_info:
            warning_message = "WARNING: No RSS links found for unsubscription."
            return 1, warning_message

        # 获取当前订阅链接列表
        current_rss_urls = set(subscribe_info.get(str(chat_id), []))
        info_messages = []

        # 遍历输入的链接，取消订阅
        for link in links:
            if link in current_rss_urls:
                current_rss_urls.remove(link)
            else:
                warning_message = (
                    f"WARNING: Link '{link}' not found in current subscriptions."
                )
                info_messages.append(warning_message)

        # 更新配置文档
        collection.update_one(
            {"type": "rss"},
            {"$set": {"subscribe_info.{}".format(chat_id): list(current_rss_urls)}},
        )

        success_message = "Unsubscription successful."
        info_messages.append(success_message)
        return 0, "\n".join(info_messages)

    except Exception as e:
        error_message = f"Error during unsubscription: {str(e)}"
        return 1, error_message

    finally:
        # 关闭 MongoDB 连接
        client.close()


def list_subscribed_rss_links(chat_id: int) -> Tuple[int, List[str]]:
    # 获取 MongoDB 相关配置
    mongo_uri = os.environ.get("MONGO_URI")
    database_name = os.environ.get("MONGO_DATABASE_NAME", "TelegramBot")
    collection_name = os.environ.get("MONGO_CONFIG_COLLECTION_NAME", "config")

    # 连接 MongoDB
    client = MongoClient(mongo_uri)
    db = client[database_name]
    collection = db[collection_name]

    try:
        # 查找当前配置文档
        config_document = collection.find_one({"type": "rss"})

        subscribe_info = config_document.get("subscribe_info", {})
        if not subscribe_info:
            print("No subscribe info")
            return 0, []

        # 获取当前订阅链接列表
        subscribed_rss_urls = subscribe_info.get(str(chat_id), [])

        return 0, subscribed_rss_urls

        return 1, []

    finally:
        # 关闭 MongoDB 连接
        client.close()


def escape_markdown_v2(text):
    # Escape special characters for MarkdownV2
    # except for triple backticks which denote code blocks
    escape_chars = "_*[]()~`>#+-=|{}.!\\"
    code_block_delimiter = "```"

    escaped_text = ""
    code_block_open = False
    last_pos = 0

    # Find all occurrences of triple backticks
    for match in re.finditer(r"(```)", text):
        start, end = match.span()

        # If we find an opening delimiter and we're not already in a code block
        if not code_block_open:
            # Escape section before code block
            for char in text[last_pos:start]:
                if (
                    char in escape_chars and char != "`"
                ):  # Single backticks (inline code) should be escaped
                    escaped_text += "\\" + char
                else:
                    escaped_text += char
            # Add code block delimiter as is
            escaped_text += code_block_delimiter
        else:
            # Add text within code block as is
            escaped_text += text[last_pos:end]

        code_block_open = not code_block_open
        last_pos = end

    # Escape section after the last code block
    for char in text[last_pos:]:
        if (
            char in escape_chars and char != "`"
        ):  # Again, make sure to escape single backticks
            escaped_text += "\\" + char
        else:
            escaped_text += char
    print(escaped_text)
    return escaped_text
