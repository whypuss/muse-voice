import asyncio
import base64
import json
import os
import sys
from urllib.parse import urlparse

def get_target():
    # 1. Environment variable override
    target = (
        os.environ.get("FORWARDER_TARGET")
        or os.environ.get("TARGET_NODE")
        or os.environ.get("ANYTLS_TARGET")
    )
    if target and target.strip():
        return target.strip()

    # 2. config.json in script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "config.json"),
        os.path.join(os.getcwd(), "config.json"),
    ]
    for cfg_path in candidates:
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    val = cfg.get("node_target") or cfg.get("target")
                    if val and isinstance(val, str) and val.strip():
                        return val.strip()
                    host = cfg.get("node_host")
                    port = cfg.get("node_port")
                    if host and port:
                        return f"{host}:{port}"
            except Exception:
                pass

    return None

async def pipe(r, w):
    try:
        while True:
            data = await r.read(65536)
            if not data:
                break
            w.write(data)
            await w.drain()
    except Exception:
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass

async def handle(cr, cw):
    try:
        target = get_target()
        if not target or "YOUR_NODE_HOST" in target:
            sys.stderr.write(f"[forwarder] Error: Invalid target node: {target}\n")
            cw.close()
            return

        proxy_env = (
            os.environ.get("https_proxy")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("http_proxy")
            or os.environ.get("HTTP_PROXY")
        )
        if not proxy_env:
            sys.stderr.write("[forwarder] Error: No egress proxy configured in https_proxy / HTTPS_PROXY\n")
            cw.close()
            return

        pu = urlparse(proxy_env)
        connect_req = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
        if pu.username and pu.password:
            auth = base64.b64encode(f"{pu.username}:{pu.password}".encode()).decode()
            connect_req += f"Proxy-Authorization: Basic {auth}\r\n"
        connect_req += "\r\n"

        pr, pw = await asyncio.open_connection(pu.hostname, pu.port)
        pw.write(connect_req.encode())
        await pw.drain()

        head = await pr.readuntil(b"\r\n\r\n")
        if b" 200 " not in head.split(b"\r\n")[0]:
            sys.stderr.write(f"[forwarder] Upstream proxy rejected CONNECT: {head.decode(errors='ignore')}\n")
            cw.close()
            pw.close()
            return

        await asyncio.gather(pipe(cr, pw), pipe(pr, cw))
    except Exception as e:
        sys.stderr.write(f"[forwarder] Connection error: {e}\n")
        try:
            cw.close()
        except Exception:
            pass

async def main():
    target = get_target()
    if not target or "YOUR_" in target:
        sys.stderr.write("[forwarder] Notice: Target node not configured or using placeholder. Set FORWARDER_TARGET or node_target in config.json\n")
    else:
        print(f"[forwarder] Target node configured: {target}")

    srv = await asyncio.start_server(handle, "127.0.0.1", 1180)
    print("forwarder up on 127.0.0.1:1180", flush=True)
    await srv.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
