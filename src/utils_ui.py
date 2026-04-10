def center_window(parent, win, width=900, height=600):
    win.update_idletasks()

    try:
        if parent and parent.winfo_exists():
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()

            x = px + (pw // 2) - (width // 2)
            y = py + (ph // 2) - (height // 2)
        else:
            raise Exception
    except Exception:
        x = (win.winfo_screenwidth() // 2) - (width // 2)
        y = (win.winfo_screenheight() // 2) - (height // 2)

    win.geometry(f"{width}x{height}+{x}+{y}")

    try:
        win.transient(parent)
        win.lift()
        win.focus_force()
    except Exception:
        pass