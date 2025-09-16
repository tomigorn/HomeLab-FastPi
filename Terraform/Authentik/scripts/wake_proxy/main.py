#!/usr/bin/env python3
"""Wake-proxy: send Wake-on-LAN and reverse-proxy requests to hosts that may be sleeping.
"""
import asyncio
import os
import yaml
from fastapi import FastAPI, Request, HTTPException
from starlette.responses import StreamingResponse
import httpx
from wakeonlan import send_magic_packet

HERE = os.path.dirname(__file__)
CFG_PATH = os.environ.get("WAKE_PROXY_CONFIG", os.path.join(HERE, "config.yml"))

app = FastAPI()
with open(CFG_PATH, "r") as f:
    cfg = yaml.safe_load(f) or {}

# cfg is a mapping: hosts: { hostname: {mac, ip, port, timeout_secs, preserve_host}} 
HOSTS = cfg.get("hosts", {})

async def tcp_is_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        fut = asyncio.open_connection(host, port)
        r, w = await asyncio.wait_for(fut, timeout)
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False

async def wait_until_up(host_ip: str, port: int, timeout: int, interval: float = 2.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await tcp_is_open(host_ip, port, timeout=1.0):
            return True
        await asyncio.sleep(interval)
    return False


@app.api_route("/{path:path}", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS","HEAD"])
async def proxy(path: str, request: Request):
    host_header = request.headers.get("host", "")
    target = HOSTS.get(host_header)
    if not target:
        hostname_only = host_header.split(":")[0]
        target = HOSTS.get(hostname_only)
    if not target:
        raise HTTPException(status_code=502, detail="No mapping for host")

    mac = target["mac"]
    target_ip = target["ip"]
    target_port = int(target.get("port", 80))
    timeout = int(target.get("timeout_secs", 90))

    # If not up -> send WOL
    if not await tcp_is_open(target_ip, target_port, timeout=1.0):
        try:
            send_magic_packet(mac)
        except Exception:
            # non-fatal; continue to wait
            pass
        ok = await wait_until_up(target_ip, target_port, timeout=timeout)
        if not ok:
            raise HTTPException(status_code=504, detail="Target did not wake up in time")

    qs = request.url.query
    url = f"http://{target_ip}:{target_port}/{path}"
    if qs:
        url = f"{url}?{qs}"

    headers = {k:v for k,v in request.headers.items() if k.lower() not in (
        "host","connection","keep-alive","proxy-authorization","proxy-authenticate","te","trailers","transfer-encoding","upgrade")}
    if target.get("preserve_host", False):
        headers["host"] = host_header

    client = httpx.AsyncClient(timeout=None, follow_redirects=False)
    try:
        req_content = await request.body()
        upstream = await client.stream(request.method, url, headers=headers, content=req_content)
    except Exception as e:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}")

    async def stream_response():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    resp_headers = [(k, v) for k, v in upstream.headers.items() if k.lower() not in (
        "connection","keep-alive","proxy-authorization","proxy-authenticate","te","trailers","transfer-encoding","upgrade")]
    return StreamingResponse(stream_response(), status_code=upstream.status_code, headers=dict(resp_headers))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080)
