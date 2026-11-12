"""Persistence: daily token budgets, agent bans and the volunteer work ledger survive a restart.
`db_path` in the gateway config is a SQLite file (standard library) or a `postgresql://` URL (needs `pip install
"psycopg[binary]"`) for gateways on several machines sharing one database. Unset means an in-memory SQLite database, so
nothing persists (fine for tests and demos). Both run the same SQL.
The ledger records raw work, neutrally: jobs and tokens served by an agent per UTC day, and how many probes it passed
or failed. Credits are separate: a node linked to a player's wallet earns them per token, they mature after hold_days, and
games spend them on their own items (no cash). Amounts are stored in milli-credits so sums stay exact.
shortcut: synchronous writes on the request path (one small statement each; about a millisecond to a nearby Postgres). Move
them off the event loop if a busy gateway shows database time. Usage rows hold player ids; purge() drops old days (retention_days)."""
import contextlib
import datetime
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage(title TEXT, player TEXT, day TEXT, tokens BIGINT, PRIMARY KEY(title, player, day));
CREATE TABLE IF NOT EXISTS bans(agent TEXT PRIMARY KEY, reason TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS ledger(agent TEXT, day TEXT, jobs BIGINT DEFAULT 0, tokens BIGINT DEFAULT 0,
                                  probes_ok BIGINT DEFAULT 0, probes_failed BIGINT DEFAULT 0, PRIMARY KEY(agent, day));
CREATE TABLE IF NOT EXISTS link_codes(code TEXT PRIMARY KEY, agent TEXT, expires BIGINT);
CREATE TABLE IF NOT EXISTS links(agent TEXT PRIMARY KEY, wallet TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS earnings(wallet TEXT, agent TEXT, day TEXT, milli BIGINT, PRIMARY KEY(wallet, agent, day));
CREATE TABLE IF NOT EXISTS wallets(wallet TEXT PRIMARY KEY, spent BIGINT);
CREATE TABLE IF NOT EXISTS spends(title TEXT, ref TEXT, wallet TEXT, milli BIGINT, at TEXT, PRIMARY KEY(title, ref));
"""


class _Short(Exception):
    pass


def today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


class Store:
    def __init__(self, path=None, hold_days=7):
        self.hold_days = hold_days  # credits mature after this many days; a ban inside the window voids them
        self.in_tx = False
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
            if self.in_tx:
                return self.db.execute(sql, args)
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

    @contextlib.contextmanager
    def tx(self):
        """Several statements as one transaction: all of them land or none do."""
        if self.url:
            if self.db.closed:
                self._connect()
            with self.db.transaction():
                yield
            return
        self.db.execute("BEGIN IMMEDIATE")  # takes the write lock now, so another process cannot interleave
        self.in_tx = True
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        finally:
            self.in_tx = False

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
        self._x("DELETE FROM earnings WHERE agent=? AND day > ?", (agent, self._matured()))  # credit still on hold is void

    # volunteer work ledger
    def credit(self, agent, tokens, day=None, milli=0):
        """One real job served by `agent` (probe traffic is not counted). milli = credits earned x 1000; they go to the
        wallet the agent is linked to, and an unlinked agent earns none."""
        day = day or today()
        self._x("INSERT INTO ledger(agent, day, jobs, tokens) VALUES(?,?,1,?) ON CONFLICT(agent, day) "
                "DO UPDATE SET jobs = ledger.jobs + 1, tokens = ledger.tokens + excluded.tokens", (agent, day, int(tokens)))
        if milli > 0:
            self._x("INSERT INTO earnings(wallet, agent, day, milli) SELECT wallet, agent, ?, ? FROM links WHERE agent=? "
                    "ON CONFLICT(wallet, agent, day) DO UPDATE SET milli = earnings.milli + excluded.milli",
                    (day, int(milli), agent))

    # credits: a node is linked to a player's wallet with a one-time code; games spend from the wallet
    def _matured(self):
        """Last day whose credit has finished its hold."""
        return (datetime.date.fromisoformat(today()) - datetime.timedelta(days=self.hold_days)).isoformat()

    def add_link_code(self, code, agent, ttl_s):
        self._x("DELETE FROM link_codes WHERE expires < ?", (int(time.time()),))
        self._x("INSERT INTO link_codes VALUES(?,?,?)", (code, agent, int(time.time() + ttl_s)))

    def link(self, code, wallet):
        """Link the agent that asked for `code` to `wallet`. The code works once. None if it is unknown or expired.
        Credit earned before the link stays where it was; only later work goes to this wallet."""
        with self.tx():
            row = self._x("SELECT agent FROM link_codes WHERE code=? AND expires >= ?", (code, int(time.time()))).fetchone()
            if not row or self._x("DELETE FROM link_codes WHERE code=?", (code,)).rowcount != 1:
                return None
            self._x("INSERT INTO links VALUES(?,?,?) ON CONFLICT(agent) DO UPDATE SET wallet = excluded.wallet, at = excluded.at",
                    (row[0], wallet, today()))
            return row[0]

    def balance(self, wallet):
        """{"balance", "pending", "nodes"} in milli-credits: balance is matured credit minus spends; pending is still on hold."""
        cut = self._matured()
        matured, pending = self._x("SELECT COALESCE(SUM(CASE WHEN day <= ? THEN milli END), 0), "
                                   "COALESCE(SUM(CASE WHEN day > ? THEN milli END), 0) FROM earnings WHERE wallet=?",
                                   (cut, cut, wallet)).fetchone()
        spent = self._x("SELECT spent FROM wallets WHERE wallet=?", (wallet,)).fetchone()
        nodes = self._x("SELECT COUNT(*) FROM links WHERE wallet=?", (wallet,)).fetchone()[0]
        return {"balance": int(matured) - (spent[0] if spent else 0), "pending": int(pending), "nodes": nodes}

    def spend(self, wallet, milli, title, ref):
        """Take milli-credits from a wallet for a game's purchase. ref is the game's id for the purchase: the same ref again
        is not charged twice. Returns "ok", "duplicate" or "short" (not enough matured credit; nothing charged)."""
        try:
            with self.tx():
                if self._x("INSERT INTO spends VALUES(?,?,?,?,?) ON CONFLICT(title, ref) DO NOTHING",
                           (title, ref, wallet, int(milli), today())).rowcount != 1:
                    return "duplicate"
                self._x("INSERT INTO wallets VALUES(?, 0) ON CONFLICT(wallet) DO NOTHING", (wallet,))
                # the row lock on the wallet makes two gateways spending at once take turns; matured credit only grows
                if self._x("UPDATE wallets SET spent = wallets.spent + ? WHERE wallet=? AND wallets.spent + ? <= "
                           "(SELECT COALESCE(SUM(milli), 0) FROM earnings WHERE wallet=? AND day <= ?)",
                           (int(milli), wallet, int(milli), wallet, self._matured())).rowcount != 1:
                    raise _Short  # rolls back the spend row too
                return "ok"
        except _Short:
            return "short"

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
