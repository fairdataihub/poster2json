import sys, glob, os
sys.path.insert(0, "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/poster2json")
from poster2json import extract as E
E.log = lambda *a, **k: None
A = "/home/joneill/Nextcloud/vaults/jmind/calmi2/poster_science/json_schema/manual_poster_annotation"
CASES = {
    "5128504": A + "/5128504",
    "8228476": A + "/8228476",
    "isporeu2023ee359130949-pdf": A + "/isporeu2023ee359130949-pdf",
    "gasimova": "/storage/poster-work",  # gasimova.pdf lives here
}
for pid, d in CASES.items():
    pdf = glob.glob(d + "/*.pdf")
    pdf = [p for p in pdf if pid.split("ee")[0] in os.path.basename(p) or pid == "gasimova"]
    if not pdf:
        print(pid, "NO PDF")
        continue
    gen = E.extract_text_with_pdfplumber(pdf[0]) or ""
    print("=" * 74)
    print(pid)
    for i, ln in enumerate([l for l in gen.splitlines() if l.strip()][:9]):
        print(f"  {i}| {ln[:118]!r}")
