"""Alati koje agent može pozivati.

Svaki alat vraća TEKST, jer je to jedino što model vidi. Najviše učiš upravo
ovdje: koliko izlaza vratiti, kako formulisati greške da se model iz njih
može oporaviti, i šta zabraniti (npr. mijenjanje testova).
"""
from pathlib import Path

MAX_IZLAZ = 3000  # maksimalan broj znakova koje alat vraća modelu
# Valgrind i gdb znaju ispisati stranice teksta; modelu treba samo sažetak.
MAX_IZLAZ_DBG = 1200

GCC = ("gcc -Wall -Wextra -g -fsanitize=address,undefined "
       "-fno-omit-frame-pointer -o prog *.c")
# Valgrind i AddressSanitizer se ne slažu, pa valgrind dobija poseban binarni fajl.
GCC_VALGRIND = ("gcc -Wall -Wextra -g -fno-omit-frame-pointer -o /tmp/prog_vg *.c")
VALGRIND = ("valgrind -q --leak-check=full --show-leak-kinds=all "
            "--error-exitcode=1 --num-callers=6 /tmp/prog_vg")


def skrati(tekst, limit=MAX_IZLAZ):
    """Ako je izlaz predug, zadrži početak i kraj (tu je obično ono bitno)."""
    if len(tekst) <= limit:
        return tekst
    sredina = f"\n... [{len(tekst) - limit} znakova izbačeno] ...\n"
    if len(sredina) >= limit:
        return tekst[:limit]
    ostatak = limit - len(sredina)
    glava = ostatak // 2
    return tekst[:glava] + sredina + tekst[-(ostatak - glava):]


def normalizuj(tekst):
    """Ignoriši razmake na kraju linija i prazne linije na kraju izlaza."""
    return "\n".join(l.rstrip() for l in tekst.strip("\n").splitlines())


class Alati:
    def __init__(self, sandbox, workdir):
        self.sb = sandbox
        self.workdir = Path(workdir).resolve()

    # ---------- pomoćne ----------

    def _putanja(self, path):
        """Ne dozvoli agentu da izađe iz radnog foldera (../../etc/passwd)."""
        p = (self.workdir / path).resolve()
        if not p.is_relative_to(self.workdir):
            raise ValueError(f"Putanja '{path}' izlazi iz radnog foldera.")
        return p

    # ---------- alati ----------

    def list_files(self):
        fajlovi = sorted(
            str(p.relative_to(self.workdir))
            for p in self.workdir.rglob("*")
            if p.is_file() and p.name != "prog"
        )
        return "\n".join(fajlovi) or "(prazno)"

    def read_file(self, path):
        p = self._putanja(path)
        if not p.is_file():
            raise FileNotFoundError(f"Fajl '{path}' ne postoji. Pozovi list_files.")
        linije = p.read_text(errors="replace").splitlines()
        return skrati("\n".join(f"{i:4} | {l}" for i, l in enumerate(linije, 1)), 8000)

    def replace_in_file(self, path, old, new):
        p = self._putanja(path)
        if p.relative_to(self.workdir).parts[0] == "tests":
            raise PermissionError("Testove nije dozvoljeno mijenjati.")
        if not p.is_file():
            raise FileNotFoundError(f"Fajl '{path}' ne postoji.")
        sadrzaj = p.read_text()
        n = sadrzaj.count(old)
        if n == 0:
            raise ValueError("Tekst 'old' nije pronađen. Pročitaj fajl ponovo i "
                             "kopiraj tačan tekst (bez brojeva linija).")
        if n > 1:
            raise ValueError(f"Tekst 'old' se pojavljuje {n} puta. Dodaj okolne "
                             "linije da bude jedinstven.")
        p.write_text(sadrzaj.replace(old, new, 1))
        return f"Izmijenjeno: {path}. Pozovi compile prije testiranja."

    def compile(self):
        code, _, err = self.sb.exec(GCC, timeout=60)
        if code != 0:
            return "GREŠKA pri kompajliranju:\n" + skrati(err)
        poruka = "Kompajliranje uspješno."
        if err.strip():
            poruka += "\nUpozorenja:\n" + skrati(err, 1500)
        return poruka

    def pokreni_testove(self):
        """Vraća (prosli, ukupno, izvjestaj). Koristi se i za konačnu provjeru u agent.py."""
        if not (self.workdir / "prog").exists():
            return 0, 0, "Nema izvršnog fajla 'prog'. Prvo pozovi compile."

        testovi = sorted((self.workdir / "tests").glob("*.in"))
        prosli, padovi = 0, []
        for t in testovi:
            ocekivano = t.with_suffix(".out").read_text()
            code, out, err = self.sb.exec("./prog", stdin=t.read_text(), timeout=5)
            # Test prolazi samo ako je izlaz isti I exit code 0
            # (ASan greška ili memory leak daju exit code != 0).
            if code == 0 and normalizuj(out) == normalizuj(ocekivano):
                prosli += 1
            else:
                padovi.append((t, ocekivano, code, out, err))

        linije = [f"Prošlo {prosli}/{len(testovi)} testova."]
        for t, ocekivano, code, out, err in padovi[:3]:  # detalji samo za prva 3 pada
            timeout = ", TIMEOUT" if code == 124 else ""
            linije.append(f"\n=== {t.name} PAO (exit code {code}{timeout}) ===")
            linije.append("Ulaz:\n" + skrati(t.read_text(), 500))
            linije.append("Očekivano:\n" + (skrati(ocekivano, 500).strip() or "(prazno)"))
            linije.append("Dobijeno:\n" + (skrati(out, 500).strip() or "(prazno)"))
            if err.strip():
                linije.append("stderr:\n" + skrati(err, 1500))
        if len(padovi) > 3:
            linije.append(f"\n(+ još {len(padovi) - 3} palih testova)")
        return prosli, len(testovi), "\n".join(linije)

    def run_tests(self):
        return self.pokreni_testove()[2]

    def _test_fajl(self, test):
        """'01', '01.in' ili 'tests/01.in' -> putanja do ulaznog fajla."""
        ime = str(test).strip()
        if ime.endswith(".out"):
            ime = ime[:-4] + ".in"
        if not ime.endswith(".in"):
            ime += ".in"
        ime = "tests/" + Path(ime).name
        p = self._putanja(ime)
        if not p.is_file():
            raise FileNotFoundError(
                f"Test '{test}' ne postoji. Očekujem npr. tests/01.in."
            )
        return p

    def run_valgrind(self, test):
        """Jedan test kroz valgrind. Binarni fajl je bez sanitizera."""
        ulaz = self._test_fajl(test)
        rel = ulaz.relative_to(self.workdir).as_posix()
        code, _, err = self.sb.exec(GCC_VALGRIND, timeout=60)
        if code != 0:
            return "GREŠKA pri kompajliranju za valgrind:\n" + skrati(err, MAX_IZLAZ_DBG)

        code, out, err = self.sb.exec(f"{VALGRIND} < {rel}", timeout=30)
        if code == 124:
            status = "Valgrind: TIMEOUT."
        elif code == 0:
            status = "Valgrind: nema prijavljenih grešaka ni curenja."
        else:
            status = f"Valgrind: ima grešaka (exit code {code})."

        dijelovi = [status]
        if out.strip():
            dijelovi.append("stdout programa:\n" + skrati(out.strip(), 300))
        if err.strip():
            dijelovi.append(err.strip())
        return skrati("\n".join(dijelovi), MAX_IZLAZ_DBG)

    def _backtrace_tekst(self, tekst):
        """Od gdb/ASan ispisa zadrži signal, prvih 12 okvira i SUMMARY liniju."""
        bitno = []
        okviri = 0
        for linija in tekst.splitlines():
            s = linija.strip()
            if (s.startswith("Program received signal")
                    or s.startswith("[Inferior")
                    or s.startswith("SUMMARY:")):
                bitno.append(s)
            elif s.startswith("#") and okviri < 12:
                bitno.append(s)
                okviri += 1
        return "\n".join(bitno)

    def gdb_backtrace(self, test):
        """gdb -batch: pokreni ./prog na jednom testu i ispiši backtrace ako padne."""
        if not (self.workdir / "prog").exists():
            return "Nema izvršnog fajla 'prog'. Prvo pozovi compile."
        ulaz = self._test_fajl(test)
        rel = ulaz.relative_to(self.workdir).as_posix()
        # detect_leaks=0: curenje nije crash. Za curenje služi run_valgrind.
        cmd = (
            "ASAN_OPTIONS=abort_on_error=1:detect_leaks=0 "
            "gdb -batch -q -nx "
            "-ex 'set pagination off' "
            "-ex 'set confirm off' "
            f"-ex 'run < {rel}' "
            "-ex bt "
            "./prog"
        )
        code, out, err = self.sb.exec(cmd, timeout=20)
        sirovo = (out + ("\n" + err if err.strip() else "")).strip()
        tekst = self._backtrace_tekst(sirovo) or sirovo
        if "exited normally" in sirovo and "Program received signal" not in sirovo:
            tekst = (
                "Program nije pao u gdb-u (nema crash backtrace-a). "
                "Za curenje memorije koristi run_valgrind.\n" + tekst
            )
        if code == 124:
            tekst = "gdb: TIMEOUT.\n" + tekst
        return skrati(tekst or f"(prazan izlaz gdb-a, exit {code})", MAX_IZLAZ_DBG)

    def finish(self, summary):
        return "Završeno."

    # ---------- dispatch ----------

    def pozovi(self, ime, argumenti):
        """Vraća (tekst, is_error). Izuzetak postaje poruka za model, a ne crash agenta."""
        funkcije = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "replace_in_file": self.replace_in_file,
            "compile": self.compile,
            "run_tests": self.run_tests,
            "run_valgrind": self.run_valgrind,
            "gdb_backtrace": self.gdb_backtrace,
            "finish": self.finish,
        }
        if ime not in funkcije:
            return f"Nepoznat alat: {ime}", True
        try:
            return funkcije[ime](**argumenti), False
        except Exception as e:
            return f"{type(e).__name__}: {e}", True


def groq_seme(seme):
    """Groq koristi OpenAI oblik: type=function, parameters umjesto input_schema."""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        }
        for s in seme
    ]


# Opisi alata koje model vidi. Opis je dio prompta: što je jasniji, to bolje.
TOOL_SCHEMAS = [
    {
        "name": "list_files",
        "description": "Lista sve fajlove u radnom folderu.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_file",
        "description": "Čita fajl i vraća ga s numerisanim linijama.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Relativna putanja, npr. main.c"}},
            "required": ["path"],
        },
    },
    {
        "name": "replace_in_file",
        "description": ("Zamijeni tačno jedno pojavljivanje teksta 'old' tekstom 'new'. "
                        "'old' mora biti doslovno kopiran iz fajla (bez brojeva linija) "
                        "i jedinstven u fajlu. Fajlovi u tests/ se ne mogu mijenjati."),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["path", "old", "new"],
        },
    },
    {
        "name": "compile",
        "description": ("Kompajlira sve .c fajlove u ./prog (gcc -Wall -Wextra -g, "
                        "AddressSanitizer i UBSan). Pozovi nakon svake izmjene koda."),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_tests",
        "description": ("Pokreće ./prog na svakom tests/*.in i poredi s .out. Test prolazi "
                        "samo ako je izlaz isti i exit code 0, pa sanitizer greške i memory "
                        "leakovi ruše test. Vraća detalje za prve pale testove."),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_valgrind",
        "description": ("Pokreće jedan test pod valgrindom (poseban binarni fajl, bez "
                        "AddressSanitizer-a). Koristi kad sumnjaš na curenje memorije "
                        "ili čitanje/pisanje oslobođene memorije. Argument test je npr. "
                        "'01' ili 'tests/01.in'. Izlaz je skraćen."),
        "input_schema": {
            "type": "object",
            "properties": {
                "test": {"type": "string", "description": "Ime testa, npr. 01 ili tests/01.in"},
            },
            "required": ["test"],
        },
    },
    {
        "name": "gdb_backtrace",
        "description": ("Pokreće ./prog u gdb-u (batch) na jednom testu i vraća backtrace "
                        "ako program padne. Prvo pozovi compile. Nije za curenje memorije "
                        "(za to je run_valgrind). Argument test je npr. '01'. Izlaz je skraćen."),
        "input_schema": {
            "type": "object",
            "properties": {
                "test": {"type": "string", "description": "Ime testa, npr. 01 ili tests/01.in"},
            },
            "required": ["test"],
        },
    },
    {
        "name": "finish",
        "description": ("Pozovi kad svi testovi prođu ili kad zaključiš da ne možeš dalje. "
                        "U summary napiši koji su bugovi bili i kako si ih popravio."),
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]
