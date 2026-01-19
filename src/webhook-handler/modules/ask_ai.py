import os
import traceback
import requests
import re
from typing import Tuple, List

import requests
import redis
import json

r = redis.from_url(os.getenv("REDIS_URL"))
# Initialize Redis connection

def load_system_prompt() -> str:
    """加载预设的聊天人格prompt"""
    prompt_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "prompts",
        "default_persona.txt"
    )
    try:
        if os.path.exists(prompt_file):
            with open(prompt_file, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        print(f"Failed to load prompt file: {e}", flush=True)
    # 如果加载失败，返回默认提示词
    return "You are an awesome chatbot\n\n{memory_context}"

def apply_memory_context(system_prompt: str, memory: str = None) -> str:
    """应用记忆上下文到system prompt中"""
    memory_placeholder = "{memory_context}"
    
    if memory and memory.strip():
        # 如果有记忆内容，替换占位符
        memory_text = f"\n\n相关记忆信息：\n{memory.strip()}"
        return system_prompt.replace(memory_placeholder, memory_text)
    else:
        # 如果没有记忆内容，移除占位符及其前后的空行
        # 先移除占位符
        result = system_prompt.replace(memory_placeholder, "")
        # 清理多余的空行（最多保留一个空行）
        result = re.sub(r'\n{3,}', '\n\n', result)
        return result.strip()

def askgpt(prompt: str, module: str, user_id: str, base64_image: str = None, memory: str = None) -> str:
    url = os.getenv("OPENAI_API_URL")
    allowed_users = os.getenv("ALLOWED_USERS", "").split(',')
    print(f"ALLOWED_USERS: {allowed_users}")
    print(f"User: {user_id}_call_count, Count: {r.get(user_id)}")
    print(f"Ask GPT: {prompt}")

    # Limit user's calls by checking redis 
    if user_id not in allowed_users:
        user_count = r.get(f"{user_id}_call_count")
        if user_count is not None and int(user_count) >= os.getenv("MAX_CALLS", 5):
            return "You have exceeded the maximum number of calls to this service."
        else:
            r.setex(f"{user_id}_call_count", 7200, 1 if user_count is None else int(user_count) + 1)

    # Get previous context
    past_conversation = r.get(f'{user_id}_context')
    if past_conversation is None:
        system_prompt = load_system_prompt()
        past_conversation = [
            {
                "role": "system",
                "content": system_prompt
            }
        ]
    else:
        past_conversation = json.loads(past_conversation)
        # 确保系统提示词存在（如果上下文被清空但还有历史记录）
        if not any(msg.get("role") == "system" for msg in past_conversation):
            system_prompt = load_system_prompt()
            past_conversation.insert(0, {
                "role": "system",
                "content": system_prompt
            })
    
    # Add new user's message
    if base64_image:
        past_conversation.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        )
    else:
        past_conversation.append(
            {
                "role": "user",
                "content": prompt
            },
        )

    payload = {
        "model": module,
        "messages": past_conversation,
        "stream": False,
        "max_tokens": 2048,
    }
    headers = {"Authorization": "Bearer " + os.getenv("OPENAI_API_KEY")}

    response = requests.post(url, json=payload, headers=headers, stream=False).json()
    
    # Save current context
    past_conversation.append(
        {
            "role": "assistant",
            "content": response["choices"][0]["message"]["content"]
        }
    )
    r.setex(f'{user_id}_context', 7000, json.dumps(past_conversation))

    return  response["choices"][0]["message"]["content"]

def chat_with_ai(prompt: str, module: str, user_id: str, memory: str = None) -> str:
    """
    普通对话函数，专门处理日常聊天
    强制使用system_prompt，并支持记忆系统
    
    Args:
        prompt: 用户输入的消息
        module: 使用的模型
        user_id: 用户ID
        memory: 记忆系统提供的相关上下文（可选）
    
    Returns:
        AI的回复内容
    """
    url = os.getenv("OPENAI_API_URL")
    allowed_users = os.getenv("ALLOWED_USERS", "").split(',')
    print(f"Chat with AI - User: {user_id}, Prompt: {prompt}", flush=True)
    
    # Limit user's calls by checking redis 
    if user_id not in allowed_users:
        user_count = r.get(f"{user_id}_call_count")
        if user_count is not None and int(user_count) >= os.getenv("MAX_CALLS", 5):
            return "You have exceeded the maximum number of calls to this service."
        else:
            r.setex(f"{user_id}_call_count", 7200, 1 if user_count is None else int(user_count) + 1)
    
    # 强制加载system_prompt
    system_prompt_template = load_system_prompt()
    system_prompt = apply_memory_context(system_prompt_template, memory)
    
    # 获取之前的对话历史
    past_conversation_raw = r.get(f'{user_id}_context')
    
    if past_conversation_raw is None:
        # 如果没有历史对话，创建新的对话列表
        past_conversation = [
            {
                "role": "system",
                "content": system_prompt
            }
        ]
    else:
        # 如果有历史对话，解析并替换其中的system消息
        past_conversation = json.loads(past_conversation_raw)
        
        # 移除所有旧的system消息
        past_conversation = [msg for msg in past_conversation if msg.get("role") != "system"]
        
        # 在开头插入新的system消息（带记忆上下文）
        past_conversation.insert(0, {
            "role": "system",
            "content": system_prompt
        })
    
    # 添加新的用户消息
    past_conversation.append({
        "role": "user",
        "content": prompt
    })
    
    # 调用API
    payload = {
        "model": module,
        "messages": past_conversation,
        "stream": False,
        "max_tokens": 2048,
    }
    headers = {"Authorization": "Bearer " + os.getenv("OPENAI_API_KEY")}
    
    response = requests.post(url, json=payload, headers=headers, stream=False).json()
    
    # 获取AI回复
    assistant_reply = response["choices"][0]["message"]["content"]
    
    # 保存对话历史（包括新的用户消息和AI回复）
    past_conversation.append({
        "role": "assistant",
        "content": assistant_reply
    })
    
    # 保存到Redis（注意：保存时system消息也会被保存，下次调用时会替换）
    r.setex(f'{user_id}_context', 7000, json.dumps(past_conversation))
    
    return assistant_reply

def pic_generator(
    module: str,
    prompt: str,
    enabled_rewrite: bool = False,
    return_type: str = "url",
    size="1024x1024",
) -> [int, str]:
    # 通过环境变量获取秘钥和模型ID以及 api 端点
    openai_key = os.environ.get("OPENAI_API_KEY")
    openai_endpoint = os.environ.get("OPENAI_IMAGE_ENDPOINT")

    print(f"Moudle: {module}")
    print(f"Prompt: {prompt}")
    # 通过 OpenAI API 生成图片
    header = {
        "Authorization": f"Bearer {openai_key}",
        "Content-Type": "application/json",
    }
    data = {"model": module, "prompt": prompt, "n": 1, "size": size}

    response = requests.post(openai_endpoint, headers=header, json=data)

    print(response.json())
    if response.status_code != 200:
        raise Exception(
            f"OpenAI API 请求失败，状态码：{response.status_code}，错误信息：{response.text}"
        )

    # 获取生成的图片的 URL
    generated_image_url = response.json()["data"][0]["url"]

    if return_type == "url":
        return 0, generated_image_url
    elif return_type == "base64":
        # 通过图片的 URL 获取图片的 base64 编码
        response = requests.get(generated_image_url)
        if response.status_code != 200:
            raise Exception(
                f"获取生成的图片失败，状态码：{response.status_code}，错误信息：{response.text}"
            )

        return 0, response.json()["image"]
    else:
        raise Exception(f"不支持的返回类型：{return_type}")
