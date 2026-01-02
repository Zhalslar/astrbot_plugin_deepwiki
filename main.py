from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.astr_message_event import AstrMessageEvent

from .deepwiki import DeepWikiClient


class DeepWikiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.client = DeepWikiClient(config)

    @filter.command("deepwiki", alias={"dw"})
    async def deepwiki(self, event: AstrMessageEvent, repo_name: str):
        """dw <作者/仓库名> <提示词>"""
        repo_name = (
            repo_name
            if len(repo_name.split("/")) == 2
            else self.config["default_repo_name"]
        )
        user_prompt = event.message_str.partition(" ")[2].removeprefix(repo_name)
        yield event.plain_result(f"正在查询仓库：{repo_name}")
        try:
            result = await self.client.query(repo_name, user_prompt)
            yield event.plain_result(result)
        except Exception as e:
            yield event.plain_result(str(e))
            logger.error(str(e))

    async def terminate(self):
        if self.client:
            await self.client.close()
