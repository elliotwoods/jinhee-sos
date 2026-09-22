#!/usr/bin/env python3
"""Neocore USB Flash Station: native Tk UI with a single serial worker."""
import argparse
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from core import ROOT, WORKSPACE, Store, Scheduler, load_manifest, atomic_json, PortLock, timestamp
from backend import Flasher, Runner, ports
from build import build
from audio import Audio
from identity import describe, usb_mac
from sync_widget import SyncWidget
import hostos

BG='#101720'; CARD='#1b2633'; FG='#e9f0f7'; MUTED='#9aafc4'; GREEN='#54d6a0'; BLUE='#82b8fa'; AMBER='#ffc16b'

class App:
    def __init__(self,root,database,simulate=False):
        self.root=root;self.path=database;self.simulate=simulate
        database.parent.mkdir(parents=True,exist_ok=True)
        self.lock=database.with_suffix('.flasher.lock').open('a')
        hostos.lock_file(self.lock)
        self.db=Store(database);self.db.recover()
        self.original_numbers={r['mac']:r['cube_id'] for r in self.db.originals()}
        self.port_macs={}
        self.events=queue.Queue();self.scheduler=Scheduler();self.busy=False;self.closing=False
        self.started=0;self.last_tick=0;self.last_scan=0;self.scanning=False;self.connected_keys=set()
        self.session=[];self.logs=[];self.manifest=None;self.port_rows={};self.active=None;self.session_start=timestamp();self.next_job_at=0
        self.audio=Audio()
        self.setup_ui();self.refresh_manifest();self.refresh_history();self.recover_receipts()
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(100,self.poll)
    def setup_ui(self):
        r=self.root;r.title('NEOCORE · USB Flash Station'+(' · SIMULATION' if self.simulate else ''))
        r.geometry('1220x940');r.minsize(1120,850);r.configure(bg=BG)
        style=ttk.Style();style.theme_use('clam')
        style.configure('.',background=BG,foreground=FG,font=('Helvetica',11))
        style.configure('TButton',background='#263749',padding=(12,8),borderwidth=0)
        style.map('TButton',background=[('active','#39536e')],foreground=[('disabled','#65778a')])
        style.configure('Treeview',background=CARD,fieldbackground=CARD,foreground=FG,rowheight=30,borderwidth=0)
        style.configure('Treeview.Heading',background='#263749',foreground=MUTED,padding=6)
        style.map('Treeview',background=[('selected','#315575')])
        style.configure('Horizontal.TProgressbar',background=GREEN,troughcolor=CARD)
        outer=ttk.Frame(r,padding=22);outer.pack(fill='both',expand=True)
        header=ttk.Frame(outer);header.pack(fill='x')
        ttk.Label(header,text='NEOCORE / FLASH STATION',font=('Helvetica',24,'bold')).pack(side='left')
        self.counts=tk.StringVar(value='READY');ttk.Label(header,textvariable=self.counts,foreground=GREEN).pack(side='right')
        ttk.Label(outer,text='USB firmware installation · automatic device intake · shared NFC inventory',foreground=MUTED).pack(anchor='w',pady=(6,16))
        self.status=tk.StringVar(value='Ready · choose a cube or arm automatic flashing')
        self.status_label=tk.Label(outer,textvariable=self.status,bg=CARD,fg=BLUE,font=('Helvetica',17,'bold'),anchor='w',padx=16,pady=15)
        self.status_label.pack(fill='x')
        self.firmware=tk.StringVar();ttk.Label(outer,textvariable=self.firmware,foreground=MUTED).pack(anchor='w',pady=(10,0))
        # Universal Sync: this app holds the cube-flasher lock itself, so web changes apply only while idle.
        self.web_status=SyncWidget(outer,self.path,'Cube flasher',held=('.flasher.lock',),can_apply=lambda:not self.busy)
        self.web_status.pack(anchor='w',fill='x',pady=(2,10))
        controls=ttk.Frame(outer);controls.pack(fill='x',pady=(0,10))
        self.auto=ttk.Button(controls,text='▶ Arm Auto',command=self.arm);self.auto.pack(side='left',padx=(0,7))
        self.manual=ttk.Button(controls,text='Flash selected / Retry',command=self.manual_flash);self.manual.pack(side='left',padx=7)
        ttk.Button(controls,text='Stop after current',command=self.disarm).pack(side='left',padx=7)
        self.rebuild=ttk.Button(controls,text='Rebuild firmware',command=self.rebuild_firmware);self.rebuild.pack(side='right')
        ttk.Label(outer,text='Auto processes compatible ESP32-C3 boards as cubes. Known readers and occupied ports are excluded. NFC mappings are preserved.',foreground=MUTED,wraplength=1140).pack(anchor='w',pady=(0,12))
        middle=ttk.Frame(outer);middle.pack(fill='both',expand=True)
        left=ttk.Frame(middle);left.pack(side='left',fill='both',expand=True)
        self.recognition_title=tk.StringVar(value='CONNECT A NEOCORE')
        self.recognition_detail=tk.StringVar(value='Existing numbers are looked up automatically')
        self.recognition_label=ttk.Label(left,textvariable=self.recognition_title,font=('Helvetica',25,'bold'),foreground=GREEN)
        self.recognition_label.pack(anchor='w',pady=(0,3))
        ttk.Label(left,textvariable=self.recognition_detail,foreground=MUTED,wraplength=740).pack(anchor='w',pady=(0,10))
        self.devices=ttk.Treeview(left,columns=('unit','port','device','state'),show='headings',height=3)
        for col,label,width in [('unit','Known identity',150),('port','USB port',175),('device','Device',145),('state','Queue',125)]:
            self.devices.heading(col,text=label);self.devices.column(col,width=width)
        self.devices.tag_configure('known',font=('Helvetica',12,'bold'),foreground=GREEN)
        self.devices.tag_configure('original',font=('Helvetica',12,'bold'),foreground=AMBER)
        self.devices.tag_configure('protected',font=('Helvetica',12,'bold'),foreground=BLUE)
        self.devices.pack(fill='both',expand=True)
        self.devices.bind('<<TreeviewSelect>>',self.select_port)
        detail=ttk.Frame(middle,padding=(20,0,0,0),width=330);detail.pack(side='right',fill='y');detail.pack_propagate(False)
        ttk.Label(detail,text='DEVICE / CURRENT ATTEMPT',foreground=MUTED).pack(anchor='w')
        self.identity=tk.StringVar(value='Connect a cube with a USB data cable.\n\nAuto is disarmed on every launch.')
        identity_frame=ttk.Frame(detail,height=90);identity_frame.pack(fill='x',pady=8);identity_frame.pack_propagate(False)
        self.detail_text=tk.Text(identity_frame,height=5,bg=BG,fg=FG,font=('Helvetica',11),wrap='word',relief='flat',state='disabled')
        self.detail_text.pack(fill='both',expand=True)
        def update_detail(*_):
            self.detail_text.configure(state='normal');self.detail_text.delete('1.0','end')
            self.detail_text.insert('1.0',self.identity.get());self.detail_text.configure(state='disabled')
        self.identity.trace_add('write',update_detail);update_detail()
        self.stage=tk.StringVar(value='Idle');ttk.Label(detail,textvariable=self.stage,font=('Helvetica',15,'bold')).pack(anchor='w',pady=(8,4))
        self.progress=ttk.Progressbar(detail,maximum=100);self.progress.pack(fill='x',pady=5)
        self.elapsed=tk.StringVar(value='');ttk.Label(detail,textvariable=self.elapsed,foreground=MUTED).pack(anchor='w')
        history_bar=ttk.Frame(outer);history_bar.pack(fill='x',pady=(10,5))
        ttk.Label(history_bar,text='FLASH HISTORY · select a result to inspect',foreground=MUTED).pack(side='left')
        self.check=ttk.Button(history_bar,text='Check boot of selected result',command=self.check_boot);self.check.pack(side='right')
        ttk.Button(history_bar,text='Recover saved results',command=self.recover_receipts).pack(side='right',padx=8)
        self.history=ttk.Treeview(outer,columns=('time','mac','version','result'),show='headings',height=4)
        for col,label,width in [('time','Time',175),('mac','MAC address',200),('version','Firmware',160),('result','Result',390)]:
            self.history.heading(col,text=label);self.history.column(col,width=width)
        self.history.pack(fill='x');self.history.bind('<<TreeviewSelect>>',self.select_history)
        footer=ttk.Frame(outer);footer.pack(fill='x',pady=10)
        self.mute=tk.BooleanVar();ttk.Checkbutton(footer,text='Mute',variable=self.mute,command=self.audio_settings).pack(side='left')
        ttk.Label(footer,text='Volume',foreground=MUTED).pack(side='left',padx=8)
        self.volume=tk.DoubleVar(value=.5);ttk.Scale(footer,from_=0,to=1,variable=self.volume,command=lambda _:self.audio_settings(),length=110).pack(side='left')
        ttk.Button(footer,text='Test sound',command=lambda:self.audio.play('success')).pack(side='left',padx=10)
        ttk.Button(footer,text='Export log…',command=self.export_log).pack(side='right')
        self.logbox=tk.Text(outer,height=5,bg='#0b1119',fg=MUTED,relief='flat',font=(hostos.MONO_FONT,10),state='disabled',wrap='word')
        self.logbox.pack(fill='x')
        ttk.Label(outer,text=str(self.path)+('   ·   SIMULATED HARDWARE' if self.simulate else ''),foreground=MUTED,font=('Helvetica',9)).pack(anchor='w',pady=(6,0))
    def audio_settings(self): self.audio.muted=self.mute.get();self.audio.volume=self.volume.get()
    def emit(self,kind,value): self.events.put((kind,value))
    def log(self,text):
        text=time.strftime('%H:%M:%S')+'  '+str(text);self.logs.append(text)
        self.logbox.configure(state='normal');self.logbox.insert('end',text+'\n')
        if len(self.logs)>1500:
            self.logs=self.logs[-1000:];self.logbox.delete('1.0','501.0')
        self.logbox.see('end');self.logbox.configure(state='disabled')
    def refresh_manifest(self):
        try:
            self.manifest=load_manifest()
            self.firmware.set(f"{self.manifest['version']}    /    XIAO ESP32-C3 · 4 MB · USB only · channel 2    /    Build {self.manifest['build_hash'][:12]}")
        except Exception as exc:
            self.manifest=None;self.firmware.set('Firmware unavailable · '+str(exc));self.log(str(exc))
    def arm(self):
        if self.scheduler.armed: self.disarm();return
        if not self.manifest:
            self.status.set('Build firmware before arming Auto');return
        self.scheduler.armed=True;self.auto.configure(text='■ Disarm Auto')
        self.status.set('Auto armed · waiting for eligible cubes')
    def disarm(self):
        self.scheduler.armed=False;self.auto.configure(text='▶ Arm Auto')
        self.status.set('Stopping after current device' if self.busy else 'Auto disarmed · manual flashing available')
    def selected_port(self):
        ids=self.devices.selection()
        return self.port_rows.get(ids[0]) if ids else None
    def port_mac(self,p):
        return self.port_macs.get(p['key']) or usb_mac(p.get('serial'))
    def show_recognition(self,mac):
        info=describe(self.db,self.original_numbers,mac)
        self.recognition_title.set(info['title']);self.recognition_detail.set(info['detail'])
        self.recognition_label.configure(foreground={'original':AMBER,'known':GREEN,'protected':BLUE}.get(info['tone'],MUTED))
        return info
    def select_port(self,*_):
        p=self.selected_port()
        if p and not self.busy:
            mac=self.port_mac(p);info=self.show_recognition(mac)
            row=self.db.get(mac) if mac else None
            self.identity.set(info['detail']+f"\n{p['description']}\n{p['port']}\nNFC: {(row or {}).get('uid') or 'unknown'}")
    def identified(self,value):
        if self.active:self.port_macs[self.active['key']]=value['mac']
        self.show_recognition(value['mac'])
        if 'chip' in value:self.identity.set(f"{value['mac']}\n{value['chip']} · {value['flash']}\n{value['port']}")
        else:self.identity.set(f"{value['mac']}\nCurrent number: {value['cube_id'] if value['cube_id'] is not None else 'not assigned'}\nNFC: {value['uid'] or 'unknown'}\nRegistration: {value['status']}")
    def manual_flash(self):
        p=self.selected_port()
        if not p: self.status.set('Select a connected USB device first');return
        self.start(p,True)
    def start(self,p,manual=False):
        if self.busy:return
        if self.db.protected((p.get('serial') or '').upper()):
            self.status.set('Registration station protected · serial port will not be opened');return
        try: self.manifest=load_manifest()
        except Exception as exc:self.status.set(str(exc));return
        self.show_recognition(self.port_mac(p))
        self.scheduler.mark(p);self.active=p;self.set_busy(True);self.audio.play('start')
        self.status.set('Flashing '+p['port']);self.progress['value']=0
        def work():
            try:
                if self.simulate:
                    result=self.simulate_flash(p,manual)
                else: result=Flasher(self.path,self.emit).execute(p,self.manifest,manual,self.session_start)
                self.emit('done',result)
            except Exception as exc:self.emit('error',str(exc))
        threading.Thread(target=work,daemon=True).start()
    def set_busy(self,value):
        self.busy=value
        if value:self.started=time.monotonic()
        for button in (self.manual,self.rebuild,self.check):button.configure(state='disabled' if value else 'normal')
    def rebuild_firmware(self):
        if self.busy:return
        self.disarm();self.set_busy(True);self.status.set('Building USB-only firmware…')
        def work():
            try:build(Runner(self.emit));self.emit('built',None)
            except Exception as exc:self.emit('error',str(exc))
        threading.Thread(target=work,daemon=True).start()
    def refresh_history(self):
        selected=self.history.selection();self.records={r['id']:r for r in self.db.history()}
        self.history.delete(*self.history.get_children())
        for ident,r in self.records.items():
            self.history.insert('', 'end',iid=ident,values=(r['started_at'],r['mac'] or '—',r['version'],r['result']))
        if selected and selected[0] in self.records:self.history.selection_set(selected[0])
    def select_history(self,*_):
        selected=self.history.selection()
        if selected and not self.busy:
            r=self.records[selected[0]];row=self.db.get(r['mac']) if r['mac'] else None
            self.identity.set(f"{r['mac'] or 'MAC unknown'}\n{r['version']}\n{r['result']}\n\n{r['detail']}\n\nNFC: {(row or {}).get('uid') or 'unknown'}")
    def recover_receipts(self):
        if self.busy:return
        n=0
        for receipt in (ROOT/'data/runs').glob('*/receipt.json'):
            try:
                r=json.loads(receipt.read_text(encoding='utf-8'))
                current=self.db.conn.execute('SELECT result FROM flash_runs WHERE id=?',(r['id'],)).fetchone()
                if not current or current[0]==r['result'] or current[0]=='success':continue
                self.db.update_run(r['id'],result=r['result'],detail=r['detail'],finished_at=r['finished_at']);n+=1
            except Exception as exc:self.log('Receipt recovery: '+str(exc))
        if n:self.log(f'Recovered {n} saved hardware results')
        self.refresh_history()
    def check_boot(self):
        selected=self.history.selection();p=self.selected_port()
        if not selected or not p:self.status.set('Select a history result and its connected USB device');return
        r=self.records[selected[0]]
        if r['result'] not in ('boot_unconfirmed','success'):
            self.status.set('Boot check requires a verified upload result');return
        self.set_busy(True);self.status.set('Checking boot without reflashing…')
        def work():
            try:
                if self.simulate:ok=True
                else:
                    with PortLock(p['port']):ok=Flasher(self.path,self.emit).boot(p,r['mac'],r['version'],Runner(self.emit))
                self.emit('checked',(r['id'],ok))
            except Exception as exc:self.emit('error',str(exc))
        threading.Thread(target=work,daemon=True).start()
    def export_log(self):
        path=filedialog.asksaveasfilename(defaultextension='.log',initialfile='neocore-flash.log')
        if path:Path(path).write_text('\n'.join(self.logs)+'\n',encoding='utf-8')
    def scan(self):
        self.scanning=True
        def work():
            try:
                data=([dict(port='SIM-CUBE',key='sim-1',description='Simulated XIAO ESP32-C3',candidate=True)] if self.simulate else ports())
                self.emit('ports',data)
            except Exception as exc:self.emit('scan_error',str(exc))
        threading.Thread(target=work,daemon=True).start()
    def show_ports(self,data):
        self.scanning=False;self.scheduler.scan(data, self.busy)
        for p in data:
            if self.db.protected((p.get('serial') or '').upper()):
                p['candidate']=False;p['protected']=True
        keys={p['key'] for p in data}
        if keys-self.connected_keys:self.audio.play('connected')
        self.connected_keys=keys;self.port_rows={p['port']:p for p in data}
        self.port_macs={key:mac for key,mac in self.port_macs.items() if key in keys or (self.busy and self.active and key==self.active['key'])}
        selected=self.devices.selection()
        self.devices.delete(*self.devices.get_children())
        for p in data:
            state='Protected station' if p.get('protected') else 'Attempted' if p['key'] in self.scheduler.attempted else 'Waiting' if p['candidate'] else 'Manual only'
            info=describe(self.db,self.original_numbers,self.port_mac(p))
            self.devices.insert('','end',iid=p['port'],values=(info['badge'],p['port'],p['description'],state),tags=(info['tone'],))
        if selected and selected[0] in self.port_rows:self.devices.selection_set(selected[0])
        elif data:
            preferred=next((p for p in data if self.port_mac(p) or p['candidate']),data[0])
            self.devices.selection_set(preferred['port'])
        if self.busy and self.active:self.show_recognition(self.port_mac(self.active))
        elif self.selected_port():self.select_port()
        else:
            self.recognition_title.set('CONNECT A NEOCORE')
            self.recognition_detail.set('Existing numbers are looked up automatically')
    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='log':self.log(value)
                elif kind=='ports':self.show_ports(value)
                elif kind=='scan_error':self.scanning=False;self.log(value)
                elif kind=='progress':self.progress['value']=value
                elif kind=='stage':self.stage.set(value);self.progress['value']=0;self.audio.play('tick')
                elif kind=='identity':self.identified(value)
                elif kind=='device':self.identified(value)
                elif kind=='done':
                    self.set_busy(False);self.next_job_at=time.monotonic()+1.2;self.session.append(value);self.status.set(value['ui_detail'].splitlines()[-1][:130]);self.stage.set(value['ui_result'].replace('_',' ').title())
                    self.status_label.configure(fg=GREEN if value['ui_result']=='success' else AMBER)
                    self.audio.play('success' if value['ui_result']=='success' else 'tick' if value['ui_result']=='skipped' else 'failure')
                    if value['ui_result']=='success':self.progress['value']=100
                    self.refresh_history()
                elif kind=='built':self.set_busy(False);self.refresh_manifest();self.status.set('Firmware built and ready');self.scheduler.attempted.clear()
                elif kind=='checked':
                    ident,ok=value;self.set_busy(False)
                    if ok:self.db.update_run(ident,result='success',detail='Firmware verified; boot confirmed on recheck',finished_at=timestamp())
                    self.status.set('Boot confirmed' if ok else 'Boot remains unconfirmed');self.audio.play('success' if ok else 'failure');self.refresh_history()
                elif kind=='error':self.set_busy(False);self.disarm();self.status.set('Operation failed · see log for details');self.log(value);self.audio.play('failure')
        except queue.Empty:pass
        except Exception as exc:
            self.disarm();self.log('UI update error: '+str(exc))
        now=time.monotonic()
        if self.busy:
            self.elapsed.set(f'{now-self.started:.0f}s elapsed · keep USB connected')
            if now-self.last_tick>4:self.audio.play('tick');self.last_tick=now
        if not self.scanning and now-self.last_scan>1:
            self.last_scan=now;self.scan()
        good=sum(r['ui_result']=='success' for r in self.session)
        self.counts.set(f'{good} SUCCESS    /    {len(self.session)} ATTEMPTS    /    '+('AUTO ARMED' if self.scheduler.armed else 'MANUAL'))
        if self.closing and not self.busy:self.finish_close();return
        if not self.busy and not self.closing and now>=self.next_job_at:
            p=self.scheduler.next()
            if p:self.start(p)
        self.root.after(100,self.poll)
    def simulate_flash(self,p,manual):
        import uuid
        from core import timestamp
        db=Store(self.path);ident=uuid.uuid4().hex;mac='02:00:00:00:FA:01'
        try:
            db.start(ident,p['port'],self.manifest,ROOT/'data/simulation.log')
            db.update_run(ident,mac=mac);self.emit('device',db.reserve(mac,source='simulation'))
            result='skipped' if not manual and db.seen(mac,self.manifest['build_hash']) else 'success'
            if result=='success':
                for stage in ['Identify','Back up registration','Write and verify','Confirm boot']:
                    self.emit('stage',stage)
                    for progress in range(0,101,20):self.emit('progress',progress);time.sleep(.08)
            detail='SIMULATION · '+('verified and boot confirmed' if result=='success' else 'already flashed')
            db.update_run(ident,result=result,detail=detail,finished_at=timestamp())
            return dict(ui_result=result,ui_detail=detail)
        finally:db.close()
    def close(self):
        self.disarm();self.closing=True
        if self.busy:self.status.set('Closing after current operation completes; keep USB connected')
        else:self.finish_close()
    def finish_close(self):
        self.audio.close();self.db.close();self.lock.close();self.root.destroy()

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',type=Path)
    parser.add_argument('--simulate',action='store_true')
    args=parser.parse_args()
    path=args.database or (ROOT/'data/simulation.sqlite3' if args.simulate else WORKSPACE/'pairing_station/data/devices.sqlite3')
    root=tk.Tk()
    try:app=App(root,path,args.simulate)
    except Exception as exc:
        root.withdraw();messagebox.showerror('Neocore Flash Station',str(exc));raise SystemExit(1)
    root.mainloop()
