import base64, io, logging, os, shutil
from pathlib import Path
import mss, pytesseract
from PIL import Image
from .config import load
log=logging.getLogger("himari.screen")
def capture(monitor="active"):
    if not load()["screen"].get("allow_capture"): raise PermissionError("Screen capture is disabled in Settings.")
    with mss.mss() as s:
        if monitor=="active":
            try:
                import pygetwindow as gw
                w=gw.getActiveWindow()
                box={"left":max(w.left,0),"top":max(w.top,0),"width":w.width,"height":w.height}
            except Exception: box=s.monitors[1]
        else:
            idx=int(monitor) if str(monitor).isdigit() else 1
            box=s.monitors[idx]
        shot=s.grab(box)
        img=Image.frombytes("RGB",shot.size,shot.rgb)
    return img
def ocr(img):
    try:
        command=os.environ.get("TESSERACT_CMD")
        if command and Path(command).is_file():
            pytesseract.pytesseract.tesseract_cmd=command
        elif not shutil.which("tesseract"):
            candidates=[
                Path(os.environ.get("ProgramFiles",""))/"Tesseract-OCR"/"tesseract.exe",
                Path(os.environ.get("LOCALAPPDATA",""))/"Programs"/"Tesseract-OCR"/"tesseract.exe",
            ]
            command=next((str(path) for path in candidates if path.is_file()),None)
            if command: pytesseract.pytesseract.tesseract_cmd=command
        return pytesseract.image_to_string(img).strip()
    except Exception as e: raise RuntimeError(f"OCR failed (is Tesseract installed?): {e}")
def to_b64(img):
    buf=io.BytesIO(); img.save(buf,format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
def analyze(prompt="Describe what is on this screen, any errors, and useful next actions."):
    from .llm import LLM
    img=capture()
    llm=LLM()
    if load()["screen"].get("vision_enabled"):
        try: return llm.vision(to_b64(img),prompt)
        except Exception as e: log.warning("Vision failed, falling back to OCR: %s",e)
    text=ocr(img)
    return f"OCR text from screen:\n{text[:4000]}"
