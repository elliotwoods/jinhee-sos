"""Real Tk event-loop acceptance check with simulated devices only."""
from pathlib import Path
import sys
import tempfile
import time
import threading
import tkinter as tk
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import App
from backend import Runner, tool_command

with tempfile.TemporaryDirectory() as folder:
    root=tk.Tk();app=App(root,Path(folder)/'simulation.sqlite3',simulate=True)
    app.audio.muted=True
    def until(predicate,seconds=15):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            root.update()
            if predicate():return
            time.sleep(.02)
        raise AssertionError('Timed out waiting for simulated GUI operation')
    tool_results=[]
    threading.Thread(target=lambda:tool_results.append(Runner(app.emit)(tool_command()+['version'])),daemon=True).start()
    until(lambda:bool(tool_results))
    assert '5.3.1' in tool_results[0]
    until(lambda:'SIM-CUBE' in app.port_rows)
    assert not app.scheduler.armed
    app.arm();until(lambda:len(app.session)==1)
    assert app.session[0]['ui_result']=='success'
    until(lambda:not app.busy)
    app.disarm();app.devices.selection_set('SIM-CUBE');app.manual_flash()
    until(lambda:len(app.session)==2)
    assert len(app.db.history())==2
    app.history.selection_set(next(iter(app.records)))
    app.check_boot();until(lambda:not app.busy)
    assert app.status.get()=='Boot confirmed'
    app.show_ports([dict(port='station',key='station',serial='3C:0F:02:AD:83:24',description='Registration station',candidate=True)])
    app.devices.selection_set('station');app.manual_flash()
    assert 'protected' in app.status.get()
    assert not app.busy
    # Native USB identity should reveal saved/original numbers before flashing.
    original=app.db.originals()[0]
    known_port=dict(port='known',key=original['mac'],serial=original['mac'],description='USB cube',candidate=True)
    app.show_ports([known_port])
    assert app.recognition_title.get()==f"NEOCORE #{original['cube_id']:02d}"
    assert 'Original #' in app.recognition_detail.get()
    assert app.devices.item('known','tags')==('original',)
    app.db.conn.execute('UPDATE devices SET cube_id=NULL WHERE mac=?',(original['mac'],));app.db.conn.commit()
    app.show_ports([known_port])
    assert app.recognition_title.get()==f"ORIGINAL #{original['cube_id']:02d}"
    assert 'No current number assigned' in app.recognition_detail.get()
    app.db.rename(original['mac'],900)
    app.show_ports([known_port])
    assert app.recognition_title.get()=='NEOCORE #900'
    assert f"Original #{original['cube_id']:02d}" in app.recognition_detail.get()
    saved=app.db.reserve('02:00:00:00:FB:02')
    app.db.conn.execute('UPDATE devices SET cube_id=NULL WHERE mac=?',(saved['mac'],));app.db.conn.commit()
    app.show_ports([dict(known_port,serial=saved['mac'],key=saved['mac'])])
    assert app.recognition_title.get()=='KNOWN DEVICE'
    assert app.devices.item('known','tags')==('known',)
    app.show_ports([dict(known_port,serial='02:00:00:00:FF:FF',key='new')])
    assert app.recognition_title.get()=='NEW DEVICE'
    root.update_idletasks()
    for widget in (app.logbox, app.history, app.auto, app.check):
        print(widget, 'mapped=',widget.winfo_ismapped(), 'geometry=',widget.winfo_geometry(), 'root=',root.winfo_geometry())
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty()+widget.winfo_height()<=root.winfo_rooty()+root.winfo_height()
    root.geometry('1120x850');root.update()
    assert app.logbox.winfo_height()>30
    assert app.check.winfo_ismapped()
    assert app.progress.winfo_ismapped()
    print('PASS: Tk layout, auto/manual flashing, boot recheck, station protection, history, shutdown')
    app.close()
