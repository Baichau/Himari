"""Planning steps for the agent loop.

The planner asks the existing local Ollama model for either a small structured
plan or exactly one next action using native tool calling. It never executes
anything itself.
"""

import json

import ollama

from ..config import load
from .plan import PLAN_PROMPT, TaskPlan

SYSTEM_PROMPT = (
    "You are Himari's task agent. Work in small, verifiable steps.\n"
    "- Decide on exactly one next action per turn, using a tool when an action "
    "is needed. Do not describe a tool call without making it.\n"
    "- Use only the provided tools with valid arguments. Never invent tools, "
    "results, file contents, or permissions.\n"
    "- Permissions are enforced outside of you. If a tool is denied, accept the "
    "denial, explain it honestly, and choose a different safe step.\n"
    "- Check each observation before claiming success. Do not repeat a "
    "dangerous action that failed or was denied.\n"
    "- When the task is complete or cannot proceed, answer directly with a "
    "short, honest summary of what happened. Say clearly when something was "
    "not done or not verified."
)


class Planner:
    def __init__(
        self,
        chat=None,
        model=None,
        host=None,
        timeout_seconds=None,
        temperature=None,
    ):
        self._chat = chat
        self._model = model
        self._host = host
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature

    def _config(self):
        config = load()
        return config.get("ollama", {}) if isinstance(config, dict) else {}

    def _client_chat(self, **kwargs):
        if self._chat is not None:
            return self._chat(**kwargs)
        cfg = self._config()
        client = ollama.Client(
            host=self._host or cfg.get("host", "http://127.0.0.1:11434"),
            timeout=self._timeout_seconds or cfg.get("timeout_seconds", 180),
        )
        return client.chat(**kwargs)

    def next_action(self, messages, tool_specs, token=None):
        if token is not None:
            token.check()
        cfg = self._config()
        payload = {
            "model": self._model or cfg.get("chat_model", "qwen3:8b"),
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": (
                    self._temperature
                    if self._temperature is not None
                    else cfg.get("temperature", 0.7)
                )
            },
        }
        if tool_specs:
            payload["tools"] = tool_specs

        response = self._client_chat(**payload)
        message = (
            response.get("message")
            if isinstance(response, dict)
            else getattr(response, "message", None)
        )
        content = _field(message, "content") or ""
        calls = _field(message, "tool_calls") or []

        if calls:
            first = calls[0]
            function = _field(first, "function") or {}
            name = _field(function, "name")
            arguments = _field(function, "arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (TypeError, ValueError):
                    arguments = None
            return {
                "type": "tool",
                "name": name,
                "arguments": arguments,
                "ignored_calls": max(0, len(calls) - 1),
                "content": content,
            }
        return {"type": "final", "content": content}

    def make_plan(self, objective, tool_specs, token=None, max_steps=8):
        """Ask for a structured plan. Returns a TaskPlan or None."""
        if token is not None:
            token.check()
        names = []
        for spec in tool_specs or []:
            function = spec.get("function") if isinstance(spec, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            if name:
                names.append(name)
        if not names:
            return None
        cfg = self._config()
        prompt = (
            PLAN_PROMPT
            + "\nAvailable tools (use only these names):\n- "
            + "\n- ".join(sorted(names))
        )
        payload = {
            "model": self._model or cfg.get("chat_model", "qwen3:8b"),
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": str(objective)},
            ],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "temperature": (
                    self._temperature
                    if self._temperature is not None
                    else min(0.3, float(cfg.get("temperature", 0.7)))
                )
            },
        }
        response = self._client_chat(**payload)
        message = (
            response.get("message")
            if isinstance(response, dict)
            else getattr(response, "message", None)
        )
        content = _field(message, "content") or ""
        try:
            data = json.loads(_strip_fence(content))
            plan = TaskPlan.from_json(data, objective=str(objective))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        known = set(names)
        plan.steps = [step for step in plan.steps if step.tool in known]
        if len(plan.steps) > max(1, int(max_steps)):
            plan.steps = plan.steps[:max_steps]
        ok, _ = plan.validate()
        return plan if ok else None


def _strip_fence(text):
    value = str(text or "").strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1]
        if value.rstrip().endswith("```"):
            value = value.rstrip()[:-3]
    return value.strip()


def _field(source, name):
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)
