import os
import sys
import subprocess
import threading
import re
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

MAX_LINES = 10000  # max lignes conservées en mémoire ET dans la vue
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _center_on_parent(win, parent, width: int, height: int):
    try:
        parent.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        if pw > 1 and ph > 1:
            x = px + max(0, (pw - width) // 2)
            y = py + max(0, (ph - height) // 2)
            win.geometry(f"{width}x{height}+{x}+{y}")
            return
    except Exception:
        pass
    win.update_idletasks()
    x = (win.winfo_screenwidth() - width) // 2
    y = (win.winfo_screenheight() - height) // 2
    win.geometry(f"{width}x{height}+{x}+{y}")


def _detect_plink() -> str:
    """
    Essaie d'utiliser plink.exe local (tools/ ou même dossier),
    sinon 'plink' depuis le PATH Windows.
    """
    if getattr(sys, "frozen", False):
        project_root = os.path.dirname(sys.executable)
        base_dir = project_root
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # si on est dans src/, on remonte au projet
        project_root = (
            os.path.dirname(base_dir)
            if os.path.basename(base_dir).lower() == "src"
            else base_dir
        )
    tools_dir = os.path.join(project_root, "tools")

    candidates = [
        os.path.join(tools_dir, "plink.exe"),
        os.path.join(base_dir, "plink.exe"),
        "plink",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "plink"


PLINK_PATH = _detect_plink()


class DebugLogsWindow:
    """
    Ultimate debug tool :
      - tail -f distant via plink
      - filtre type "grep -i" en temps réel
      - filtres par niveau (ERROR / WARN / INFO)
      - pause du flux temps réel
      - auto-scroll optionnel
      - sauvegarde de la vue filtrée
    """

    def __init__(self, parent, ssh_info):
        """
        ssh_info:
            - (host, user, password)
            - ou (host, user, password, port)
        """
        self.parent = parent
        if len(ssh_info) == 4:
            self.host, self.user, self.password, self.port = ssh_info
        elif len(ssh_info) == 3:
            self.host, self.user, self.password = ssh_info
            self.port = 22
        else:
            raise ValueError("ssh_info doit être (host, user, password[, port])")

        # Processus & états
        self.processes = {}        # log_name -> subprocess.Popen
        self.running = {}          # log_name -> bool

        # Widgets & options
        self.text_widgets = {}     # log_name -> Text
        self.autoscroll = {}       # log_name -> BooleanVar
        self.pause_live = {}       # log_name -> BooleanVar
        self.saved_files = {}      # log_name -> chemin fichier local

        # Buffers & filtres (pour chaque log)
        self.log_buffers = {}            # log_name -> [str]
        self.filter_text = {}            # log_name -> StringVar
        self.filter_ignore_case = {}     # log_name -> BooleanVar
        self.filter_error = {}           # log_name -> BooleanVar
        self.filter_warn = {}            # log_name -> BooleanVar
        self.filter_info = {}            # log_name -> BooleanVar

        # Fenêtre modale
        self.window = tk.Toplevel(parent)
        self.window.title("Debug - Service Logs (Ultimate)")
        self.window.geometry("1100x700")
        self.window.transient(parent)
        self.window.grab_set()
        self.window.minsize(800, 450)

        # Centrage sur la fenêtre parente
        _center_on_parent(self.window, parent, 1100, 700)

        # Notebook
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True)

        # 3 logs (adaptables)
        self.logs_paths = {
            "EnergyManager.log": "/var/aux/EnergyManager/EnergyManager.log",
            "ChargerApp.log": "/var/aux/ChargerApp/ChargerApp.log",
            "iotc-meter-dispatcher.log": "/var/aux/iotc-meter-dispatcher/iotc-meter-dispatcher.log",
        }

        for name, path in self.logs_paths.items():
            self._create_tab(name, path)

        self.window.protocol("WM_DELETE_WINDOW", self.on_close)
        self.window.wait_window()

    # ------------------------------------------------------------------
    # Création d'un onglet complet (zone texte + barre grep + boutons)
    # ------------------------------------------------------------------
    def _create_tab(self, name: str, remote_path: str):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=name)

        # layout
        frame.rowconfigure(0, weight=1)  # zone texte
        frame.rowconfigure(1, weight=0)  # barre filtre grep
        frame.rowconfigure(2, weight=0)  # boutons
        frame.columnconfigure(0, weight=1)

        # Zone de texte scrollable
        text_area = ScrolledText(frame, wrap="word", height=30)
        text_area.grid(row=0, column=0, sticky="nsew")
        text_area.tag_configure("ERROR", foreground="red")
        text_area.tag_configure("WARN", foreground="orange")
        text_area.tag_configure("INFO", foreground="green")
        self.text_widgets[name] = text_area

        # --- Filtres (grep -i + niveaux) ---
        self.log_buffers[name] = []

        self.filter_text[name] = tk.StringVar()
        self.filter_ignore_case[name] = tk.BooleanVar(value=True)
        self.filter_error[name] = tk.BooleanVar(value=False)
        self.filter_warn[name] = tk.BooleanVar(value=False)
        self.filter_info[name] = tk.BooleanVar(value=False)

        filter_frame = ttk.Frame(frame)
        filter_frame.grid(row=1, column=0, sticky="ew", padx=4, pady=3)
        filter_frame.columnconfigure(1, weight=1)

        ttk.Label(filter_frame, text="grep:").grid(row=0, column=0, padx=4, sticky="w")
        entry = ttk.Entry(filter_frame, textvariable=self.filter_text[name])
        entry.grid(row=0, column=1, sticky="ew", padx=4)
        entry.bind("<Return>", lambda e, n=name: self.apply_filter(n))

        ttk.Checkbutton(
            filter_frame,
            text="-i (ignore case)",
            variable=self.filter_ignore_case[name],
            command=lambda n=name: self.apply_filter(n),
        ).grid(row=0, column=2, padx=4)

        # Filtres par niveau
        ttk.Checkbutton(
            filter_frame,
            text="ERROR",
            variable=self.filter_error[name],
            command=lambda n=name: self.apply_filter(n),
        ).grid(row=1, column=0, padx=4, sticky="w")

        ttk.Checkbutton(
            filter_frame,
            text="WARN",
            variable=self.filter_warn[name],
            command=lambda n=name: self.apply_filter(n),
        ).grid(row=1, column=1, padx=4, sticky="w")

        ttk.Checkbutton(
            filter_frame,
            text="INFO",
            variable=self.filter_info[name],
            command=lambda n=name: self.apply_filter(n),
        ).grid(row=1, column=2, padx=4, sticky="w")

        ttk.Button(
            filter_frame,
            text="Apply",
            command=lambda n=name: self.apply_filter(n),
        ).grid(row=0, column=3, padx=4)

        ttk.Button(
            filter_frame,
            text="Clear",
            command=lambda n=name: self.clear_filter(n),
        ).grid(row=0, column=4, padx=4)

        # Barre de boutons en bas
        self.autoscroll[name] = tk.BooleanVar(value=True)
        self.pause_live[name] = tk.BooleanVar(value=False)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, sticky="ew")
        for col in range(7):
            btn_frame.columnconfigure(col, weight=0)
        btn_frame.columnconfigure(4, weight=1)  # espace élastique

        ttk.Button(
            btn_frame, text="Start",
            command=lambda n=name: self.start_log(n)
        ).grid(row=0, column=0, padx=5, pady=5, sticky="w")

        ttk.Button(
            btn_frame, text="Stop",
            command=lambda n=name: self.stop_log(n)
        ).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Button(
            btn_frame, text="Clear view",
            command=lambda n=name: self.clear_log(n)
        ).grid(row=0, column=2, padx=5, pady=5, sticky="w")

        ttk.Button(
            btn_frame, text="Save view",
            command=lambda n=name: self.save_log(n)
        ).grid(row=0, column=3, padx=5, pady=5, sticky="w")

        ttk.Button(
            btn_frame, text="Exit",
            command=lambda n=name: self.exit_log(n)
        ).grid(row=0, column=4, padx=5, pady=5, sticky="e")

        ttk.Checkbutton(
            btn_frame,
            text="Pause live",
            variable=self.pause_live[name],
            command=lambda n=name: self.on_pause_toggle(n),
        ).grid(row=0, column=5, padx=5, pady=5, sticky="e")

        ttk.Checkbutton(
            btn_frame,
            text="Auto-scroll",
            variable=self.autoscroll[name],
        ).grid(row=0, column=6, padx=5, pady=5, sticky="e")

    # ------------------------------------------------------------------
    # Construction de la commande plink
    # ------------------------------------------------------------------
    def _build_plink_tail_cmd(self, remote_path: str):
        """
        Construit la commande plink pour faire un tail -f sur un fichier de log.
        """
        return [
            PLINK_PATH,
            "-ssh",
            "-batch",
            "-P", str(self.port),
            "-l", self.user,
            "-pw", self.password,
            self.host,
            f"tail -f {remote_path}",
        ]

    # ------------------------------------------------------------------
    # Start / Stop / reader thread
    # ------------------------------------------------------------------
    def start_log(self, log_name: str):
        if log_name in self.processes:
            messagebox.showinfo("Info", f"{log_name} is already being followed.")
            return

        remote_log = self.logs_paths.get(log_name)
        if not remote_log:
            messagebox.showerror("Error", f"No remote path defined for {log_name}.")
            return

        # Dossier local logs
        logs_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_path = os.path.join(logs_dir, f"{log_name.split('.')[0]}_{date_str}.log")

        try:
            log_file = open(file_path, "w", encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open local log file:\n{e}")
            return

        cmd = self._build_plink_tail_cmd(remote_log)

        try:
            popen_kwargs = {}
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                popen_kwargs["startupinfo"] = startupinfo
                popen_kwargs["creationflags"] = CREATE_NO_WINDOW

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                **popen_kwargs,
            )
        except FileNotFoundError:
            messagebox.showerror(
                "Error",
                "Impossible de lancer plink.\n"
                "Vérifie que plink.exe est dans le dossier du projet\n"
                "ou dans le PATH Windows."
            )
            log_file.close()
            return
        except Exception as e:
            messagebox.showerror("Error", f"Could not start log for {log_name}:\n{e}")
            log_file.close()
            return

        self.processes[log_name] = proc
        self.running[log_name] = True

        self.insert_line(log_name, f"[INFO] Started following {log_name}")
        self.insert_line(log_name, f"[INFO] Local file: {file_path}")

        def reader():
            while self.running.get(log_name, False):
                line = proc.stdout.readline()
                if not line:
                    break
                # MAJ UI (thread-safe) + buffer
                self.parent.after(0, self.insert_line, log_name, line)
                # Écrit dans le fichier local complet
                log_file.write(line)
                log_file.flush()
            try:
                proc.kill()
            except Exception:
                pass
            log_file.close()

        threading.Thread(target=reader, daemon=True).start()

    # ------------------------------------------------------------------
    # Filtrage type "tail -f | grep -i"
    # ------------------------------------------------------------------
    def _matches_filter(self, log_name: str, line: str) -> bool:
        # grep text
        pattern = (self.filter_text[log_name].get() or "").strip()
        if pattern:
            if self.filter_ignore_case[log_name].get():
                if pattern.lower() not in line.lower():
                    return False
            else:
                if pattern not in line:
                    return False

        # filtres par niveau
        use_error = self.filter_error[log_name].get()
        use_warn = self.filter_warn[log_name].get()
        use_info = self.filter_info[log_name].get()

        if use_error or use_warn or use_info:
            up = line.upper()
            is_err = "ERROR" in up
            is_warn = "WARN" in up
            is_info = "INFO" in up

            if use_error and is_err:
                return True
            if use_warn and is_warn:
                return True
            if use_info and is_info:
                return True
            # au moins un filtre actif mais aucun match
            return False

        return True

    def _append_line_to_widget(self, log_name: str, line: str):
        text_widget = self.text_widgets.get(log_name)
        if text_widget is None:
            return

        # Tag en fonction du niveau
        tag = None
        if re.search(r"\bERROR\b", line, re.IGNORECASE):
            tag = "ERROR"
        elif re.search(r"\bWARN\b", line, re.IGNORECASE):
            tag = "WARN"
        elif re.search(r"\bINFO\b", line, re.IGNORECASE):
            tag = "INFO"

        text_widget.insert(tk.END, line + "\n", tag)

        # Limiter le nombre de lignes affichées
        try:
            lines = int(text_widget.index("end-1c").split(".")[0])
            if lines > MAX_LINES:
                text_widget.delete("1.0", f"{lines - MAX_LINES}.0")
        except Exception:
            pass

        if self.autoscroll[log_name].get() and not self.pause_live[log_name].get():
            text_widget.see(tk.END)

    def insert_line(self, log_name: str, line: str):
        """
        Appelé à chaque nouvelle ligne reçue (comme tail -f).
        On stocke dans le buffer + on affiche seulement si ça matche le filtre,
        et si le flux live n'est pas en pause.
        """
        line = line.rstrip("\n")

        # buffer mémoire
        buf = self.log_buffers.get(log_name)
        if buf is not None:
            buf.append(line)
            if len(buf) > MAX_LINES:
                buf.pop(0)

        # si pause live : on n'affiche rien, mais on garde dans le buffer
        if self.pause_live[log_name].get():
            return

        if not self._matches_filter(log_name, line):
            return

        self._append_line_to_widget(log_name, line)

    def apply_filter(self, log_name: str):
        """
        Réapplique le filtre sur le buffer complet (comme si on faisait
        tail -f | grep ... mais sur l'historique).
        """
        text_widget = self.text_widgets.get(log_name)
        buf = self.log_buffers.get(log_name)
        if text_widget is None or buf is None:
            return

        text_widget.delete("1.0", tk.END)

        for line in buf:
            if self._matches_filter(log_name, line):
                self._append_line_to_widget(log_name, line)

        text_widget.see("end")

    def clear_filter(self, log_name: str):
        self.filter_text[log_name].set("")
        self.filter_ignore_case[log_name].set(True)
        self.filter_error[log_name].set(False)
        self.filter_warn[log_name].set(False)
        self.filter_info[log_name].set(False)
        self.apply_filter(log_name)

    def on_pause_toggle(self, log_name: str):
        """
        Quand on enlève la pause, on réapplique le filtre pour afficher
        l'historique complet à jour.
        """
        if not self.pause_live[log_name].get():
            # on vient de REPRENDRE le flux => on resynchronise la vue
            self.apply_filter(log_name)

    # ------------------------------------------------------------------
    # Boutons
    # ------------------------------------------------------------------
    def stop_log(self, log_name: str):
        if log_name in self.processes:
            self.running[log_name] = False
            try:
                self.processes[log_name].kill()
            except Exception:
                pass
            del self.processes[log_name]
            messagebox.showinfo("Info", f"Stopped following {log_name}.")

    def clear_log(self, log_name: str):
        # efface la vue + le buffer
        if log_name in self.log_buffers:
            self.log_buffers[log_name] = []
        if log_name in self.text_widgets:
            self.text_widgets[log_name].delete("1.0", tk.END)

    def save_log(self, log_name: str):
        """
        Sauvegarde la VUE COURANTE (filtrée), comme un grep redirigé
        vers un fichier.
        """
        text_widget = self.text_widgets.get(log_name)
        if text_widget is None:
            return

        content = text_widget.get("1.0", tk.END)
        if not content.strip():
            messagebox.showwarning("Warning", "No content to save.")
            return

        # dossier logs du projet
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(base_dir)
        logs_dir = os.path.join(project_root, "logs")
        os.makedirs(logs_dir, exist_ok=True)

        file_path = filedialog.asksaveasfilename(
            title=f"Save view of {log_name}",
            defaultextension=".log",
            initialfile=f"view_{log_name}",
            initialdir=logs_dir,
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            messagebox.showerror("Error", f"Could not save log:\n{e}")
            return

        self.saved_files[log_name] = file_path
        messagebox.showinfo("Success", f"Log successfully saved:\n{file_path}")

    def exit_log(self, log_name: str):
        self.stop_log(log_name)
        self.window.destroy()

    def on_close(self):
        for log_name in list(self.processes.keys()):
            self.stop_log(log_name)
        self.window.destroy()


# ---------- Wrapper utilisé par RemoteBorneManager.py ----------
def open_debug_logs_window(parent, host: str, user: str, password: str, port: int = 22):
    """
    Appel simple depuis RemoteBorneManager:
        debug_logs.open_debug_logs_window(self.root, self.host, self.user, self.password, self.port)
    """
    ssh_info = (host, user, password, port)
    DebugLogsWindow(parent, ssh_info)
