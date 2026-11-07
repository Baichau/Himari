import json, logging, ollama
from .config import load
from . import db
log=logging.getLogger("himari.llm")
MAX_TOOL_ROUNDS=5
class LLMError(Exception): pass
class LLM:
    def __init__(self, tools=None):
        self.tools=tools or []
    @property
    def cfg(self): return load()["ollama"]
    def client(self):
        cfg=self.cfg
        return ollama.Client(host=cfg["host"],timeout=cfg.get("timeout_seconds",180))
    def ping(self):
        try:
            self.client().list(); return True
        except Exception as e:
            log.warning("Ollama ping failed: %s",e); return False
    def list_models(self):
        try: return [m["name"] for m in self.client().list().get("models",[])]
        except Exception: return []
    def stream_chat(self, messages, on_token=None, on_tool=None, confirm=None):
        cfg=self.cfg
        payload={"model":cfg["chat_model"],"messages":messages,"stream":True,
                 "options":{"temperature":cfg.get("temperature",0.7)},"think":False}
        if self.tools: payload["tools"]=[t["spec"] for t in self.tools]
        client=self.client()
        for round_index in range(MAX_TOOL_ROUNDS+1):
            try: stream=client.chat(**payload)
            except Exception as e: raise LLMError(f"Cannot reach Ollama: {e}") from e
            content=""; tool_calls=[]
            for chunk in stream:
                m=chunk.message
                if getattr(m,"content",None):
                    content+=m.content
                    if on_token: on_token(m.content)
                if getattr(m,"tool_calls",None): tool_calls.extend(m.tool_calls)
            messages.append({"role":"assistant","content":content,"tool_calls":tool_calls or None})
            if not tool_calls:
                return content
            if round_index == MAX_TOOL_ROUNDS:
                raise LLMError(f"Stopped after {MAX_TOOL_ROUNDS} tool rounds to prevent an unbounded action loop.")
            for tc in tool_calls:
                name=tc.function.name; args=tc.function.arguments or {}
                handler=next((t for t in self.tools if t["name"]==name),None)
                allowed=False
                if not isinstance(args,dict):
                    result="Invalid arguments: tool arguments must be an object."
                elif not handler:
                    result=f"Unknown tool: {name}"
                else:
                    needs_confirmation=handler.get("confirm",False)
                    allowed=not needs_confirmation
                    if needs_confirmation and confirm:
                        allowed=bool(confirm(name,args,handler.get("confirm_message","Allow this action?")))
                    if not allowed:
                        result="User denied this action or confirmation was unavailable."
                    else:
                        try: result=handler["fn"](**args)
                        except TypeError as e: result=f"Invalid arguments: {e}"
                        except Exception as e: result=f"Tool error: {e}"
                db.log_action(name,args,result,allowed)
                if on_tool and not (handler and handler.get("silent", False)):
                    on_tool(name,args,result)
                messages.append({"role":"tool","content":str(result),"tool_name":name})
        raise LLMError("Tool execution stopped unexpectedly.")
    def vision(self,image_b64,prompt):
        cfg=self.cfg
        r=self.client().chat(model=cfg["vision_model"],messages=[
            {"role":"user","content":prompt,"images":[image_b64]}])
        return r.message.content
