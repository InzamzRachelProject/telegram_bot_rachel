# -*- coding: utf-8 -*-
import logging
import pymongo
import os
import random
import json
import time
import requests
from datetime import datetime
from typing import Optional, Dict, Tuple

logger = logging.getLogger()

client = None

def initialize(context):
    # 在initialize回调中创建客户端，可以实现在整个函数实例生命周期内复用该客户端
    global client
    client = pymongo.MongoClient(os.environ['MONGO_URL'])


def pre_stop(context):
    if client != None:
        client.close()


def parse_date_to_timestamp(date_str: str) -> str:
    """
    解析日期字符串转换为时间戳，失败则返回原字符串
    
    Args:
        date_str: 日期字符串，如 "April 20, 2025"
    
    Returns:
        时间戳字符串或原字符串
    """
    if not date_str:
        return date_str
    
    try:
        # 尝试解析常见格式
        # 格式1: "April 20, 2025"
        # 格式2: "2025-04-20"
        # 格式3: "20/04/2025"
        
        # 先尝试使用 dateutil.parser（如果可用）
        try:
            from dateutil import parser
            dt = parser.parse(date_str)
            return str(int(dt.timestamp()))
        except ImportError:
            pass
        
        # 手动解析常见格式
        formats = [
            "%B %d, %Y",  # April 20, 2025
            "%b %d, %Y",  # Apr 20, 2025
            "%Y-%m-%d",   # 2025-04-20
            "%d/%m/%Y",   # 20/04/2025
            "%m/%d/%Y",   # 04/20/2025
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return str(int(dt.timestamp()))
            except ValueError:
                continue
        
        # 如果所有格式都失败，返回原字符串
        return date_str
    except Exception as e:
        logger.warning(f"Failed to parse date '{date_str}': {e}, using original string")
        return date_str


def ensure_sync_config_collection(rachel_db) -> pymongo.collection.Collection:
    """
    确保配置库 collection 存在，不存在则创建
    
    Args:
        rachel_db: Rachel 数据库对象
    
    Returns:
        配置库 collection 对象
    """
    collection_name = "NoteSyncConfig"
    collection = rachel_db[collection_name]
    
    # 检查 collection 是否存在，如果不存在则创建索引
    try:
        # 创建唯一索引
        collection.create_index([("contenthash", pymongo.ASCENDING)], unique=True, name="contenthash_unique")
    except pymongo.errors.OperationFailure:
        # 索引可能已存在，忽略错误
        pass
    
    return collection


def get_random_note(books_notes_db) -> Optional[Tuple[str, Dict]]:
    """
    从所有笔记中随机获取一条笔记
    
    Args:
        books_notes_db: BooksNotes 数据库对象
    
    Returns:
        (book_name, note_dict) 或 None
    """
    # 获取所有 collection 名称
    all_collections = books_notes_db.list_collection_names()
    
    # 排除系统 collection
    system_collections = ["BookNoteConfig", "MsgToBookname"]
    book_collections = [c for c in all_collections if c not in system_collections]
    
    if not book_collections:
        logger.warning("No book collections found")
        return None
    
    # 随机选择一个 collection
    book_name = random.choice(book_collections)
    collection = books_notes_db[book_name]
    
    # 获取该 collection 中的笔记总数
    total_count = collection.count_documents({})
    if total_count == 0:
        logger.warning(f"No notes found in collection: {book_name}")
        return None
    
    # 随机选择一个索引
    random_index = random.randint(0, total_count - 1)
    
    # 获取随机笔记
    note = collection.find().skip(random_index).limit(1).next()
    
    return (book_name, note)


def check_note_should_sync(note: Dict, sync_config_collection: pymongo.collection.Collection) -> bool:
    """
    检查笔记是否需要同步（基于配置库中的记录和 hash）
    
    Args:
        note: 笔记字典
        sync_config_collection: 配置库 collection
    
    Returns:
        True 如果需要同步，False 如果不需要
    """
    contenthash = note.get("contenthash")
    if not contenthash:
        logger.warning("Note missing contenthash, skipping")
        return False
    
    current_hash = note.get("hash", "")
    
    # 查询配置库中是否存在该 contenthash 的记录
    existing_config = sync_config_collection.find_one({"contenthash": contenthash})
    
    if not existing_config:
        # 不存在记录，需要同步
        return True
    
    # 存在记录，检查 hash 是否改变
    last_hash = existing_config.get("last_hash", "")
    if current_hash != last_hash:
        # hash 改变了，需要重新同步
        return True
    
    # hash 相同，不需要同步
    return False


def add_book_note_to_memos(note: Dict, book_name: str) -> Dict:
    """
    调用 MemOS API 添加笔记到记忆
    
    Args:
        note: 笔记字典
        book_name: 书名
    
    Returns:
        API 响应结果
    """
    api_key = os.getenv("MEMOS_API_KEY")
    base_url = os.getenv("MEMOS_BASE_URL", "https://memos.memtensor.cn/api/openmem/v1")
    user_id = os.getenv("MEMOS_USER_ID")
    
    if not api_key:
        logger.error("MEMOS_API_KEY not set")
        return {"error": "MEMOS_API_KEY not configured"}
    
    if not user_id:
        logger.error("MEMOS_USER_ID not set")
        return {"error": "MEMOS_USER_ID not configured"}
    
    contenthash = note.get("contenthash", "")
    conversation_id = book_name
    
    # 定义tag字段
    tag_fields = ["author", "from", "chapter"]
    
    # 构建 messages
    # 参考 webhook-handler 中的格式，使用 role 和 content
    content = note.get("content", "")
    author = note.get("author", "")
    speaker = note.get("speaker", "")
    character_comment = note.get("character_comment", "")
    ref_from = note.get("ref_from", "")
    ref_author = note.get("ref_author", "")
    
    # 创建去除了tag字段的note副本用于获取评论
    note_without_tags = {k: v for k, v in note.items() if k not in tag_fields}
    comments = note_without_tags.get("note", "").strip()
    
    # system 消息：说明这是用户的书摘
    system_message = {
        "role": "system",
        "content": "这是用户的书摘"
    }
    
    # user 消息：明确标注这是来自哪个作者哪本书的书摘
    # 构建书摘来源信息
    source_parts = []
    if author:
        source_parts.append(author)
    if book_name:
        source_parts.append(book_name)
    
    if source_parts:
        source_info = "".join(source_parts)
        user_content = f"这是来自{source_info}的书摘："
    else:
        user_content = "这是书摘："
    
    # 如果有引用信息，添加引用说明
    if ref_from:
        ref_info = f"这部作品引用了{ref_from}"
        if ref_author:
            ref_info = f"{ref_info}（作者：{ref_author}）"
        user_content = f"{user_content}\n{ref_info}"
    
    # 如果有speaker，添加角色信息
    if speaker:
        user_content = f"{user_content}\n这是角色{speaker}说的话"
    
    # 添加书摘内容
    user_content = f"{user_content}\n\n{content}"
    
    # 如果有角色评论，添加角色评论信息
    if character_comment:
        user_content = f"{user_content}\n\n这是对这个角色的评论：{character_comment}"
    
    # 如果有用户评论，添加用户评论信息
    if comments:
        user_content = f"{user_content}\n\n我写下了评论：{comments}"
    
    user_message = {
        "role": "user",
        "content": user_content
    }
    
    messages = [system_message, user_message]
    
    # 构建 tags（只包含非空值）
    tags = []
    for field in tag_fields:
        value = note.get(field)
        if value is not None and value != "":
            # 确保值是字符串
            tag_value = str(value).strip()
            if tag_value:
                tags.append(tag_value)
    
    # 添加mongo数据中的tag字段
    mongo_tag = note.get("tag")
    if mongo_tag:
        if isinstance(mongo_tag, list):
            # 如果是列表，添加所有非空元素
            for tag_item in mongo_tag:
                if tag_item and str(tag_item).strip():
                    tags.append(str(tag_item).strip())
        else:
            # 如果是字符串或其他类型，直接添加
            tag_value = str(mongo_tag).strip()
            if tag_value:
                tags.append(tag_value)
    
    # 构建 info（包含书名、作者等元信息）
    info = {
        "book_name": book_name,
        "author": note.get("author", ""),
        "from": note.get("from", book_name),
        "chapter": note.get("chapter", ""),
        "color": note.get("color", ""),
        "type": note.get("type", ""),
        "position": note.get("position", ""),
        "page": note.get("page", ""),
        "section": note.get("section", "")
    }
    # 移除空值
    info = {k: v for k, v in info.items() if v != "" and v is not None}
    
    # 直接使用date字段
    chat_time = note.get("date", "")
    
    # 构建请求数据
    data = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "messages": messages,
        "tags": tags,
        "info": info,
        "chat_time": chat_time
    }
    
    # 记录要添加的记忆格式（用于调试）
    logger.info(f"Adding note to MemOS, format: {json.dumps(data, ensure_ascii=False, indent=2)}")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {api_key}"
    }
    
    url = f"{base_url}/add/message"
    
    try:
        response = requests.post(url=url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        logger.info(f"MemOS add note result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error adding note to MemOS: {str(e)}")
        return {"error": str(e)}


def clear_sync_config(sync_config_collection: pymongo.collection.Collection):
    """
    清空配置库中的所有同步配置
    
    Args:
        sync_config_collection: 配置库 collection
    """
    try:
        result = sync_config_collection.delete_many({})
        logger.info(f"Cleared {result.deleted_count} sync config records")
        return result.deleted_count
    except Exception as e:
        logger.error(f"Error clearing sync config: {str(e)}")
        raise


def update_sync_config(note: Dict, book_name: str, sync_config_collection: pymongo.collection.Collection):
    """
    更新配置库中的同步状态
    
    Args:
        note: 笔记字典
        book_name: 书名
        sync_config_collection: 配置库 collection
    """
    contenthash = note.get("contenthash")
    if not contenthash:
        logger.warning("Note missing contenthash, cannot update sync config")
        return
    
    current_hash = note.get("hash", "")
    date_str = note.get("date", "")
    current_time = int(time.time())
    
    # 更新或插入配置
    sync_config_collection.update_one(
        {"contenthash": contenthash},
        {
            "$set": {
                "contenthash": contenthash,
                "book_name": book_name,
                "last_sync_time": current_time,
                "last_hash": current_hash,
                "last_note_date": date_str
            }
        },
        upsert=True
    )


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
        
        # 获取数据库
        mongo_url = os.environ.get('MONGO_URL')
        books_notes_db_name = os.environ.get('MONGO_DATABASE', 'BooksNotes')
        rachel_db_name = os.environ.get('RACHEL_DATABASE', 'Rachel')
        
        if not mongo_url:
            logger.error("MONGO_URL not set")
            return {"error": "MONGO_URL not configured"}
        
        # 确保 client 已初始化
        if client is None:
            initialize(context)
        
        # 获取数据库
        books_notes_db = client[books_notes_db_name]
        rachel_db = client[rachel_db_name]
        
        # 确保配置库存在
        sync_config_collection = ensure_sync_config_collection(rachel_db)
        
        # 检查是否需要清空配置
        # 支持从环境变量或event参数中获取
        clear_config = False
        if isinstance(event_dict, dict):
            clear_config = event_dict.get("clear_sync_config", False)
        if not clear_config:
            clear_config_env = os.environ.get('CLEAR_SYNC_CONFIG', '').lower()
            clear_config = clear_config_env in ('true', '1', 'yes')
        
        if clear_config:
            deleted_count = clear_sync_config(sync_config_collection)
            logger.info(f"Sync config cleared, deleted {deleted_count} records")
            return {
                "message": "Sync config cleared",
                "deleted_count": deleted_count
            }
        
        # 循环尝试获取需要同步的笔记，最多尝试20次
        max_attempts = 20
        attempted_hashes = set()  # 记录已尝试过的contenthash，避免重复尝试
        
        for attempt in range(max_attempts):
            # 随机获取一条笔记
            result = get_random_note(books_notes_db)
            if not result:
                logger.info("No notes found to process")
                return {"message": "No notes found to process"}
            
            book_name, note = result
            contenthash = note.get("contenthash", "")
            
            # 如果已经尝试过这条笔记，跳过
            if contenthash in attempted_hashes:
                continue
            
            attempted_hashes.add(contenthash)
            
            # 打印mongo原始数据
            logger.info(f"Mongo note data: {json.dumps(note, ensure_ascii=False, indent=2, default=str)}")
            
            # 检查是否需要同步
            if not check_note_should_sync(note, sync_config_collection):
                logger.info(f"Note {contenthash} already synced and up to date, trying next one (attempt {attempt + 1}/{max_attempts})")
                continue  # 继续尝试下一条
            
            # 找到需要同步的笔记，添加到 memos
            memos_result = add_book_note_to_memos(note, book_name)
            if "error" in memos_result:
                logger.error(f"Failed to add note to memos: {memos_result['error']}")
                return {"error": f"Failed to add note to memos: {memos_result['error']}"}
            
            # 更新配置库
            update_sync_config(note, book_name, sync_config_collection)
            
            logger.info(f"Successfully synced note {contenthash} from book {book_name}")
            return {
                "message": "Note synced successfully",
                "contenthash": contenthash,
                "book_name": book_name,
                "attempts": attempt + 1
            }
        
        # 如果尝试了max_attempts次都没有找到需要同步的笔记
        logger.info(f"Tried {max_attempts} notes, all appear to be already synced")
        return {
            "message": "All notes appear to be already synced",
            "attempts": max_attempts
        }
        
    except Exception as e:
        logger.error(f"Error in handler: {str(e)}", exc_info=True)
        return {"error": str(e)}
