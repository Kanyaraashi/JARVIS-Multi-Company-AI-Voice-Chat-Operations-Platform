"""Simple load test: many callers at once hitting the read endpoints.

    python loadtest/load_test.py --base http://localhost:8000 --key $env:JARVIS_KEY_SMILE --users 20 --seconds 20

Use a TEST company or a quiet moment. It only READS (company, faq lookup), never creates tickets.
It lowers its own speed when it sees 429 (that is the rate limiter working, and is reported separately).
Pass mark: error rate under 1%, p95 under 800 ms for your expected number of simultaneous callers.
"""
import argparse
import asyncio
import statistics
import time

import httpx


async def worker(client, base, headers, deadline, results):
    paths = ["/company/me", "/faq/search?q=opening%20hours"]
    i = 0
    while time.perf_counter() < deadline:
        path = paths[i % len(paths)]; i += 1
        start = time.perf_counter()
        try:
            r = await client.get(base + path, headers=headers, timeout=15)
            results.append((r.status_code, (time.perf_counter() - start) * 1000))
            if r.status_code == 429:
                await asyncio.sleep(1)
        except Exception:
            results.append((0, (time.perf_counter() - start) * 1000))


def summarize(results):
    total = len(results)
    ok = [ms for code, ms in results if 200 <= code < 300]
    limited = sum(1 for code, _ in results if code == 429)
    errors = sum(1 for code, _ in results if code == 0 or code >= 500)
    ok.sort()
    p = lambda q: ok[min(len(ok) - 1, int(len(ok) * q))] if ok else None
    return {"requests": total, "ok": len(ok), "rate_limited": limited, "errors": errors,
            "error_pct": round(100 * errors / total, 2) if total else None,
            "p50_ms": round(p(0.5)) if ok else None, "p95_ms": round(p(0.95)) if ok else None,
            "mean_ms": round(statistics.mean(ok)) if ok else None}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--key", required=True, help="an AI key (jrv_...) of a TEST company")
    ap.add_argument("--users", type=int, default=10)
    ap.add_argument("--seconds", type=int, default=15)
    a = ap.parse_args()
    results = []
    deadline = time.perf_counter() + a.seconds
    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[worker(client, a.base.rstrip("/"), {"X-API-Key": a.key}, deadline, results)
                               for _ in range(a.users)])
    s = summarize(results)
    print(s)
    if s["requests"] and s["rate_limited"] > s["requests"] * 0.2:
        print("NOTE: over 20% of requests were rate limited (limit is 120/min per company). That protects you; raise it only if real traffic needs it.")
    verdict = s["ok"] and s["error_pct"] < 1 and (s["p95_ms"] or 9999) < 800
    print("PASS" if verdict else "FAIL: errors above 1% or p95 above 800 ms")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
