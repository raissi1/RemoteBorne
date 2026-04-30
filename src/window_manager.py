import tkinter as tk


class WindowManager:
    def __init__(self, root):
        self.root = root

    def create_window(self, title="Window", width=900, height=600, modal=True):
        win = tk.Toplevel(self.root)
        win.title(title)

        # Taille par défaut
        win.geometry(f"{width}x{height}")

        # Centrage automatique
        self.center(win, width, height)

        # Comportement pro
        if modal:
            win.transient(self.root)
            win.grab_set()

        win.lift()
        win.focus_force()

        return win

    def center(self, win, width, height):
        win.update_idletasks()

        try:
            px = self.root.winfo_rootx()
            py = self.root.winfo_rooty()
            pw = self.root.winfo_width()
            ph = self.root.winfo_height()

            x = px + (pw // 2) - (width // 2)
            y = py + (ph // 2) - (height // 2)
        except Exception:
            x = (win.winfo_screenwidth() // 2) - (width // 2)
            y = (win.winfo_screenheight() // 2) - (height // 2)

        win.geometry(f"{width}x{height}+{x}+{y}")