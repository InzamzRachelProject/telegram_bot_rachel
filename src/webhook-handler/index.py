# -*- coding: utf8 -*-
from math import log
from cgitb import text
from hashlib import md5
from http import client
import json
import time
import telebot
from telebot import types
import os
import redis
import traceback
import requests
import logging
import re
import base64
import pymongo
from pymongo import MongoClient
from typing import Tuple, List
from modules.ask_ai import pic_generator, askgpt, chat_with_ai
from modules.redis_keys import redis_key
from modules.card_maker import send_quote_pic_to_telegram
from modules.note_forward import push_channel
from modules.memory import (
    get_all_memory_users,
    get_memory_by_user_id,
    delete_memories,
)
from modules.score import handle_score_callback, handle_score_command

logger = logging.getLogger()

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

CHAT_SUPPORT_MODULES = [
    "qwen3-max",
    "qwen-plus",
    "qwen-plus-latest",
    "qwen-plus-character"
]

TEMP_JSON = """{
    "author": "衣笠彰梧",
    "chapter": "",
    "color": "黄色",
    "comments": "",
    "content": "总之，我唯独清楚轻井泽今天是要持续她的方针——贬低我了。",
    "date": "April 20, 2025",
    "from": "欢迎来到实力至上主义的教室 7.5",
    "type": 1
}"""


TEMP_JSON_CHAR = """{
  "images": {
    "large": "https://lain.bgm.tv/pic/crt/l/80/4a/53767_crt_iatMC.jpg?r=1646570423"
  },
  "name": "堀北鈴音",
  "relation": "主角",
  "actors": [
    {
      "images": {
        "large": "https://lain.bgm.tv/pic/crt/l/a1/78/19339_prsn_3Dg35.jpg?r=1694799715"
      },
      "name": "鬼頭明里",
      "short_summary": "鬼頭明里（きとう あかり）は、日本の女性声優である。ラクーンドッグ所属。\r\nあだ名は「あかりん」。\r\n\r\n10月16日生まれ、愛知県出身、血液型B型、153cm。プロ・フィット声優養成所を経て、現事務所に2015年4月から所属。\r\n趣味は絵を描くこと、歌うこと。特技は絵を描くこと、歌うこと、湯切り。",
      "career": [
        "artist",
        "seiyu"
      ],
      "id": 19339,
      "type": 1,
      "locked": false
    }
  ],
  "type": 1,
  "from": "欢迎来到实力至上主义的教室"
}"""

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


def handler(event, context):
    """
    主处理函数，每次调用随机处理一条笔记
    
    支持通过环境变量 CLEAR_SYNC_CONFIG 或 event 参数 clear_sync_config 控制清空配置
    """
    try:
        # 解析 event，如果是 bytes 则先解码为字符串再解析 JSON
        event_dict = {}
        if event:
            if isinstance(event, bytes):
                try:
                    event_str = event.decode('utf-8')
                    event_dict = json.loads(event_str) if event_str else {}
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    logger.warning(f"Failed to parse event as JSON: {e}, using empty dict")
                    event_dict = {}
            elif isinstance(event, str):
                try:
                    event_dict = json.loads(event)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse event string as JSON: {e}, using empty dict")
                    event_dict = {}
            elif isinstance(event, dict):
                event_dict = event
        print("event_dict: ", event_dict, flush=True)
        return main_handler(event_dict, context)
    except Exception as e:
        logger.error(f"Error in handler: {str(e)}", exc_info=True)
        return {"error": str(e)}

def main_handler(event, context):
    # 对 webhook 进行鉴权
    stoken = event.get("headers", {}).get("x-telegram-bot-api-secret-token", None)
    if stoken == None:
        stoken = event.get("headers", {}).get("X-Telegram-Bot-Api-Secret-Token", None)
    if stoken != os.getenv("telegram_bot_api_secret_token"):
        return "Api auth failed"
    print("Received event: " + json.dumps(event))
    tele_token = os.getenv("tele_token")

    if not tele_token:
        return "No tele_token found"

    bot = telebot.TeleBot(tele_token)

    # 解析 webhook body（兼容 str / dict / base64）
    raw_body = event.get("body", "{}")
    if event.get("isBase64Encoded") and isinstance(raw_body, str):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    if isinstance(raw_body, dict):
        update = raw_body
    elif isinstance(raw_body, (bytes, bytearray)):
        update = json.loads(raw_body.decode("utf-8"))
    else:
        update = json.loads(str(raw_body))
    print("Received update: " + json.dumps(update, indent=2, ensure_ascii=False), flush=True)

    # Inline 积分按钮
    callback_query = update.get("callback_query")
    if callback_query:
        data = callback_query.get("data") or ""
        print(f"callback_query data={data!r}", flush=True)
        if data.startswith("score:"):
            from_id = str(callback_query.get("from", {}).get("id", "")).strip()
            admin_id = str(os.getenv("tg_admin", "")).strip()
            if from_id != admin_id:
                try:
                    bot.answer_callback_query(
                        callback_query.get("id"),
                        text="仅管理员可用",
                        show_alert=True,
                    )
                except Exception:
                    pass
                return "Score callback forbidden"
            ret, msg = handle_score_callback(callback_query, bot)
            print(f"score callback result: ret={ret} msg={msg}", flush=True)
            return msg if ret == 0 else f"Score callback failed: {msg}"
        try:
            bot.answer_callback_query(callback_query.get("id"))
        except Exception:
            pass
        return "Ignored non-score callback"

    message = update.get("message", {})
    if not message:
        return "No message in update"

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

        msg_config.update_one(
            {"channel_message_id": forward_from_message_id},
            {
                "$set": {
                    "reply_msg_info": reply_msg_info, 
                    "chat_group_message_id": chat_group_message_id,
                    "chat_group": chat_group,
                }
            },
        )
        break

    # 处理新加的 /add_note 命令
    if (
        bot
        and "text" in message
        and "entities" in message
        and message["text"].startswith("/add_note")
    ):
        bot = telebot.TeleBot(tele_token)
        raw_text = message["text"].replace("/add_note", "").strip()
        raw_text = raw_text.replace('\\"', '"')
        try:
            print("raw_text: ", raw_text, flush=True)
            x = json.loads(raw_text)
            """{
                "author": "衣笠彰梧",
                "chapter": "",
                "color": "黄色",
                "comments": "",
                "content": "总之，我唯独清楚轻井泽今天是要持续她的方针——贬低我了。",
                "date": "April 20, 2025",
                "from": "欢迎来到实力至上主义的教室 7.5",
                "speaker": "衣笠彰梧",
                "character_comment": "轻井泽惠",
                "type": 1
            }"""
            if x.get("from", None) == None:
                bot.send_message(
                    message["chat"]["id"],
                    "🤖 Invalid JSON format, from is empty",
                    reply_to_message_id=message["message_id"],
                )
                return "🤖 Invalid JSON format: " + raw_text

            client = MongoClient(os.getenv("MONGODB_ATLAS_URI"))
            db = client.get_database("BooksNotes")
            collections = db.get_collection(x["from"])
            print("collections" + str(collections), flush=True)
            
            content = x["content"]
            contenthash = md5(content.encode("utf-8")).hexdigest()
            x["contenthash"] = contenthash
        
            # 创建临时对象用于哈希计算（排除hash和sync_flag字段）
            temp_obj = {k: v for k, v in x.items() if k not in ('hash', 'sync_flag')}
            temp_obj['hash'] = '0'  # 设置临时哈希值
            
            # 计算完整对象哈希
            json_str = json.dumps(temp_obj, sort_keys=True).encode('utf-8')
            new_hash = md5(json_str).hexdigest()
            x['hash'] = new_hash
            # 查询数据库中的现有记录
            existing = collections.find_one({"contenthash": contenthash})
        
            # 处理同步标志逻辑
            if existing:
                # 当哈希值变化时设置同步标志
                if existing.get('hash') != new_hash:
                    x['sync_flag'] = 1
                    print("sync_flag set 1", flush=True)
                else:
                    # 保留原有同步标志值
                    x['sync_flag'] = existing.get('sync_flag', 0)
                    print("sync_flag set 0", flush=True)
            else:
                # 新记录默认需要同步
                x['sync_flag'] = 1
                print("sync_flag set 1", flush=True)

            # print(f"note: {str(x)}")
            upd_rst = collections.update_one(
                {"contenthash": x["contenthash"]}, {"$set": x}, upsert=True
            )
            if os.environ.get("DEBUG"):
                print(f"push to atlas: {x['contenthash']}")
            collections.create_index(
                [("contenthash", pymongo.ASCENDING)], unique=True, name="contenthash"
            )
            bot.send_message(
                message["chat"]["id"],
                "🤖 Added note to atlas: " + x["contenthash"] + " " + str(upd_rst),
                reply_to_message_id=message["message_id"],
            )
            return "🤖 Added note to atlas: " + x["contenthash"] + " " + str(upd_rst)

        except Exception as e:
            bot.send_message(
                message["chat"]["id"],
                "🤖 Invalid JSON format," +str(e)  + " copy the template below and edit it\n\n" + TEMP_JSON,
                reply_to_message_id=message["message_id"],
            )
            print(
                "🤖 Invalid JSON format," +str(e)  + " copy the template below and edit it\n\n" + TEMP_JSON
            )
            print(traceback.format_exc())
            return "🤖 Invalid JSON format: " + raw_text

    # 处理新加的 /add_charactor 命令
    elif (
        bot
        and "text" in message
        and "entities" in message
        and message["text"].startswith("/add_charactor")
    ):
        bot = telebot.TeleBot(tele_token)
        raw_text = message["text"].replace("/add_charactor", "").strip()
        raw_text = raw_text.replace('\\"', '"')
        try:
            print("raw_text: ", raw_text, flush=True)
            x = json.loads(raw_text)
            # 检查必填字段
            if not x.get("name"):
                raise ValueError("Missing required field 'name'")
            if not x.get("from"):
                raise ValueError("Missing required field 'from'")
            if not x.get("images") or not isinstance(x["images"], dict) or not x["images"].get("large"):
                raise ValueError("Missing required field 'images.large'")
            
            client = MongoClient(os.getenv("MONGODB_ATLAS_URI"))
            db = client.get_database("ExtraCharactor")
            collection_name = x["from"].split(maxsplit=1)[0] if " " in x["from"] else x["from"]
            collection = db.get_collection(collection_name)

            # ========== 新增数据清洗逻辑 ==========
            def cleanup_duplicates(col):
                """
                清理重复的 name+from 组合，保留最新（最大id）的记录
                返回清理的文档数量
                """
                pipeline = [
                    {"$group": {
                        "_id": {"name": "$name", "from": "$from"},
                        "dups": {"$push": "$_id"},
                        "maxId": {"$max": "$id"},
                        "count": {"$sum": 1}
                    }},
                    {"$match": {"count": {"$gt": 1}}}
                ]
                
                deleted_count = 0
                for group in col.aggregate(pipeline):
                    # 删除除最大id之外的所有文档
                    delete_filter = {
                        "_id": {"$in": group["dups"]},
                        "id": {"$ne": group["maxId"]}
                    }
                    result = col.delete_many(delete_filter)
                    deleted_count += result.deleted_count
                    print(f"Cleaned {result.deleted_count} duplicates for {group['_id']}")
                return deleted_count

            # 先执行数据清洗再创建索引
            try:
                # 尝试创建唯一索引（可能因重复数据失败）
                collection.create_index(
                    [("name", pymongo.ASCENDING), ("from", pymongo.ASCENDING)],
                    unique=True,
                    name="name_from_unique"
                )
            except pymongo.errors.OperationFailure as e:
                if "duplicate key" in str(e):
                    print("Detected duplicate data, starting cleanup...")
                    cleaned = cleanup_duplicates(collection)
                    print(f"Cleaned {cleaned} duplicate documents")
                    # 重试创建索引
                    collection.create_index(
                        [("name", pymongo.ASCENDING), ("from", pymongo.ASCENDING)],
                        unique=True,
                        name="name_from_unique"
                    )
                else:
                    raise
            # ========== 清洗逻辑结束 ==========

            # 检查现有文档（使用清洗后的数据）
            existing_doc = collection.find_one({"name": x["name"], "from": x["from"]})
            
            # ID处理逻辑
            if existing_doc:
                # 强制使用现有ID（防止脏数据残留）
                x["id"] = existing_doc["id"]
                print(f"Updating existing entry ID: {x['id']}")
            else:
                if "id" not in x:
                    # 更安全的ID生成方式（考虑并发情况）
                    max_id_doc = collection.find_one(
                        sort=[("id", pymongo.DESCENDING)],
                        projection={"id": 0}
                    )
                    # 防止部分老数据没有id字段
                    try:
                        new_id = max_id_doc["id"] + 1 if max_id_doc else 1
                    except KeyError:
                        new_id = 1
                    
                    # 防止ID冲突的回溯机制
                    while collection.count_documents({"id": new_id}, limit=1) > 0:
                        new_id += 1
                    x["id"] = new_id
                    
            last_updated = time.time()
            x["last_updated"] = last_updated
            
            # 使用替换模式更新（替换整个文档）
            result = collection.replace_one(
                {"id": x["id"]},
                x,
                upsert=True
            )
            
            # 确保ID索引存在
            if "id" not in collection.index_information():
                collection.create_index(
                    [("id", pymongo.ASCENDING)],
                    name="id"
                )

            # 构造响应消息
            action = "更新" if result.matched_count > 0 else "添加"
            reply_msg = f"🤖 成功{action}角色，ID: {x['id']} (匹配: {result.matched_count}, 修改: {result.modified_count})"
            bot.send_message(
                message["chat"]["id"],
                reply_msg,
                reply_to_message_id=message["message_id"],
            )
            return reply_msg
            
        except pymongo.errors.DuplicateKeyError as e:
            error_msg = f"🤖 数据冲突：请检查以下字段的唯一性：\n- ID: {x.get('id')}\n- 名称: {x['name']}\n- 来源: {x['from']}\n错误详情：{str(e)}"
            bot.send_message(
                message["chat"]["id"],
                error_msg,
                reply_to_message_id=message["message_id"],
            )
            return error_msg
        # ... 其他异常处理保持不变 ...
        except json.JSONDecodeError as e:
            error_msg = f"🤖 JSON解析错误：{str(e)}\n请检查JSON格式并参考示例模板。\n{TEMP_JSON_CHAR}"
            bot.send_message(
                message["chat"]["id"],
                error_msg,
                reply_to_message_id=message["message_id"],
            )
            return error_msg
        except ValueError as e:
            error_msg = f"🤖 数据验证失败：{str(e)}\n{TEMP_JSON_CHAR}"
            bot.send_message(
                message["chat"]["id"],
                error_msg,
                reply_to_message_id=message["message_id"],
            )
            return error_msg
        except Exception as e:
            error_msg = f"🤖 处理请求时发生错误：{str(e)}"
            bot.send_message(
                message["chat"]["id"],
                error_msg,
                reply_to_message_id=message["message_id"],
            )
            print(traceback.format_exc())
            return error_msg
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
        return "Pic command processed"

    # 处理普通文本消息（非命令），自动调用大模型
    if (
        bot
        and "text" in message
        and text
        and not text.startswith("/")
        and forward_from_chat_id is None
    ):
        try:
            bot = telebot.TeleBot(tele_token)
            model = os.getenv("CHAT_OPENAI_MODEL", "qwen-plus-character")
            
            # 判断模型是否支持
            if model not in CHAT_SUPPORT_MODULES:
                return "Model not supported"
            
            # 发送"正在思考"消息
            resp = bot.send_message(
                message["chat"]["id"],
                "Rachel 绞尽脑汁...",
                reply_to_message_id=message["message_id"],
            )

            # 调用普通对话函数获取回复
            # 传递平台和用户ID信息，记忆系统会自动从MemOS获取相关记忆
            platform = "telegram"
            platform_user_id = str(message["from"]["id"])
            
            answer = chat_with_ai(
                text,
                model,
                str(message["from"]["id"]),  # user_id用于Redis上下文（保持向后兼容）
                memory=None,  # 设置为None，让函数自动从MemOS获取
                platform=platform,
                platform_user_id=platform_user_id,
            )
            
            # 编辑消息，显示回复
            bot.edit_message_text(
                escape_markdown_v2(answer),
                message["chat"]["id"],
                resp.message_id,
                parse_mode="MarkdownV2",
            )
            return "Normal message processed with AI"
        except Exception as e:
            error_msg = f"处理消息时出错：{str(e)}"
            print(error_msg, flush=True)
            print(traceback.format_exc(), flush=True)
            try:
                bot.send_message(
                    message["chat"]["id"],
                    error_msg,
                    reply_to_message_id=message["message_id"],
                )
            except:
                pass
            return "Error processing normal message"

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

    # /score*（动作/翻页/录入，仅管理员）
    score_cmd = command_args[0].split("@")[0]
    if score_cmd == "/score" or score_cmd.startswith("/score_"):
        if str(message["from"]["id"]).strip() != str(os.getenv("tg_admin", "")).strip():
            bot.send_message(
                message["chat"]["id"],
                "只有管理员可以使用 /score 命令。",
                reply_to_message_id=message["message_id"],
            )
            return 1, "Only administrators are allowed to use /score commands."
        return handle_score_command(message, bot, command_args)
    if command_args[0].startswith("/askgptclear"):
        r.delete(redis_key(f'{message["from"]["id"]}_context'))
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
                message["text"][len(command_args[0]) :],
                module,
                str(message["from"]["id"]),
                platform="telegram",
                platform_user_id=str(message["from"]["id"]),
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

    # 检查是否是 /memory 命令
    if command_args[0] == "/memory":
        # 检查是否是管理员
        if str(message["from"]["id"]) != os.getenv("tg_admin"):
            bot.send_message(
                message["chat"]["id"],
                "只有管理员可以使用 /memory 命令。",
                reply_to_message_id=message["message_id"],
            )
            return 1, "Only administrators are allowed to use /memory commands."
        
        # 获取页码参数（默认为1）
        current_page = 1
        if len(command_args) > 1:
            try:
                current_page = int(command_args[1])
            except ValueError:
                current_page = 1
        
        # 获取所有有记忆的用户
        users = get_all_memory_users()
        if not users:
            bot.send_message(
                message["chat"]["id"],
                "当前没有用户有记忆记录。",
                reply_to_message_id=message["message_id"],
            )
            return 0, "No memory users found"
        
        # 分页设置
        users_per_page = 5
        total_pages = (len(users) + users_per_page - 1) // users_per_page
        current_page = max(1, min(current_page, total_pages))  # 确保页码在有效范围内
        
        # 获取当前页的用户
        start_idx = (current_page - 1) * users_per_page
        end_idx = start_idx + users_per_page
        page_users = users[start_idx:end_idx]
        
        # 构建消息文本
        message_text = f"有记忆的用户列表 (第 {current_page}/{total_pages} 页，共 {len(users)} 个用户):\n\n"
        for idx, user in enumerate(page_users, start=1):
            user_id_str = user.get("user_id", "")
            message_text += f"{start_idx + idx}. {user_id_str}\n"
        
        # 构建回复键盘（包含user_id按钮和翻页按钮）
        keyboard = build_memory_reply_keyboard(page_users, current_page, total_pages)
        
        # 发送带按钮的消息
        bot.send_message(
            message["chat"]["id"],
            message_text,
            reply_to_message_id=message["message_id"],
            reply_markup=keyboard
        )
        return 0, "Memory command exec success"
    
    # 检查是否是 /memory_page 命令（用于翻页）
    if command_args[0].startswith("/memory_page"):
        # 检查是否是管理员
        if str(message["from"]["id"]) != os.getenv("tg_admin"):
            bot.send_message(
                message["chat"]["id"],
                "只有管理员可以使用 /memory_page 命令。",
                reply_to_message_id=message["message_id"],
            )
            return 1, "Only administrators are allowed to use /memory_page commands."
        
        # 解析页码
        page_num = 1
        # 首先尝试从命令本身解析，如 /memory_page_2
        try:
            page_num = int(command_args[0].split("_")[-1])
        except (ValueError, IndexError):
            # 如果失败，尝试从参数解析，如 /memory_page 2
            if len(command_args) > 1:
                try:
                    page_num = int(command_args[1])
                except ValueError:
                    page_num = 1
        
        # 获取所有有记忆的用户
        users = get_all_memory_users()
        if not users:
            bot.send_message(
                message["chat"]["id"],
                "当前没有用户有记忆记录。",
                reply_to_message_id=message["message_id"],
            )
            return 0, "No memory users found"
        
        # 分页设置
        users_per_page = 5
        total_pages = (len(users) + users_per_page - 1) // users_per_page
        page_num = max(1, min(page_num, total_pages))  # 确保页码在有效范围内
        
        # 获取当前页的用户
        start_idx = (page_num - 1) * users_per_page
        end_idx = start_idx + users_per_page
        page_users = users[start_idx:end_idx]
        
        # 构建消息文本
        message_text = f"有记忆的用户列表 (第 {page_num}/{total_pages} 页，共 {len(users)} 个用户):\n\n"
        for idx, user in enumerate(page_users, start=1):
            user_id_str = user.get("user_id", "")
            message_text += f"{start_idx + idx}. {user_id_str}\n"
        
        # 构建回复键盘（包含user_id按钮和翻页按钮）
        keyboard = build_memory_reply_keyboard(page_users, page_num, total_pages)
        
        # 发送带按钮的消息
        bot.send_message(
            message["chat"]["id"],
            message_text,
            reply_to_message_id=message["message_id"],
            reply_markup=keyboard
        )
        return 0, "Memory page command exec success"
    
    # 检查是否是 /search_memory 命令
    if command_args[0] == "/search_memory":
        # 只有 master/管理员可以调用记忆相关接口
        if str(message["from"]["id"]) != os.getenv("tg_admin"):
            bot.send_message(
                message["chat"]["id"],
                "只有管理员（master）可以使用 /search_memory 命令。",
                reply_to_message_id=message["message_id"],
                reply_markup=types.ReplyKeyboardRemove(),
            )
            return 1, "Only master is allowed to use /search_memory commands."

        # 参数：/search_memory <user_id> [page] [size]
        if len(command_args) < 2:
            bot.send_message(
                message["chat"]["id"],
                "用法: /search_memory <user_id> [page] [size]\n例如: /search_memory telegram_123456 1 5",
                reply_to_message_id=message["message_id"],
                reply_markup=types.ReplyKeyboardRemove(),
            )
            return 1, "Missing user_id parameter"

        user_id = command_args[1]

        # 解析分页参数（page + size），size 主要影响每类返回条数，后续仍会按每类最多2条展示
        page = 1
        size = 2  # 默认每类两条
        if len(command_args) >= 3:
            try:
                page = int(command_args[2])
            except ValueError:
                page = 1
        if len(command_args) >= 4:
            try:
                size = int(command_args[3])
            except ValueError:
                size = 5

        if page < 1:
            page = 1
        if size < 1:
            size = 1
        if size > 50:
            size = 50

        # 调用 MemOS /get/memory 接口（size 为每类返回条数上限）
        result = get_memory_by_user_id(
            user_id=user_id,
            page=page,
            size=size,
            include_preference=True,
            include_tool_memory=True,
        )

        if not isinstance(result, dict) or "error" in result:
            error_msg = result.get("error") if isinstance(result, dict) else "unknown error"
            bot.send_message(
                message["chat"]["id"],
                f"调用记忆接口失败: {error_msg}",
                reply_to_message_id=message["message_id"],
                reply_markup=types.ReplyKeyboardRemove(),
            )
            return 1, "Search memory failed"

        data = result.get("data", {}) if isinstance(result, dict) else {}

        # 按类型分别取出列表
        fact_list = []
        pref_list = []
        tool_list = []

        if isinstance(data, dict):
            raw_fact = data.get("memory_detail_list") or data.get("memory_list") or []
            raw_pref = data.get("preference_detail_list") or data.get("preference_list") or []
            raw_tool = data.get("tool_memory_detail_list") or data.get("tool_memory_list") or []

            # 过滤掉没有 ID 的条目（无法删除），并且每类最多保留 2 条，方便检索删除
            def _normalize_with_limit(items, max_count: int = 2):
                cleaned = []
                if not isinstance(items, list):
                    return cleaned
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    mem_id = str(it.get("id") or it.get("memory_id") or "").strip()
                    if not mem_id:
                        continue
                    cleaned.append(it)
                    if len(cleaned) >= max_count:
                        break
                return cleaned

            fact_list = _normalize_with_limit(raw_fact, 2)
            pref_list = _normalize_with_limit(raw_pref, 2)
            tool_list = _normalize_with_limit(raw_tool, 2)

        # 组装一个总列表用于生成删除按钮（最多 6 条）
        memories: List[dict] = []
        for it in fact_list:
            mem = dict(it)
            mem.setdefault("_memory_type", "fact")
            memories.append(mem)
        for it in pref_list:
            mem = dict(it)
            mem.setdefault("_memory_type", "preference")
            memories.append(mem)
        for it in tool_list:
            mem = dict(it)
            mem.setdefault("_memory_type", "tool")
            memories.append(mem)

        if not memories:
            bot.send_message(
                message["chat"]["id"],
                f"用户 {user_id} 在第 {page} 页没有可展示的记忆（或未返回可删除的记录）。",
                reply_to_message_id=message["message_id"],
                reply_markup=types.ReplyKeyboardRemove(),
            )
            return 0, "No memories found"

        # 构造展示文本（按照三种类型分别展示；每类最多两条，内容完整）
        lines: List[str] = []
        total_pages = data.get("pages")
        current_page = data.get("current", page)
        # 使用接口返回的 total 字段作为当前查询可用的总条数信息
        size_per_type = data.get("total", data.get("size", size))
        if isinstance(total_pages, int) and total_pages > 0:
            lines.append(
                f"用户 {user_id} 的记忆（第 {current_page} / {total_pages} 页，每类最多 {size_per_type} 条）："
            )
        else:
            lines.append(f"用户 {user_id} 的记忆（第 {page} 页，每类最多 {size_per_type} 条）：")
        lines.append("")

        # 事实记忆：直接输出完整字段 JSON
        if fact_list:
            lines.append("【事实记忆（memory_detail_list）】")
            for idx, mem in enumerate(fact_list, start=1):
                try:
                    mem_json = json.dumps(mem, ensure_ascii=False, indent=2)
                except Exception:
                    mem_json = str(mem)
                lines.append(f"{idx}. {mem_json}")
                lines.append("")  # 空行分隔

        # 偏好记忆：直接输出完整字段 JSON
        if pref_list:
            lines.append("【偏好记忆（preference_detail_list）】")
            for idx, mem in enumerate(pref_list, start=1):
                try:
                    mem_json = json.dumps(mem, ensure_ascii=False, indent=2)
                except Exception:
                    mem_json = str(mem)
                lines.append(f"{idx}. {mem_json}")
                lines.append("")

        # 工具记忆：直接输出完整字段 JSON
        if tool_list:
            lines.append("【工具记忆（tool_memory_detail_list）】")
            for idx, mem in enumerate(tool_list, start=1):
                try:
                    mem_json = json.dumps(mem, ensure_ascii=False, indent=2)
                except Exception:
                    mem_json = str(mem)
                lines.append(f"{idx}. {mem_json}")
                lines.append("")

        message_text = "\n".join(lines)

        # 构建删除/翻页/清空按钮键盘
        keyboard = build_memory_manage_keyboard(memories, user_id, page, size)

        bot.send_message(
            message["chat"]["id"],
            message_text,
            reply_to_message_id=message["message_id"],
            reply_markup=keyboard,
        )
        return 0, "Search memory command exec success"

    # 删除记忆命令 /delete_memory <memory_id> [memory_id2 ...]
    if command_args[0] == "/delete_memory":
        if str(message["from"]["id"]) != os.getenv("tg_admin"):
            bot.send_message(
                message["chat"]["id"],
                "只有管理员（master）可以使用 /delete_memory 命令。",
                reply_to_message_id=message["message_id"],
            )
            return 1, "Only master is allowed to use /delete_memory commands."

        if len(command_args) < 2:
            bot.send_message(
                message["chat"]["id"],
                "用法: /delete_memory <memory_id1> [memory_id2 ...]",
                reply_to_message_id=message["message_id"],
            )
            return 1, "Missing memory_ids"

        memory_ids = command_args[1:]
        result = delete_memories(memory_ids)

        if not isinstance(result, dict) or "error" in result:
            error_msg = result.get("error") if isinstance(result, dict) else "unknown error"
            bot.send_message(
                message["chat"]["id"],
                f"删除记忆失败: {error_msg}",
                reply_to_message_id=message["message_id"],
            )
            return 1, "Delete memory failed"

        bot.send_message(
            message["chat"]["id"],
            f"已请求删除记忆: {', '.join(memory_ids)}",
            reply_to_message_id=message["message_id"],
        )
        # 不移除键盘，以满足「点击删除按钮后其他按钮不会消失」
        return 0, "Delete memory command exec success"

    # 清空记忆相关按钮键盘
    if command_args[0] == "/clear_memory_keyboard":
        if str(message["from"]["id"]) != os.getenv("tg_admin"):
            bot.send_message(
                message["chat"]["id"],
                "只有管理员（master）可以清空记忆操作按钮。",
                reply_to_message_id=message["message_id"],
            )
            return 1, "Only master is allowed to clear memory keyboard."

        bot.send_message(
            message["chat"]["id"],
            "已清空记忆操作按钮。",
            reply_to_message_id=message["message_id"],
            reply_markup=types.ReplyKeyboardRemove(),
        )
        return 0, "Clear memory keyboard command exec success"

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
                prompt,
                module,
                str(message["from"]["id"]),
                base64_image=base64_image,
                platform="telegram",
                platform_user_id=str(message["from"]["id"]),
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


def build_memory_reply_keyboard(page_users: List[dict] = None, current_page: int = 1, total_pages: int = 1) -> types.ReplyKeyboardMarkup:
    """
    构建记忆用户列表的回复键盘，包含可点击的user_id按钮（最多5个）和翻页按钮
    点击user_id按钮后会发送 /search_memory user_id 命令
    点击翻页按钮后会发送 /memory_page_X 命令来刷新键盘
    
    Args:
        page_users: 用户列表（最多5个）
        current_page: 当前页码
        total_pages: 总页数
    
    Returns:
        回复键盘对象
    """
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    
    # 添加user_id按钮（最多5个）
    if page_users:
        buttons = []
        for user in page_users[:5]:  # 确保最多5个
            user_id_str = user.get("user_id", "")
            if user_id_str:
                # 按钮文本为 /search_memory user_id，点击后会发送这个命令
                button_text = f"/search_memory {user_id_str}"
                # 限制按钮文本长度（Telegram限制64字符）
                if len(button_text) > 64:
                    # 如果太长，截断user_id部分
                    max_user_id_len = 64 - len("/search_memory ")
                    truncated_user_id = user_id_str[:max_user_id_len]
                    button_text = f"/search_memory {truncated_user_id}"
                buttons.append(button_text)
        
        # 每行一个按钮
        for button_text in buttons:
            keyboard.add(types.KeyboardButton(button_text))
    
    # 添加翻页按钮
    if total_pages > 1:
        # 第一行：第一页、上一页、下一页、最后一页
        row1 = []
        if current_page > 1:
            row1.append(types.KeyboardButton("/memory_page_1"))
            row1.append(types.KeyboardButton(f"/memory_page_{current_page - 1}"))
        else:
            row1.append(types.KeyboardButton("/memory_page_1"))
            row1.append(types.KeyboardButton("/memory_page_1"))
        
        if current_page < total_pages:
            row1.append(types.KeyboardButton(f"/memory_page_{current_page + 1}"))
            row1.append(types.KeyboardButton(f"/memory_page_{total_pages}"))
        else:
            row1.append(types.KeyboardButton(f"/memory_page_{total_pages}"))
            row1.append(types.KeyboardButton(f"/memory_page_{total_pages}"))
        
        keyboard.add(*row1)
        
        # 第二行：前32页、前16页、前8页、前4页
        row2 = []
        for offset in [32, 16, 8, 4]:
            target_page = max(1, current_page - offset)
            row2.append(types.KeyboardButton(f"/memory_page_{target_page}"))
        keyboard.add(*row2)
        
        # 第三行：后4页、后8页、后16页、后32页
        row3 = []
        for offset in [4, 8, 16, 32]:
            target_page = min(total_pages, current_page + offset)
            row3.append(types.KeyboardButton(f"/memory_page_{target_page}"))
        keyboard.add(*row3)
    
    return keyboard


def build_memory_manage_keyboard(
    memories: List[dict],
    user_id: str,
    page: int,
    size: int,
) -> types.ReplyKeyboardMarkup:
    """
    为 /search_memory 结果构建管理键盘：
    - 每条记忆一个删除按钮：/delete_memory <memory_id>
    - 一行刷新 & 翻页按钮：/search_memory <user_id> <page> <size> 等
    - 底部一个清空按钮：/clear_memory_keyboard
    """
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)

    # 为每条有 ID 的记忆生成删除按钮（数量与展示条数一致）
    for mem in memories:
        mem_id = str(mem.get("id") or mem.get("memory_id") or "").strip()
        if not mem_id:
            continue
        # 文本形如：/delete_memory 123456
        btn_text = f"/delete_memory {mem_id}"
        # Telegram 按钮文本最长 64 字符，这里一般不会超，但仍做保护
        if len(btn_text) > 64:
            btn_text = btn_text[:64]
        keyboard.add(types.KeyboardButton(btn_text))

    # 刷新按钮：重复当前命令
    refresh_btn = types.KeyboardButton(f"/search_memory {user_id} {page} {size}")

    # 翻页按钮：上一页 / 下一页，始终提供，交给业务决定是否有数据
    prev_page = max(1, page - 1)
    next_page = page + 1
    prev_btn = types.KeyboardButton(f"/search_memory {user_id} {prev_page} {size}")
    next_btn = types.KeyboardButton(f"/search_memory {user_id} {next_page} {size}")
    keyboard.add( prev_btn, refresh_btn,next_btn)

    # 全局清空按钮
    keyboard.add(types.KeyboardButton("/clear_memory_keyboard"))

    return keyboard


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
