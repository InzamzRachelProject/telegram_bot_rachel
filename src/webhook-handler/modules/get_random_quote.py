import os
from pymongo import MongoClient
import random


def get_random_quote():
    # 创建MongoDB客户端，连接到默认本地MongoDB实例
    atlas_uri = os.getenv("MONGODB_ATLAS_URI")  # 从环境变量中获取Atlas URI
    client = MongoClient(atlas_uri)

    # 选择数据库
    database_name = os.getenv(
        "MONGODB_DATABASE_NAME", default="BooksNotes"
    )  # 从环境变量中获取数据库名
    db = client[database_name]  # 替换为你的数据库名

    # 获取数据库中所有集合的名称列表
    collections = db.list_collection_names()

    # 如果数据库中没有集合，则打印信息并退出
    if not collections:
        print("数据库中没有集合。")
        client.close()
        exit()

    # 随机选择一个集合名称
    chosen_collection_name = random.choice(collections)

    # 根据随机选出的集合名称选择集合
    collection = db[chosen_collection_name]

    # 在选中的集合中执行聚合查询，随机选择一个文档
    random_doc = collection.aggregate([{"$sample": {"size": 1}}])

    # 输出随机选中的文档
    for doc in random_doc:
        print(f"集合: {chosen_collection_name}, 文档: {doc}")

    # 关闭MongoDB客户端连接
    client.close()

    return doc
