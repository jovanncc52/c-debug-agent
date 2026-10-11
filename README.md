# c-debug-agent

Agent koji popravlja C programe dok ne prođu svi testovi. Pisan bez frameworka:
Groq API (tool calling) + Docker sandbox.

## Pokretanje

```bash
docker build -t c-agent-sandbox .
pip install -r requirements.txt
export GROQ_API_KEY=...
python agent.py zadaci/seznam
```

Ključ se uzima na [console.groq.com](https://console.groq.com). Model je `openai/gpt-oss-120b`.
Besplatni nivo ima mali limit tokena u minuti; ako iskoči, agent sačeka 30s i proba ponovo.

Svaki run se kopira u `runs/<zadatak>-<vrijeme>/` (original ostaje netaknut). Tamo
završe `trace.json` (svaki korak agenta), `rezultat.json` (testovi, koraci, tokeni)
i `izvjestaj.md` (sažetak za čitanje).

## Postupak

Dvije stvari rade zajedno, i nisu ista stvar:

- **Docker** je Linux kutija u kojoj se kompajlira i pokreće C. Unutra su `gcc`, `valgrind` i `gdb`. Nema interneta. Agentov kod ne može da ti sruši mašinu.
- **Groq** je servis koji vrati odgovor modela (`openai/gpt-oss-120b`). Model ne vidi tvoj disk i ne pokreće `gcc`. On samo kaže koji alat treba pozvati. `agent.py` taj alat stvarno izvrši.

Kad pokreneš `python agent.py zadaci/seznam`, redoslijed je ovaj:

1. Skripta kopira `zadaci/seznam/` u `runs/seznam-<vrijeme>/work/`. Original ostaje kakav jeste. Sve izmjene idu u kopiju.
2. Podigne se kontejner `c-agent-sandbox`. Folder `work` je unutra vidljiv kao `/work`.
3. Groqu se pošalje sistemsko uputstvo i tekst iz `TASK.md`.
4. Petlja, najviše 25 koraka. Svaki korak:
   - model vrati rečenicu (`[1] MISLI:`) i/ili zahtjev za alatom (`[1] ALAT:`);
   - `tools.py` izvrši alat (čitanje fajla je na disku, `compile` i testovi idu kroz Docker);
   - rezultat alata se vrati modelu kao sljedeća poruka.
5. Petlja stane kad model pozove `finish`, kad prestane zvati alate, ili kad potroši 25 koraka.
6. Skripta sama obriše `prog`, ponovo kompajlira i ponovo pusti sve testove. Ne vjeruje modelu da je "gotovo".
7. U `runs/seznam-<vrijeme>/` upiše `trace.json`, `rezultat.json` i `izvjestaj.md`. Popravljeni kod je u `work/`.

Ako terminal ispiše `Groq rate limit, čekam 30s...`, to je besplatni limit (oko 8000 tokena u minuti). Skripta čeka i nastavlja sama.

Alati koje model smije zvati:

| Alat | Šta uradi |
|---|---|
| `list_files` | lista fajlove u kopiji zadatka |
| `read_file` | pročita fajl s brojevima linija |
| `compile` | `gcc` sa AddressSanitizerom, napravi `./prog` |
| `run_tests` | pokrene `./prog` na svakom `tests/*.in` i uporedi s `.out` |
| `run_valgrind` | jedan test kroz Valgrind, za curenje memorije |
| `gdb_backtrace` | gdb na jednom testu, ako program padne |
| `replace_in_file` | zamijeni jedan tačan komad teksta. Fajlove u `tests/` odbija |
| `finish` | model kaže da je gotov i napiše sažetak |

## Struktura

| Fajl | Šta radi |
|---|---|
| `sandbox.py` | Docker kontejner bez mreže, s limitom memorije/procesa i timeoutom |
| `tools.py` | Alati: `list_files`, `read_file`, `replace_in_file`, `compile`, `run_tests`, `run_valgrind`, `gdb_backtrace`, `finish` |
| `agent.py` | Agentska petlja, budžet koraka, logovanje, konačna provjera |
| `zadaci/<ime>/` | `main.c` s bugovima, `TASK.md`, `tests/*.in` + `*.out` |

## Format zadatka

```
zadaci/seznam/
  TASK.md        opis zadatka
  main.c         program s bugovima
  tests/01.in    ulaz
  tests/01.out   očekivani izlaz
```

Test prolazi samo ako je izlaz isti **i** exit code 0, pa use-after-free i memory
leak (AddressSanitizer) ruše test čak i kad je izlaz tačan.

`compile` pravi `./prog` sa AddressSanitizerom. `run_valgrind` zato kompajlira
poseban binarni fajl u `/tmp` (valgrind i ASan se ne slažu) i vraća skraćen
izvještaj za jedan test. `gdb_backtrace` pokreće već kompajlirani `./prog` u
`gdb -batch` i vraća backtrace ako program padne.
