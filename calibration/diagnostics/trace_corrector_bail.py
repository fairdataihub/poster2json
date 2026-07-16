import sys, json, glob, os, re
sys.path.insert(0, "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json")
from poster2json import extract as E
A = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/json_schema/manual_poster_annotation"
IDS = ["15963941", "42", "4519718", "4560930", "4564017", "6724771", "isporeu2023ee359130949-pdf"]


def trace(pid, raw, gt):
    fams = []
    for c in gt:
        nm = c["name"]
        fams.append(nm.split(",")[0].strip() if "," in nm else nm)
    print("=" * 72)
    print(pid, "| authors:", len(gt), "| families:", fams[:4], "...")
    region = E._banner_region(raw, fams[0])
    if not region:
        print("  BAIL: no banner_region for", repr(fams[0]))
        return
    region = region.translate(E._SUP_TRANS)
    print("  region[:240]:", repr(region[:240]))
    # affiliation candidates
    cands = [(int(m.group(1)), m.start(1), m.end()) for m in E._AFFIL_MARK.finditer(region)]
    print("  _AFFIL_MARK cands nums:", [c[0] for c in cands])
    real = []
    for i, (num, ms, me) in enumerate(cands):
        seg_end = cands[i + 1][1] if i + 1 < len(cands) else len(region)
        seg = region[me:seg_end][:280]
        kw = bool(E._INSTITUTION_KW.search(seg))
        if kw:
            real.append((num, ms, me))
        else:
            print(f"    marker {num}: NO institution-kw in {seg[:70]!r}")
    print("  real (kw-bearing) nums:", [r[0] for r in real])
    parsed = E._parse_affiliation_block(region)
    if parsed is None:
        print("  BAIL: _parse_affiliation_block -> None")
        # detect ran-into-body
        for num, ms, me in real:
            end = len(region)
            txt = region[me:end][:200]
            if E._affiliation_ran_into_body(txt):
                why = ("len>180" if len(txt) > E._AFFIL_MAX_LEN else
                       "PROSE_RUN" if E._PROSE_RUN.search(txt) else "CAPS_RUN")
                print(f"    ran_into_body[{num}] ({why}): {txt[:90]!r}")
        return
    amap, bs = parsed
    print("  amap keys:", sorted(amap.keys()))
    ar = region[:bs]
    bad = []
    for fam in fams:
        marks = E._author_marker_nums(ar, fam)
        if not marks or any(n not in amap for n in marks):
            bad.append((fam, marks))
    if bad:
        print("  BAIL: authors without resolvable marker:", bad[:6])
    else:
        print("  WOULD FIRE OK")


for pid in IDS:
    d = os.path.join(A, pid)
    raw = open(glob.glob(d + "/*_raw.md")[0], encoding="utf-8").read()
    ann = json.load(open(os.path.join(d, pid + ".json"), encoding="utf-8"))
    gt = [c for c in ann["creators"] if c.get("name")]
    trace(pid, raw, gt)
