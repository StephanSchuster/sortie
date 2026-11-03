#!/usr/bin/env python3
"""Give three demo runs more than one model, so Cost per model shows several groups.

Usage: multi-model.py STATE_DIR...
Idempotent: a run that already has more than one part is left alone.
"""
import sqlite3
import sys

PLANS = [
    # (issue identifier, attempt-order index from the end, [(model, share, status, unrated, source)])
    ("LIVE-7", 0, [("claude-sonnet-5-5", 0.6, "estimated", "", "fetched"),
                   ("claude-haiku-5-5", 0.4, "partial", "cache_write", "builtin")]),
    ("APP-30", 0, [("claude-opus-5-5", 0.7, "estimated", "", "fetched"),
                   ("claude-sonnet-5-5", 0.3, "estimated", "", "fetched")]),
    ("APP-26", 0, [("claude-sonnet-5-5", 0.55, "estimated", "", "fetched"),
                   ("claude-haiku-5-5", 0.3, "partial", "cache_write", "builtin"),
                   ("", 0.15, "unpriced", "", "")]),
]


def patch(path):
    db = sqlite3.connect(path)
    for identifier, nth, parts in PLANS:
        runs = db.execute(
            "select id from run_history where identifier=? and status='succeeded' order by id desc",
            (identifier,)).fetchall()
        if len(runs) <= nth:
            continue
        run_id = runs[nth][0]
        if db.execute("select count(*) from run_model_usage where run_id=?", (run_id,)).fetchone()[0] != 1:
            continue
        base = db.execute(
            "select input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, estimated_cost_usd, price_table_version "
            "from run_model_usage where run_id=?", (run_id,)).fetchone()
        inp, out, cread, cwrite, cost, version = base
        db.execute("delete from run_model_usage where run_id=?", (run_id,))
        total_cost = 0.0
        priced = True
        for model, share, status, unrated, source in parts:
            part_cost = None if status == "unpriced" else round(cost * share, 4)
            if part_cost is not None:
                total_cost += part_cost
            else:
                priced = False
            db.execute(
                "insert into run_model_usage values (?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, model, int(inp * share), int(out * share), int(cread * share), int(cwrite * share),
                 part_cost, status, source, version if source else "", unrated))
        run_status = "estimated" if priced and all(p[2] == "estimated" for p in parts) else "partial"
        db.execute("update run_history set estimated_cost_usd=?, cost_status=? where id=?",
                   (round(total_cost, 4), run_status, run_id))
        print(path, identifier, run_id, [p[0] or "(not reported)" for p in parts])
    db.commit()


for state in sys.argv[1:]:
    patch(f"{state}/state.db")
