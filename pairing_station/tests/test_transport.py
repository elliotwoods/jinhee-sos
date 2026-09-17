import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from transport import Transport

class TransportTests(unittest.TestCase):
    def test_native_usb_open_avoids_reset_sequence(self):
        changes=[]
        class Port:
            def __init__(self,**kwargs): self.is_open=False
            def __setattr__(self,name,value):
                if name in ('rts','dtr'): changes.append((name,value))
                object.__setattr__(self,name,value)
            def open(self):
                self.is_open=True
                changes.append(('open',self.dtr,self.rts))
            def close(self): self.is_open=False
        with patch('transport.serial.Serial',Port), patch('transport.threading.Thread',MagicMock()):
            link=Transport();link.open('/dev/mock')
            # This is esp-idf-monitor's no-reset sequence. False/False on open
            # reproduced a USB_UART_CHIP_RESET and wedged the live PN532 bus.
            self.assertEqual(changes,[('dtr',True),('rts',True),('open',True,True),('rts',False),('dtr',False)])
            link.close()

    def test_failed_open_releases_port_and_can_retry(self):
        from serial import SerialException
        failed=MagicMock()
        failed.open.side_effect=SerialException('Device unplugged')
        working=MagicMock()
        with patch('transport.serial.Serial',side_effect=[failed,working]), patch('transport.threading.Thread',MagicMock()):
            link=Transport()
            with self.assertRaises(SerialException): link.open('/dev/missing')
            self.assertIsNone(link.port)
            failed.close.assert_called_once()
            link.open('/dev/reconnected')
            self.assertIs(link.port,working)
            link.close()

    def test_fragmented_json_and_boot_noise(self):
        link=Transport()
        class Port:
            in_waiting=0
            def __init__(self):
                self.chunks=iter([b'boot log\r\n{"event":"he',b'llo","id":"x"}\n',b'{"event":"pong"}\n'])
            def read(self,n):
                try:return next(self.chunks)
                except StopIteration:link.stopping.set();return b''
        link.port=Port();link._run()
        self.assertEqual(link.inbox.get()['event'],'boot_log')
        self.assertEqual(link.inbox.get(),dict(event='hello',id='x'))
        self.assertEqual(link.inbox.get()['event'],'pong')

if __name__=='__main__':unittest.main()
