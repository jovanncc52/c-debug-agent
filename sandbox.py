"""Docker sandbox: jedan kontejner po pokretanju agenta, komande idu kroz `docker exec`.

Zašto kontejner: agent pokreće kod koji je sam napisao. Bez mreže, s limitom
memorije i procesa, i s timeoutom, beskonačna petlja ili fork bomba ne mogu
ništa da pokvare na tvom računaru.
"""
import os
import subprocess
import uuid

IMAGE = "c-agent-sandbox"


class Sandbox:
    def __init__(self, workdir):
        self.workdir = os.path.abspath(workdir)
        self.ime = f"c-agent-{uuid.uuid4().hex[:8]}"

    def start(self):
        cmd = [
            "docker", "run", "-d", "--rm",
            "--name", self.ime,
            "--network", "none",        # bez interneta
            "--memory", "256m",         # limit memorije
            "--pids-limit", "64",       # nema fork bombi
            "--cap-add", "SYS_PTRACE",  # treba za LeakSanitizer i gdb
            "-v", f"{self.workdir}:/work",
            "-w", "/work",
        ]
        # Da fajlovi koje kontejner napravi (npr. ./prog) pripadaju tebi, a ne root-u.
        if hasattr(os, "getuid"):
            cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
        cmd += [IMAGE, "sleep", "infinity"]
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    def exec(self, komanda, stdin=None, timeout=10):
        """Pokreće komandu u kontejneru. Vraća (exit_code, stdout, stderr).

        Exit code 124 znači da je komanda prekinuta zbog timeouta.
        """
        try:
            p = subprocess.run(
                ["docker", "exec", "-i", self.ime,
                 "timeout", str(timeout), "sh", "-c", komanda],
                input=stdin if stdin is not None else "",  # nikad ne nasljeđuj stdin terminala
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout + 5,
            )
            return p.returncode, p.stdout, p.stderr
        except subprocess.TimeoutExpired:
            return 124, "", f"TIMEOUT nakon {timeout}s"

    def stop(self):
        subprocess.run(["docker", "rm", "-f", self.ime], capture_output=True)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()
