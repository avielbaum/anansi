"""Node picker: bounded-load rendezvous hashing for affinity, power-of-two-choices otherwise,
peak-EWMA latency, outlier ejection with doubling back-off, panic mode (DESIGN.md 11, 16.2-16.3)."""
import hashlib
import math
import random
import time

EJECT_AFTER = 3        # consecutive failures
EJECT_BASE_S = 30
EJECT_MAX_S = 300
LOAD_FACTOR = 1.25     # bounded-load cap over the mean in-flight


class Node:
    def __init__(self, url, models, region="default", upstream_model=None, extra=None):
        self.url, self.models, self.region = url.rstrip("/"), set(models), region
        # models are our logical names; upstream_model is what this server calls it. extra is trusted
        # per-node config merged into every request (for example to switch off a model's thinking mode).
        self.upstream_model, self.extra = upstream_model, extra or {}
        self.inflight = 0
        self.ewma_ms = 0.0
        self.consecutive = 0
        self.ejections = 0
        self.ejected_until = 0.0

    def load(self):
        return self.inflight + self.ewma_ms / 1000


def _score(key, url):
    return int.from_bytes(hashlib.sha256(f"{key}|{url}".encode()).digest()[:8], "big")


class Scheduler:
    def __init__(self, nodes):
        self.nodes = [Node(n["url"], n["models"], n.get("region", "default"), n.get("upstream_model"), n.get("extra"))
                      for n in nodes]

    def pick(self, model, key=None, exclude=()):
        now = time.monotonic()
        cands = [n for n in self.nodes if model in n.models and n not in exclude]
        pool = [n for n in cands if n.ejected_until <= now] or cands  # panic: use ejected nodes rather than fail
        if not pool:
            return None
        if key:
            cap = math.ceil(LOAD_FACTOR * sum(n.inflight for n in pool) / len(pool)) + 1
            for n in sorted(pool, key=lambda n: -_score(key, n.url)):
                if n.inflight < cap:
                    return n
        a, b = random.choice(pool), random.choice(pool)
        return a if a.load() <= b.load() else b

    def begin(self, node):
        node.inflight += 1

    def end(self, node, ok, ms):
        node.inflight -= 1
        if ok:
            node.ewma_ms = ms if ms > node.ewma_ms else 0.9 * node.ewma_ms + 0.1 * ms  # peak-EWMA
            node.consecutive = node.ejections = 0
            return
        node.consecutive += 1
        if node.consecutive >= EJECT_AFTER:
            node.ejections += 1
            node.consecutive = 0
            node.ejected_until = time.monotonic() + min(EJECT_BASE_S * 2 ** (node.ejections - 1), EJECT_MAX_S)

    def snapshot(self):
        now = time.monotonic()
        return [{"url": n.url, "region": n.region, "inflight": n.inflight, "ewma_ms": round(n.ewma_ms, 1),
                 "ejected": n.ejected_until > now} for n in self.nodes]
