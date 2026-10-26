import subprocess, shutil, sys
F="live_v6/engine.py"; orig=open(F).read()
M=[
("O1 disable orphan detection (_is_orphan_prearm -> False)", '        cid = str(o.get("client_id") or "")\n        return (cid.startswith', '        cid = str(o.get("client_id") or "")\n        return False and (cid.startswith'),
("O2 orphan test ignores our cid prefix (user's *p orders qualify)", 'return (cid.startswith(self.cfg.cid_prefix) and cid.endswith("p")', 'return (cid.endswith("p")'),
("O3 never cancel orphans next to an unknown position", '                    for o in orphans:\n                        self._cancel_quiet(sym, o)', '                    for o in orphans:\n                        pass'),
("O4 cancel orphan even while the bot has no own stop yet", 'if orphans and u.get("stop_cid") and not u.get("unprotected"):', 'if orphans:'),
("O5 flat reconcile cancels ANY reduceOnly/closePosition order (no prefix check)", 'if (str(o["client_id"]).startswith(self.cfg.cid_prefix) and (o["close_position"] or o["reduce_only"])\n                            and str(o["client_id"]) not in pending):', 'if ((o["close_position"] or o["reduce_only"])\n                            and str(o["client_id"]) not in pending):'),
("O6 flat reconcile never cancels the orphan", 'self.x("cancel", sym, o)                 # our own stale stop, position flat', 'pass'),
("O7 flat reconcile ignores pending (cancels unresolved-entry pre-arm)", 'and str(o["client_id"]) not in pending):', 'and True):'),
]
sel=sys.argv[1:]
for name,old,new in M:
    if sel and name[:2] not in sel: continue
    assert orig.count(old)==1,(name,orig.count(old))
    open(F,"w").write(orig.replace(old,new))
    r=subprocess.run(["pytest","live_v6/tests/test_sizing_minorder.py","live_v6/tests/test_unknown_position.py","live_v6/tests/test_faults.py","-q","-m","not testnet and not slow","-p","no:cacheprovider","-x" if False else "-q"],capture_output=True,text=True)
    lines=r.stdout.strip().splitlines()
    failed=[l.split("::")[-1].split(" ")[0] for l in lines if l.startswith("FAILED")]
    print(f"{name}\n   -> {'KILLED' if failed else 'SURVIVED'} ({len(failed)}): {failed[:6]}  | {lines[-1]}",flush=True)
open(F,"w").write(orig)
