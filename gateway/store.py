"""SQLite persistence: daily token budgets, agent bans and the volunteer work ledger survive a restart.
One file, standard library only. Set `db_path` in the gateway config; unset means an in-memory database, so nothing
persists (fine for tests and demos).
The ledger records raw work, neutrally: jobs and tokens served by an agent per UTC day, and how many probes it passed
or failed. What a credit is worth or can be redeemed for is a separate, undecided question.
shortcut: synchronous writes on the request path (each is one small local transaction). Several gateway processes on ONE
machine may share the file (WAL, atomic reserve, bans read from the file); gateways on several machines need a network database. Usage rows hold player ids; purge() drops old days (retention_days)."""
import datetime
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage(title TEXT, player TEXT, day TEXT, tokens INTEGER, PRIMARY KEY(title, player, day));
CREATE TABLE IF NOT EXISTS bans(agent TEXT PRIMARY KEY, reason TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS ledger(agent TEXT, day TEXT, jobs INTEGER DEFAULT 0, tokens INTEGER DEFAULT 0,
                                  probes_ok INTEGER DEFAULT 0, probes_failed INTEGER DEFAULT 0, PRIMARY KEY(agent, day));
"""


def today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


class Store:
    def __init__(self, path=None):
        self.db = sqlite3.connect(path or ":memory:", check_same_thread=False)
        if path:
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    # daily budgets
    def usage(self, title, player, day):
        row = self.db.execute("SELECT tokens FROM usage WHERE title=? AND player=? AND day=?",
                              (title, player, str(day))).fetchone()
        return row[0] if row else 0

    def reserve(self, title, player, day, tokens, limit):
        """Add tokens to a player's day unless it is already at the limit. One statement, so several gateway processes sharing
        the file cannot both pass the check. False means over budget and nothing was added."""
        with self.db:
            cur = self.db.execute("INSERT INTO usage VALUES(?,?,?,?) ON CONFLICT(title, player, day) "
                                  "DO UPDATE SET tokens = tokens + excluded.tokens WHERE tokens < ?",
                                  (title, player, str(day), int(tokens), int(limit)))
        return cur.rowcount > 0

    def add_usage(self, title, player, day, tokens):
        with self.db:
            self.db.execute("INSERT INTO usage VALUES(?,?,?,?) ON CONFLICT(title, player, day) "
                            "DO UPDATE SET tokens = tokens + excluded.tokens", (title, player, str(day), int(tokens)))

    # bans
    def bans(self):
        return {r[0] for r in self.db.execute("SELECT agent FROM bans")}

    def ban(self, agent, reason=""):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO bans VALUES(?,?,?)", (agent, reason, today()))

    # volunteer work ledger
    def credit(self, agent, tokens, day=None):
        """One real job served by `agent` (probe traffic is not counted)."""
        with self.db:
            self.db.execute("INSERT INTO ledger(agent, day, jobs, tokens) VALUES(?,?,1,?) ON CONFLICT(agent, day) "
                            "DO UPDATE SET jobs = jobs + 1, tokens = tokens + excluded.tokens",
                            (agent, day or today(), int(tokens)))

    def probe(self, agent, ok, day=None):
        col = "probes_ok" if ok else "probes_failed"
        with self.db:
            self.db.execute(f"INSERT INTO ledger(agent, day, {col}) VALUES(?,?,1) ON CONFLICT(agent, day) "
                            f"DO UPDATE SET {col} = {col} + 1", (agent, day or today()))

    def report(self, day=None):
        """Usage per title and work per agent for one UTC day (default today)."""
        day = day or today()
        titles = [{"title": t, "accounts": n, "tokens": tok} for t, n, tok in self.db.execute(
            "SELECT title, COUNT(*), SUM(tokens) FROM usage WHERE day=? GROUP BY title ORDER BY title", (day,))]
        banned = self.bans()
        agents = [{"agent": a, "jobs": j, "tokens": tok, "probes_ok": ok, "probes_failed": bad, "banned": a in banned}
                  for a, j, tok, ok, bad in self.db.execute(
                      "SELECT agent, jobs, tokens, probes_ok, probes_failed FROM ledger WHERE day=? ORDER BY tokens DESC",
                      (day,))]
        return {"day": day, "titles": titles, "agents": agents}

    def purge(self, keep_days):
        """Drop usage rows older than keep_days (they hold player ids). The ledger is kept."""
        cutoff = (datetime.date.today() - datetime.timedelta(days=keep_days)).isoformat()
        with self.db:
            self.db.execute("DELETE FROM usage WHERE day < ?", (cutoff,))
