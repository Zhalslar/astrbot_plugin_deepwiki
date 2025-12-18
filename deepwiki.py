import asyncio
from typing import Any

import aiohttp

from astrbot import logger


class DeepWikiClient:
    def __init__(
        self,
        retry_interval: int = 4,
        max_retries: int = 50,
    ):
        self.base_url = "https://api.devin.ai/ada/query"
        self.referer = "https://deepwiki.com/"
        self.retry_interval = retry_interval
        self.max_retries = max_retries
        self.headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": self.referer,
            "referer": self.referer,
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        }

    async def _send_message(
        self,
        session: aiohttp.ClientSession,
        repo_name: str,
        user_prompt: str,
        query_id: str,
    ) -> dict[str, Any]:
        payload = {
            "engine_id": "multihop",
            "user_query": f"<relevant_context>This query was sent from the wiki page: {repo_name.split('/')[1]} Overview.</relevant_context> {user_prompt}",
            "keywords": ["通过http"],
            "repo_names": [repo_name],
            "additional_context": "",
            "query_id": query_id,
            "use_notes": False,
            "generate_summary": False,
        }

        logger.debug("发送用户提示请求:", payload)

        try:
            async with session.post(
                self.base_url, headers=self.headers, json=payload
            ) as resp:
                return await resp.json()
        except aiohttp.ClientError as e:
            logger.error("请求异常:", str(e))
            return {}

    async def _get_markdown_data(
        self, session: aiohttp.ClientSession, query_id: str
    ) -> dict[str, Any]:
        try:
            async with session.get(
                f"{self.base_url}/{query_id}", headers=self.headers
            ) as resp:
                data = await resp.json()
                logger.debug("查询结果:", data)
        except aiohttp.ClientError as e:
            logger.error("查询异常:", str(e))
            return {"is_error": True, "is_done": False, "content": ""}

        if not data.get("queries"):
            return {"is_error": True, "is_done": False, "content": ""}

        last_item = data["queries"][-1]

        if last_item.get("state") == "error":
            return {"is_error": True, "is_done": False, "content": ""}

        if not last_item.get("response"):
            return {"is_error": False, "is_done": False, "content": ""}

        is_done = last_item["response"][-1].get("type") == "done"
        if not is_done:
            return {"is_error": False, "is_done": False, "content": ""}

        markdown_data = "".join(
            item.get("data", "")
            for item in last_item["response"]
            if item.get("type") == "chunk"
        )

        return {"is_error": False, "is_done": True, "content": markdown_data}

    async def _polling_response(
        self, session: aiohttp.ClientSession, query_id: str
    ) -> dict[str, Any]:
        retry_count = 0

        while retry_count < self.max_retries:
            logger.debug(f"轮询中（第 {retry_count + 1}/{self.max_retries} 次）...")
            result = await self._get_markdown_data(session, query_id)

            if result["is_error"]:
                raise Exception("deepwiki 响应错误")

            if result["is_done"]:
                logger.debug("已完成响应")
                return result

            await asyncio.sleep(self.retry_interval)
            retry_count += 1

        return {"is_done": False, "content": "", "error": "响应超时"}

    async def query(
        self, repo_name: str, user_prompt: str, query_id: str
    ) -> dict[str, Any]:
        logger.debug(f"开始查询: repo={repo_name}, prompt={user_prompt}, id={query_id}")
        try:
            async with aiohttp.ClientSession() as session:
                send_result = await self._send_message(
                    session, repo_name, user_prompt, query_id
                )
                if not send_result or not send_result.get("status"):
                    raise Exception("发送失败")

                logger.debug("消息已发送，开始轮询...")
                response = await self._polling_response(session, query_id)
                if not response.get("is_done"):
                    raise Exception("轮询超时")

                return {
                    "success": True,
                    "chat_results": response.get("content", ""),
                }

        except Exception as e:
            logger.error("异常:", str(e))
            raise Exception("❌ DeepWiki 查询失败: " + str(e))
