# -*- coding: utf8 -*-
from cgitb import text
from datetime import datetime
from hashlib import md5
from http import client
import json
import time
import telebot
import os
import traceback
import requests
import re
import base64
import pymongo
from pymongo import MongoClient
from typing import Tuple, List
from modules.cos_wrapper import upload_file_to_cos
from PIL import Image


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


def get_character_info_from_bgm(character, bookname, mongo_uri = os.getenv("MONGODB_ATLAS_URI")):
    try:
        book_name_search_key = bookname.split()[0]
        print("book_name_search_key: ", book_name_search_key)
    
        url = f"https://api.bgm.tv/search/subject/{quote(book_name_search_key)}?type=2&responseGroup=medium"
        headers = {
            "Authorization": "Bearer " + os.getenv("BANGUMI_TOKEN"),
            "User-Agent": "Misaka19614/CharacterInfo",
            "accept": "application/json",
        }
    
        print("url: ", url)
        response_json = requests.get(url, headers=headers, stream=False)
        response_json = response_json.json()
        print("response_json: ", response_json)
        time.sleep(0.1)
        results = response_json["results"]
        anime_list = response_json["list"]
        if anime_list == None:
            return None
        for anime in anime_list:
            anime_id = anime["id"]
            character_info = get_character_info_by_anime_id(anime_id, character, bookname, mongo_uri)
            print("character_info: ", character_info)
            if character_info != None:
                return character_info
        return None
    except Exception as e:
        return None


def get_image_size(image_path):
    with open(image_path, "rb") as f:
        with Image.open(f) as image:
            return image.size

import opencc

# 初始化简繁转换器，繁体转简体
converter = opencc.OpenCC('t2s')

def get_character_info_by_anime_id(anime_id, character_name, book_name, mongo_uri):
    # 转换角色名到简体中文
    converted_character_name = converter.convert(character_name)
    
    # 初始化角色信息模板
    character_info = {
        "name": character_name,
        "nickname": character_name,
        "bio": "",
        "avatar": "https://lain.bgm.tv/img/no_icon_subject.png",
        "birthDate": "unknown",
        "joinDate": "unknown",
        "lastActive": "unknown",
        "gender": "lgbtq",
        "group": book_name,
    }

    try:
        # 获取 MongoDB 集合名称（取书名第一个单词）
        collection_name = book_name.split(maxsplit=1)[0] if " " in book_name else book_name
        
        # 连接 ExtraCharactor 数据库
        client = MongoClient(mongo_uri, maxPoolSize=10, minPoolSize=5,)
        db = client.get_database("ExtraCharactor")
        collection = db.get_collection(collection_name)
        
        # 查询转换后的角色名
        db_char = collection.find_one({"name": converted_character_name})
        
        if db_char:
            print(f"Found character in MongoDB: {db_char['name']}")
            # 合并数据库中的图像数据
            if "images" in db_char and "large" in db_char["images"]:
                character_info["avatar"] = db_char["images"]["large"]
            # 合并其他字段（可选）
            character_info.update({
                k: db_char.get(k, v) 
                for k, v in character_info.items() 
                if k not in ["avatar"]
            })
        else:
            # 调用 BGM API 获取数据
            url = f"https://api.bgm.tv/v0/subjects/{anime_id}/characters"
            headers = {
                "Authorization": "Bearer " + os.getenv("BANGUMI_TOKEN"),
                "User-Agent": "Misaka19614/CharacterInfo",
            }
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
            
            # 匹配转换后的角色名
            for result in resp.json():
                if converter.convert(result["name"]) == converted_character_name:
                    character_info["avatar"] = result["images"]["large"]
                    # ==== 新增 MongoDB 更新逻辑 ====
                    try:
                        with MongoClient(os.getenv("MONGODB_ATLAS_URI"), maxPoolSize=10, minPoolSize=5) as client:
                            db = client["ExtraCharactor"]
                            collection = db[collection_name]
                            
                            # 更新或插入角色数据
                            collection.update_one(
                                {"name": converted_character_name},
                                {"$set": {
                                    "name": converted_character_name,
                                    "source": book_name,
                                    "images": result["images"],
                                    "last_updated": datetime.utcnow()
                                }},
                                upsert=True
                            )
                            print(f"Updated MongoDB record for {converted_character_name}")
                            
                    except Exception as e:
                        print(f"MongoDB update failed: {str(e)}")
                    # ==== 结束新增逻辑 ====
                    break

    except IndexError:
        print("Book name format invalid")
    except pymongo.errors.PyMongoError as e:
        print(f"MongoDB error: {str(e)}")
    except requests.exceptions.RequestException as e:
        print(f"BGM API error: {str(e)}")

    # 统一处理头像上传
    try:
        uid = md5(character_name.encode()).hexdigest()[:13]
        uid = f"anime-{anime_id}-{uid}"
        character_info["uuid"] = uid
        
        # 下载并处理头像
        with open(f"/tmp/{uid}.png", "wb") as f:
            f.write(requests.get(character_info["avatar"]).content)
        
        # 上传到 COS
        upload_file_to_cos(
            os.getenv("IMAGE_COS_BUCKET"),
            f"avatar/{uid}.png",
            f"/tmp/{uid}.png"
        )
        
        # 生成裁剪后的 URL
        width, height = get_image_size(f"/tmp/{uid}.png")
        min_size = min(width, height)
        character_info["avatar"] = (
            f"{os.getenv('IMAGE_COS_URL', 'https://image.inzamz.top/')}avatar/{uid}.png"
            f"?imageMogr2/cut/{min_size}x{min_size}/gravity/north/"
        )
        character_info["card_url"] = (
            f"https://char.misaka19614.com/profile/userId/{uid}"
            f"?random={int(time.time())}"
        )

    except Exception as e:
        print(f"Avatar processing failed: {str(e)}")
        character_info["avatar"] = "https://example.com/fallback.png"

    return character_info if character_info["avatar"] != "https://example.com/fallback.png" else None


def sync_messages(bot):
    """
    定期同步MongoDB中的笔记数据到Telegram群组
    功能：1.删除不存在消息 2.发送新增消息 3.更新现有消息
    """
    # 初始化全局计时
    global_start = time.time()
    stage_timings = {}

    try:
        # 阶段1：数据库连接
        connect_start = time.time()
        client = MongoClient(os.getenv("MONGODB_ATLAS_URI"))
        db = client.get_database("BooksNotes")
        msg_config = db.get_collection("MsgToBookname")
        stage_timings["db_connect"] = time.time() - connect_start
        print(f"===== 数据库连接耗时：{stage_timings['db_connect']:.3f}s =====")

        # 阶段2：获取配置数据
        config_query_start = time.time()
        config_docs = list(msg_config.find())
        stage_timings["config_query"] = time.time() - config_query_start
        print(f"===== 配置查询耗时：{stage_timings['config_query']:.3f}s，获取文档数：{len(config_docs)} =====")

        for doc in config_docs:
            doc_start = time.time()
            doc_id = str(doc['_id'])
            print(f"\n—— 开始处理文档 {doc_id} ——")

            try:
                # 阶段3：文档预处理
                preprocess_start = time.time()
                # 提取必要字段
                print("doc: ", doc)
                required_fields = {
                    "channel_message_id": doc.get("channel_message_id"),
                    "chat_group": doc.get("chat_group"),
                    "chat_group_message_id": doc.get("chat_group_message_id"),
                    "book_name": doc.get("book_name"),
                    "reply_msg_info": doc.get("reply_msg_info", {})
                }

                # 跳过字段不全的记录
                if None in required_fields.values():
                    print(f"[警告] 跳过不完整记录：{doc['_id']}")
                    continue
                stage_timings.setdefault("preprocess", 0)
                stage_timings["preprocess"] += time.time() - preprocess_start

                # 解包字段
                channel_msg_id = required_fields["channel_message_id"]
                chat_group = required_fields["chat_group"]
                chat_group_msg_id = required_fields["chat_group_message_id"]
                book_name = required_fields["book_name"]
                reply_msg_info = required_fields["reply_msg_info"].copy()
                
                # 阶段4：获取书籍数据
                book_query_start = time.time()
                book_collection = db.get_collection(book_name)
                current_notes = list(book_collection.find())
                book_query_time = time.time() - book_query_start
                current_hashes = {note.get("contenthash", 0) for note in current_notes}
                print(f"  ├── 书籍查询耗时：{book_query_time:.3f}s，获取笔记数：{len(current_notes)}")

                # 阶段5：删除过期消息
                existing_hashes = set(reply_msg_info.keys())
                stale_hashes = existing_hashes - current_hashes
                delete_start = time.time()
                deleted_count = 0
                print("existing_hashes: ", existing_hashes)
                print("current_hashes: ", current_hashes)
                print("stale_hashes: ", stale_hashes)
                for stale_hash in stale_hashes:
                    single_delete_start = time.time()
                    try:
                        bot.delete_message(chat_group, reply_msg_info[stale_hash])
                        del reply_msg_info[stale_hash]
                        single_delete_time = time.time() - single_delete_start
                        print(f"  ├── 删除消息 {stale_hash[:6]} 耗时：{single_delete_time:.3f}s")
                        deleted_count += 1
                    except Exception as e:
                        del reply_msg_info[stale_hash]
                        print(f"  ├── 删除失败 {stale_hash[:6]}（耗时：{time.time()-single_delete_start:.3f}s）：{str(e)}")
                total_delete_time = time.time() - delete_start
                print(f"  ├── 删除阶段总耗时：{total_delete_time:.3f}s，成功删除：{deleted_count}/{len(stale_hashes)}")

                # 阶段6：消息处理
                msg_process_start = time.time()
                processed_msgs = 0
                for note in current_notes:
                    note_start = time.time()
                    content_hash = note["contenthash"]
                    existing_msg_id = reply_msg_info.get(content_hash)

                    # 组装消息内容
                    text_parts = [f"📚 {note['content'].replace('&', '&amp;')}"]
                    preview_url = None

                    # 处理说话人信息
                    if note.get("speaker"):
                        speaker_link = get_character_info_from_bgm(note["speaker"], book_name)
                        text_parts.append(f"🎙️ {note['speaker'].replace('&', '&amp;')}")
                        if speaker_link:
                            preview_url = speaker_link

                    # 处理角色评论
                    if note.get("character_comment"):
                        comment_link = get_character_info_from_bgm(note["character_comment"], book_name)
                        text_parts.append(f"⚖️ {note['character_comment'].replace('&', '&amp;')}")
                        if comment_link:
                            preview_url = comment_link

                    if note["sync_flag"] == 0 and preview_url == note.get('preview_url', None):
                        print("Skip! ", note["sync_flag"], preview_url, note.get('preview_url', None))
                        continue 
                    print("note: ", note)
                    # 添加笔记
                    if note.get("note") and note["note"].strip():
                        text_parts.append(f"💬 {note['note'].replace('&', '&amp;')}")

                    # 标签处理计时
                    tag_start = time.time()
                    tags = note.get("tag", [])
                    if isinstance(tags, str):
                        tags = [tags]
                    elif not isinstance(tags, list):
                        tags = []
                    tag_str = ' '.join([f"#{t.strip()}" for t in tags]) if tags else ""
                    text_parts.append(tag_str)
                    tag_time = time.time() - tag_start
                    final_text = "\n".join(text_parts)

                    # 消息发送/更新计时
                    send_start = time.time()
                    if existing_msg_id:
                        # === 更新现有消息 ===
                        try:
                            if note["sync_flag"] != 0:
                                bot.edit_message_text(
                                    text=final_text,
                                    chat_id=chat_group,
                                    message_id=existing_msg_id,
                                    parse_mode="HTML",
                                    link_preview_options=telebot.types.LinkPreviewOptions(
                                        url=preview_url,
                                        prefer_small_media=True,
                                        show_above_text=True
                                    )
                                )
                                print(f"[更新] 已更新消息：{content_hash}")
                        except Exception as e:
                            book_collection.update_one(
                                {'contenthash': content_hash},
                                {'$set': {"sync_flag": 0, "preview_url": preview_url}},
                            )
                            print(f"[错误] 更新失败 {content_hash}：{str(e)}")
                    else:
                        # === 发送新消息 ===
                        try:
                            if note["sync_flag"] != 0:
                                sent_msg = bot.send_message(
                                    chat_id=chat_group,
                                    text=final_text,
                                    reply_to_message_id=chat_group_msg_id,
                                    parse_mode="HTML",
                                    link_preview_options=telebot.types.LinkPreviewOptions(
                                        url=preview_url,
                                        prefer_small_media=True,
                                        show_above_text=True
                                    )
                                )
                                reply_msg_info[content_hash] = sent_msg.message_id
                                print(f"[新增] 已发送消息：{content_hash}")
                        except Exception as e:
                            print(f"[错误] 发送失败 {content_hash}：{str(e)}")
                    send_time = time.time() - send_start

                    processed_msgs += 1
                    print(f"  ├── 笔记 {content_hash[:6]} 处理耗时：{time.time()-note_start:.3f}s， (标签处理：{tag_time:.3f}s，消息操作：{send_time:.3f}s)")
                    book_collection.update_one(
                        {'contenthash': content_hash},
                        {'$set': {"sync_flag": 0, "preview_url": preview_url}},
                    )
                    time.sleep(0.1)  # 控制API调用频率

                total_msg_time = time.time() - msg_process_start
                print(f"  ├── 消息处理总耗时：{total_msg_time:.3f}s，平均：{total_msg_time/len(current_notes):.3f}s/条")

                # 阶段7：数据库更新
                update_start = time.time()
                print("reply_msg_info: ", reply_msg_info)
                msg_config.update_one(
                    {"channel_message_id": channel_msg_id},
                    {"$set": {"reply_msg_info": reply_msg_info}}
                )
                update_time = time.time() - update_start
                print(f"  ├── 数据库更新耗时：{update_time:.3f}s")

            finally:
                doc_time = time.time() - doc_start
                stage_timings.setdefault("doc_process", 0)
                stage_timings["doc_process"] += doc_time
                print(f"  └── 文档 {doc_id} 总耗时：{doc_time:.3f}s")

    finally:
        # 最终统计
        total_time = time.time() - global_start
        print("\n===== 同步完成 =====")
        print(f"总耗时：{total_time:.2f}s")
        print(f"各阶段耗时分布：")
        print(f"├── 数据库连接：{stage_timings.get('db_connect',0):.2f}s")
        print(f"├── 配置查询：{stage_timings.get('config_query',0):.2f}s")
        print(f"├── 文档预处理：{stage_timings.get('preprocess',0):.2f}s")
        print(f"├── 单文档处理：{stage_timings.get('doc_process',0):.2f}s")
        print(f"└── 其他操作：{total_time - sum(stage_timings.values()):.2f}s")


def main_handler(event, context):
    tele_token = os.getenv("tele_token")
    if not tele_token:
        return "No tele_token found"

    bot = telebot.TeleBot(tele_token)
    sync_messages(bot)
    return True