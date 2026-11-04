"""Replay a saved run's prompts through the old and the J2_SLIM prompt builders and print input size per call.
No model calls; the run folder is only read.   python3 j2_replay_size.py [runs/j2-20261015-114723]

Old = the prompt exactly as it was sent (calls.jsonl). New = the same prompt rebuilt the J2_SLIM way with the same code
the live run uses (j2.slim_atom, j2.build_agent_output, j2.fallback_human): finished atoms in STATE shrink to
id + status + agent_output, and a builder's whole-page block becomes its manifest of other atoms' agent_output.
A third column, "old+fields", is the old prompt with the two new atom fields added and nothing slimmed.
The run has no human_output or agent_output of its own: both are produced from its sections.json, receipts.jsonl and
expected outputs (human_output by code's fallback sentence, which is a stand-in for the builder's). Tokens are
estimated as characters / 4 and labelled so; recorded input tokens, when the run has them, are shown as measured."""
import json
import os
import re
import sys

os.environ.setdefault("STUDIO_MOCK", "1")
if "--documents" in sys.argv:       # the estimate runs one mock run of the document chain, in a throw-away folder
    import tempfile
    os.environ.setdefault("J2_MEMORY", "0")
    os.environ["J2_RUNS_DIR"] = tempfile.mkdtemp(prefix="j2-replay-docs-")
import j2  # noqa: E402

RUN = ([a for a in sys.argv[1:] if not a.startswith("--")] or [os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs",
                                                         "j2-20261015-114723")])[0]
# What the new builder reply format adds to every builder call (the atom_human_output instruction), from the live text.
FORMAT_ADD = len(', "atom_human_output": str (1 or 2 plain sentences telling the Requester what this part created, in '
                 'everyday words: no ids, no selectors, no "units")')


def jl(name):
    return [json.loads(x) for x in open(os.path.join(RUN, name), encoding="utf-8")]


def main():
    calls, receipts = [c for c in jl("calls.jsonl") if not c.get("extra")], jl("receipts.jsonl")
    sections = json.load(open(os.path.join(RUN, "sections.json"), encoding="utf-8"))
    audits = json.load(open(os.path.join(RUN, "audits.json"), encoding="utf-8"))
    last = audits[-1] if audits else None
    noun = "site"
    n_sites = len([f for f in os.listdir(os.path.join(RUN, "site")) if re.fullmatch(r"v\d+\.html", f)])
    outputs = {}                          # atom id -> (human_output, agent_output): what the live code would have stored

    def make(w, a):
        if a["id"] not in outputs:
            att = max([r["attempt"] for r in receipts if r["atom"] == a["id"]] or [1])
            ag = j2.build_agent_output(w, a, att, (sections.get(w["section"]) or {}).get("body") or "", receipts, last,
                                       n_sites, False, None)
            h = {"atom": a["id"], "attempt": att, "text": j2.fallback_human(a, noun)}
            outputs[a["id"]] = (h, ag)
        return outputs[a["id"]]

    rows, per_atom = [], {}
    for c in calls:
        user = c["prompt"]
        old = len(c["system"]) + len(user)
        m = re.search(r"STATE:\n(.*?)\n\nCHAT:", user, re.S)
        if not m:
            rows.append((c["id"], c["fn"], old, old, old, (c.get("tokens") or {}).get("input")))
            continue
        st = json.loads(m.group(1))
        fat, slim_ = json.loads(m.group(1)), json.loads(m.group(1))
        for ws, sl in ((fat["workflows"], False), (slim_["workflows"], True)):
            for w in ws:
                for a in w.get("atoms") or []:
                    if a.get("status") == "passed":
                        h, ag = make(w, a)
                        a["human_output"], a["agent_output"] = h, ag
                        per_atom[a["id"]] = (len(json.dumps(h, ensure_ascii=False)), len(json.dumps(ag, ensure_ascii=False)))
                if sl and w.get("atoms"):
                    w["atoms"] = [j2.slim_atom(a) for a in w["atoms"]]
        sep = lambda d: json.dumps(d, ensure_ascii=False)
        with_fields = user.replace(m.group(1), sep(fat))
        new = user.replace(m.group(1), sep(slim_))
        if c["fn"].startswith("W-") and "THE WHOLE SITE FILE NOW" in new:
            manifest = [{k: (a.get("agent_output") or {}).get(k) for k in ("atom", "section", "anchor", "selectors")}
                        for w in slim_["workflows"] if w["id"] != c["fn"] for a in w.get("atoms") or [] if a.get("agent_output")]
            new = new[:new.index("\nTHE WHOLE SITE FILE NOW")] + "\nOTHER SECTIONS (their atoms' agent_output; the rest of " \
                "the page isn't shown): " + sep(manifest)
        add = FORMAT_ADD if c["fn"].startswith("W-") else 0
        rows.append((c["id"], c["fn"], old, len(with_fields) + len(c["system"]) + add, len(new) + len(c["system"]) + add,
                     (c.get("tokens") or {}).get("input")))
    t = lambda n: round(n / 4)
    print(f"Replay of {os.path.basename(RUN)}: {len(rows)} calls, input characters per call (tokens estimated as chars/4)")
    print(f"{'call':>4} {'agent':<12} {'old chars':>10} {'old+fields':>11} {'new (slim)':>11} {'old tok~':>9} {'new tok~':>9} {'change':>7}")
    for i, fn, o, f, n, tok in rows:
        print(f"{i:>4} {fn:<12} {o:>10,} {f:>11,} {n:>11,} {t(o):>9,} {t(n):>9,} {(n - o) / o * 100:>+6.1f}%")
    O, F, N = (sum(r[k] for r in rows) for k in (2, 3, 4))
    print(f"{'':>4} {'TOTAL':<12} {O:>10,} {F:>11,} {N:>11,} {t(O):>9,} {t(N):>9,} {(N - O) / O * 100:>+6.1f}%")
    print(f"old+fields vs old: {(F - O) / O * 100:+.1f}%   new vs old: {(N - O) / O * 100:+.1f}%")
    rec = [(r[2], r[5]) for r in rows if r[5]]
    if rec:
        print(f"measured input tokens (old run): {sum(x for _, x in rec):,}; chars/token in this run: "
              f"{sum(c for c, _ in rec) / sum(x for _, x in rec):.2f} (the /4 estimate is a rule of thumb)")
    print("\nNew text per atom (characters; stored once, then carried in later prompts):")
    print(f"{'atom':<10} {'human_output':>13} {'agent_output':>13}")
    for a, (h, ag) in sorted(per_atom.items()):
        print(f"{a:<10} {h:>13,} {ag:>13,}")
    H, A = sum(v[0] for v in per_atom.values()), sum(v[1] for v in per_atom.values())
    print(f"{'TOTAL':<10} {H:>13,} {A:>13,}   (~{t(H + A):,} tokens, estimated)")
    by = {}
    by_old = {}
    for i, fn, o, f, n, tok in rows:
        k = "builder" if fn.startswith("W-") else fn
        by.setdefault(k, []).append(n)
        by_old.setdefault(k, []).append(o)
    avg = {k: sum(v) / len(v) for k, v in by.items()}
    avg_old = {k: sum(v) / len(v) for k, v in by_old.items()}
    print(f"Net: slim saves {O - N:,} characters (~{t(O - N):,} tokens est.) across the run's prompts; the new fields are "
          f"{H + A:,} characters once, plus {FORMAT_ADD} characters per builder call; the fields cost less than they save: "
          f"{'yes' if O - N > H + A else 'NO'}.")
    return avg, avg_old


def documents_estimate(avg, avg_old):
    """Extra calls and characters per design document, estimated from one mock run of the chain (its calls are the
    real prompt builders' output, with mock-sized content) and, as stand-ins for real content, the replayed run's
    average prompt per agent (page-heavy, so an upper bound for documents)."""
    import time
    brief = ("Design docs for Brew Lab, a one-page website for a small coffee shop in Indiranagar. Visitors see the menu with "
             "prices, the opening hours and where to find us, and pre-order a coffee for pickup. Users: coffee lovers and "
             "office staff. Problem: people can't see the menu or order ahead. Must-have features: see the menu with "
             "prices, pre-order a coffee, find the shop, read the opening hours. Constraints: one page only. Success: 30 "
             "pre-orders per week.")
    r = j2.J2Run()
    r.budget = max(r.budget, 50_000_000)      # tokens: never the limit in this measurement
    r.user_says(brief)
    while r.status != "waiting":
        time.sleep(0.02)
    rows = [c for c in jl_dir(r.dir, "calls.jsonl") if not c.get("extra")]
    kind = lambda fn: "builder" if fn.startswith("W-") else fn
    ranges = [(k, v["calls"]["from"], v["calls"]["to"]) for k, v in r.docs.items()]
    ranges.append(("website (blueprint)", r.docs["lld"]["calls"]["to"] + 1, 10 ** 9))
    print(f"\nDesign documents, estimated from a mock run of the chain ({r.outcome[:40]}...): extra AI calls and input characters")
    print(f"{'stage':<22} {'calls':>5} {'builder':>7} {'coord':>6} {'other':>6} {'mock chars':>11} {'stand-in chars':>15} {'~tokens (stand-in)':>19}")
    tot = [0, 0, 0]
    for k, a, b in ranges:
        rs = [c for c in rows if a <= c["id"] <= b]
        n = {x: sum(kind(c["fn"]) == x for c in rs) for x in ("builder", "coordination")}
        mock = sum(len(c["system"]) + len(c["prompt"]) for c in rs)
        stand = sum(avg.get(kind(c["fn"]), avg["builder"]) for c in rs)
        print(f"{k:<22} {len(rs):>5} {n['builder']:>7} {n['coordination']:>6} {len(rs) - n['builder'] - n['coordination']:>6} "
              f"{mock:>11,} {stand:>15,.0f} {stand / 4:>19,.0f}")
        if not k.startswith("website"):
            tot = [tot[0] + len(rs), tot[1] + mock, tot[2] + stand]
    print(f"{'documents total':<22} {tot[0]:>5} {'':>7} {'':>6} {'':>6} {tot[1]:>11,} {tot[2]:>15,.0f} {tot[2] / 4:>19,.0f}")
    web = [c for c in rows if c["id"] > r.docs["lld"]["calls"]["to"] and c["fn"].startswith("W-")]
    spec = [len(c["prompt"].split("YOUR SPEC", 1)[1]) for c in web if "YOUR SPEC" in c["prompt"]]
    if spec:
        print(f"Site builders with an LLD slice: the slice plus HLD summary is about {sum(spec) // len(spec):,} characters per builder "
              f"in this mock run; the whole page the old path sends them was {avg_old['builder']:,.0f} characters on average in "
              "the replayed run (J2_SLIM off).")
    print("Stand-in = the replayed run's average prompt per agent with J2_SLIM=1, so it overstates a document (no page, "
          "smaller state); mock chars understate real content. Treat the pair as a range.")


def jl_dir(d, name):
    return [json.loads(x) for x in open(os.path.join(d, name), encoding="utf-8")]


if __name__ == "__main__":
    avg, avg_old = main()
    if "--documents" in sys.argv:
        documents_estimate(avg, avg_old)
