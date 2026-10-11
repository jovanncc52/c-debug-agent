"""Agentska petlja bez frameworka: model -> tool call -> rezultat -> model.

Upotreba:  python agent.py zadaci/seznam
"""
import json
import shutil
import sys
import time
from pathlib import Path

import anthropic

from sandbox import Sandbox
from tools import Alati, TOOL_SCHEMAS

MODEL = "claude-sonnet-5-5"
MAX_KORAKA = 25            # budžet: koliko puta smijemo pozvati model
MAX_TOKENA_ODGOVOR = 4096

SYSTEM = """Ti si agent za debagovanje C programa. Radiš u izolovanom sandboxu i \
možeš koristiti samo date alate.

Postupak:
1. Pogledaj fajlove i opis zadatka.
2. Kompajliraj i pokreni testove.
3. Na osnovu grešaka (razlika u izlazu, AddressSanitizer izvještaj, upozorenja \
kompajlera) nađi uzrok u kodu. Ako test padne zbog curenja memorije, pozovi \
run_valgrind na tom testu. Ako program padne (segfault ili ASan abort), pozovi \
gdb_backtrace.
4. Prije svake izmjene u jednoj rečenici napiši hipotezu: šta je bug i zašto.
5. Napravi minimalnu izmjenu, ponovo kompajliraj i testiraj.

Pravila: ne prepisuj cijeli program, ne mijenjaj ponašanje koje testovi ne traže, \
ne mijenjaj testove. Kad svi testovi prođu, pozovi finish."""


def pripremi_run(task_dir):
    """Kopira zadatak u runs/<ime>-<vrijeme>/work, da original ostane netaknut."""
    run_dir = Path("runs") / f"{task_dir.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copytree(task_dir, run_dir / "work")
    return run_dir


def kratko(tekst, n=200):
    tekst = str(tekst).replace("\n", " ")
    return tekst if len(tekst) <= n else tekst[:n] + "..."


def napisi_izvjestaj(run_dir, rezultat, trace):
    """Ljudski čitljiv sažetak runa, pored trace.json i rezultat.json."""
    sazetak = ""
    brojac = {}
    for stavka in trace:
        if stavka.get("uloga") != "alat":
            continue
        ime = stavka.get("ime", "?")
        brojac[ime] = brojac.get(ime, 0) + 1
        if ime == "finish":
            sazetak = (stavka.get("ulaz") or {}).get("summary", "")

    linije = [
        f"# Izvještaj: {rezultat['zadatak']}",
        "",
        f"- Testovi: {rezultat['prosli']}/{rezultat['ukupno']}",
        f"- Koraci: {rezultat['koraci']} / {MAX_KORAKA}",
        f"- Tokeni: {rezultat['ulazni_tokeni']} ulaz, {rezultat['izlazni_tokeni']} izlaz",
        "",
        "## Sažetak agenta",
        "",
        (sazetak or "").strip() or "(agent nije pozvao finish)",
        "",
        "## Pozivi alata",
        "",
    ]
    if brojac:
        linije += [f"- {ime}: {n}" for ime, n in brojac.items()]
    else:
        linije.append("(nema poziva)")
    tekst = "\n".join(linije) + "\n"
    (run_dir / "izvjestaj.md").write_text(tekst)
    return tekst


def main():
    if len(sys.argv) != 2:
        print("Upotreba: python agent.py zadaci/<zadatak>")
        sys.exit(1)

    run_dir = pripremi_run(Path(sys.argv[1]))
    workdir = (run_dir / "work").resolve()
    opis_fajl = workdir / "TASK.md"
    opis = opis_fajl.read_text() if opis_fajl.exists() else "(nema opisa, zaključi iz koda i testova)"

    client = anthropic.Anthropic()  # čita ANTHROPIC_API_KEY iz okruženja
    messages = [{
        "role": "user",
        "content": f"Opis zadatka:\n{opis}\n\nPopravi program tako da prolaze svi testovi u tests/.",
    }]
    trace = []
    ulazni_tokeni = izlazni_tokeni = 0
    korak = 0

    with Sandbox(workdir) as sb:
        alati = Alati(sb, workdir)
        zavrseno = False

        for korak in range(1, MAX_KORAKA + 1):
            odgovor = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENA_ODGOVOR,
                system=SYSTEM,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
            ulazni_tokeni += odgovor.usage.input_tokens
            izlazni_tokeni += odgovor.usage.output_tokens

            # Odgovor modela ide nazad u historiju tačno onakav kakav jeste.
            messages.append({"role": "assistant", "content": odgovor.content})
            trace.append({"korak": korak, "uloga": "assistant",
                          "sadrzaj": [b.model_dump() for b in odgovor.content]})

            for blok in odgovor.content:
                if blok.type == "text" and blok.text.strip():
                    print(f"\n[{korak}] MISLI: {blok.text.strip()}")

            if odgovor.stop_reason != "tool_use":
                print(f"\nAgent je stao bez poziva alata (stop_reason={odgovor.stop_reason}).")
                break

            # Izvrši sve pozive alata iz ovog odgovora.
            rezultati = []
            for blok in odgovor.content:
                if blok.type != "tool_use":
                    continue
                tekst, greska = alati.pozovi(blok.name, blok.input)
                print(f"[{korak}] ALAT: {blok.name}({kratko(json.dumps(blok.input, ensure_ascii=False), 120)})")
                print(f"      {'GREŠKA' if greska else '->'} {kratko(tekst)}")

                rezultati.append({
                    "type": "tool_result",
                    "tool_use_id": blok.id,   # povezuje rezultat s pozivom
                    "content": tekst,
                    "is_error": greska,
                })
                trace.append({"korak": korak, "uloga": "alat", "ime": blok.name,
                              "ulaz": blok.input, "izlaz": tekst, "greska": greska})

                if blok.name == "finish":
                    zavrseno = True
                    print(f"\nSAŽETAK AGENTA:\n{blok.input.get('summary', '')}")

            # Rezultati alata se šalju kao "user" poruka.
            messages.append({"role": "user", "content": rezultati})
            if zavrseno:
                break
        else:
            print(f"\nPotrošen budžet od {MAX_KORAKA} koraka.")

        # Konačna provjera: ne vjerujemo agentu na riječ, sami kompajliramo i testiramo.
        (workdir / "prog").unlink(missing_ok=True)
        alati.compile()
        prosli, ukupno, _ = alati.pokreni_testove()

    rezultat = {
        "zadatak": Path(sys.argv[1]).name,
        "prosli": prosli,
        "ukupno": ukupno,
        "koraci": korak,
        "ulazni_tokeni": ulazni_tokeni,
        "izlazni_tokeni": izlazni_tokeni,
    }
    (run_dir / "trace.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False))
    (run_dir / "rezultat.json").write_text(json.dumps(rezultat, indent=2, ensure_ascii=False))
    izvjestaj = napisi_izvjestaj(run_dir, rezultat, trace)

    print("\n" + "=" * 50)
    print(f"Rezultat: {prosli}/{ukupno} testova prolazi")
    print(f"Koraci: {korak}, tokeni: {ulazni_tokeni} ulaz / {izlazni_tokeni} izlaz")
    print(f"Trace, izvještaj i popravljen kod: {run_dir}")
    print()
    print(izvjestaj)


if __name__ == "__main__":
    main()
