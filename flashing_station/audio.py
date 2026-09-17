"""Nonblocking, self-contained audio cues on macOS."""
import math
import struct
import subprocess
import wave
from core import ROOT

class Audio:
    def __init__(self):
        self.muted=False;self.volume=.5;self.process=None
        self.folder=ROOT/'data'/'sounds';self.folder.mkdir(parents=True,exist_ok=True)
        tones={'connected':[660], 'start':[440,660], 'tick':[520],
               'success':[523,659,784,1047], 'failure':[392,294,196]}
        for name,notes in tones.items():
            path=self.folder/(name+'.wav')
            if path.exists(): continue
            samples=[];rate=22050
            for frequency in notes:
                n=int(rate*(.07 if name=='tick' else .14))
                for i in range(n):
                    envelope=min(1,i/220,(n-i)/440)
                    samples.append(int(10000*envelope*math.sin(2*math.pi*frequency*i/rate)))
            with wave.open(str(path),'wb') as f:
                f.setparams((1,2,rate,0,'NONE','not compressed'))
                f.writeframes(struct.pack('<'+'h'*len(samples),*samples))
    def play(self,name):
        if self.muted: return
        try:
            if self.process and self.process.poll() is None:
                if name=='tick': return
                self.process.terminate()
            self.process=subprocess.Popen(['/usr/bin/afplay','-v',str(self.volume),str(self.folder/(name+'.wav'))],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError: pass
    def close(self):
        if self.process and self.process.poll() is None: self.process.terminate()
