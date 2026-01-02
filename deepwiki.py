import asyncio
import uuid
from typing import Any

import aiohttp

from astrbot.api import logger


class DeepWikiClient:
    QUERY_URL = "https://api.devin.ai/ada/query"
    HEADERS = {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://deepwiki.com/",
        "referer": "https://deepwiki.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    }

    def __init__(self, config: dict):
        self.config = config
        self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()

    async def _repo_query(
        self, repo_name: str, user_prompt: str, query_id: str
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
            async with self.session.post(
                self.QUERY_URL, headers=self.HEADERS, json=payload
            ) as resp:
                data = await resp.json()
                return data
        except aiohttp.ClientError as e:
            logger.error("请求异常:", str(e))
            return {}

    async def _get_poll_data(self, query_id: str) -> dict[str, Any]:
        try:
            async with self.session.get(
                f"{self.QUERY_URL}/{query_id}", headers=self.HEADERS
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

    async def _polling_response(self, query_id: str) -> dict[str, Any]:
        retry_count = 0
        max_retries = self.config["poll_max_times"]

        while retry_count < max_retries:
            logger.debug(f"轮询中（第 {retry_count + 1}/{max_retries} 次）...")
            result = await self._get_poll_data(query_id)

            if result["is_error"]:
                raise Exception("deepwiki 响应错误")

            if result["is_done"]:
                logger.debug("已完成响应")
                return result

            await asyncio.sleep(self.config["poll_intelval"])
            retry_count += 1

        return {"is_done": False, "content": "", "error": "响应超时"}

    async def query(self, repo_name: str, prompt: str) -> str:
        """查询接口"""
        query_id = str(uuid.uuid4())
        logger.debug(f"开始查询: repo={repo_name}, prompt={prompt}, id={query_id}")
        result = await self._repo_query(repo_name, prompt, query_id)
        if not result or not result.get("status"):
            raise Exception("查询失败")

        logger.debug("查询请求已发送，开始轮询响应...")
        response = await self._polling_response(query_id)
        if not response.get("is_done"):
            raise Exception("轮询超时")

        return response.get("content", "")


