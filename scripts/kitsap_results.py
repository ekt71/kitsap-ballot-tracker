#!/usr/bin/env python3
"""Build the Kitsap Ballot Tracker data document.

Multi-county contests come from the Secretary of State (full results);
Kitsap-only contests come from the Kitsap County Auditor page.

Usage: python3 kitsap_results.py KITSAP_HTML STATE_JSON PREV_JSON_OR_- OUT_JSON
  KITSAP_HTML: https://www.kitsap.gov/auditor/Documents/results.html
  STATE_JSON:  https://results.votewa.gov/results/public/api/elections/washington/20261103/data
Prints one JSON line: {"changed": bool, "message": str}
"""
import json, re, sys, datetime
from bs4 import BeautifulSoup

CONTESTS = [
    ("ip26-645", "Initiative Measure No. IP26-645", "State measures", "Initiative Measure No. IP26-645", "Repeals the 9.9% tax on annual income over $1M; prohibits income taxes"),
    ("il26-001", "Initiative Measure No. IL26-001", "State measures", "Initiative Measure No. IL26-001", "Parental rights relating to children in public school"),
    ("il26-638", "Initiative Measure No. IL26-638", "State measures", "Initiative Measure No. IL26-638", "Participation in K-12 school athletics"),
    ("cd6", "Congressional District 6 U.S. Representative", "Federal", "U.S. Representative, CD 6", ""),
    ("ld23-1", "Legislative District 23 State Representative Position 1", "Legislative", "LD 23 State Rep., Position 1", ""),
    ("ld23-2", "Legislative District 23 State Representative Position 2", "Legislative", "LD 23 State Rep., Position 2", ""),
    ("assessor", "Kitsap County Assessor", "County offices", "County Assessor", ""),
    ("auditor", "Kitsap County Auditor", "County offices", "County Auditor", ""),
    ("clerk", "Kitsap County Clerk", "County offices", "County Clerk", ""),
    ("prosecutor", "Kitsap County Prosecuting Attorney", "County offices", "Prosecuting Attorney", ""),
    ("sheriff", "Kitsap County Sheriff", "County offices", "County Sheriff", ""),
    ("sc1", "Supreme Court Justice Position 1 - 2-year unexpired term", "Judicial", "Supreme Court, Position 1", "2-year unexpired term"),
    ("sc3", "Supreme Court Justice Position 3", "Judicial", "Supreme Court, Position 3", ""),
    ("sc4", "Supreme Court Justice Position 4", "Judicial", "Supreme Court, Position 4", ""),
    ("sc5", "Supreme Court Justice Position 5 - 2-year unexpired term", "Judicial", "Supreme Court, Position 5", "2-year unexpired term"),
    ("sc7", "Supreme Court Justice Position 7", "Judicial", "Supreme Court, Position 7", ""),
    ("coa", "Court of Appeals, Division 2, District 2 - Judge Position 1", "Judicial", "Court of Appeals, Div. 2, Dist. 2, Pos. 1", ""),
    ("pud-prop1", "Kitsap County Public Utility District No. 1", "Local measure", "PUD No. 1 Proposition 1", "Authorizes the PUD to build or acquire electric generation, transmission or distribution facilities"),
]

STATE_NAMES = {'ip26-645': 'Initiative Measure No. IP26-645', 'il26-001': 'Initiative Measure No. IL26-001', 'il26-638': 'Initiative Measure No. IL26-638', 'cd6': 'Congressional District 6 - U.S. Representative', 'sc1': 'Supreme Court - Justice Position #01', 'sc3': 'Supreme Court - Justice Position #03', 'sc4': 'Supreme Court - Justice Position #04', 'sc5': 'Supreme Court - Justice Position #05', 'sc7': 'Supreme Court - Justice Position #07', 'coa': 'Court of Appeals, Division 2, District 2 - Judge Position 1'}

# Districts that include only part of a county, where county-level ballots-left estimates don't apply
PARTIAL_COUNTY_DISTRICTS = {"cd6"}

NUM = re.compile(r"^-?[\d,]+$")
PCT = re.compile(r"^-?[\d.]+%$")


def num(s):
    return int(s.replace(",", ""))


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    t = [re.sub(r"\s+", " ", x).strip() for x in soup.get_text("\n").split("\n")]
    t = [x for x in t if x]
    meta = {"runTime": "", "runDate": "", "ballots": 0, "registered": 0, "precincts": "", "status": ""}
    for i, x in enumerate(t):
        if x == "Run Time" and i + 1 < len(t): meta["runTime"] = t[i + 1]
        if x == "Run Date" and i + 1 < len(t): meta["runDate"] = t[i + 1]
        if x in ("Unofficial Results", "Official Results") and not meta["status"]: meta["status"] = x
        if x == "Registered Voters" and i + 1 < len(t):
            m = re.match(r"([\d,]+) of ([\d,]+)", t[i + 1])
            if m: meta["ballots"], meta["registered"] = num(m.group(1)), num(m.group(2))
        if x == "Precincts Reporting" and i + 1 < len(t): meta["precincts"] = t[i + 1]

    found = {}
    i = 0
    while i < len(t):
        if t[i] == "Choice" and i > 0:
            name = t[i - 1]
            j = i + 1
            while j < len(t) and t[j] != "Total": j += 1
            j += 1
            choices, extra = [], {}
            while j < len(t) and t[j] != "Choice" and t[j] != "*** End of report ***":
                label = t[j]; j += 1
                vals = []
                while j < len(t) and (NUM.match(t[j]) or PCT.match(t[j])):
                    vals.append(t[j]); j += 1
                nums = [num(v) for v in vals if NUM.match(v)]
                if label.endswith(":"):
                    if nums: extra[label[:-1].lower()] = nums[-1]
                    if label == "write-ins:": break
                    continue
                if not nums: continue
                party = ""
                m = re.match(r"(.*?)\s*\(Prefers (.*?)\)$", label)
                if m: label, party = m.group(1).strip(), m.group(2).strip()
                choices.append({"name": label, "party": party, "votes": nums[-1]})
            found[name] = {"choices": choices, **extra}
            i = j
            continue
        i += 1

    contests = []
    for cid, src, group, title, note in CONTESTS:
        c = found.get(src)
        if c is None:
            contests.append({"id": cid, "group": group, "title": title, "note": note, "missing": True, "choices": []})
            continue
        wi = c.get("write-ins", 0)
        ch = list(c["choices"])
        if wi: ch.append({"name": "Write-in", "party": "", "votes": wi, "writein": True})
        cast = sum(x["votes"] for x in ch)
        for x in ch: x["pct"] = round(100 * x["votes"] / cast, 2) if cast else 0
        ch.sort(key=lambda x: -x["votes"])
        contests.append({"id": cid, "group": group, "title": title, "note": note,
                         "measure": ch and {x["name"] for x in ch if not x.get("writein")} <= {"Yes", "No"},
                         "cast": cast, "undervotes": c.get("undervotes", 0), "overvotes": c.get("overvotes", 0),
                         "choices": ch})
    return meta, contests


def txt(v):
    if isinstance(v, list):
        for x in v:
            if x.get("languageId") == "en": return x.get("text") or ""
        return (v[0].get("text") or "") if v else ""
    return v or ""


def parse_state(data, contests):
    """Replace multi-county contests with full results from the state data."""
    el = data.get("election") or {}
    items = {txt(b.get("name")).strip(): b for b in data.get("ballotItems") or []}
    # Per-county ballots counted and each county's own estimate of ballots left to count
    left_by, names = {}, {}
    for s in data.get("statistics") or []:
        if "Ballots Left" in txt(s.get("name")):
            for g in s.get("groups") or []:
                for ch in g.get("children") or []:
                    cid = (ch.get("id") or "").lower()
                    names[cid] = txt(ch.get("name")).strip()
                    if ch.get("value") is not None: left_by[cid] = float(ch["value"])
    counted_by = {}
    for l in data.get("localityElections") or []:
        cid = (l.get("jurisdictionId") or "").lower()
        counted_by[names.get(cid, cid)] = float(l.get("ballotsCast") or 0)
    left_named = {names[k]: v for k, v in left_by.items() if k in names}

    def est(counties):
        """Estimated % of ballots counted, over the counties that have reported and given an estimate.
        Returns {"pct", "of", "total"}: "of" counties used out of "total" in scope."""
        if not counties: return None
        use = [c for c in counties if counted_by.get(c, 0) > 0 and c in left_named]
        if not use: return None
        cnt = sum(counted_by[c] for c in use); lft = sum(left_named[c] for c in use)
        return {"pct": round(100 * cnt / (cnt + lft), 1), "of": len(use), "total": len(counties)} if cnt + lft else None

    all_counties = sorted(counted_by)
    tot_counted = int(sum(counted_by.values())); tot_left = int(sum(left_named.values()))
    smeta = {"ballots": int(el.get("ballotsCast") or 0) or tot_counted, "registered": int(el.get("totalVoters") or 0),
             "left": tot_left, "pctCounted": est(all_counties), "kitsapPct": est(["Kitsap County"]),
             "asOf": el.get("asOf") or "", "official": bool(el.get("isOfficialResults"))}
    out = []
    for c in contests:
        name = STATE_NAMES.get(c["id"])
        b = items.get(name) if name else None
        if not name:
            c["scope"] = "Kitsap County"
            c["pctCounted"] = smeta["kitsapPct"]
            out.append(c); continue
        if b is None:
            c["stateMissing"] = True
            c["scope"] = "Kitsap share only (state results not found)"
            out.append(c); continue
        ch = []
        for o in (b.get("summaryResults") or {}).get("ballotOptions") or []:
            nm = txt(o.get("name")).strip()
            wi = bool(o.get("isWriteIn"))
            if wi and not o.get("voteCount"): continue
            ch.append({"name": "Write-in" if wi else nm, "party": c_party(c, nm), "votes": int(o.get("voteCount") or 0),
                       "writein": wi, "winner": bool(o.get("isWinner"))})
        cast = sum(x["votes"] for x in ch)
        for x in ch: x["pct"] = round(100 * x["votes"] / cast, 2) if cast else 0
        ch.sort(key=lambda x: -x["votes"])
        rs = b.get("reportingStatus") or {}
        counties = b.get("crossCounties") or []
        total = int(rs.get("totalUnits") or len(counties) or 1)
        if total >= 39: scope = "Statewide"
        else: scope = f"All {total} counties in the district"
        partial = c["id"] in PARTIAL_COUNTY_DISTRICTS
        out.append({**c, "choices": ch, "cast": cast, "scope": scope,
                    "pctCounted": None if partial else est(counties if total < 39 else all_counties),
                    "pctNote": "Estimate unavailable: district covers only part of Pierce County" if partial else "",
                    "reporting": f'{int(rs.get("reportingUnits") or 0)} of {total} counties reporting',
                    "undervotes": int(b.get("underVoteCount") or 0), "overvotes": int(b.get("overVoteCount") or 0)})
    return smeta, out


def c_party(c, name):
    for x in c.get("choices") or []:
        if x["name"] == name: return x.get("party", "")
    return ""


def leader(c):
    ch = [x for x in c["choices"] if x["votes"] > 0]
    if not ch: return None
    if len(ch) > 1 and ch[0]["votes"] == ch[1]["votes"]: return "tie"
    return ch[0]["name"]


def main():
    html = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    try:
        sdata = json.load(open(sys.argv[2]))
    except Exception:
        sdata = {}
    prev = None
    if sys.argv[3] != "-":
        try:
            d = json.load(open(sys.argv[3]))
            prev = d.get("data", d)
        except Exception:
            prev = None
    meta, contests = parse(html)
    smeta, contests = parse_state(sdata, contests)
    missing = [c["title"] for c in contests if c.get("missing")]
    stamp = f'{meta["runDate"]} {meta["runTime"]}'.strip()
    prev_stamp = (prev or {}).get("countStamp", "")
    prev_ballots = (prev or {}).get("ballots", 0)
    prev_state = (prev or {}).get("state") or {}
    county_new = stamp != prev_stamp or meta["ballots"] != prev_ballots
    state_new = smeta["ballots"] != prev_state.get("ballots", 0) or (
        sum(c.get("cast", 0) for c in contests if c.get("scope") != "Kitsap County")
        != prev_state.get("castSum", -1))
    smeta["castSum"] = sum(c.get("cast", 0) for c in contests if c.get("scope") != "Kitsap County")
    changed = (not prev) or county_new or state_new

    flips = []
    if prev:
        pl = {c["id"]: leader(c) for c in prev.get("contests", [])}
        for c in contests:
            a, b = pl.get(c["id"]), leader(c)
            if a and b and a != b: flips.append(f'{c["title"]}: {b} now leads')
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    doc = {"countStamp": stamp, "status": meta["status"], "ballots": meta["ballots"],
           "registered": meta["registered"], "precincts": meta["precincts"],
           "checkedAt": now, "updatedAt": now if changed else (prev or {}).get("updatedAt", now),
           "prevBallots": prev_ballots if changed else (prev or {}).get("prevBallots", 0),
           "flips": flips if changed else (prev or {}).get("flips", []),
           "state": smeta, "missing": missing, "contests": contests}
    json.dump(doc, open(sys.argv[4], "w"))
    parts = []
    if state_new and smeta["castSum"]:
        parts.append(f'New statewide results: {smeta["ballots"]:,} ballots counted statewide'
                     + (f', about {smeta["left"]:,} left to count.' if smeta["left"] else "."))
    if county_new and meta["ballots"]:
        parts.append(f'New Kitsap count ({stamp}): {meta["ballots"]:,} ballots.')
    msg = " ".join(parts) or "No new results."
    if flips: msg += " Lead changes: " + "; ".join(flips) + "."
    if missing: msg += " Not found on county page: " + ", ".join(missing) + "."
    has_votes = meta["ballots"] > 0 or smeta["castSum"] > 0
    print(json.dumps({"changed": bool(changed and has_votes and parts), "message": msg}))


if __name__ == "__main__":
    main()
