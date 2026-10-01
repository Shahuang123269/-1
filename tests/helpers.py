import json

from issue_agent.connectors import FixtureConnector
from issue_agent.mcp_client import READ_TOOLS
from issue_agent.models import FixtureModel


class DirectTools:
    """Transport substitute only; uses the same persistent connector."""

    schemas = [
        {"type": "function", "function": {"name": name, "parameters": {}}}
        for name in sorted(READ_TOOLS)
    ]

    def __init__(self, settings):
        self.remote = FixtureConnector(settings)

    async def call(self, name, args):
        if name == "list_issue_comments":
            return {"comments": await self.remote.list_comments(args["issue_number"])}
        if name == "list_issues":
            return {"issues": await self.remote.list_issues()}
        return await self.remote.get_issue(args["issue_number"])


class ModifiedModel(FixtureModel):
    def __init__(self, mutate):
        self.mutate = mutate

    async def complete(self, messages, tools):
        message, usage = await super().complete(messages, tools)
        self.mutate(message)
        return message, usage


def mutate_final(change):
    def mutate(message):
        call = message["tool_calls"][0]["function"]
        if call["name"] == "submit_assessment":
            value = json.loads(call["arguments"])
            change(value)
            call["arguments"] = json.dumps(value)

    return mutate
