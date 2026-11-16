"""Offline Tk capture lifecycle check; no EVSE connection is started."""
import sys, tempfile, pathlib
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import tkinter as tk
from src.debug_logs import DebugLogsWindow
from src.diagnostic_capture import DiagnosticRecorder
r=tk.Tk()
r.withdraw()
recorder=DiagnosticRecorder()
with tempfile.TemporaryDirectory() as directory, patch('src.debug_logs._runtime_incidents_dir', return_value=directory):
    win=DebugLogsWindow(r, ('192.0.2.1','user','secret',22), recorder=recorder,
                        snapshot_callback=lambda s:s.configuration({'success':True,'out':'power=1'}))
    win.processes['EnergyManager.log']=object()
    win.running['EnergyManager.log']=True
    def start(name):
        win.processes[name]=object()
        win.running[name]=True
        recorder.log(name, 'raw incoming despite pause/filter\n')
    def stop(name, silent=False):
        win.processes.pop(name, None)
        win.running.pop(name, None)
    with patch.object(win, 'start_log', side_effect=start), patch.object(win,'stop_log',side_effect=stop):
        win.start_test_capture()
        assert win.capture_menu.entrycget(2,'state')=='disabled'
        assert len(win.processes)==4
        recorder.log('EnergyManager.log','existing stream\n')
        win.finish_test_capture()
        assert list(win.processes)==['EnergyManager.log'], 'stopped a pre-existing stream'
        assert recorder.session.finished.wait(3)
        r.after(200,r.quit)
        r.mainloop()
        assert win.capture_menu.entrycget(4,'state')=='normal'
        assert recorder.session.state=='finished'
        win.start_test_capture()
        win.on_close()
        assert recorder.session.finished.wait(3), 'close did not finalize capture'
        assert not recorder.session.active
r.destroy()
print('Capture UI lifecycle, automatic streams and existing-stream preservation: OK')
