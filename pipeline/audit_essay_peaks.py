"""Which peaks and turning points in the essay can the data tell apart from noise?

Reads the committed site/data/series.js (5-year trailing series + their 95% intervals) and, for
each series, lists the years whose window is statistically indistinguishable from the peak
(z < 1.96, only windows that do not overlap), then a set of the specific pairs the essay's
sentences lean on. Run: python3 audit_essay_peaks.py
"""

import json
import math
import re
from pathlib import Path

S = (Path(__file__).resolve().parent.parent / "site" / "data" / "series.js").read_text(
    encoding="utf-8"
)


def load(name):
    i = S.index(f"const {name}=") + len(name) + 7
    t = re.sub(r"\s*//[^\n]*|/\*.*?\*/", "", S[i:], flags=re.S)
    return json.JSONDecoder().raw_decode(t.lstrip())[0]


CI = load("SERIES_CI")
PTS = {
    "dark": load("DARK_PTS"),
    "red": load("RED_PTS"),
    "face": load("FACE_PTS"),
    "text": load("TEXT_PTS"),
    "sym": load("SYM_PTS"),
    "diag": load("DIAG_PTS"),
}


def se(c):
    return (c[2] - c[1]) / (2 * 1.96)


for k, pts in PTS.items():
    ci = {c[0]: c for c in CI[k]}
    val = {y: v for y, v in pts}
    ys = [y for y in val if y in ci and ci[y][3] >= 0]
    pk = max(ys, key=lambda y: val[y])
    mn = min(ys, key=lambda y: val[y])
    print(f"\n== {k}: peak {pk} = {val[pk]} (n={ci[pk][3]}) ; low {mn} = {val[mn]}")
    for ref in (pk,):
        ind = []
        for y in sorted(ys):
            if y == ref or abs(y - ref) < 5:
                continue
            z = (val[ref] - val[y]) / math.sqrt(se(ci[ref]) ** 2 + se(ci[y]) ** 2)
            ind.append((y, round(val[y], 1), round(z, 1)))
        print(" vs peak (year, value, z)  [|z|<1.96 = not distinguishable]:")
        print("  ", [t for t in ind if abs(t[2]) < 1.96] or "ninguno indistinguible")
    print("  serie:", [(y, val[y], ci[y][3]) for y in sorted(ys)])

print("\n\n######## pares concretos")


def pair(k, a, b):
    ci = {c[0]: c for c in CI[k]}
    val = dict(PTS[k])
    z = (val[b] - val[a]) / math.sqrt(se(ci[a]) ** 2 + se(ci[b]) ** 2)
    print(
        f"{k}: {a}={val[a]} [{ci[a][1]},{ci[a][2]}] n={ci[a][3]}  vs  {b}={val[b]} [{ci[b][1]},{ci[b][2]}] n={ci[b][3]}  z={z:+.1f}  {'distinguible' if abs(z) > 1.96 else 'NO distinguible'}"
    )


for a in [
    ("dark", 1935, 1950),
    ("dark", 1935, 1970),
    ("dark", 1950, 1970),
    ("dark", 1970, 1980),
    ("dark", 1980, 2020),
    ("dark", 1985, 2020),
    ("red", 1985, 2000),
    ("red", 1960, 2000),
    ("red", 1980, 2000),
    ("red", 2000, 2020),
    ("face", 1940, 1945),
    ("face", 1945, 1955),
    ("face", 1945, 2026),
    ("face", 1990, 2000),
    ("text", 1960, 2026),
    ("text", 1975, 2010),
    ("text", 2010, 2026),
    ("sym", 1960, 1980),
    ("sym", 1980, 2010),
    ("sym", 2010, 2020),
    ("sym", 1985, 2010),
    ("diag", 1945, 1960),
    ("diag", 1960, 1970),
    ("diag", 1970, 1990),
    ("diag", 1990, 2010),
    ("diag", 2010, 2026),
]:
    pair(*a)
D = load("DECADE_STATS")
T = load("TYPO")
B = load("BLOOD_SEMANTIC")
dec = [1920 + 10 * i for i in range(11)]
print(
    "\ntypo 1940s ornate", T[2][0], D["typo"]["ci"][2][0], "minimal", T[2][4], D["typo"]["ci"][2][4]
)
print(
    "typo 2020s ornate",
    T[10][0],
    D["typo"]["ci"][10][0],
    "minimal",
    T[10][4],
    D["typo"]["ci"][10][4],
    "clean",
    T[10][3],
    D["typo"]["ci"][10][3],
)
print("blood", [(d, b, c) for d, b, c in zip(dec, B, D["blood"]["ci"])])
