#!/usr/bin/env python3
"""cm.py - content-manager-fa execution engine (runs without Claude).

  python cm.py home [<path>]                         where brands, database and secrets live
  python cm.py brand new <slug> | list
  python cm.py secret set <brand> <name>             asks for the value in this terminal (hidden)
  python cm.py secret import <brand> <file> --map KEY=name,KEY2=name2   move tokens from a KEY=value file
  python cm.py secret list <brand> | delete <brand> <name>
  python cm.py platform test <brand> <platform>      checks token + channel + bot permissions (sends nothing)
  python cm.py add <brand> <folder>                  register a content package as draft (validated)
  python cm.py list [--brand b] [--status s]
  python cm.py show <item>                           full preview of every platform version
  python cm.py approve <item> --by "<owner's exact words>"
  python cm.py reject <item> --note "..." | cancel <item> --note "..."
  python cm.py run [--dry-run] [--item id]           publish everything approved and due
  python cm.py retry <item> [--platform p]           after fixing a failure
  python cm.py posted <item> <platform> [--url u]    owner posted a manual platform by hand
  python cm.py stop | resume                         emergency stop switch
  python cm.py awake                                 keep the laptop awake in the brands' awake window
  python cm.py schedule [--apply|--remove] [--every 15]   Windows Task Scheduler entries
  python cm.py report [--brand b] [--days 1]
"""

import argparse
import getpass
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from cmlib import awake, brand, connectors, paths, runner, store, vault  # noqa: E402

TASK_RUN = "content-manager-fa run"
TASK_AWAKE = "content-manager-fa awake"


def setup_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def cmd_home(a):
    if a.path:
        c = paths.conf()
        c["home"] = os.path.abspath(a.path)
        paths.save_conf(c)
        os.makedirs(paths.brands_dir(), exist_ok=True)
    print(paths.home())


def cmd_brand(a):
    if a.action == "new":
        print(brand.create(a.slug))
    else:
        for b in brand.list_brands():
            print(b)


def cmd_secret(a):
    if a.action == "set":
        v = getpass.getpass(f"value for {a.brand}:{a.name} (hidden, Enter when done): ")
        vault.put(a.brand, a.name, v)
        print(f"saved {a.name} (encrypted)")
    elif a.action == "import":
        mapping = dict(x.split("=", 1) for x in (a.map or "").split(",") if "=" in x)
        found = {}
        with open(a.file, encoding="utf-8-sig") as f:
            for line in f:
                if "=" in line:
                    k, v = line.split("=", 1)
                    found[k.strip()] = v.strip()
        for k, name in mapping.items():
            if k in found and found[k]:
                vault.put(a.brand, name, found[k])
                print(f"imported {k} -> {name} (encrypted)")
            else:
                print(f"not found in file: {k}")
        print("now delete the plain-text file yourself once the platform test passes.")
    elif a.action == "delete":
        print("deleted" if vault.delete(a.brand, a.name) else "no such secret")
    else:
        for n in vault.names(a.brand):
            print(n)


def cmd_platform(a):
    pc = brand.platform_cfg(a.brand, a.platform)
    conn = connectors.get(a.platform)
    if not pc:
        sys.exit(f"{a.platform} is not configured for {a.brand}")
    if not conn:
        sys.exit(f"{a.platform}: no automatic connector (manual platform)")
    try:
        info = conn.check(pc, lambda n: vault.get(a.brand, n))
    except (connectors.Transient, connectors.Permanent, vault.VaultError) as e:
        sys.exit("FAIL: " + vault.redact(str(e), a.brand))
    ok = info.get("bot_status") in (None, "administrator", "creator")
    for k, v in info.items():
        print(f"{k}: {v}")
    print("OK" if ok else "WARN: the bot is not an admin of the channel")


def cmd_add(a):
    try:
        print(runner.add(a.brand, a.folder))
    except runner.QueueError as e:
        sys.exit("NOT ADDED:\n" + str(e))


def cmd_list(a):
    for it, tg in runner.list_items(a.brand, a.status):
        ts = " ".join(f"{t['platform']}:{t['status']}" for t in tg)
        print(f"{it['id']:<40} {it['status']:<15} {it['scheduled_at'] or '-':<17} {ts}")


def cmd_show(a):
    print(runner.preview(a.item))


def cmd_approve(a):
    try:
        runner.approve(a.item, a.by)
        print(f"approved: {a.item}")
    except runner.QueueError as e:
        sys.exit(str(e))


def cmd_close(a):
    try:
        (runner.reject if a.cmd == "reject" else runner.cancel)(a.item, a.note)
        print(f"{a.cmd}: {a.item}")
    except runner.QueueError as e:
        sys.exit(str(e))


def cmd_run(a):
    s = runner.run(dry_run=a.dry_run, only_item=a.item)
    if s["stopped"]:
        return
    for iid, p, url in s["published"]:
        print(f"PUBLISHED {iid} -> {p} {url or ''}")
    for iid, p, msg in s["failed"]:
        print(f"FAILED    {iid} -> {p}: {msg}")
    for iid, p in s["manual"]:
        print(f"MANUAL    {iid} -> {p} (owner posts by hand)")
    for x in s["skipped"]:
        print("SKIPPED   " + " ".join(str(v) for v in x))
    if not any(s[k] for k in ("published", "failed", "manual", "skipped")):
        print("nothing due")


def cmd_retry(a):
    print(f"{runner.retry(a.item, a.platform)} target(s) back in the queue")


def cmd_posted(a):
    try:
        runner.mark_posted(a.item, a.platform, a.url)
        print("recorded")
    except runner.QueueError as e:
        sys.exit(str(e))


def cmd_stop(a):
    os.makedirs(paths.home(), exist_ok=True)
    if a.cmd == "stop":
        with open(paths.stop_file(), "w", encoding="utf-8") as f:
            f.write("publishing stopped by owner\n")
        print("STOP: nothing will be published until `cm resume`")
    else:
        if os.path.exists(paths.stop_file()):
            os.remove(paths.stop_file())
        print("resumed")


def _should_stay_awake():
    if runner.stopped():
        return False
    for b in brand.list_brands():
        w = brand.config(b).get("awake") or {}
        if w.get("from") and w.get("to") and awake.in_window(w["from"], w["to"]):
            return True
    with store.connect() as c:
        return bool(store.upcoming(c, 30))


def cmd_awake(a):
    awake.loop(_should_stay_awake, check_every=a.every)


def _schtasks(args):
    r = subprocess.run(["schtasks"] + args, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def cmd_schedule(a):
    py = sys.executable.replace("python.exe", "pythonw.exe") if sys.platform == "win32" else sys.executable
    me = os.path.abspath(__file__)
    run_tr = f'"{py}" "{me}" run'
    awake_tr = f'"{py}" "{me}" awake'
    starts = sorted({(brand.config(b).get("awake") or {}).get("from") for b in brand.list_brands()} - {None})
    plan = [(TASK_RUN, ["/SC", "MINUTE", "/MO", str(a.every), "/TR", run_tr]),
            (TASK_AWAKE, ["/SC", "DAILY", "/ST", (starts[0] if starts else "06:00"), "/TR", awake_tr])]
    if sys.platform != "win32":
        sys.exit("schedule: Windows only (use cron with: " + run_tr + ")")
    for name, args in plan:
        if a.remove:
            code, out = _schtasks(["/Delete", "/F", "/TN", name])
        elif a.apply:
            code, out = _schtasks(["/Create", "/F", "/TN", name, "/RL", "LIMITED"] + args)
        else:
            print(f"{name}: schtasks /Create /TN \"{name}\" " + " ".join(args))
            continue
        print(f"{name}: {'OK' if code == 0 else 'FAIL'} {out}")


def cmd_report(a):
    for e in runner.report(a.brand, a.days):
        print(f"{e['ts']} [{e['level']}] {e['item_id'] or '-'} {e['platform'] or '-'}: {e['msg']}")


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(prog="cm", description="content-manager-fa engine")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("home"); p.add_argument("path", nargs="?"); p.set_defaults(fn=cmd_home)
    p = sp.add_parser("brand"); p.add_argument("action", choices=["new", "list"]); p.add_argument("slug", nargs="?"); p.set_defaults(fn=cmd_brand)
    p = sp.add_parser("secret"); p.add_argument("action", choices=["set", "import", "list", "delete"]); p.add_argument("brand")
    p.add_argument("name", nargs="?"); p.add_argument("file", nargs="?"); p.add_argument("--map"); p.set_defaults(fn=cmd_secret)
    p = sp.add_parser("platform"); p.add_argument("action", choices=["test"]); p.add_argument("brand"); p.add_argument("platform"); p.set_defaults(fn=cmd_platform)
    p = sp.add_parser("add"); p.add_argument("brand"); p.add_argument("folder"); p.set_defaults(fn=cmd_add)
    p = sp.add_parser("list"); p.add_argument("--brand"); p.add_argument("--status"); p.set_defaults(fn=cmd_list)
    p = sp.add_parser("show"); p.add_argument("item"); p.set_defaults(fn=cmd_show)
    p = sp.add_parser("approve"); p.add_argument("item"); p.add_argument("--by", required=True); p.set_defaults(fn=cmd_approve)
    for n in ("reject", "cancel"):
        p = sp.add_parser(n); p.add_argument("item"); p.add_argument("--note", default=""); p.set_defaults(fn=cmd_close)
    p = sp.add_parser("run"); p.add_argument("--dry-run", action="store_true"); p.add_argument("--item"); p.set_defaults(fn=cmd_run)
    p = sp.add_parser("retry"); p.add_argument("item"); p.add_argument("--platform"); p.set_defaults(fn=cmd_retry)
    p = sp.add_parser("posted"); p.add_argument("item"); p.add_argument("platform"); p.add_argument("--url", default=""); p.set_defaults(fn=cmd_posted)
    for n in ("stop", "resume"):
        p = sp.add_parser(n); p.set_defaults(fn=cmd_stop)
    p = sp.add_parser("awake"); p.add_argument("--every", type=int, default=60); p.set_defaults(fn=cmd_awake)
    p = sp.add_parser("schedule"); p.add_argument("--apply", action="store_true"); p.add_argument("--remove", action="store_true")
    p.add_argument("--every", type=int, default=15); p.set_defaults(fn=cmd_schedule)
    p = sp.add_parser("report"); p.add_argument("--brand"); p.add_argument("--days", type=int, default=1); p.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    if a.cmd == "secret" and a.action == "import":
        a.file = a.name  # secret import <brand> <file>
    try:
        a.fn(a)
    except (brand.BrandError, vault.VaultError, runner.QueueError) as e:
        sys.exit(str(e))
    except Exception:
        # scheduled runs have no console (pythonw): keep the crash where the owner can find it
        import traceback
        os.makedirs(paths.home(), exist_ok=True)
        with open(os.path.join(paths.home(), "engine-error.log"), "a", encoding="utf-8") as f:
            f.write(f"--- {store.iso(store.now())} cm {' '.join(sys.argv[1:])}\n{traceback.format_exc()}\n")
        raise


if __name__ == "__main__":
    main()
