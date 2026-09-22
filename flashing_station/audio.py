"""Nonblocking, self-contained audio cues: afplay on macOS, winsound on Windows, silent elsewhere."""
import math
import struct
import subprocess
import wave
from core import ROOT
import hostos

TONES={'connected':[660], 'start':[440,660], 'tick':[520],
       'success':[523,659,784,1047], 'failure':[392,294,196]}

class Audio:
    def __init__(self):
        self.muted=False;self.volume=.5;self.process=None
        self.folder=ROOT/'data'/'sounds';self.folder.mkdir(parents=True,exist_ok=True)
        for name in TONES: self.wav(name)
    def wav(self,name,level=None):
        """The cue's file. winsound has no volume control, so Windows plays one file per volume step (0-10)."""
        path=self.folder/(name+'.wav' if level is None else f'{name}-{level}.wav')
        if path.exists(): return path
        samples=[];rate=22050;amplitude=10000 if level is None else 2000*level
        for frequency in TONES[name]:
            n=int(rate*(.07 if name=='tick' else .14))
            for i in range(n):
                envelope=min(1,i/220,(n-i)/440)
                samples.append(int(amplitude*envelope*math.sin(2*math.pi*frequency*i/rate)))
        with wave.open(str(path),'wb') as f:
            f.setparams((1,2,rate,0,'NONE','not compressed'))
            f.writeframes(struct.pack('<'+'h'*len(samples),*samples))
        return path
    def play(self,name):
        if self.muted: return
        try:
            if hostos.WINDOWS:
                import winsound
                level=round(max(0,min(1,self.volume))*10)
                if not level: return
                # A tick never interrupts another cue: SND_NOSTOP raises RuntimeError while one plays.
                flags=winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT|(winsound.SND_NOSTOP if name=='tick' else 0)
                winsound.PlaySound(str(self.wav(name,level)),flags)
                return
            if self.process and self.process.poll() is None:
                if name=='tick': return
                self.process.terminate()
            self.process=subprocess.Popen(['/usr/bin/afplay','-v',str(self.volume),str(self.folder/(name+'.wav'))],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except (OSError,RuntimeError): pass
    def close(self):
        if self.process and self.process.poll() is None: self.process.terminate()
