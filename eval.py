"""Pokreće agenta na svim zadacima i ispiše tabelu rezultata.

Upotreba:  python3 eval.py                 (svi zadaci u zadaci/)
           python3 eval.py zbroj neparni   (samo navedeni)
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ZADACI = Path("zadaci")
RUNS = Path("runs")


def nadji_zadatke(imena):
    if imena:
        return [ZADACI / ime for ime in imena]
    return sorted(p for p in ZADACI.iterdir() if p.is_dir())


def pokreni(zadatak):
    """Pokrene agent.py na jednom zadatku i vrati sadržaj njegovog rezultat.json."""
    prije = set(RUNS.glob(f"{zadatak.name}-*"))
    subprocess.run([sys.executable, "agent.py", str(zadatak)], check=False)
    novi = sorted(set(RUNS.glob(f"{zadatak.name}-*")) - prije)

    if not novi:
        return {"zadatak": zadatak.name, "greska": "agent nije napravio run folder"}
    fajl = novi[-1] / "rezultat.json"
    if not fajl.exists():
        return {"zadatak": zadatak.name, "greska": "nema rezultat.json", "run": str(novi[-1])}
    r = json.loads(fajl.read_text())
    r["run"] = str(novi[-1])
    return r


def popravljen(r):
    return r.get("prosli") is not None and r.get("prosli") == r.get("ukupno") and r["ukupno"] > 0


def red(r):
    if "greska" in r:
        return f"{r['zadatak']:16} PAO: {r['greska']}"
    testovi = f"{r['prosli']}/{r['ukupno']}" if r.get("prosli") is not None else "?"
    oznaka = "OK " if popravljen(r) else "NE "
    linija = (f"{r['zadatak']:16} {oznaka} {testovi:>5}   koraci {r['koraci']:2}   "
              f"tokeni {r['ulazni_tokeni']:6} / {r['izlazni_tokeni']:5}")
    if r.get("prekid"):
        linija += f"   prekid: {r['prekid']}"
    return linija


def main():
    if not os.environ.get("GROQ_API_KEY"):
        sys.exit("GROQ_API_KEY nije postavljen. Prvo: export GROQ_API_KEY=...")

    zadaci = nadji_zadatke(sys.argv[1:])
    rezultati = []
    for i, zadatak in enumerate(zadaci, 1):
        print(f"\n######## [{i}/{len(zadaci)}] {zadatak.name} ########")
        rezultati.append(pokreni(zadatak))

    print("\n" + "=" * 78)
    for r in rezultati:
        print(red(r))
    print("=" * 78)

    ok = sum(popravljen(r) for r in rezultati)
    ulaz = sum(r.get("ulazni_tokeni", 0) for r in rezultati)
    izlaz = sum(r.get("izlazni_tokeni", 0) for r in rezultati)
    print(f"Popravljeno: {ok}/{len(rezultati)}   Ukupno tokena: {ulaz} ulaz / {izlaz} izlaz")

    RUNS.mkdir(exist_ok=True)
    sazetak = RUNS / f"eval-{time.strftime('%Y%m%d-%H%M%S')}.json"
    sazetak.write_text(json.dumps(rezultati, indent=2, ensure_ascii=False))
    print(f"Sažetak: {sazetak}")


if __name__ == "__main__":
    main()