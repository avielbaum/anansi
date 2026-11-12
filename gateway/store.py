"""Persistence: daily token budgets, agent bans and the volunteer work ledger survive a restart.
`db_path` in the gateway config is a SQLite file (standard library) or a `postgresql://` URL (needs `pip install
"psycopg[binary]"`) for gateways on several machines sharing one database. Unset means an in-memory SQLite database, so
nothing persists (fine for tests and demos). Both run the same SQL.
The ledger records raw work, neutrally: jobs and tokens served by an agent per UTC day, and how many probes it passed
or failed. What a credit is worth or can be redeemed for is a separate, undecided question.
shortcut: synchronous writes on the request path (one small statement each; about a millisecond to a nearby Postgres). Move
them off the event loop if a busy gateway shows database time. Usage rows hold player ids; purge() drops old days (retention_days)."""
import datetime
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage(title TEXT, player TEXT, day TEXT, tokens BIGINT, PRIMARY KEY(title, player, day));
CREATE TABLE IF NOT EXISTS bans(agent TEXT PRIMARY KEY, reason TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS ledger(agent TEXT, day TEXT, jobs BIGINT DEFAULT 0, tokens BIGINT DEFAULT 0,
                                  probes_ok BIGINT DEFAULT 0, probes_failed BIGINT DEFAULT 0, PRIMARY KEY(agent, day));
"""


def today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


class Store:
    def __init__(self, path=None):
        self.url = path if (path or "").startswith(("postgres://", "postgresql://")) else None
        if self.url:
            self._connect()
        else:
            self.db = sqlite3.connect(path or ":memory:", check_same_thread=False)
            if path:
                self.db.execute("PRAGMA journal_mode=WAL")
        for stmt in filter(str.strip, SCHEMA.split(";")):
            self._x(stmt)

    def _connect(self):
        try:
            import psycopg
        except ImportError:
            raise ValueError('db_path is a Postgres URL: pip install "psycopg[binary]"') from None
        self.db = psycopg.connect(self.url, autocommit=True)  # every statement below is one atomic statement

    def _x(self, sql, args=()):
        """Run one statement and commit it. SQL is written with ? placeholders and works on both databases."""
        if not self.url:
            with self.db:
                return self.db.execute(sql, args)
        if self.db.closed:  # the database restarted or the network dropped: reconnect for this and later calls
            self._connect()
        try:
            return self.db.execute(sql.replace("?", "%s"), args)
        except Exception:
            # shortcut: no retry, since a write may have landed before the connection broke and repeating it would count twice.
            # This request fails; the next one reconnects.
            if self.db.closed or self.db.broken:
                self.db.close()
            raise

    # daily budgets
    def usage(self, title, player, day):
        row = self._x("SELECT tokens FROM usage WHERE title=? AND player=? AND day=?", (title, player, str(day))).fetchone()
        return row[0] if row else 0

    def reserve(self, title, player, day, tokens, limit):
        """Add tokens to a player's day unless it is already at the limit. One statement, so several gateway processes sharing
        the database cannot both pass the check. False means over budget and nothing was added."""
        cur = self._x("INSERT INTO usage VALUES(?,?,?,?) ON CONFLICT(title, player, day) "
                      "DO UPDATE SET tokens = usage.tokens + excluded.tokens WHERE usage.tokens < ?",
                      (title, player, str(day), int(tokens), int(limit)))
        return cur.rowcount > 0

    def add_usage(self, title, player, day, tokens):
        self._x("INSERT INTO usage VALUES(?,?,?,?) ON CONFLICT(title, player, day) "
                "DO UPDATE SET tokens = usage.tokens + excluded.tokens", (title, player, str(day), int(tokens)))

    # bans
    def bans(self):
        return {r[0] for r in self._x("SELECT agent FROM bans")}

    def ban(self, agent, reason=""):
        self._x("INSERT INTO bans VALUES(?,?,?) ON CONFLICT(agent) DO NOTHING", (agent, reason, today()))

    # volunteer work ledger
    def credit(self, agent, tokens, day=None):
        """One real job served by `agent` (probe traffic is not counted)."""
        self._x("INSERT INTO ledger(agent, day, jobs, tokens) VALUES(?,?,1,?) ON CONFLICT(agent, day) "
                "DO UPDATE SET jobs = ledger.jobs + 1, tokens = ledger.tokens + excluded.tokens",
                (agent, day or today(), int(tokens)))

    def probe(self, agent, ok, day=None):
        col = "probes_ok" if ok else "probes_failed"
        self._x(f"INSERT INTO ledger(agent, day, {col}) VALUES(?,?,1) ON CONFLICT(agent, day) "
                f"DO UPDATE SET {col} = ledger.{col} + 1", (agent, day or today()))

    def report(self, day=None):
        """Usage per title and work per agent for one UTC day (default today)."""
        day = day or today()
        titles = [{"title": t, "accounts": n, "tokens": int(tok)} for t, n, tok in self._x(
            "SELECT title, COUNT(*), SUM(tokens) FROM usage WHERE day=? GROUP BY title ORDER BY title", (day,))]
        banned = self.bans()
        agents = [{"agent": a, "jobs": j, "tokens": tok, "probes_ok": ok, "probes_failed": bad, "banned": a in banned}
                  for a, j, tok, ok, bad in self._x(
                      "SELECT agent, jobs, tokens, probes_ok, probes_failed FROM ledger WHERE day=? ORDER BY tokens DESC",
                      (day,))]
        return {"day": day, "titles": titles, "agents": agents}

    def purge(self, keep_days):
        """Drop usage rows older than keep_days (they hold player ids). The ledger is kept."""
        cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
        self._x("DELETE FROM usage WHERE day < ?", (cutoff,))
