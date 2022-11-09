import json
import logging
import os
from datetime import datetime

import requests

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG
)
owner = os.getenv("OWNER")
github_token = os.getenv("GITHUB_TOKEN")
date_info = None


# 获取当前日期和周数
def get_date_info() -> dict:
    now = datetime.now()
    year = now.year
    month = now.month
    day = now.day
    week = now.isocalendar()[1]
    return {'year': year, 'month': month, 'day': day, 'week': week}


def update_issue_comment(comments):
    global owner, github_token, date_info
    date_info = get_date_info()
    comment_ctx, comment_id = get_issue_comments(date_info['year'], date_info['week'])
    if comment_id == 0:
        return None
    # 更新 issue 评论
    url = f'https://api.github.com/repos/{owner}/My{date_info["year"]}/issues/comments/{comment_id}'
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': f'token {github_token}',
    }
    data = {'body': comment_ctx + comments}
    logging.debug(f'更新 issue 评论: {url}')
    response = requests.patch(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        logging.info(f'更新 issue 评论成功')
    else:
        logging.error(f'更新 issue 评论失败，错误信息：{response.text}')


def create_issue_comment(issue_url: str, week: int) -> (str, int):
    global github_token
    # 创建 issue 评论
    url = f'{issue_url}/comments'
    headers = {
        'Authorization': f'token {github_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/vnd.github.v3+json',
    }
    data = {
        'body': f'周记 {week}周',
    }
    r = requests.post(url, headers=headers, data=json.dumps(data))
    if r.status_code == 201:
        return f'周记 {week}周', r.json()['id']
    else:
        logging.error(f'创建 issue 评论失败: {r.status_code}')
        return '', 0


def get_weekly_issue_url(year: int) -> str:
    global owner, github_token
    repo = "My" + str(year)
    # 获取 issue 链接
    url = f'https://api.github.com/repos/{owner}/{repo}/issues'
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': f'token {github_token}',
    }
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        logging.error(f'获取 issue 失败: {r.status_code}')
        return None, r.status_code
    issues = r.json()
    issue_url = None
    for each_issue in issues:
        if each_issue['title'] == f'周记{year}':
            issue_url = each_issue['url']
            break
    if issue_url is None:
        logging.error('未找到 issue , 创建 issue')
        issue_url, status_code = create_issue(year)
    return issue_url


def create_issue(year):
    global owner, github_token
    repo = "My" + str(year)
    # 创建 issue
    url = f'https://api.github.com/repos/{owner}/{repo}/issues'
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': f'token {github_token}',
    }
    data = {
        'title': f'周记{year}',
        'body': '这是我的周记',
    }
    r = requests.post(url, headers=headers, data=json.dumps(data))
    if r.status_code != 201:
        logging.error(f'创建 issue 失败: {r.status_code}')
        return None, r.status_code
    issue_url = r.json()['url']
    return issue_url, r.status_code


def get_issue_comments(year: int, week: int) -> (str, int):
    global github_token
    issue_url = get_weekly_issue_url(year)
    if issue_url is None:
        return None, 0
    logging.info(f'issue_url: {issue_url}')
    # 获取 issue 评论
    url = f'{issue_url}/comments'
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'Authorization': f'token {github_token}',
    }
    r = requests.get(url, headers=headers)
    comments = r.json()
    """
    each comment is like:
    {
        "url": "https://api.github.com/repos/InzamZ/My2022/issues/comments/1308335646",
        "html_url": "https://github.com/InzamZ/My2022/issues/1#issuecomment-1308335646",
        "issue_url": "https://api.github.com/repos/InzamZ/My2022/issues/1",
        "id": 1308335646,
        "node_id": "IC_kwDOIW9Ra85N-54e",
        "user": {
            "login": "InzamZ"
        },
        "created_at": "2022-11-09T07:37:26Z",
        "updated_at": "2022-11-09T07:37:26Z",
        "author_association": "OWNER",
        "body": "测试评论",
        "reactions": {
            "url": "https://api.github.com/repos/InzamZ/My2022/issues/comments/1308335646/reactions",
            "total_count": 0,
        },
        "performed_via_github_app": null
    }
    """
    cur_week_comment_ctx = ""
    cur_week_comment_id = 0
    for each_comment in comments:
        comment_body = each_comment['body']
        if not isinstance(comment_body, str):
            logging.debug(f'评论内容不是字符串，跳过: {comment_body}')
            continue
        if comment_body.startswith(f'周记 {week}周'):
            logging.debug(f'找到本周评论: {comment_body}')
            cur_week_comment_ctx = comment_body
            cur_week_comment_id = each_comment['id']
            break
    if cur_week_comment_ctx == "":
        logging.debug(f'未找到本周评论, 新建评论')
        cur_week_comment_ctx, cur_week_comment_id = create_issue_comment(
            issue_url, week
        )
    logging.info(f'cur_week_comment_ctx: {cur_week_comment_ctx}')
    logging.info(f'cur_week_comment_id: {cur_week_comment_id}')
    return cur_week_comment_ctx, cur_week_comment_id


def main():
    # 获取当前日期和周数
    update_issue_comment("test")


if __name__ == '__main__':
    main()
