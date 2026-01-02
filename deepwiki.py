import asyncio
import uuid
from typing import Any

import aiohttp
from aiohttp import ContentTypeError

from astrbot.api import logger


class DeepWikiClient:
    QUERY_URL = "https://api.devin.ai/ada/query"

    HEADERS = {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://deepwiki.com/",
        "referer": "https://deepwiki.com/",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self, config: dict):
        self.config = config
        self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # --------------------------------------------------
    # 通用安全请求封装
    # --------------------------------------------------

    async def _safe_json(self, resp: aiohttp.ClientResponse) -> dict[str, Any]:
        try:
            return await resp.json()
        except ContentTypeError:
            text = await resp.text()
            logger.error(f"响应不是 JSON | status={resp.status} | body={text[:500]}")
        except Exception as e:
            logger.error(f"JSON 解析失败: {e}")

        return {}

    async def _request_json(self, method: str, url: str, **kwargs) -> dict[str, Any]:
        try:
            async with self.session.request(
                method, url, headers=self.HEADERS, **kwargs
            ) as resp:
                if resp.status < 200 or resp.status >= 300:
                    body = await resp.text()
                    logger.error(
                        f"HTTP 错误 | {method} {url} | "
                        f"status={resp.status} | body={body[:500]}"
                    )
                    return {
                        "ok": False,
                        "status": resp.status,
                        "error": "http_error",
                        "data": None,
                    }

                data = await self._safe_json(resp)
                return {
                    "ok": True,
                    "status": resp.status,
                    "error": None,
                    "data": data,
                }

        except aiohttp.ClientError as e:
            logger.error(f"HTTP 请求异常: {e}")
            return {
                "ok": False,
                "status": None,
                "error": "client_error",
                "data": None,
            }

    # --------------------------------------------------
    # DeepWiki 接口封装
    # --------------------------------------------------

    async def _repo_query(
        self, repo_name: str, user_prompt: str, query_id: str
    ) -> dict[str, Any]:
        payload = {
            "engine_id": "multihop",
            "user_query": (
                f"<relevant_context>This query was sent from the wiki page: "
                f"{repo_name.split('/')[1]} Overview.</relevant_context> "
                f"{user_prompt}"
            ),
            "keywords": ["通过http"],
            "repo_names": [repo_name],
            "additional_context": "",
            "query_id": query_id,
            "use_notes": False,
            "generate_summary": False,
        }

        logger.debug(f"发送查询请求: {payload}")

        return await self._request_json(
            "POST",
            self.QUERY_URL,
            json=payload,
        )

    async def _get_poll_data(self, query_id: str) -> dict[str, Any]:
        result = await self._request_json(
            "GET",
            f"{self.QUERY_URL}/{query_id}",
        )

        if not result["ok"]:
            return {
                "is_error": True,
                "is_done": False,
                "content": "",
            }

        data = result["data"]
        if not data or not data.get("queries"):
            return {
                "is_error": True,
                "is_done": False,
                "content": "",
            }

        last_item = data["queries"][-1]

        if last_item.get("state") == "error":
            return {
                "is_error": True,
                "is_done": False,
                "content": "",
            }

        response = last_item.get("response")
        if not response:
            return {
                "is_error": False,
                "is_done": False,
                "content": "",
            }

        is_done = response[-1].get("type") == "done"
        if not is_done:
            return {
                "is_error": False,
                "is_done": False,
                "content": "",
            }

        markdown = "".join(
            item.get("data", "") for item in response if item.get("type") == "chunk"
        )

        return {
            "is_error": False,
            "is_done": True,
            "content": markdown,
        }

    async def _polling_response(self, query_id: str) -> dict[str, Any]:
        max_retries = self.config["poll_max_times"]

        for i in range(max_retries):
            logger.debug(f"轮询中（{i + 1}/{max_retries}）")

            result = await self._get_poll_data(query_id)

            if result["is_error"]:
                raise RuntimeError("deepwiki 返回错误状态")

            if result["is_done"]:
                logger.debug("响应完成")
                return result

            await asyncio.sleep(self.config["poll_interval"])

        return {
            "is_done": False,
            "content": "",
            "error": "timeout",
        }

    async def query(self, repo_name: str, prompt: str) -> str:
        query_id = str(uuid.uuid4())

        logger.debug(f"开始查询 repo={repo_name}, id={query_id}, prompt={prompt}")

        result = await self._repo_query(repo_name, prompt, query_id)
        if not result["ok"]:
            raise RuntimeError("查询请求失败")

        logger.debug("查询已提交，进入轮询阶段")

        response = await self._polling_response(query_id)
        if not response.get("is_done"):
            raise TimeoutError("轮询超时")

        return response.get("content", "")
