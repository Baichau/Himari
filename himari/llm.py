import json, logging, time, ollama
from .config import load
from . import db
from .tool_exec import ToolTimeoutError, call as call_tool, timeout_for
from .tool_results import classify_result
log=logging.getLogger("himari.llm")
MAX_TOOL_ROUNDS=5
MAX_START_RETRIES=2
RETRY_DELAYS=(2.0,4.0)
EMPTY_RETRY_DELAY=0.4
_TRANSIENT_ERRORS=(
    "connection refused","connection reset","connection aborted","connect error",
    "failed to establish","temporarily unavailable","timed out","timeout",
    "read timed out","remote end closed","server disconnected","broken pipe",
)
class LLMError(Exception): pass


class LLMCancelled(LLMError):
    def __init__(self, partial=""):
        super().__init__("Generation stopped.")
        self.partial = partial


def _is_missing_model(message):
    text = message.lower()
    return "model" in text and any(
        term in text for term in ("not found", "404", "does not exist")
    )


def _is_transient(message):
    text = message.lower()
    return any(term in text for term in _TRANSIENT_ERRORS)


def _validated_arguments(handler, arguments):
    """Fail closed on malformed tool arguments before a handler runs."""
    from .tool_schema import validate_arguments

    spec = handler.get("spec") or {}
    parameters = (spec.get("function") or {}).get("parameters") or {}
    return validate_arguments(parameters, arguments)


def _invoke_tool(handler, name, arguments):
    """Run one tool with its own timeout and convert failures to observations."""
    try:
        return call_tool(
            handler["fn"],
            arguments,
            timeout=timeout_for(handler),
            label=name,
        )
    except ToolTimeoutError as exc:
        return f"Timed out: {exc}"
    except TypeError as exc:
        return f"Invalid arguments: {exc}"
    except Exception as exc:
        return f"Tool error: {exc}"


def _log_tool_outcome(name, result):
    succeeded, error = classify_result(result)
    if not succeeded:
        log.info("Tool %s reported a failure: %s", name, error[:300])


_RETRY_TAIL_LIMIT = 12
_RETRY_TOOL_CHARS = 1200


def _short_retry_messages(messages):
    """Keep the instructions, the current request, and its tool results.

    Retrying must not drop observations from tool work, otherwise the model
    answers as if it never looked anything up. Old history is trimmed and long
    tool outputs are capped instead.
    """
    messages = [m for m in (messages or []) if isinstance(m, dict)]
    system_messages = [
        dict(message)
        for message in messages
        if message.get("role") == "system"
    ]
    last_user = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if messages[index].get("role") == "user"
        ),
        None,
    )
    if last_user is None:
        return None
    tail = []
    for message in messages[last_user:][: _RETRY_TAIL_LIMIT + 1]:
        copy = dict(message)
        content = copy.get("content")
        if copy.get("role") == "tool" and isinstance(content, str):
            if len(content) > _RETRY_TOOL_CHARS:
                copy["content"] = content[:_RETRY_TOOL_CHARS] + " …"
        tail.append(copy)
    return system_messages + tail


class LLM:
    def __init__(self, tools=None, security=None):
        self.tools=tools or []
        self.security=security
        self.capabilities=None
    @property
    def cfg(self): return load()["ollama"]
    def client(self, timeout=None):
        cfg=self.cfg
        return ollama.Client(
            host=cfg["host"],
            timeout=timeout if timeout is not None else cfg.get("timeout_seconds",180),
        )
    def model_status(self):
        try:
            response = self.client(timeout=5).list()
            raw_models = (
                response.get("models", [])
                if isinstance(response, dict)
                else getattr(response, "models", [])
            )
            names = []
            for model in raw_models:
                if isinstance(model, dict):
                    name = model.get("name") or model.get("model")
                else:
                    name = getattr(model, "model", None) or getattr(model, "name", None)
                if name:
                    names.append(str(name))
            return names, None
        except Exception as e:
            log.warning("Ollama model check failed: %s",e)
            return [], str(e)
    def ping(self):
        _, error = self.model_status()
        return error is None
    def list_models(self):
        models, _ = self.model_status()
        return models
    def _stream_timeout(self):
        return self.cfg.get("stream_timeout_seconds", 900)
    def _start_stream(self, client, payload, cancel_event, on_status=None):
        last_error = None
        for attempt in range(MAX_START_RETRIES + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise LLMCancelled("")
            try:
                return client.chat(**payload)
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if _is_missing_model(message) or not _is_transient(message):
                    raise
                if attempt >= MAX_START_RETRIES:
                    raise
                if on_status:
                    on_status(
                        f"Ollama is not responding — retrying "
                        f"({attempt + 1}/{MAX_START_RETRIES})…"
                    )
                delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                if cancel_event is not None:
                    if cancel_event.wait(delay):
                        raise LLMCancelled("")
                else:
                    time.sleep(delay)
        raise last_error
    def _context_window(self):
        try:
            value = int(self.cfg.get("context_window", 8192))
        except (TypeError, ValueError):
            value = 8192
        return max(2048, min(value, 32768))
    def refresh_capabilities(self):
        """Cache what the configured chat model actually supports."""
        try:
            from .models import model_capabilities

            self.capabilities = model_capabilities(self.cfg.get("chat_model"))
        except Exception as exc:
            log.info("Model capability check skipped: %s", exc)
            self.capabilities = None
        return self.capabilities
    def preload(self):
        cfg = self.cfg
        client = self.client(timeout=cfg.get("stream_timeout_seconds", 900))
        return client.chat(
            model=cfg["chat_model"],
            messages=[{"role": "user", "content": "Hi"}],
            stream=False,
            keep_alive=cfg.get("keep_alive", "30m"),
            options={
                "num_predict": 1,
                "temperature": 0,
                "num_ctx": self._context_window(),
            },
        )
    def stream_chat(self, messages, on_token=None, on_tool=None, confirm=None,
                    cancel_event=None, on_status=None, think=False):
        cfg=self.cfg
        think_requested=bool(think)
        if (
            think_requested
            and self.capabilities is not None
            and "thinking" not in self.capabilities
        ):
            think_requested=False
            if on_status:
                on_status(
                    f"{cfg['chat_model']} does not support deep thinking — "
                    "answering directly."
                )
        tools_supported = self.capabilities is None or "tools" in self.capabilities
        payload={"model":cfg["chat_model"],"messages":messages,"stream":True,
                 "options":{
                     "temperature":cfg.get("temperature",0.7),
                     "num_ctx":self._context_window(),
                 },
                 "think":think_requested,
                 "keep_alive":cfg.get("keep_alive","30m")}
        if self.tools and tools_supported:
            payload["tools"]=[t["spec"] for t in self.tools]
        elif self.tools and on_status:
            on_status(
                f"{cfg['chat_model']} does not support tool calls — "
                "answering without desktop control."
            )
        client=self.client(timeout=self._stream_timeout())
        def cancelled():
            return cancel_event is not None and cancel_event.is_set()
        round_index=0
        retried_empty=False
        retried_think=not payload["think"]
        while True:
            if cancelled():
                raise LLMCancelled("")
            try:
                stream=self._start_stream(client,payload,cancel_event,on_status)
            except LLMCancelled:
                raise
            except Exception as e:
                message = str(e)
                if _is_missing_model(message):
                    raise LLMError(
                        f"Ollama does not have '{cfg['chat_model']}' installed. "
                        f"Install it manually with: ollama pull {cfg['chat_model']}"
                    ) from e
                lowered = message.lower()
                if (
                    not retried_think
                    and "think" in lowered
                    and "support" in lowered
                ):
                    retried_think = True
                    payload["think"] = False
                    if on_status:
                        on_status(
                            "This model does not support deep thinking — "
                            "continuing without it."
                        )
                    continue
                if "timed out" in lowered or "timeout" in lowered:
                    raise LLMError(
                        "Ollama did not answer in time. A local model can need "
                        "several minutes to load; press Retry, or raise the "
                        "'Reply wait limit' in Settings."
                    ) from e
                raise LLMError(
                    f"Cannot reach Ollama: {e}. Make sure Ollama is running."
                ) from e
            content=""; tool_calls=[]
            try:
                for chunk in stream:
                    if cancelled():
                        raise LLMCancelled(content)
                    m=chunk.message
                    if getattr(m,"content",None):
                        content+=m.content
                        if on_token: on_token(m.content)
                    if getattr(m,"tool_calls",None): tool_calls.extend(m.tool_calls)
            except LLMCancelled:
                raise
            except Exception as e:
                if content:
                    raise LLMError(
                        "Ollama stopped responding before the reply finished. "
                        "The partial reply above was kept; press Retry to try again."
                    ) from e
                raise LLMError(
                    f"Ollama stopped responding: {e}. Press Retry to try again."
                ) from e
            if cancelled():
                raise LLMCancelled(content)
            messages.append({"role":"assistant","content":content,"tool_calls":tool_calls or None})
            if not tool_calls:
                if content.strip():
                    return content
                if not retried_empty:
                    retried_empty=True
                    retry_messages=_short_retry_messages(messages)
                    if retry_messages is not None:
                        messages=retry_messages
                        payload["messages"]=messages
                        if on_status:
                            on_status(
                                "The model returned an empty reply — retrying "
                                "with a shorter context…"
                            )
                        if cancel_event is not None:
                            if cancel_event.wait(EMPTY_RETRY_DELAY):
                                raise LLMCancelled("")
                        else:
                            time.sleep(EMPTY_RETRY_DELAY)
                        continue
                raise LLMError(
                    "The local model returned an empty reply instead of text. "
                    "Press Retry, or start a new chat if it keeps happening."
                )
            if round_index >= MAX_TOOL_ROUNDS:
                raise LLMError(f"Stopped after {MAX_TOOL_ROUNDS} tool rounds to prevent an unbounded action loop.")
            round_index+=1
            for tc in tool_calls:
                if cancelled():
                    raise LLMCancelled(content)
                name=tc.function.name; args=tc.function.arguments or {}
                handler=next((t for t in self.tools if t["name"]==name),None)
                if name == "research_web" and on_status:
                    on_status("Researching the web and reading sources…")
                allowed=False
                if not isinstance(args,dict):
                    result="Invalid arguments: tool arguments must be an object."
                elif not handler:
                    result=f"Unknown tool: {name}"
                else:
                    try:
                        args=_validated_arguments(handler,args)
                    except ValueError as e:
                        result=f"Invalid arguments: {e}"
                    else:
                        if self.security is not None:
                            decision=self.security.authorize(name,args)
                            allowed=decision.allowed
                            if not allowed:
                                result=f"Denied: {decision.reason}"
                            else:
                                result=_invoke_tool(handler,name,args)
                                _log_tool_outcome(name, result)
                                self.security.record_result(name,args,result)
                        else:
                            needs_confirmation=handler.get("confirm",False)
                            allowed=not needs_confirmation
                            if needs_confirmation and confirm:
                                allowed=bool(confirm(name,args,handler.get("confirm_message","Allow this action?")))
                            if not allowed:
                                result="User denied this action or confirmation was unavailable."
                            else:
                                result=_invoke_tool(handler,name,args)
                                _log_tool_outcome(name, result)
                if self.security is None:
                    db.log_action(name,args,result,allowed)
                if on_tool and not (handler and handler.get("silent", False)):
                    on_tool(name,args,result)
                messages.append({"role":"tool","content":str(result),"tool_name":name})
        raise LLMError("Tool execution stopped unexpectedly.")
    def vision(self,images,prompt,model=None):
        cfg=self.cfg
        if isinstance(images,str):
            images=[images]
        client=self.client(timeout=cfg.get("vision_timeout_seconds",300))
        r=client.chat(
            model=model or cfg.get("vision_model") or "qwen2.5vl:3b",
            messages=[{"role":"user","content":prompt,"images":list(images)}],
            stream=False,
            keep_alive=cfg.get("keep_alive","30m"),
            options={"temperature":0.1},
        )
        return r.message.content
