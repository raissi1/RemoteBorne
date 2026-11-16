"""Presentation A: compact connection strip, file table and adjustable workspace.

Every action delegates to the existing RemoteBorneApp handler. No SSH command,
setpoint validation, cancellation rule or background polling is defined here.
"""

import tkinter as tk
import ttkbootstrap as ttk

try:
    from .utils_ui import ScrollableFrame
    from .ui_widgets import FileTable, MenuCommand
except ImportError:
    from utils_ui import ScrollableFrame
    from ui_widgets import FileTable, MenuCommand


def build_main_workspace(app):
    app._configure_ui_styles()
    outer = ScrollableFrame(app.root, horizontal=False)
    outer.pack(fill="both", expand=True)
    main = ttk.Frame(outer.content, padding=8)
    main.pack(fill="both", expand=True)
    connection = ttk.Frame(main, padding=(6, 4))
    connection.pack(fill="x", pady=(0, 6))
    connection.columnconfigure(4, weight=1)
    app.workspace_logo_left = (
        app.logo_left.subsample(max(1, (app.logo_left.height() + 23) // 24))
        if app.logo_left
        else None
    )
    ttk.Label(
        connection,
        text="RBM",
        image=app.workspace_logo_left or "",
        compound="left",
        style="Section.TLabelframe.Label",
    ).grid(row=0, column=0, padx=(0, 12))
    app.ip_label = ttk.Label(
        connection, text=f"IP: {app.host or '-'}", style="Status.TLabel"
    )
    app.ip_label.grid(row=0, column=1, padx=(0, 12))
    app.user_label = ttk.Label(
        connection, text=f"User: {app.user or '-'}", style="Status.TLabel"
    )
    app.user_label.grid(row=0, column=2, padx=(0, 12))
    app.led_canvas = tk.Canvas(
        connection,
        width=20,
        height=20,
        highlightthickness=0,
        background=app.style.colors.bg,
    )
    app.led_canvas.grid(row=0, column=3)
    status_label = ttk.Label(connection, textvariable=app.status_var)
    status_label.grid(row=0, column=4, sticky="w", padx=(4, 8))
    connection_buttons = ttk.Frame(connection)
    connection_buttons.grid(row=0, column=5, sticky="e")
    app.btn_connect = ttk.Button(
        connection_buttons,
        text="Connect",
        bootstyle="info",
        command=app.force_reconnect,
    )
    app.btn_connect.pack(side="left", padx=3)
    app.btn_disconnect = ttk.Button(
        connection_buttons, text="Disconnect", command=app._manual_disconnect
    )
    app.btn_disconnect.pack(side="left", padx=3)
    app.btn_exit = ttk.Button(
        connection_buttons,
        text="Exit",
        bootstyle="secondary-outline",
        command=app.on_exit,
    )
    app.btn_exit.pack(side="left", padx=(3, 0))
    app.workspace_logo_right = (
        app.logo_right.subsample(max(1, (app.logo_right.height() + 23) // 24))
        if app.logo_right
        else None
    )
    if app.workspace_logo_right:
        ttk.Label(connection_buttons, image=app.workspace_logo_right).pack(
            side="left", padx=(8, 0)
        )
    simulation = ttk.Label(
        main, textvariable=app.simulation_var, bootstyle="warning", anchor="center"
    )
    app.simulation_banner = simulation
    # Keep the simulation warning visible exactly as before; its text is empty
    # for real chargers. Brand marks are retained without a large title block.
    # Mapped only in simulation mode, so a blank banner reserves no space.

    app.main_panes = tk.PanedWindow(
        main,
        orient="vertical",
        sashwidth=7,
        borderwidth=0,
        background=app.style.colors.bg,
        sashrelief="flat",
        height=480,
    )
    app.main_panes.pack(fill="both", expand=True)
    app.workspace_panes = tk.PanedWindow(
        app.main_panes,
        orient="horizontal",
        sashwidth=7,
        borderwidth=0,
        background=app.style.colors.bg,
        height=360,
    )
    app.main_panes.add(app.workspace_panes, minsize=300, stretch="always")
    left = ttk.Labelframe(
        app.workspace_panes, text="GridCodes - File browser", padding=6
    )
    right = ttk.Frame(app.workspace_panes)
    app.workspace_panes.add(left, minsize=260, stretch="always")
    app.workspace_panes.add(right, minsize=400, stretch="always")
    left.columnconfigure(0, weight=1)
    left.rowconfigure(3, weight=1)

    path_row = ttk.Frame(left)
    path_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
    path_row.columnconfigure(1, weight=1)
    ttk.Label(path_row, text="Path:").grid(row=0, column=0, padx=(0, 4))
    app.path_entry = ttk.Entry(path_row)
    app.path_entry.grid(row=0, column=1, sticky="ew")
    app.path_entry.insert(0, app.current_path)
    app.path_entry.bind("<Return>", lambda _event: app._go_to_path())
    navigation = ttk.Frame(left)
    navigation.grid(row=1, column=0, sticky="ew", pady=(0, 4))
    navigation_buttons = []
    for column, (attribute, label, command) in enumerate(
        (
            ("btn_go", "Go", app._go_to_path),
            ("btn_up", "Up", app._go_parent),
            ("btn_root", "Root", app._go_root),
            ("btn_refresh", "Refresh", app.refresh_file_list),
        )
    ):
        navigation.columnconfigure(column, weight=1)
        button = ttk.Button(
            navigation,
            text=label,
            width=7 if label == "Refresh" else 4,
            command=command,
        )
        button.grid(row=0, column=column, sticky="ew", padx=(0, 3))
        setattr(app, attribute, button)
        navigation_buttons.append(button)
    find = ttk.Frame(left)
    find.grid(row=2, column=0, sticky="ew", pady=(0, 6))
    find.columnconfigure(0, weight=1)
    app.find_entry = ttk.Entry(find, textvariable=app._file_find_var, width=12)
    app.find_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
    app.find_entry.bind("<Return>", lambda _event: app._apply_file_filter_from_entry())
    app._file_find_var.trace_add("write", app._on_file_find_changed)
    app.btn_find = ttk.Button(
        find, text="Find", width=4, command=app._apply_file_filter_from_entry
    )
    app.btn_find.grid(row=0, column=1, padx=(0, 4))
    app.btn_clear_find = ttk.Button(
        find, text="Clear", width=4, command=app._clear_file_filter
    )
    app.btn_clear_find.grid(row=0, column=2)
    listing = ttk.Frame(left)
    listing.grid(row=3, column=0, sticky="nsew")
    listing.columnconfigure(0, weight=1)
    listing.rowconfigure(0, weight=1)
    app.file_list = FileTable(listing)
    app.file_list.grid(row=0, column=0, sticky="nsew")
    vs = ttk.Scrollbar(listing, orient="vertical", command=app.file_list.yview)
    vs.grid(row=0, column=1, sticky="ns")
    hs = ttk.Scrollbar(listing, orient="horizontal", command=app.file_list.xview)
    hs.grid(row=1, column=0, sticky="ew")
    app.file_list.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
    app.file_list.bind_open_command(app.on_file_double_click)
    app.file_list.bind("<Button-3>", app._on_file_menu)

    file_actions = ttk.Frame(left)
    file_actions.grid(row=4, column=0, sticky="ew", pady=(6, 0))
    for column, (attribute, label, command) in enumerate(
        (
            ("btn_download", "Download", app._menu_download),
            ("btn_edit", "Edit", app._menu_edit),
            ("btn_upload", "Upload", app.upload_files_to_current_path),
        )
    ):
        button = ttk.Button(file_actions, text=label, bootstyle="info", command=command)
        button.grid(row=0, column=column, sticky="ew", padx=(0, 4))
        setattr(app, attribute, button)
    app.file_actions_menu = tk.Menu(app.root, tearoff=0)
    app.btn_print = MenuCommand(app.file_actions_menu, "Print", app._menu_print)
    app.btn_copy_panel = MenuCommand(
        app.file_actions_menu, "Apply Grid Code", app.copy_selected_to_gridcodes
    )
    app.btn_edit_current_properties = MenuCommand(
        app.file_actions_menu,
        "Active properties",
        app.edit_current_gridcodes_properties,
    )
    app.btn_netlogger = MenuCommand(
        app.file_actions_menu, "NetLogger logs", app.open_netlogger_download
    )
    app.btn_more_file_actions = ttk.Menubutton(
        file_actions, text="Actions", menu=app.file_actions_menu
    )
    app.btn_more_file_actions.grid(row=0, column=3, sticky="ew")
    action_buttons = (
        app.btn_download,
        app.btn_edit,
        app.btn_upload,
        app.btn_more_file_actions,
    )

    right_scroll = ScrollableFrame(right, horizontal=False)
    right_scroll.pack(fill="both", expand=True)
    right_content = ttk.Frame(right_scroll.content, padding=(2, 0, 4, 0))
    right_content.pack(fill="both", expand=True)
    right_content.columnconfigure(0, weight=1)
    metrics = ttk.Labelframe(right_content, text="Charger measurements", padding=8)
    metrics.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    metrics.columnconfigure(0, weight=1)
    app.temp_label = ttk.Label(metrics, textvariable=app.temp_label_var, anchor="w")
    app.temp_label.grid(row=0, column=0, columnspan=2, sticky="ew")
    app.soc_label = ttk.Label(metrics, textvariable=app.soc_label_var, anchor="w")
    app.soc_label.grid(row=1, column=0, sticky="ew", pady=(4, 0))
    app.btn_monitor = ttk.Button(metrics, text="Refresh", command=app.update_monitor)
    app.btn_monitor.grid(row=1, column=1, rowspan=2, sticky="e", padx=(8, 0))
    app.monitor_updated_var = tk.StringVar(
        master=app.root, value="No measurement received"
    )
    ttk.Label(
        metrics, textvariable=app.monitor_updated_var, style="HeaderSubtitle.TLabel"
    ).grid(row=2, column=0, sticky="w")

    energy = ttk.Labelframe(right_content, text="Energy Manager Controls", padding=8)
    energy.grid(row=1, column=0, sticky="nsew")
    energy.columnconfigure(0, weight=1, uniform="setpoint_panels")
    energy.columnconfigure(1, weight=1, uniform="setpoint_panels")
    vcmd = (app.root.register(app._validate_float_key), "%P")
    pn = ttk.Labelframe(energy, text="Active power limit (Pn)", padding=6)
    pn.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    pn.columnconfigure(1, weight=1)
    ttk.Label(pn, text="Pn max [W]:").grid(row=0, column=0, sticky="w")
    app.pn_entry = ttk.Entry(
        pn,
        textvariable=app.pn_value_var,
        width=9,
        justify="right",
        validate="key",
        validatecommand=vcmd,
    )
    app.pn_entry.grid(row=0, column=1, sticky="w", padx=6)
    app.pn_entry.bind("<Return>", app._commit_manual_pn)
    app.pn_entry.bind("<FocusOut>", app._commit_manual_pn)
    app.btn_read_pn = ttk.Button(
        pn, text="Read Pn", command=app.read_pn_from_gridcodes_properties
    )
    app.btn_read_pn.grid(row=0, column=2)
    ttk.Label(pn, text="P [%]:").grid(row=1, column=0, sticky="w", pady=4)
    app.pn_scale = tk.Scale(
        pn,
        from_=-100,
        to=100,
        resolution=1,
        orient="horizontal",
        showvalue=False,
        variable=app.pn_slider_var,
        command=app._on_pn_slider_changed,
        highlightthickness=0,
    )
    app.pn_scale.grid(row=1, column=1, sticky="ew", padx=6)
    app.pn_percent_entry = ttk.Entry(
        pn,
        textvariable=app.pn_percent_var,
        width=6,
        justify="right",
        validate="key",
        validatecommand=vcmd,
    )
    app.pn_percent_entry.grid(row=1, column=2, sticky="e")
    app.pn_percent_entry.bind("<Return>", app._commit_manual_percent)
    app.pn_percent_entry.bind("<FocusOut>", app._commit_manual_percent)
    ttk.Label(pn, text="Confirmed P [W]:").grid(row=2, column=0, sticky="w")
    ttk.Label(
        pn, textvariable=app.last_active_power_var, style="MetricValue.TLabel"
    ).grid(row=2, column=1, sticky="w", padx=6)
    app.btn_read_last_active_power = ttk.Button(
        pn, text="Refresh P", command=app.read_last_active_power_from_energy_log
    )
    app.btn_read_last_active_power.grid(row=2, column=2)

    pq = ttk.Labelframe(energy, text="P / Q Setpoint", padding=6)
    pq.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
    pq.columnconfigure(1, weight=1)
    ttk.Label(pq, text="P [W]:").grid(row=0, column=0, sticky="w")
    app.active_entry = ttk.Entry(
        pq, width=9, justify="right", validate="key", validatecommand=vcmd
    )
    app.active_entry.grid(row=0, column=1, sticky="w", padx=(6, 0), pady=2)
    app.active_entry.insert(0, "0")
    ttk.Label(pq, text="Q [var]:").grid(row=1, column=0, sticky="w")
    app.reactive_entry = ttk.Entry(
        pq, width=9, justify="right", validate="key", validatecommand=vcmd
    )
    app.reactive_entry.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=2)
    app.btn_send_power = ttk.Button(
        pq, text="Send P/Q", bootstyle="info", command=app.send_power_command
    )
    app.btn_send_power.grid(row=2, column=0, columnspan=2, sticky="e", pady=(6, 0))
    cos = ttk.Labelframe(energy, text="CosPhi Setpoint", padding=6)
    cos.grid(row=1, column=1, sticky="nsew", padx=(4, 0))
    cos.columnconfigure(1, weight=1)
    ttk.Checkbutton(
        cos,
        text="Use CosPhi mode",
        variable=app.use_cosphi_var,
        command=app._on_cosphi_toggle,
    ).grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(cos, text="P [W]:").grid(row=1, column=0, sticky="w")
    app.cosphi_active_entry = ttk.Entry(
        cos, width=9, justify="right", validate="key", validatecommand=vcmd
    )
    app.cosphi_active_entry.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=2)
    app.cosphi_active_entry.insert(0, "0")
    ttk.Label(cos, text="CosPhi:").grid(row=2, column=0, sticky="w")
    app.cosphi_entry = ttk.Entry(
        cos, width=9, justify="right", validate="key", validatecommand=vcmd
    )
    app.cosphi_entry.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=2)
    app.btn_send_cosphi = ttk.Button(
        cos, text="Send CosPhi", bootstyle="info", command=app.send_cosphi_command
    )
    app.btn_send_cosphi.grid(row=3, column=0, columnspan=2, sticky="e", pady=(6, 0))
    services = ttk.Labelframe(right, text="Services", padding=6)
    services.pack(side="bottom", fill="x", before=right_scroll, pady=(6, 0))
    services.columnconfigure(0, weight=1)
    services.columnconfigure(1, weight=1)
    app.btn_restart_services = ttk.Button(
        services,
        text="Restart services",
        bootstyle="warning-outline",
        command=app.restart_initd_services,
    )
    app.btn_restart_services.grid(row=0, column=0, sticky="ew", padx=(0, 4))
    app.btn_reboot = ttk.Button(
        services,
        text="Reboot device",
        bootstyle="danger-outline",
        command=app.reboot_device,
    )
    app.btn_reboot.grid(row=0, column=1, sticky="ew", padx=(4, 0))
    logs = ttk.Labelframe(app.main_panes, text="Logs", padding=6)
    app.main_panes.add(logs, minsize=100, stretch="never")
    logs.columnconfigure(0, weight=1)
    logs.rowconfigure(0, weight=1)
    app.log_text = tk.Text(logs, height=4, width=60, wrap="word", state="disabled")
    app.log_text.grid(row=0, column=0, sticky="nsew")
    log_scroll = ttk.Scrollbar(logs, orient="vertical", command=app.log_text.yview)
    log_scroll.grid(row=0, column=1, sticky="ns")
    app.log_text.configure(yscrollcommand=log_scroll.set)
    app._style_logs()

    orientation = [None]
    last_layout = [None]
    applied_height = [None]

    def reflow(_event=None):
        width = outer.canvas.winfo_width()
        if width < 100:
            return  # The unmapped canvas has not received its actual size yet.
        signature = (
            width,
            left.winfo_width(),
            right_scroll.canvas.winfo_width(),
            right_scroll.canvas.winfo_height(),
            app.btn_download.winfo_reqheight(),
            app.ip_label.winfo_reqwidth(),
            app.user_label.winfo_reqwidth(),
            status_label.winfo_reqwidth(),
            connection_buttons.winfo_reqwidth(),
            tuple(
                button.winfo_reqwidth()
                for button in navigation_buttons + list(action_buttons)
            ),
            pq.winfo_reqwidth(),
            cos.winfo_reqwidth(),
        )
        if signature == last_layout[0]:
            return
        last_layout[0] = signature
        minimum_wide = 900
        desired = "horizontal" if width >= minimum_wide else "vertical"
        if desired != orientation[0]:
            orientation[0] = desired
            app.workspace_panes.configure(
                orient=desired, height=360 if desired == "horizontal" else 640
            )
            app.main_panes.configure(height=480 if desired == "horizontal" else 760)
            app.workspace_panes.paneconfigure(
                left, minsize=260 if desired == "horizontal" else 220
            )
            app.workspace_panes.paneconfigure(
                right, minsize=400 if desired == "horizontal" else 280
            )

            def position():
                if app.workspace_panes.winfo_exists():
                    length = (
                        app.workspace_panes.winfo_width()
                        if desired == "horizontal"
                        else app.workspace_panes.winfo_height()
                    )
                    if desired == "horizontal":
                        app.workspace_panes.sash_place(0, int(length * 0.34), 0)
                    else:
                        app.workspace_panes.sash_place(0, 0, int(length * 0.4))

            app.root.after_idle(position)
        connection_width = (
            app.ip_label.winfo_reqwidth()
            + app.user_label.winfo_reqwidth()
            + status_label.winfo_reqwidth()
            + connection_buttons.winfo_reqwidth()
            + 120
        )
        compact_connection = width < connection_width
        connection_buttons.grid(
            row=1 if compact_connection else 0,
            column=0 if compact_connection else 5,
            columnspan=6 if compact_connection else 1,
            sticky="e",
            pady=(4, 0) if compact_connection else 0,
        )
        navigation_columns = (
            2
            if left.winfo_width()
            < sum(button.winfo_reqwidth() + 3 for button in navigation_buttons) + 12
            else 4
        )
        for column in range(4):
            navigation.columnconfigure(
                column, weight=1 if column < navigation_columns else 0
            )
        for index, button in enumerate(navigation_buttons):
            row, column = divmod(index, navigation_columns)
            button.grid(row=row, column=column, sticky="ew", padx=(0, 3), pady=(0, 3))
        columns = 2 if left.winfo_width() < 460 else 4
        for column in range(4):
            file_actions.columnconfigure(column, weight=1 if column < columns else 0)
        for index, button in enumerate(action_buttons):
            row, column = divmod(index, columns)
            button.grid(row=row, column=column, sticky="ew", padx=(0, 4), pady=(0, 4))
        available = max(200, right_scroll.canvas.winfo_width() - 24)
        stack_modes = available < 2 * max(pq.winfo_reqwidth(), cos.winfo_reqwidth()) + 8
        pq.grid(
            row=1,
            column=0,
            columnspan=2 if stack_modes else 1,
            sticky="nsew",
            padx=0 if stack_modes else (0, 4),
        )
        cos.grid(
            row=2 if stack_modes else 1,
            column=0 if stack_modes else 1,
            columnspan=2 if stack_modes else 1,
            sticky="nsew",
            padx=0 if stack_modes else (4, 0),
            pady=(6, 0) if stack_modes else 0,
        )
        if desired == "horizontal":
            # Reserve room for the browser toolbars and several complete rows.
            # Use font-scaled control height, not the pane's own requested size,
            # which changes during reflow and can create a geometry feedback loop.
            workspace_height = max(360, app.btn_download.winfo_reqheight() * 9)
            if applied_height[0] != (desired, workspace_height):
                applied_height[0] = (desired, workspace_height)
                app.workspace_panes.configure(height=workspace_height)
                app.main_panes.paneconfigure(
                    app.workspace_panes, minsize=workspace_height
                )
                app.main_panes.configure(height=workspace_height + 120)
        elif applied_height[0] != (desired, 500):
            applied_height[0] = (desired, 500)
            app.main_panes.paneconfigure(app.workspace_panes, minsize=500)
        app.temp_label.configure(wraplength=available)
        app.soc_label.configure(
            wraplength=max(160, available - app.btn_monitor.winfo_reqwidth() - 8)
        )
        outer.after_idle(outer._layout)
        right_scroll.after_idle(right_scroll._layout)

    # Observe viewport and panel geometry; content width must not decide reflow.
    outer.canvas.bind("<Configure>", reflow, add="+")
    left.bind("<Configure>", reflow, add="+")
    navigation.bind("<Configure>", reflow, add="+")
    file_actions.bind("<Configure>", reflow, add="+")
    right_scroll.canvas.bind("<Configure>", reflow, add="+")
    right_content.bind("<Configure>", right_scroll._layout, add="+")
    main.bind("<Configure>", outer._layout, add="+")
    app.root.after_idle(reflow)
