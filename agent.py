"""Agentska petlja bez frameworka: model -> tool call -> rezultat -> model.

Upotreba:  python agent.py zadaci/seznam
"""
import json
import shutil
import sys
import time
from pathlib import Path

from groq import APIError, BadRequestError, Groq, RateLimitError

from sandbox import Sandbox
from tools import Alati, TOOL_SCHEMAS, groq_seme

MODEL = "openai/gpt-oss-120b"  # besplatni nivo na Groqu, podržava tool calling
MAX_KORAKA = 25                 # budžet: koliko puta smijemo pozvati model
MAX_TOKENA_ODGOVOR = 4096
GROQ_ALATI = groq_seme(TOOL_SCHEMAS)

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


def je_tool_use_failed(greska):
    """gpt-oss ponekad vrati 400 tool_use_failed umjesto normalnog tool call-a."""
    tijelo = getattr(greska, "body", None) or {}
    if isinstance(tijelo, dict):
        err = tijelo.get("error") or {}
        if isinstance(err, dict) and err.get("code") == "tool_use_failed":
            return True
    return "tool_use_failed" in str(greska)


def sacuvaj_trace(run_dir, trace):
    """Poslije svakog koraka, da pad ili Ctrl+C ne pobriše historiju."""
    (run_dir / "trace.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False))


def pozovi_model(client, messages):
    """Jedan poziv Groq chat API-ja. Na 429 sačeka i proba ponovo (besplatni limit)."""
    for pokusaj in range(6):
        try:
            return client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_TOKENA_ODGOVOR,
                messages=messages,
                tools=GROQ_ALATI,
                tool_choice="auto",
            )
        except RateLimitError:
            if pokusaj == 5:
                raise
            print("Groq rate limit, čekam 30s...")
            time.sleep(30)


def argumenti_poziva(sirovo):
    """function.arguments stiže kao JSON string. Loš JSON ide modelu kao greška."""
    try:
        argumenti = json.loads(sirovo or "{}")
    except json.JSONDecodeError as e:
        return None, f"Argumenti nisu ispravan JSON: {e}"
    if not isinstance(argumenti, dict):
        return None, "Argumenti moraju biti JSON objekat."
    return argumenti, None


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
        (
            f"- Testovi: {rezultat['prosli']}/{rezultat['ukupno']}"
            if rezultat.get("prosli") is not None
            else "- Testovi: nisu provjereni"
        ),
        f"- Koraci: {rezultat['koraci']} / {MAX_KORAKA}",
        f"- Tokeni: {rezultat['ulazni_tokeni']} ulaz, {rezultat['izlazni_tokeni']} izlaz",
        "",
        "## Prekid",
        "",
        (rezultat.get("prekid") or "").strip() or "(nema, run je došao do kraja)",
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

    client = Groq()  # čita GROQ_API_KEY iz okruženja
    messages = [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": f"Opis zadatka:\n{opis}\n\nPopravi program tako da prolaze svi testovi u tests/.",
        },
    ]
    trace = []
    ulazni_tokeni = izlazni_tokeni = 0
    korak = 0
    prosli = ukupno = None
    prekid = None
    sacuvaj_trace(run_dir, trace)

    try:
        with Sandbox(workdir) as sb:
            alati = Alati(sb, workdir)
            zavrseno = False

            try:
                for korak in range(1, MAX_KORAKA + 1):
                    try:
                        odgovor = pozovi_model(client, messages)
                    except RateLimitError as e:
                        prekid = f"Groq rate limit i poslije čekanja: {e}"
                        print(f"\n{prekid}")
                        break
                    except BadRequestError as e:
                        if je_tool_use_failed(e):
                            tekst = kratko(e, 500)
                            print(f"\n[{korak}] GROQ je odbio tool call (tool_use_failed). Tražim novi poziv.")
                            messages.append({
                                "role": "user",
                                "content": (
                                    "Tvoj zadnji poziv alata je odbijen (tool_use_failed). "
                                    "Pozovi alat ponovo, s ispravnim JSON argumentima.\n"
                                    + tekst
                                ),
                            })
                            trace.append({"korak": korak, "uloga": "greska",
                                          "tekst": f"tool_use_failed: {tekst}"})
                            sacuvaj_trace(run_dir, trace)
                            continue
                        prekid = f"Groq 400: {e}"
                        print(f"\n{prekid}")
                        break
                    except APIError as e:
                        prekid = f"Groq API: {e}"
                        print(f"\n{prekid}")
                        break

                    poruka = odgovor.choices[0].message
                    if odgovor.usage:
                        ulazni_tokeni += odgovor.usage.prompt_tokens or 0
                        izlazni_tokeni += odgovor.usage.completion_tokens or 0

                    pozivi = poruka.tool_calls or []
                    # Historija mora dobiti isti tool_calls koje je model vratio, pa da
                    # sljedeći "tool" odgovori imaju na šta da se vežu.
                    asistent = {"role": "assistant", "content": poruka.content or ""}
                    if pozivi:
                        asistent["tool_calls"] = [
                            {
                                "id": p.id,
                                "type": "function",
                                "function": {
                                    "name": p.function.name,
                                    "arguments": p.function.arguments,
                                },
                            }
                            for p in pozivi
                        ]
                    messages.append(asistent)
                    trace.append({"korak": korak, "uloga": "assistant", "sadrzaj": asistent})

                    if poruka.content and poruka.content.strip():
                        print(f"\n[{korak}] MISLI: {poruka.content.strip()}")

                    if not pozivi:
                        razlog = odgovor.choices[0].finish_reason
                        print(f"\nAgent je stao bez poziva alata (finish_reason={razlog}).")
                        sacuvaj_trace(run_dir, trace)
                        break

                    for p in pozivi:
                        argumenti, greska_json = argumenti_poziva(p.function.arguments)
                        if greska_json:
                            tekst, greska = greska_json, True
                            argumenti = {}
                        else:
                            tekst, greska = alati.pozovi(p.function.name, argumenti)
                        print(f"[{korak}] ALAT: {p.function.name}({kratko(json.dumps(argumenti, ensure_ascii=False), 120)})")
                        print(f"      {'GREŠKA' if greska else '->'} {kratko(tekst)}")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": p.id,
                            "name": p.function.name,
                            "content": tekst,
                        })
                        trace.append({"korak": korak, "uloga": "alat", "ime": p.function.name,
                                      "ulaz": argumenti, "izlaz": tekst, "greska": greska})

                        if p.function.name == "finish":
                            zavrseno = True
                            print(f"\nSAŽETAK AGENTA:\n{argumenti.get('summary', '')}")

                    sacuvaj_trace(run_dir, trace)
                    if zavrseno:
                        break
                else:
                    print(f"\nPotrošen budžet od {MAX_KORAKA} koraka.")
            except KeyboardInterrupt:
                prekid = "prekinuto (Ctrl+C)"
                print("\nPrekinuto. Spremam ono što je do sad urađeno.")

            # Konačna provjera: ne vjerujemo agentu na riječ, sami kompajliramo i testiramo.
            if prekid != "prekinuto (Ctrl+C)":
                try:
                    (workdir / "prog").unlink(missing_ok=True)
                    alati.compile()
                    prosli, ukupno, _ = alati.pokreni_testove()
                except Exception as e:
                    dodatak = f"konačna provjera nije uspjela: {type(e).__name__}: {e}"
                    prekid = f"{prekid}; {dodatak}" if prekid else dodatak
                    print(f"\n{dodatak}")
    except KeyboardInterrupt:
        prekid = "prekinuto (Ctrl+C)"
        print("\nPrekinuto. Spremam ono što je do sad urađeno.")
    except Exception as e:
        prekid = prekid or f"{type(e).__name__}: {e}"
        print(f"\nGreška: {prekid}")
    finally:
        rezultat = {
            "zadatak": Path(sys.argv[1]).name,
            "prosli": prosli,
            "ukupno": ukupno,
            "koraci": korak,
            "ulazni_tokeni": ulazni_tokeni,
            "izlazni_tokeni": izlazni_tokeni,
            "prekid": prekid,
        }
        sacuvaj_trace(run_dir, trace)
        (run_dir / "rezultat.json").write_text(json.dumps(rezultat, indent=2, ensure_ascii=False))
        izvjestaj = napisi_izvjestaj(run_dir, rezultat, trace)

    print("\n" + "=" * 50)
    if prosli is None:
        print("Rezultat: testovi nisu provjereni")
    else:
        print(f"Rezultat: {prosli}/{ukupno} testova prolazi")
    if prekid:
        print(f"Prekid: {prekid}")
    print(f"Koraci: {korak}, tokeni: {ulazni_tokeni} ulaz / {izlazni_tokeni} izlaz")
    print(f"Trace, izvještaj i popravljen kod: {run_dir}")
    print()
    print(izvjestaj)


if __name__ == "__main__":
    main()
