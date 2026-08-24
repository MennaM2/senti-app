"""
Measure real request latency for the Senti Health backend.

Sends a set of sample messages to /api/chat and reports timing stats
(min/max/mean/median), plus separate quick checks for the read-only
GET endpoints. Results are printed as a ready-to-paste Markdown table
for the README's Performance/Latency section.

IMPORTANT: the backend server must already be running (python app.py)
in a separate terminal before you run this script.

Usage:
    python measure_latency.py
"""

import statistics
import time
import requests

BASE_URL = "http://127.0.0.1:5000"

# A mix of message types, since tool-calling messages take an extra
# round trip to Groq and will be meaningfully slower than plain replies.
TEST_MESSAGES = [
    "Hi, how are you?",
    "I've been feeling really anxious about work lately.",       # likely triggers log_mood
    "How have I been feeling this past week?",                    # likely triggers get_recent_moods
    "I'm doing okay today, just a bit tired.",                    # likely triggers log_mood
    "What's a good way to relax before bed?",
    "I feel great today, everything is going well!",              # likely triggers log_mood
    "Can you remind me what we talked about earlier?",
    "I've had a rough couple of days.",                            # likely triggers log_mood
]


def time_request(method, url, **kwargs):
    start = time.perf_counter()
    resp = requests.request(method, url, timeout=60, **kwargs)
    elapsed = time.perf_counter() - start
    resp.raise_for_status()
    return elapsed, resp.json()


def measure_chat_endpoint():
    print(f"Sending {len(TEST_MESSAGES)} requests to /api/chat ...\n")
    timings = []

    for i, msg in enumerate(TEST_MESSAGES, 1):
        try:
            elapsed, data = time_request(
                "POST", f"{BASE_URL}/api/chat", json={"message": msg}
            )
            timings.append(elapsed)
            preview = data.get("reply", "")[:60].replace("\n", " ")
            print(f"  [{i}/{len(TEST_MESSAGES)}] {elapsed:6.2f}s  \"{msg[:40]}...\" -> \"{preview}...\"")
        except Exception as e:
            print(f"  [{i}/{len(TEST_MESSAGES)}] FAILED: {e}")

    return timings


def measure_get_endpoints():
    results = {}
    for name, path in [
        ("GET /api/moods", "/api/moods"),
        ("GET /api/chat-history", "/api/chat-history"),
    ]:
        try:
            elapsed, _ = time_request("GET", f"{BASE_URL}{path}")
            results[name] = elapsed
        except Exception as e:
            results[name] = None
            print(f"  {name} FAILED: {e}")
    return results


def print_summary(timings, get_results):
    print("\n" + "=" * 60)
    print("LATENCY SUMMARY")
    print("=" * 60)

    if timings:
        print(f"\n/api/chat  (n={len(timings)} requests)")
        print(f"   min:    {min(timings):.2f}s")
        print(f"   max:    {max(timings):.2f}s")
        print(f"   mean:   {statistics.mean(timings):.2f}s")
        print(f"   median: {statistics.median(timings):.2f}s")
        if len(timings) > 1:
            print(f"   stdev:  {statistics.stdev(timings):.2f}s")

    print("\nOther endpoints (single request each):")
    for name, t in get_results.items():
        if t is not None:
            print(f"   {name:25s}: {t*1000:.0f} ms")

    # Markdown table for README
    print("\n" + "-" * 60)
    print("Markdown table (paste into README's Performance section):")
    print("-" * 60)
    print()
    print("| Endpoint | Metric | Value |")
    print("|---|---|---|")
    if timings:
        print(f"| `POST /api/chat` | Min | {min(timings):.2f}s |")
        print(f"| `POST /api/chat` | Mean | {statistics.mean(timings):.2f}s |")
        print(f"| `POST /api/chat` | Median | {statistics.median(timings):.2f}s |")
        print(f"| `POST /api/chat` | Max | {max(timings):.2f}s |")
    for name, t in get_results.items():
        if t is not None:
            print(f"| `{name.split(' ', 1)[1]}` | Response time | {t*1000:.0f} ms |")
    print(f"\n*(measured with {len(TEST_MESSAGES)} sample messages against the live Groq-backed API, "
          f"{time.strftime('%Y-%m-%d')})*")


def main():
    print("Checking backend is reachable...")
    try:
        requests.get(BASE_URL, timeout=5)
    except Exception:
        print(f"\n!! Could not reach {BASE_URL}")
        print("   Make sure the backend is running first: python app.py")
        return

    timings = measure_chat_endpoint()
    get_results = measure_get_endpoints()
    print_summary(timings, get_results)


if __name__ == "__main__":
    main()