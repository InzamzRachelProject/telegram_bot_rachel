import hashlib
from hmac import new
import os
import requests
import json
import xml.etree.ElementTree as ET  # 用于解析 XML
from pymongo import MongoClient
from typing import Union


def main_handler(event: Union[None, dict], context: Union[None, dict]):
    print("Received event: " + json.dumps(event, indent=2))
    event_body = json.loads(event["body"].replace('\\"', '"'))
    sub_rss = event_body["rss"]

    # 初始化 MongoDB 客户端
    mongo_uri = os.environ.get("MONGO_URI")
    mongo_database_name = os.environ.get("MONGO_DATABASE_NAME")
    mongo_collection_name = os.environ.get("MONGO_COLLECTION_NAME")
    mongo_client = MongoClient(mongo_uri)
    db = mongo_client[mongo_database_name]
    hash_collection = db[mongo_collection_name]
    rss_result = {}

    for rss_url in sub_rss:
        # 本地存储路径
        local_path = "/tmp/rss_feed.xml"

        # 下载 RSS Feed 文件到本地
        try:
            download_rss(rss_url, local_path)
        except requests.exceptions.RequestException as e:
            print(f"Error downloading RSS Feed from {rss_url}: {e}")
            continue  # 继续处理下一个 RSS Feed

        # 计算本地 RSS 文件的哈希值
        local_hash = calculate_hash(local_path)

        # 获取上次保存的哈希值和 XML
        previous_data = get_previous_data(hash_collection, rss_url)

        # 比较哈希值，检测是否改变
        if local_hash != previous_data["hash"] or event_body["force"] == "true":
            # RSS 发生改变，执行你的逻辑
            print(f"RSS Feed for {rss_url} has changed. Performing logic...")

            xml_content = get_xml_content(local_path)

            # 解析 XML 文件以提取新增文章的内容
            try:
                new_articles = parse_and_get_new_articles(
                    xml_content,
                    "" if event_body["force"] == "true" else previous_data["xml"],
                )
            except ET.ParseError as e:
                print(f"Error parsing XML content: {e}")
                new_articles = []  # 返回一个空列表或其他适当的值

            rss_result[rss_url] = new_articles
            for article in new_articles:
                article_info = "\n".join(
                    [f"{key}: {value}" for key, value in article.items()]
                )
                print(f"{rss_url}: Found new article:\n{article_info}")

            # 保存新的哈希值和 XML
            save_current_data(
                hash_collection, rss_url, local_hash, xml_content=xml_content
            )
        else:
            print(f"RSS Feed for {rss_url} has not changed.")

    return rss_result


def download_rss(rss_url: str, local_path: str) -> None:
    response = requests.get(rss_url)
    response.raise_for_status()  # 如果请求不成功，抛出异常
    with open(local_path, "wb") as f:
        f.write(response.content)


def calculate_hash(file_path: str) -> str:
    # 计算文件的 MD5 哈希值
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_previous_data(hash_collection, rss_url: str) -> dict:
    # 获取上次保存的哈希值和 XML（从 MongoDB 中获取）
    document = hash_collection.find_one({"rss_url": rss_url})
    return (
        {"hash": document["hash"], "xml": document.get("xml", "")}
        if document
        else {"hash": "", "xml": ""}
    )


def save_current_data(
    hash_collection, rss_url: str, current_hash: str, xml_content: str
) -> None:
    # 保存当前 RSS 文件的哈希值和 XML 到 MongoDB
    hash_collection.update_one(
        {"rss_url": rss_url},
        {"$set": {"hash": current_hash, "xml": xml_content}},
        upsert=True,
    )


def parse_and_get_new_articles(xml_content: str, previous_xml: str) -> list:
    # 解析 XML 字符串，提取新增文章的内容
    root = ET.fromstring(xml_content)

    new_articles = []

    if root.find(".//{http://www.w3.org/2005/Atom}entry") is not None:
        # 如果没有之前的 XML，说明所有的 entry 元素都是新的
        if not previous_xml:
            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                article = extract_article_info(entry)
                new_articles.append(article)
        else:
            # 如果有之前的 XML，需要对比找出新增的 entry 元素
            previous_root = ET.fromstring(previous_xml)

            # 用于存储之前文章的标题，防止标题重复
            previous_titles = set(
                entry.find(".//{http://www.w3.org/2005/Atom}title").text
                for entry in previous_root.findall(
                    ".//{http://www.w3.org/2005/Atom}entry"
                )
            )

            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                title = entry.find(".//{http://www.w3.org/2005/Atom}title").text

                # 如果标题不在之前的文章中，说明是新增的
                if title not in previous_titles:
                    article = extract_article_info(entry)
                    new_articles.append(article)

    elif root.find(".//item") is not None:
        # 如果没有之前的 XML，说明所有的 item 元素都是新的
        if not previous_xml:
            for item in root.findall(".//item"):
                article = extract_article_info(item)
                new_articles.append(article)
        else:
            # 如果有之前的 XML，需要对比找出新增的 item 元素
            previous_root = ET.fromstring(previous_xml)

            # 用于存储之前文章的标题，防止标题重复
            previous_titles = set(
                item.find(".//title").text
                for item in previous_root.findall(".//item")
            )

            for item in root.findall(".//item"):
                title = item.find(".//title").text

                # 如果标题不在之前的文章中，说明是新增的
                if title not in previous_titles:
                    article = extract_article_info(item)
                    new_articles.append(article)

    else:
        raise ValueError("RSS Feed is not in a valid format.")

    return new_articles


def extract_article_info(element) -> dict:
    # 提取文章信息
    article_info = {}

    for child in element:
        # 获取标签名
        tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        # 获取文本内容
        text = child.get("href") if child.get("href") else child.text

        # 使用标签名作为字典的键，文本内容作为值
        article_info[tag_name] = text

    return article_info


def get_xml_content(xml_path: str) -> str:
    # 获取 XML 文件的内容
    try:
        with open(xml_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Error reading XML file {xml_path}: {e}")
        return ""  # 返回一个空字符串或其他适当的值


if __name__ == "__main__":
    event = {
        "body": "{\"rss\": [\"http://blog.misaka19614.com/index.xml\"], \"force\": \"true\"}",
        "headerParameters": {},
        "headers": {
            "accept": "*/*",
            "accept-encoding": "gzip, deflate",
            "connection": "keep-alive",
            "content-length": "67",
            "content-type": "application/json",
            "host": "service-4z1m12cm-1305878470.hk.tencentapigw.com",
            "requestsource": "APIGW",
            "user-agent": "python-requests/2.31.0",
            "x-api-requestid": "11e754266a45a0d3383eb8407360cbdb",
            "x-api-scheme": "https",
            "x-b3-traceid": "11e754266a45a0d3383eb8407360cbdb"
        }
    }
    print(main_handler(event, None))  # 在本地测试时调用 main_handler 函数
