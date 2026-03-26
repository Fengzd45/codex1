from fastapi import FastAPI, HTTPException
from pathlib import Path
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from family_query import load_family_data, print_relationships

app = FastAPI()

DATA_FILE = Path(__file__).parent.parent / "family_data.jsonl"

if not DATA_FILE.exists():
    raise RuntimeError("找不到 family_data.jsonl")

people = load_family_data(DATA_FILE)

@app.get("/api/query")
def query(name: str):
    if name not in people:
        raise HTTPException(status_code=404, detail=f"没有这个人：{name}")

    import io
    from contextlib import redirect_stdout
    f = io.StringIO()
    with redirect_stdout(f):
        print_relationships(people, name)
    res = f.getvalue()

    return {"text": res}
