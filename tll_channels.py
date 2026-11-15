#!/usr/bin/env python3
"""
Reorder TV / radio channels in an LG .TLL channel file.

  python3 tll_channels.py export  in.TLL channels.csv
  python3 tll_channels.py apply   in.TLL channels.csv out.TLL [--by-row]

prNum encoding: list = prNum >> 14 (0 = TV, 1 = radio), number = prNum & 0x3FFF.

CSV columns: list, number, name, key, service_type
 - Edit 'name' to rename a channel.
 - Edit 'number' to change the position, or
 - reorder the rows and run apply with --by-row to renumber 1..N per list
   in row order.
Do not edit the 'key' column (onid_tsid_sid) - it identifies the channel.
The file is processed as bytes (Latin-1), so nothing else is modified.
"""
import csv, re, sys

ITEM = re.compile(r"<ITEM>.*?</ITEM>", re.S)
RADIO_BIT = 0x4000


def field(block, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
    return m.group(1) if m else None


def read(path):
    with open(path, "rb") as f:
        return f.read().decode("latin-1")


def dtv_span(text):
    a, b = text.index("<DTV>"), text.index("</DTV>")
    return a, b


def decode_name(hexname):
    raw = bytes.fromhex(hexname)
    if raw and raw[0] < 0x20:  # DVB character-set prefix (05 = ISO 8859-9)
        enc = "iso8859-9" if raw[0] == 5 else "latin-1"
        raw = raw[1:]
    else:
        enc = "latin-1"
    return raw.decode(enc, errors="replace")


def channels(text):
    a, b = dtv_span(text)
    out = []
    for m in ITEM.finditer(text, a, b):
        blk = m.group(0)
        if field(blk, "isDisabled") == "1":
            continue  # disabled duplicates (mapType 3)
        pr = int(field(blk, "prNum"))
        key = "_".join(field(blk, t) for t in
                       ("original_network_id", "transport_id", "service_id"))
        out.append(dict(span=m.span(), pr=pr, key=key,
                        lst="radio" if pr & RADIO_BIT else "tv",
                        num=pr & 0x3FFF,
                        name=decode_name(field(blk, "hexVchName")),
                        stype=field(blk, "serviceType")))
    return out


def export(src, dst):
    ch = channels(read(src))
    ch.sort(key=lambda c: (c["lst"], c["num"]))
    with open(dst, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["list", "number", "name", "key", "service_type"])
        for c in ch:
            w.writerow([c["lst"], c["num"], c["name"], c["key"], c["stype"]])
    print(f"{len(ch)} channels written to {dst}")


def rename(blk, name):
    """Set a new name: hexVchName, vchName and both length fields."""
    old = bytes.fromhex(field(blk, "hexVchName"))
    prefixed = bool(old) and old[0] < 0x20
    try:
        raw = name.encode("iso8859-9" if prefixed else "latin-1")
    except UnicodeEncodeError:
        sys.exit(f"Name {name!r} has characters the TV list cannot store")
    if prefixed:
        raw = old[:1] + raw
    def sub(b, tag, val):
        return re.sub(rf"<{tag}>.*?</{tag}>", lambda m: f"<{tag}>{val}</{tag}>", b, count=1, flags=re.S)
    blk = sub(blk, "hexVchName", raw.hex())
    blk = sub(blk, "notConvertedLengthOfVchName", len(raw))
    blk = sub(blk, "lengthOfVchName", len(raw))
    if not prefixed:  # prefixed entries keep their original (lossy) vchName
        blk = sub(blk, "vchName", name)
    return blk


def mangled(key):
    """How a spreadsheet shows 'onid_tsid_sid': as a time of day (h:mm)."""
    o, t, v = (int(x) for x in key.split("_"))
    tot = (o * 3600 + t * 60 + v) % 86400
    return f"{tot // 3600}:{tot % 3600 // 60:02d}"


def resolve(rows, ch):
    """Find the file channel for each CSV row, even if the spreadsheet
    mangled the key column and/or the name was edited."""
    res = [None] * len(rows)
    claimed = set()
    def claim(i, k):
        res[i] = k
        claimed.add(k)
    # 1. intact keys
    for i, r in enumerate(rows):
        k = r["key"].strip().replace(":", "_")
        if k in ch and k not in claimed:
            claim(i, k)
    # 2. unchanged names that are unique among unclaimed channels
    for i, r in enumerate(rows):
        if res[i] is None:
            c = [k for k in ch if k not in claimed
                 and ch[k]["name"].strip() == r["name"].strip()]
            if len(c) > 1:
                c = [k for k in c if ch[k]["lst"] == r["list"].strip().lower()]
            if len(c) == 1:
                claim(i, c[0])
    # 3. leftovers: match by mangled-key time and service type, by elimination
    changed = True
    while changed and any(x is None for x in res):
        changed = False
        for i, r in enumerate(rows):
            if res[i] is not None:
                continue
            kk = r["key"].strip()
            c = [k for k in ch if k not in claimed
                 and ch[k]["stype"] == r["service_type"].strip()
                 and (mangled(k) == kk or kk.startswith(mangled(k) + ":"))]
            if len(c) != 1:
                c = [k for k in c if ch[k]["lst"] == r["list"].strip().lower()]
            if len(c) == 1:
                claim(i, c[0])
                changed = True
    for i, r in enumerate(rows):
        if res[i] is None:
            sys.exit(f"Cannot identify channel '{r['name']}' (key {r['key']}); "
                     "restore its key or its original name in the CSV")
    return res


def apply(src, csvp, dst, by_row):
    text = read(src)
    ch = {c["key"]: c for c in channels(text)}
    rows = list(csv.DictReader(open(csvp, newline="", encoding="utf-8-sig")))
    new, counters, renames = {}, {"tv": 0, "radio": 0}, {}
    keys = resolve(rows, ch)
    for r, k in zip(rows, keys):
        lst = r["list"].strip().lower()
        if lst not in counters:
            sys.exit(f"List must be tv or radio: {r['name']}")
        counters[lst] += 1
        num = counters[lst] if by_row else int(r["number"])
        if not 1 <= num < 0x4000:
            sys.exit(f"Bad number {num} for {r['name']}")
        new[k] = (lst, num)
        if r["name"].strip() != ch[k]["name"].strip():
            renames[k] = r["name"].strip()
    seen = {}
    for k, (lst, num) in new.items():
        if (lst, num) in seen:
            sys.exit(f"Duplicate {lst} number {num}: {ch[k]['name']} / {ch[seen[(lst, num)]]['name']}")
        seen[(lst, num)] = k
    # rebuild text, replacing prNum only (back to front keeps offsets valid)
    for k, (lst, num) in sorted(new.items(), key=lambda kv: -ch[kv[0]]["span"][0]):
        a, b = ch[k]["span"]
        pr = num | (RADIO_BIT if lst == "radio" else 0)
        blk = re.sub(r"<prNum>\d+</prNum>", f"<prNum>{pr}</prNum>", text[a:b], count=1)
        if k in renames:
            blk = rename(blk, renames[k])
        text = text[:a] + blk + text[b:]
    with open(dst, "wb") as f:
        f.write(text.encode("latin-1"))
    print(f"Wrote {dst}: {len(new)} channels updated, {len(renames)} renamed")
    for k, n in renames.items():
        print(f"  renamed {ch[k]['name']!r} -> {n!r}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 3 and a[0] == "export":
        export(a[1], a[2])
    elif len(a) >= 4 and a[0] == "apply":
        apply(a[1], a[2], a[3], "--by-row" in a)
    else:
        print(__doc__)

