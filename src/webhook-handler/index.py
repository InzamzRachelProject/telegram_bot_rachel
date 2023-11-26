# -*- coding: utf8 -*-
import json
import telebot
import os
import openai
import traceback
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
            bot.send_message(
                message["chat"]["id"],
                askgpt(message["text"][8:]),
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
    openai.api_key = os.getenv("openai_api_key")
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo-1106",
        messages=[
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )
    print("Answer:\n" + completion.choices[0].message.content)
    return completion.choices[0].message.content


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
