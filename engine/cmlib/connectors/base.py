"""base.py - the contract every platform connector follows.

A connector gets one target payload from item.json (e.g. item["targets"]["telegram"]),
the item folder (to resolve media paths), the brand's platform config and a secret getter.

  validate(payload, folder, cfg) -> list of error strings (empty = ok); no network
  publish(payload, folder, cfg, secret) -> {"remote_id": ..., "url": ...}
      raise Transient(...) for errors worth retrying later (network, 5xx, rate limit)
      raise Permanent(...) for errors that will not fix themselves (bad token, bad content)
  check(cfg, secret) -> dict with account/channel info; used by `cm platform test`

Connectors never print secrets and never publish without being called by the runner,
and the runner only calls them for items approved by the owner.
"""


class ConnectorError(Exception):
    pass


class Transient(ConnectorError):
    def __init__(self, msg, retry_after=None):
        super().__init__(msg)
        self.retry_after = retry_after


class Permanent(ConnectorError):
    pass


class Connector:
    name = "base"
    manual = False          # True = we only prepare a package; the owner posts it by hand
    min_gap_seconds = 3     # pause between two sends to the same platform

    def validate(self, payload, folder, cfg):
        return []

    def publish(self, payload, folder, cfg, secret):
        raise NotImplementedError

    def check(self, cfg, secret):
        return {}
