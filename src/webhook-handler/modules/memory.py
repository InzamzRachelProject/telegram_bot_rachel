# -*- coding: utf8 -*-
"""
记忆模块：用于存储和检索用户对话记忆
使用MemOS API实现，支持多平台，根据平台和用户ID区分不同用户的记忆
"""
import os
import requests
import json
import time
import re
from typing import List, Dict, Optional
from pymongo import MongoClient
from datetime import datetime


def get_memos_user_id(platform: str, platform_user_id: str) -> str:
    """
    根据平台和平台用户ID生成MemOS的user_id
    
    Args:
        platform: 平台名称（如 "telegram", "wechat" 等）
        platform_user_id: 平台用户ID
    
    Returns:
        MemOS格式的user_id
    """
    return f"{platform}_{platform_user_id}"


def record_user_with_memory(platform: str, platform_user_id: str) -> bool:
    """
    在MongoDB中记录添加过记忆的用户ID
    如果用户不存在则插入，如果存在则更新最后添加记忆的时间
    
    Args:
        platform: 平台名称（如 "telegram", "wechat" 等）
        platform_user_id: 平台用户ID
    
    Returns:
        是否成功记录
    """
    mongo_uri = os.getenv("MONGODB_ATLAS_URI")
    if not mongo_uri:
        print("Warning: MONGODB_ATLAS_URI not set, skipping user record", flush=True)
        return False
    rachel_db_name = os.environ.get('RACHEL_DATABASE', 'Rachel')
    
    try:
        # 生成MemOS的user_id
        memos_user_id = get_memos_user_id(platform, platform_user_id)
        
        # 连接MongoDB
        client = MongoClient(mongo_uri, maxPoolSize=10, minPoolSize=5)
        db = client.get_database(rachel_db_name)
        collection_name = "MemoryUsers"
        collection = db.get_collection(collection_name)
        
        # 确保user_id字段有索引（如果不存在则创建）
        collection.create_index("user_id", unique=True)
        
        # 插入或更新用户记录
        collection.update_one(
            {"user_id": memos_user_id},
            {
                "$set": {
                    "user_id": memos_user_id,
                    "platform": platform,
                    "platform_user_id": platform_user_id,
                    "last_memory_added_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                },
                "$setOnInsert": {
                    "created_at": datetime.utcnow()
                }
            },
            upsert=True
        )
        
        client.close()
        print(f"Recorded user with memory: {memos_user_id}", flush=True)
        return True
    except Exception as e:
        print(f"Error recording user with memory: {str(e)}", flush=True)
        return False


def save_conversation(
    platform: str,
    platform_user_id: str,
    messages: List[Dict[str, str]],
    conversation_id: Optional[str] = None
) -> Dict:
    """
    存储原始对话到MemOS
    
    Args:
        platform: 平台名称（如 "telegram", "wechat" 等）
        platform_user_id: 平台用户ID
        messages: 对话消息列表，格式为 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        conversation_id: 对话ID（可选，如果不提供则使用时间戳）
    
    Returns:
        API响应结果
    """
    # 在添加记忆前，先在MongoDB中记录用户ID
    record_user_with_memory(platform, platform_user_id)
    
    api_key = os.getenv("MEMOS_API_KEY")
    base_url = os.getenv("MEMOS_BASE_URL", "https://memos.memtensor.cn/api/openmem/v1")
    
    if not api_key:
        print("Warning: MEMOS_API_KEY not set, skipping memory save", flush=True)
        return {"error": "MEMOS_API_KEY not configured"}
    
    # 生成MemOS的user_id
    memos_user_id = get_memos_user_id(platform, platform_user_id)
    
    # 如果没有提供conversation_id，使用时间戳
    if conversation_id is None:
        conversation_id = str(int(time.time()))
    
    data = {
        "user_id": memos_user_id,
        "conversation_id": conversation_id,
        "messages": messages
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {api_key}"
    }
    
    url = f"{base_url}/add/message"
    
    try:
        response = requests.post(url=url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        result = response.json()
        print(f"MemOS save conversation result: {result}", flush=True)
        return result
    except Exception as e:
        print(f"Error saving conversation to MemOS: {str(e)}", flush=True)
        return {"error": str(e)}


def search_memory(
    platform: str,
    platform_user_id: str,
    query: str,
    conversation_id: Optional[str] = None
) -> Dict:
    """
    从MemOS检索相关记忆
    
    Args:
        platform: 平台名称
        platform_user_id: 平台用户ID
        query: 查询文本
        conversation_id: 对话ID（可选）
    
    Returns:
        API响应结果，包含相关记忆
    """
    api_key = os.getenv("MEMOS_API_KEY")
    base_url = os.getenv("MEMOS_BASE_URL", "https://memos.memtensor.cn/api/openmem/v1")
    
    if not api_key:
        print("Warning: MEMOS_API_KEY not set, returning empty memory", flush=True)
        return {"memories": []}
    
    # 生成MemOS的user_id
    memos_user_id = get_memos_user_id(platform, platform_user_id)
    
    # 如果没有提供conversation_id，使用时间戳
    if conversation_id is None:
        conversation_id = str(int(time.time()))
    
    data = {
        "query": query,
        "user_id": memos_user_id,
        "conversation_id": conversation_id
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {api_key}"
    }
    
    url = f"{base_url}/search/memory"
    
    try:
        response = requests.post(url=url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        result = response.json()
        print(f"MemOS search memory result: {result}", flush=True)
        return result
    except Exception as e:
        print(f"Error searching memory from MemOS: {str(e)}", flush=True)
        return {"memories": [], "error": str(e)}


def format_memories_for_context(memory_result: Dict) -> str:
    """
    将MemOS返回的记忆结果格式化为上下文字符串
    
    根据MemOS返回的数据结构，包含：
    - memory_detail_list: 事实记忆列表（按相关性排序）
    - preference_detail_list: 偏好记忆列表（显式和隐式偏好）
    - tool_memory_detail_list: 工具记忆列表
    - preference_note: 偏好注意事项
    
    Args:
        memory_result: MemOS API返回的结果，格式为：
            {
                'code': 0,
                'data': {
                    'memory_detail_list': [...],
                    'preference_detail_list': [...],
                    'tool_memory_detail_list': [...],
                    'preference_note': '...'
                },
                'message': 'ok'
            }
    
    Returns:
        格式化后的记忆上下文字符串
    """
    # 兼容旧格式：如果直接有memories字段
    if "memories" in memory_result and "data" not in memory_result:
        memories = memory_result.get("memories", [])
        if not memories:
            return ""
        formatted = []
        for memory in memories:
            if isinstance(memory, str):
                content = memory.strip()
            elif isinstance(memory, dict):
                content = memory.get("content", memory.get("memory", "")).strip()
            else:
                content = str(memory).strip()
            if content:
                formatted.append(f"- {content}")
        if formatted:
            return "\n".join(formatted)
        return ""
    
    # 处理新格式：从data字段提取
    data = memory_result.get("data", {})
    if not data:
        return ""
    
    sections = []
    
    # 1. 首先处理偏好记忆（最重要，需要严格遵守）
    preference_list = data.get("preference_detail_list", [])
    if preference_list:
        # 分离显式和隐式偏好
        explicit_prefs = []
        implicit_prefs = []
        
        for pref in preference_list:
            preference_type = pref.get("preference_type", "")
            preference = pref.get("preference", "")
            reasoning = pref.get("reasoning", "")
            
            pref_entry = f"- {preference}"
            if reasoning:
                pref_entry += f" (原因: {reasoning})"
            
            if preference_type == "explicit_preference":
                explicit_prefs.append(pref_entry)
            else:
                implicit_prefs.append(pref_entry)
        
        preference_section = ["## ⚠️ 用户偏好（必须严格遵守）"]
        
        if explicit_prefs:
            preference_section.append("### 显式偏好（用户明确表达的偏好）")
            preference_section.extend(explicit_prefs)
        
        if implicit_prefs:
            preference_section.append("### 隐式偏好（从用户行为推断的偏好）")
            preference_section.extend(implicit_prefs)
        
        if explicit_prefs or implicit_prefs:
            sections.append("\n".join(preference_section))
    
    # 2. 添加偏好注意事项（紧跟在偏好后面）
    preference_note = data.get("preference_note", "")
    if preference_note and preference_note.strip():
        # 清理preference_note中的markdown标题，因为我们已经有了自己的标题
        note_content = preference_note.strip()
        # 移除开头的 # 注意： 等markdown标记
        note_content = re.sub(r'^#+\s*注意[：:]\s*', '', note_content, flags=re.MULTILINE)
        sections.append(f"## 📌 偏好使用说明\n{note_content}")
    
    # 3. 处理事实记忆（memory_detail_list）
    memory_list = data.get("memory_detail_list", [])
    if memory_list:
        memory_section = ["## 📚 相关事实记忆"]
        # 记忆已经按相关性排序，直接使用
        for mem in memory_list:
            memory_key = mem.get("memory_key", "")
            memory_value = mem.get("memory_value", "")
            memory_type = mem.get("memory_type", "")
            tags = mem.get("tags", [])
            relativity = mem.get("relativity", 0)
            
            # 构建记忆条目
            mem_entry = f"- **{memory_key}**"
            if memory_type:
                mem_entry += f" [{memory_type}]"
            mem_entry += f": {memory_value}"
            
            # 如果有标签，添加标签信息
            if tags:
                mem_entry += f" (标签: {', '.join(tags)})"
            
            # 添加相关性评分（可选，用于调试）
            # mem_entry += f" [相关性: {relativity:.2f}]"
            
            memory_section.append(mem_entry)
        
        sections.append("\n".join(memory_section))
    
    # 4. 处理工具记忆（tool_memory_detail_list）
    tool_memory_list = data.get("tool_memory_detail_list", [])
    if tool_memory_list:
        tool_section = ["## 🔧 工具记忆"]
        for tool_mem in tool_memory_list:
            # 根据实际工具记忆结构提取信息
            tool_key = tool_mem.get("tool_key", "")
            tool_value = tool_mem.get("tool_value", "")
            if tool_key and tool_value:
                tool_section.append(f"- **{tool_key}**: {tool_value}")
        
        if len(tool_section) > 1:  # 除了标题还有其他内容
            sections.append("\n".join(tool_section))
    
    # 组合所有部分
    if sections:
        return "\n\n".join(sections)
    
    return ""


def get_relevant_memory_context(
    platform: str,
    platform_user_id: str,
    query: str,
    conversation_id: Optional[str] = None
) -> str:
    """
    获取相关记忆并格式化为上下文字符串（便捷函数）
    
    Args:
        platform: 平台名称
        platform_user_id: 平台用户ID
        query: 查询文本
        conversation_id: 对话ID（可选）
    
    Returns:
        格式化后的记忆上下文字符串
    """
    memory_result = search_memory(platform, platform_user_id, query, conversation_id)
    return format_memories_for_context(memory_result)


def get_all_memory_users() -> List[Dict]:
    """
    获取所有有记忆的用户列表
    
    Returns:
        用户列表，每个用户包含 user_id, platform, platform_user_id 等字段
    """
    mongo_uri = os.getenv("MONGODB_ATLAS_URI")
    if not mongo_uri:
        print("Warning: MONGODB_ATLAS_URI not set, returning empty list", flush=True)
        return []
    
    rachel_db_name = os.environ.get('RACHEL_DATABASE', 'Rachel')
    
    try:
        client = MongoClient(mongo_uri, maxPoolSize=10, minPoolSize=5)
        db = client.get_database(rachel_db_name)
        collection = db.get_collection("MemoryUsers")
        
        # 获取所有用户，按最后添加记忆的时间倒序排列
        users = list(collection.find(
            {},
            {"user_id": 1, "platform": 1, "platform_user_id": 1, "last_memory_added_at": 1}
        ).sort("last_memory_added_at", -1))
        
        client.close()
        print(f"Retrieved {len(users)} memory users", flush=True)
        return users
    except Exception as e:
        print(f"Error retrieving memory users: {str(e)}", flush=True)
        return []
