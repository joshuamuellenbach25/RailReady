"""Object storage (private). All access through the backend.

With EMERGENT_LLM_KEY set, objects go to Emergent Object Storage. Without it, objects are kept on local disk under
RAILREADY_STORAGE_DIR (default backend/.local_storage) so the app runs standalone."""
import os
import logging
import pathlib
import requests

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
log = logging.getLogger("storage")
_key = None


def _local_root() -> pathlib.Path | None:
    if os.environ.get("EMERGENT_LLM_KEY"):
        return None
    return pathlib.Path(os.environ.get("RAILREADY_STORAGE_DIR") or pathlib.Path(__file__).parent / ".local_storage").resolve()


def _local_path(root: pathlib.Path, path: str) -> pathlib.Path:
    p = (root / path.lstrip("/")).resolve()
    if root != p and root not in p.parents:
        raise ValueError(f"object path escapes storage root: {path}")
    return p


def init_storage(force: bool = False) -> str:
    global _key
    root = _local_root()
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        return "local"
    if _key and not force:
        return _key
    r = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": os.environ["EMERGENT_LLM_KEY"]}, timeout=30)
    r.raise_for_status()
    _key = r.json()["storage_key"]
    return _key


def _call(method: str, path: str, **kw):
    for attempt in range(2):
        r = requests.request(method, f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": init_storage(), **kw.pop("headers", {})}, timeout=120, **kw)
        if r.status_code == 404 and attempt == 0 and method == "PUT":
            init_storage(force=True)
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()


def put_object(path: str, data: bytes, content_type: str) -> dict:
    root = _local_root()
    if root is not None:
        p = _local_path(root, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return {"path": path, "size": len(data), "content_type": content_type}
    return _call("PUT", path, data=data, headers={"Content-Type": content_type}).json()


def get_object(path: str) -> bytes:
    root = _local_root()
    if root is not None:
        return _local_path(root, path).read_bytes()
    return _call("GET", path).content
