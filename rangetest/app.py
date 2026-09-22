#!/usr/bin/env python3
"""ESP-NOW range test console: live link quality at the back-room receiver.

Screen only. Nothing is written to disk.
"""
import argparse
import sys
import time
from collections import deque
import tkinter as tk
from tkinter import ttk
import serial
from serial.tools import list_ports

from serial_open import open_serial

BG, CARD, TEXT, MUTED = '#101720', '#1b2633', '#e9f0f7', '#a5b5c8'
GREEN, AMBER, BLUE, RED, LINE = '#54d6a0', '#ffc16b', '#82b8fa', '#ff647d', '#2a3849'
PLOT = '#151e2a'
# Standalone app (no shared modules on its path): the monospace face per host OS.
MONO = 'Menlo' if sys.platform == 'darwin' else 'Consolas' if sys.platform == 'win32' else 'DejaVu Sans Mono'

RSSI_TOP, RSSI_BOTTOM = -10, -100   # dBm window drawn on the signal charts
MINUTE, HALF_HOUR = 60, 1800
LED_SCALE = 255 / 100               # firmware caps every channel at 100

LEGEND = [
    ('One dot per packet', RED,
     'A dot lights for each ping the receiver hears, then fades, so the comet travels '
     'once round the ring every eight packets. Its speed is the packet rate.'),
    ('Brightness', RED,
     'Full brightness above −65 dBm, down to a quarter at −85 dBm and below. '
     'A dim comet still moving means the link is weak but alive.'),
    ('Gaps in the flow', AMBER,
     'A lost packet leaves its dot dark, so loss reads as a stutter. If the comet stops '
     'moving entirely the board has crashed or browned out.'),
    ('Breathing, not moving', AMBER,
     'Red: heard the transmitter and then lost it (nothing for 2 s). '
     'Amber: nothing heard at all since boot.'),
    ('The transmitter', BLUE,
     'Identical display in blue. It advances on every ping it sends, and a dot only '
     'brightens once this receiver’s ACK comes back, at the strength measured here.'),
]


def parse_fields(line):
    """`STAT role=RX loss_pct=0.0` -> {'role': 'RX', 'loss_pct': '0.0'}."""
    return {k: v for k, _, v in (t.partition('=') for t in line.split()) if k and v}


def number(fields, key, default=None):
    try:
        return float(fields[key])
    except (KeyError, ValueError, TypeError):
        return default


def scale_channel(value):
    return min(255, int(value * LED_SCALE))


class Receiver:
    """The USB connection to the back-room receiver, reconnecting on its own."""

    def __init__(self, app):
        self.app = app
        self.serial = None
        self.port = None
        self.buffer = b''
        self.stat = {}
        self.banner = {}
        self.pixels = ['000000'] * 8
        self.next_attempt = 0.0
        # Per packet at 5 Hz, and one STAT per second.
        self.packets = deque(maxlen=MINUTE * 25)
        self.samples = deque(maxlen=HALF_HOUR + 60)

    @property
    def connected(self):
        return self.serial is not None

    def open(self, port):
        self.serial = open_serial(port)
        self.port = port
        self.buffer = b''
        self.banner = {}
        self.send('VERBOSE ON')
        self.send('LEDS ON')
        self.send('STATUS')

    def close(self, tell_board=True):
        if self.serial:
            try:
                if tell_board:
                    self.serial.write(b'LEDS OFF\n')
                self.serial.close()
            except (serial.SerialException, OSError):
                pass
        self.serial = None
        self.stat = {}
        self.pixels = ['000000'] * 8

    def send(self, command):
        if not self.serial:
            return
        try:
            self.serial.write((command + '\n').encode())
        except (serial.SerialException, OSError) as exc:
            self.app.record(f'Write failed: {exc}')
            self.close(tell_board=False)

    def read_lines(self):
        if not self.serial:
            return []
        try:
            self.buffer += self.serial.read(16384)
        except (serial.SerialException, OSError) as exc:
            self.app.record(f'Receiver disconnected: {exc}')
            self.close(tell_board=False)
            return []
        lines = []
        while b'\n' in self.buffer:
            raw, self.buffer = self.buffer.split(b'\n', 1)
            text = raw.decode('utf8', 'replace').strip()
            if text:
                lines.append(text)
        return lines

    def consume(self, line, now):
        if line.startswith('STAT '):
            self.stat = parse_fields(line)
            loss = number(self.stat, 'loss_pct')
            if loss is not None:
                self.samples.append((now, loss, number(self.stat, 'rssi_avg'),
                                     number(self.stat, 'nf_avg')))
        elif line.startswith('PKT '):
            fields = parse_fields(line)
            rssi = number(fields, 'rssi')
            if rssi is not None and rssi != 127:
                self.packets.append((now, rssi, number(fields, 'nf'), number(fields, 'gap', 0)))
        elif line.startswith('LEDS '):
            parts = parse_fields(line).get('px', '').split(',')
            if len(parts) == 8:
                self.pixels = parts
        elif ':' in line and not line.startswith('='):
            key, _, value = line.partition(':')
            self.banner[key.strip()] = value.strip()


class App:
    def __init__(self, root, port=None):
        self.root = root
        self.receiver = Receiver(self)
        self.preferred = port
        self.auto = tk.BooleanVar(value=True)

        root.title('NCT · ESP-NOW range test')
        root.configure(bg=BG)
        root.geometry('1320x980')
        root.minsize(1140, 900)
        self.configure_style()

        frame = ttk.Frame(root, padding=20)
        frame.pack(fill='both', expand=True)

        header = ttk.Frame(frame)
        header.pack(fill='x')
        ttk.Label(header, text='NEOCORE / RANGE TEST', style='Title.TLabel').pack(side='left')
        self.headline = tk.StringVar(value='Looking for the receiver…')
        ttk.Label(header, textvariable=self.headline, style='Head.TLabel').pack(side='right')
        ttk.Label(frame, style='Muted.TLabel', text='Back-room receiver. Signal strength and packet '
                  'loss from the transmitter being carried around the exhibition.')\
            .pack(anchor='w', pady=(4, 14))

        self.build_connection(frame)
        self.build_readout(frame)
        self.build_charts(frame)
        self.build_leds(frame)

        self.log = tk.Text(frame, height=4, bg='#0b1119', fg=MUTED, font=(MONO, 10),
                           relief='flat', state='disabled', padx=10, pady=6,
                           highlightthickness=0, borderwidth=0)
        self.log.pack(fill='x', pady=(14, 0))

        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_ports()
        root.after(50, self.poll)

    # ---------------------------------------------------------------- styling
    def configure_style(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Helvetica', 11), background=BG, foreground=TEXT)
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=TEXT)
        style.configure('Title.TLabel', font=('Helvetica', 25, 'bold'))
        style.configure('Head.TLabel', font=('Helvetica', 13, 'bold'), foreground=GREEN)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('Card.TFrame', background=CARD)
        style.configure('Card.TLabel', background=CARD, foreground=TEXT)
        style.configure('CardMuted.TLabel', background=CARD, foreground=MUTED)
        style.configure('CardTitle.TLabel', background=CARD, foreground=MUTED,
                        font=('Helvetica', 10, 'bold'))
        style.configure('Metric.TLabel', background=CARD, foreground=TEXT,
                        font=('Helvetica', 30, 'bold'))
        style.configure('TButton', padding=(10, 7), background='#263749', borderwidth=0)
        style.map('TButton', background=[('active', '#39536e'), ('disabled', '#19232e')],
                  foreground=[('disabled', '#65778a')])
        style.configure('TCheckbutton', background=BG, foreground=MUTED)
        style.map('TCheckbutton', background=[('active', BG)])
        style.configure('TCombobox', fieldbackground='#263749', background='#263749',
                        foreground=TEXT, arrowcolor=TEXT, bordercolor=CARD, lightcolor=CARD,
                        darkcolor=CARD, padding=(8, 6))
        style.map('TCombobox', fieldbackground=[('readonly', '#263749')],
                  background=[('readonly', '#263749'), ('active', '#39536e')],
                  foreground=[('readonly', TEXT)],
                  selectbackground=[('readonly', '#263749')],
                  selectforeground=[('readonly', TEXT)])
        self.root.option_add('*TCombobox*Listbox.background', '#263749')
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT)
        self.root.option_add('*TCombobox*Listbox.selectBackground', '#39536e')

    def card(self, parent, title):
        outer = ttk.Frame(parent, style='Card.TFrame', padding=14)
        if title:
            ttk.Label(outer, text=title, style='CardTitle.TLabel').pack(anchor='w', pady=(0, 8))
        return outer

    # ----------------------------------------------------------------- layout
    def build_connection(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=(0, 14))
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(row, textvariable=self.port_var, width=26, state='readonly')
        self.port_box.pack(side='left')
        ttk.Button(row, text='Refresh ports', command=self.refresh_ports).pack(side='left', padx=4)
        ttk.Button(row, text='Reconnect', command=self.reconnect).pack(side='left', padx=4)
        ttk.Checkbutton(row, text='Stay connected', variable=self.auto).pack(side='left', padx=10)
        self.connection = tk.StringVar(value='Not connected')
        ttk.Label(row, textvariable=self.connection, foreground=BLUE).pack(side='left', padx=10)
        ttk.Button(row, text='Reset counters', command=self.reset).pack(side='right')

    def build_readout(self, parent):
        card = self.card(parent, 'RECEIVER')
        card.pack(fill='x')
        metrics = ttk.Frame(card, style='Card.TFrame')
        metrics.pack(fill='x')
        self.metrics = {}
        for index, (key, title, unit) in enumerate((
                ('loss', 'Packet loss', '%'), ('rssi', 'Signal', 'dBm'),
                ('snr', 'Signal to noise', 'dB'), ('rate', 'Received', '/s'))):
            column = ttk.Frame(metrics, style='Card.TFrame')
            column.grid(row=0, column=index, sticky='w', padx=(0, 46))
            ttk.Label(column, text=title.upper(), style='CardTitle.TLabel').pack(anchor='w')
            value = tk.StringVar(value='—')
            label = ttk.Label(column, textvariable=value, style='Metric.TLabel')
            label.pack(anchor='w')
            ttk.Label(column, text=unit, style='CardMuted.TLabel').pack(anchor='w')
            self.metrics[key] = (value, label)
        self.identity = tk.StringVar(value='Waiting for the range test firmware…')
        ttk.Label(card, textvariable=self.identity, style='CardMuted.TLabel')\
            .pack(anchor='w', pady=(12, 0))

    def build_charts(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill='both', expand=True, pady=(14, 0))
        self.charts = {}
        for index, (key, title, note) in enumerate((
                ('minute', 'LAST MINUTE', 'every packet'),
                ('half_hour', 'LAST 30 MINUTES', 'one-second averages'))):
            card = self.card(row, f'{title}   ·   {note}')
            card.grid(row=0, column=index, sticky='nsew', padx=(0, 14) if index == 0 else 0)
            rssi = tk.Canvas(card, height=170, bg=CARD, highlightthickness=0)
            rssi.pack(fill='both', expand=True)
            ttk.Label(card, text='PACKET LOSS', style='CardTitle.TLabel')\
                .pack(anchor='w', pady=(10, 2))
            loss = tk.Canvas(card, height=64, bg=CARD, highlightthickness=0)
            loss.pack(fill='x')
            self.charts[key] = (rssi, loss)
            row.columnconfigure(index, weight=1)
        row.rowconfigure(0, weight=1)

    def build_leds(self, parent):
        card = self.card(parent, 'RECEIVER LEDS   ·   live mirror of the eight pixels on the board')
        card.pack(fill='x', pady=(14, 0))
        body = ttk.Frame(card, style='Card.TFrame')
        body.pack(fill='x')
        self.led_canvas = tk.Canvas(body, height=86, width=420, bg=CARD, highlightthickness=0)
        self.led_canvas.pack(side='left', padx=(0, 22))
        legend = ttk.Frame(body, style='Card.TFrame')
        legend.pack(side='left', fill='both', expand=True)
        for name, colour, description in LEGEND:
            line = ttk.Frame(legend, style='Card.TFrame')
            line.pack(fill='x', anchor='w', pady=2)
            tk.Label(line, text=name, bg=CARD, fg=colour, font=('Helvetica', 10, 'bold'),
                     width=18, anchor='w').pack(side='left')
            tk.Label(line, text=description, bg=CARD, fg=MUTED, font=('Helvetica', 10),
                     justify='left', anchor='w', wraplength=620).pack(side='left', fill='x')

    # ------------------------------------------------------------- behaviour
    def record(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', time.strftime('%H:%M:%S') + '  ' + text + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 200:
            self.log.delete('1.0', '50.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def refresh_ports(self):
        ports = [p.device for p in list_ports.comports() if p.vid is not None]
        self.port_box['values'] = ports
        if self.port_var.get() not in ports:
            self.port_var.set(self.preferred if self.preferred in ports
                              else (ports[0] if ports else ''))

    def reconnect(self):
        self.receiver.close()
        self.receiver.next_attempt = 0

    def reset(self):
        if self.receiver.connected:
            self.receiver.send('RESET')
            self.receiver.packets.clear()
            self.receiver.samples.clear()
            self.record('Counters and history cleared')

    def maintain_connection(self, now):
        if self.receiver.connected or not self.auto.get() or now < self.receiver.next_attempt:
            return
        self.receiver.next_attempt = now + 2.0
        port = self.port_var.get()
        if not port:
            self.refresh_ports()
            port = self.port_var.get()
        if not port:
            return
        try:
            self.receiver.open(port)
            self.record(f'Connected to {port}')
        except (serial.SerialException, OSError) as exc:
            self.receiver.close(tell_board=False)
            self.connection.set(f'{port}: unavailable')
            self.record(f'{port}: {exc}')

    # ----------------------------------------------------------------- paint
    def draw_rssi(self, canvas, points, span):
        canvas.delete('all')
        width, height = max(canvas.winfo_width(), 10), max(canvas.winfo_height(), 10)
        now = time.monotonic()
        canvas.create_rectangle(38, 8, width, height - 18, fill=PLOT, outline='')
        for step in range(5):
            value = RSSI_TOP - step * (RSSI_TOP - RSSI_BOTTOM) / 4
            y = 8 + step * (height - 26) / 4
            canvas.create_line(38, y, width, y, fill=LINE)
            canvas.create_text(32, y, anchor='e', fill=MUTED, font=(MONO, 9),
                               text=f'{value:.0f}')
        coordinates = []
        for timestamp, rssi, _noise, _gap in points:
            age = now - timestamp
            if age > span or rssi is None:
                continue
            x = 38 + (1 - age / span) * (width - 42)
            clamped = min(max(rssi, RSSI_BOTTOM), RSSI_TOP)
            coordinates += [x, 8 + (RSSI_TOP - clamped) / (RSSI_TOP - RSSI_BOTTOM) * (height - 26)]
        if len(coordinates) >= 4:
            canvas.create_line(*coordinates, fill=GREEN, width=2)
        elif not points:
            canvas.create_text(width / 2, height / 2, fill=MUTED, font=('Helvetica', 11),
                               text='No packets yet')
        canvas.create_text(width - 4, height - 6, anchor='e', fill=MUTED, font=(MONO, 9),
                           text='dBm  ·  now at right')

    def draw_loss(self, canvas, points, span):
        canvas.delete('all')
        width, height = max(canvas.winfo_width(), 10), max(canvas.winfo_height(), 10)
        now = time.monotonic()
        base, top = height - 14, 10
        canvas.create_rectangle(38, top, width, base, fill=PLOT, outline='')
        for fraction, text in ((0.0, '100'), (0.5, '50'), (1.0, '0')):
            y = top + fraction * (base - top)
            canvas.create_line(38, y, width, y, fill=LINE)
            canvas.create_text(32, y, anchor='e', fill=MUTED, font=(MONO, 9), text=text)

        # A filled area rather than one bar per sample: at 1 Hz the bars are ten
        # pixels apart and read as scattered dots rather than as a flat zero.
        worst, outline = 0.0, []
        for timestamp, loss, _rssi, _noise in points:
            age = now - timestamp
            if age > span or loss is None:
                continue
            x = 38 + (1 - age / span) * (width - 42)
            outline += [x, base - (min(loss, 100) / 100) * (base - top)]
            worst = max(worst, loss)
        if len(outline) >= 4:
            colour = GREEN if worst < 2 else (AMBER if worst < 20 else RED)
            area = [outline[0], base] + outline + [outline[-2], base]
            canvas.create_polygon(*area, fill=colour, outline='', stipple='gray25')
            canvas.create_line(*outline, fill=colour, width=2)
        else:
            canvas.create_text(width / 2, height / 2 - 4, fill=MUTED, font=('Helvetica', 11),
                               text='No measurements yet')

    def draw_leds(self):
        canvas = self.led_canvas
        canvas.delete('all')
        size, gap, top = 40, 11, 14
        for index, colour in enumerate(self.receiver.pixels):
            try:
                red, green, blue = (int(colour[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                red = green = blue = 0
            x = 6 + index * (size + gap)
            dark = max(red, green, blue) < 8
            # An unlit pixel is a dim outlined disc, not pure black, so it reads
            # as an LED that is off rather than as a hole in the card.
            fill = ('#161f2b' if dark
                    else f'#{scale_channel(red):02x}{scale_channel(green):02x}{scale_channel(blue):02x}')
            canvas.create_oval(x, top, x + size, top + size, fill=fill,
                               outline='#33465c' if dark else fill, width=1)
            canvas.create_text(x + size / 2, top + size + 12, text=str(index), fill=MUTED,
                               font=(MONO, 9))

    def repaint(self):
        receiver = self.receiver
        stat = receiver.stat
        if receiver.connected:
            self.connection.set(f'{receiver.port}  ·  connected')
        elif self.auto.get():
            self.connection.set('Reconnecting…')

        loss = number(stat, 'loss_pct')
        rssi = number(stat, 'rssi_avg')
        noise = number(stat, 'nf_avg')
        received = number(stat, 'received')
        quiet = number(stat, 'quiet_ms', 0) or 0

        if not receiver.connected or not stat:
            self.headline.set('Waiting for the receiver…')
            colour = MUTED
        elif quiet > 2000:
            self.headline.set('LINK LOST')
            colour = RED
        elif loss is not None and loss >= 20:
            self.headline.set('HEAVY LOSS')
            colour = RED
        elif loss:
            self.headline.set('LOSING PACKETS')
            colour = AMBER
        else:
            self.headline.set('LINK GOOD')
            colour = GREEN
        ttk.Style().configure('Head.TLabel', foreground=colour)

        def show(key, value, fmt='{:.0f}'):
            variable, _label = self.metrics[key]
            variable.set('—' if value is None else fmt.format(value))

        show('loss', loss, '{:.1f}')
        self.metrics['loss'][1].configure(
            foreground=TEXT if not loss else (AMBER if loss < 20 else RED))
        show('rssi', rssi)
        show('snr', None if rssi is None or noise is None else rssi - noise)
        show('rate', received)

        if receiver.banner:
            banner = receiver.banner
            self.identity.set(
                f"{banner.get('MAC', '?')}   ·   channel {banner.get('ESP-NOW CHANNEL', '?')}"
                f"   ·   boot {banner.get('Boot ID', '?')}"
                f"   ·   {banner.get('TX power', '?')}"
                f"   ·   sleep {banner.get('Wi-Fi sleep', '?')}"
                f"   ·   transmitter {stat.get('src', 'none')}")

        self.draw_rssi(self.charts['minute'][0], receiver.packets, MINUTE)
        self.draw_loss(self.charts['minute'][1], receiver.samples, MINUTE)
        self.draw_rssi(self.charts['half_hour'][0],
                       [(t, r, n, 0) for t, _l, r, n in receiver.samples], HALF_HOUR)
        self.draw_loss(self.charts['half_hour'][1], receiver.samples, HALF_HOUR)
        self.draw_leds()

    def poll(self):
        now = time.monotonic()
        self.maintain_connection(now)
        for line in self.receiver.read_lines():
            self.receiver.consume(line, now)
            if line.startswith(('EVENT ', 'WARNING', 'ESP-NOW INIT')):
                self.record(line)
        self.repaint()
        self.root.after(50, self.poll)

    def close(self):
        self.receiver.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', '--rx', dest='port', help='Serial port of the back-room receiver')
    options = parser.parse_args()
    root = tk.Tk()
    App(root, port=options.port)
    root.mainloop()


if __name__ == '__main__':
    main()
