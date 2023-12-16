# -*- coding: utf8 -*-
import json
import telebot
import os
import openai
import traceback
import requests
import re
from pymongo import MongoClient
from typing import Tuple, List


def main_handler(event, context):
    # 对 webhook 进行鉴权
    if event["headers"]["x-telegram-bot-api-secret-token"] != os.getenv(
        "telegram_bot_api_secret_token"
    ):
        return "Api auth failed"
    print("Received event: " + json.dumps(event, indent=2))
    tele_token = os.getenv("tele_token")

    if not tele_token:
        return "No tele_token found"

    bot = telebot.TeleBot(tele_token)
    update = json.loads(event["body"].replace('"', '"'))
    # print("Received message: " + json.dumps(update, indent = 2))
    message = update["message"]

    # 命令处理器
    if bot and message["entities"][0]["type"] == "bot_command":
        bot = telebot.TeleBot(tele_token)
        ret, msg = command_handler(message, bot)
        if ret == 0:
            return msg
        print(bot.get_me())
    return "Received message: " + json.dumps(message, indent=2)


def command_handler(message: dict, bot: telebot.TeleBot) -> Tuple[int, str]:
    command_args: list = message["text"].split(" ")
    if command_args[0] == "/echo":
        bot.send_message(
            message["chat"]["id"],
            message["text"][6:],
            reply_to_message_id=message["message_id"],
        )
        return 0, "Echo command exec success"
    if command_args[0] == "/askgpt":
        try:
            answer = askgpt(message["text"][8:])
            bot.send_message(
                message["chat"]["id"],
                escape_markdown_v2(answer),
                reply_to_message_id=message["message_id"],
                parse_mode="MarkdownV2",
            )
        except Exception as e:
            bot.send_message(
                message["chat"]["id"], "Error:\n==========\n" + str(e.args)
            )
            ret = bot.forward_message(
                os.getenv("tg_admin"), message["chat"]["id"], message["message_id"]
            )
            tg_admin: str | None = os.getenv("tg_admin")
            if tg_admin:
                bot.send_message(
                    tg_admin,
                    "Error:\n==========\n"
                    + str(e.args)
                    + "\n\nTraceback:\n==========\n"
                    + traceback.format_exc(),
                    reply_to_message_id=ret.message_id,
                )
            print(
                "Error:\n==========\n"
                + str(e.args)
                + "\n\nTraceback:\n==========\n"
                + traceback.format_exc()
            )
            return 1, "Askgpt command exec error, traceback send to admin"
        else:
            return 0, "Askgpt command exec success"

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


def askgpt(prompt: str) -> str:
    url = os.getenv("OPENAI_API_URL")
    payload = {
        "model": os.getenv("OPENAI_MODEL"),
        "messages": [
            {
                "role": "system",
                "content": "You are an awesome chatbot"
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    }
    headers = {
        "Authorization": "Bearer " + os.getenv("OPENAI_API_KEY")
    }

    response = requests.post(url, json=payload, headers=headers, stream=False).json()
    # print(response.text)
    
    print("Answer:" + response['choices'][0]['message']['content'])
    return response['choices'][0]['message']['content']


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
            info_messages.append(f"INFO: These RSS links are already subscribed: {', '.join(duplicate_links)}")

        # 更新订阅配置
        new_rss_urls = list(set(chat_subscribe).union(rss_links))
        collection.update_one(
            {"type": "rss"}, {"$set": {"subscribe_info.{}".format(chat_id): new_rss_urls}}, upsert=True
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
                warning_message = f"WARNING: Link '{link}' not found in current subscriptions."
                info_messages.append(warning_message)

        # 更新配置文档
        collection.update_one(
            {"type": "rss"}, {"$set": {"subscribe_info.{}".format(chat_id): list(current_rss_urls)}}
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
    escape_chars = '_*[]()~`>#+-=|{}.!\\'
    code_block_delimiter = '```'

    escaped_text = ''
    code_block_open = False
    last_pos = 0

    # Find all occurrences of triple backticks
    for match in re.finditer(r'(```)', text):
        start, end = match.span()

        # If we find an opening delimiter and we're not already in a code block
        if not code_block_open:
            # Escape section before code block
            for char in text[last_pos:start]:
                if char in escape_chars and char != '`':  # Single backticks (inline code) should be escaped
                    escaped_text += '\\' + char
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
        if char in escape_chars and char != '`':  # Again, make sure to escape single backticks
            escaped_text += '\\' + char
        else:
            escaped_text += char
    print(escaped_text)
    return escaped_text

# 写一个 Hello World 程序在 Python 中是非常简单的。下面是一个基本示例：
# ```python
# print("Hello, World!")
# ```
# 要运行这个程序，你需要有 Python 安装在你的计算机上。然后你可以把这段代码保存到一个文件中，通常以 `.py` 结尾（例如: `hello_world.py`），然后在命令行中运行这个文件。例如，如果你使用的是 Windows 系统，可以在命令提示符中输入：
# ```bash
# python hello_world.py
# ```
# 如果你使用的是 Linux 或 macOS，你可能需要这样执行：
# ```bash
# python3 hello_world.py
# ```
# 在某些系统中，你可能需要确保 Python 的安装路径被添加到了环境变量中，否则你可能需要使用完整的路径来运行 Python，像这样：
# ```bash
# /path/to/python3 hello_world.py
# ```
# 当你运行这个 Python 脚本时，它会在终端或命令行窗口中打印出 "Hello, World!"。
# markdown_text = (
#     "写一个 Hello World 程序在 Python 中是非常简单的。下面是一个基本示例：\n"
#     "```python\n"
#     'print("Hello, World!")\n'
#     "```\n"
#     "要运行这个程序，你需要有 Python 安装在你的计算机上。然后你可以把这段代码保存到一个文件中，通常以 `.py` 结尾（例如: `hello_world.py`），然后在命令行中运行这个文件。例如，如果你使用的是 Windows 系统，可以在命令提示符中输入：\n"
#     "```bash\n"
#     "python hello_world.py\n"
#     "```\n"
#     "如果你使用的是 Linux 或 macOS，你可能需要这样执行：\n"
#     "```bash\n"
#     "python3 hello_world.py\n"
#     "```\n"
#     "在某些系统中，你可能需要确保 Python 的安装路径被添加到了环境变量中，否则你可能需要使用完整的路径来运行 Python，像这样：\n"
#     "```bash\n"
#     "/path/to/python3 hello_world.py\n"
#     "```\n"
#     "当你运行这个 Python 脚本时，它会在终端或命令行窗口中打印出 \"Hello, World!\"。"
# )

# escaped_text = escape_markdown_v2(markdown_text)
# print(escaped_text)

# bot = telebot.TeleBot(os.getenv("TELEGRAM_BOT_TOKEN"))
# bot.send_message(
#     os.getenv("MASTER_CHAT_ID"),
#     escaped_text,
#     parse_mode="MarkdownV2",
# )