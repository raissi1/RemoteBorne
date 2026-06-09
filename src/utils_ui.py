import os
import sys

def resource_path(path):
    """Retourne le bon chemin (dev ou exe PyInstaller)"""
    try:
        base = sys._MEIPASS  # mode exe
    except Exception:
        base = os.path.abspath(".")  # mode dev

    return os.path.join(base, path)
    
def center_window(parent, win, width=900, height=600):
    try:
        if parent and parent.winfo_exists():
            parent.update_idletasks()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            if pw > 1 and ph > 1:
                x = px + max(0, (pw - width) // 2)
                y = py + max(0, (ph - height) // 2)
                win.geometry(f"{width}x{height}+{x}+{y}")
                return
    except Exception:
        pass
    win.update_idletasks()
    x = max(0, (win.winfo_screenwidth() - width) // 2)
    y = max(0, (win.winfo_screenheight() - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")

    try:
        if parent:
            win.transient(parent)
        win.lift()
        win.focus_force()
    except Exception:
        pass