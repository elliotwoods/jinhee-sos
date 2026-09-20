"""Opening a native USB-JTAG ESP32-C3 without resetting it.

Same sequence as `pairing_station/transport.py`: assert DTR and RTS before the
port is opened, then release RTS before DTR. Opening with both deasserted, or
toggling them afterwards, resets the chip on these boards and can wedge the
USB serial peripheral until it is physically unplugged.
"""
import serial


def open_serial(path, timeout=0, write_timeout=0.15):
    port = serial.Serial(port=None, baudrate=115200, timeout=timeout,
                         write_timeout=write_timeout, exclusive=True)
    port.dtr = True
    port.rts = True
    port.port = path
    try:
        port.open()
        port.rts = False
        port.dtr = False
    except Exception:
        try:
            port.close()
        except Exception:
            pass
        raise
    return port
