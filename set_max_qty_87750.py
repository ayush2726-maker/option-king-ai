from pathlib import Path
import py_compile
import re

p = Path("app.py")
text = p.read_text(encoding="utf-8")
text = re.sub(
    r'SERVER_VERSION\s*=\s*"[^"]+"',
    'SERVER_VERSION = "2026.05.09-max-qty-87750-1"',
    text,
    count=1,
)
text = text.replace("MAX_ORDER_QTY = 1350", "MAX_ORDER_QTY = 87750")
text = text.replace("MAX_ORDER_QTY = 1300", "MAX_ORDER_QTY = 87750")
p.write_text(text, encoding="utf-8")
py_compile.compile("app.py", doraise=True)
print("MAX_ORDER_QTY set to 87750 and compile OK")
