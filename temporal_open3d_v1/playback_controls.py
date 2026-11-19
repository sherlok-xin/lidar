import sys
sys.dont_write_bytecode = True
from pathlib import Path
import argparse
import collections
import copy
import importlib.util
import json
import math
import os
import queue
import select
import signal
import threading
import time
from urllib.parse import urlparse

class FrameController:
    """Pure navigation state. Source stamps are never synthesized."""
    def __init__(self,frames,start_seq=None,rate=10.):
        self.frames=frames;self.position=0;self.playing=False;self.rate=float(rate)
        self.seek_by_seq={f['seq']:i for i,f in enumerate(frames)}
        self._rate(self.rate)
        if start_seq is not None:self.position=self.seek_by_seq[start_seq]
    def _rate(self,value):
        if not .1<=value<=30:raise ValueError('Frame rate must be .1..30 FPS')
        self.rate=value
    def command(self,text):
        parts=text.strip().lower().split()
        if not parts:return 'noop'
        cmd=parts[0];old=self.position
        if cmd in ('show',):pass
        elif cmd in ('n','next'):self.position=min(len(self.frames)-1,self.position+1)
        elif cmd in ('p','prev','previous'):self.position=max(0,self.position-1)
        elif cmd in ('seq','g'):
            if len(parts)!=2 or int(parts[1]) not in self.seek_by_seq:raise ValueError('Requested seq is not in this indexed source window')
            self.position=self.seek_by_seq[int(parts[1])]
        elif cmd in ('play','a'):self.playing=True;return 'play'
        elif cmd in ('pause','stop'):self.playing=False;return 'pause'
        elif cmd in ('rate','r'):
            if len(parts)!=2:raise ValueError('Use rate FPS')
            self._rate(float(parts[1]));return 'rate'
        elif cmd in ('q','quit'):return 'quit'
        elif cmd in ('s','status'):return 'status'
        elif cmd in ('h','help','?'):return 'help'
        else:raise ValueError('Unknown command; use n/p/seq N/play/pause/rate FPS/status/q')
        return 'backward' if self.position<old else 'forward' if self.position>old else 'unchanged'




class InputLines:
    """select on an fd + os.read, never combine fd readiness with buffered readline.

    No input thread or blocking readline to strand during pause, EOF or shutdown.
    Canonical terminal editing/echo/signal handling remain owned by the terminal.
    """
    def __init__(self, stream):
        self.fd = stream.fileno()
        self.is_tty = os.isatty(self.fd)
        self.pending = b''
        self.eof = False

    def poll(self, timeout=.03):
        if self.eof:
            return []
        try:
            ready = select.select([self.fd], [], [], timeout)[0]
        except InterruptedError:
            return []
        if not ready:
            return []
        try:
            data = os.read(self.fd, 4096)
        except InterruptedError:
            return []
        except OSError as exc:
            # PTY peer disappearing on Linux is an input hangup, not a ROS error.
            if exc.errno != 5:
                raise
            data = b''
        self.pending += data
        lines = []
        while b'\n' in self.pending:
            line, self.pending = self.pending.split(b'\n', 1)
            lines.append(line.decode('utf-8', errors='replace').rstrip('\r'))
        if not data:
            self.eof = True
            if self.pending:
                lines.append(self.pending.decode('utf-8', errors='replace'))
                self.pending = b''
        if len(self.pending) > 16384:
            raise ValueError('Input line exceeds 16 KiB')
        return lines


class AsyncLog:
    """Only this writer touches the JSONL file; disk I/O never holds control lock."""
    def __init__(self, path):
        self.output = Path(path).open('a', buffering=1)
        self.queue = queue.Queue()
        self.error = None
        self.thread = threading.Thread(target=self._write, name='opdf-event-log', daemon=True)
        self.thread.start()

    def event(self, kind, **kwargs):
        self.queue.put(dict(wall_time_ns=time.time_ns(), event=kind, **kwargs))

    def _write(self):
        try:
            while True:
                row = self.queue.get()
                if row is None:
                    break
                self.output.write(json.dumps(row) + '\n')
            self.output.flush()
        except Exception as exc:
            self.error = exc
        finally:
            self.output.close()

    def close(self):
        self.queue.put(None)
        self.thread.join(2.)
        return not self.thread.is_alive() and self.error is None


class Console:
    """Sparse UI on its own writer; even a blocked output pipe cannot stall input.

    If stdin is a terminal, open its terminal for UI feedback even when stdout
    and stderr were redirected. Per-frame diagnostics go ONLY to --log.
    """
    def __init__(self, stdin=sys.stdin):
        self.queue = queue.Queue()
        self.stop = threading.Event()
        self.error = None
        try:
            if os.isatty(stdin.fileno()):
                self.fd = os.open(os.ttyname(stdin.fileno()), os.O_WRONLY | os.O_NONBLOCK)
            else:
                self.fd = os.dup(sys.stdout.fileno())
        except (OSError, AttributeError, ValueError):
            self.fd = os.dup(sys.stderr.fileno())
        self.thread = threading.Thread(target=self._write, name='opdf-terminal-ui', daemon=True)
        self.thread.start()

    def say(self, text):
        self.queue.put((text + '\n').encode('utf-8'))

    def _write(self):
        try:
            while not self.stop.is_set():
                data = self.queue.get()
                if data is None:
                    break
                while data and not self.stop.is_set():
                    try:
                        n = os.write(self.fd, data)
                        data = data[n:]
                    except BlockingIOError:
                        self.stop.wait(.02)
        except OSError as exc:
            self.error = str(exc)
        finally:
            os.close(self.fd)

    def close(self):
        self.queue.put(None)
        self.thread.join(.3)
        self.stop.set()
        self.thread.join(.1)
        return not self.thread.is_alive()


class Playback:
    """Control/scheduler lock is NEVER held across load, publish, sleep or log I/O.

    Only one worker publishes; manual seeks remain FIFO. Pause prevents future
    autoplay scheduling. An already started whole-frame batch finishes intact.
    """
    def __init__(self, frames, publish, event, start_seq=None, rate=10., refresh_hz=2., autoplay=False):
        self.controller = FrameController(frames, start_seq, rate)
        self.controller.playing = autoplay
        self.publish = publish
        self.event = event
        self.refresh_hz = refresh_hz
        self.condition = threading.Condition()
        self.stopped = False
        self.requests = collections.deque([(self.controller.position, 'initial')])
        self.last_finished = time.monotonic()
        self.last_published = None
        self.busy = False
        self.error = None
        self.first_published = threading.Event()
        self.thread = threading.Thread(target=self._run, name='opdf-frame-publisher', daemon=True)

    def start(self, delay=.8):
        self.start_delay = delay
        self.thread.start()

    def snapshot(self):
        with self.condition:
            return dict(seq=self.controller.frames[self.controller.position]['seq'],
                        position=self.controller.position, playing=self.controller.playing,
                        rate_fps=self.controller.rate, published_seq=self.last_published,
                        publishing=self.busy, queued_seeks=len(self.requests))

    def command(self, text):
        parts = text.strip().lower().split()
        if not parts:
            return 'noop', self.snapshot()
        cmd = parts[0]
        if len(parts) != (2 if cmd in ('seq', 'g', 'rate', 'r') else 1):
            raise ValueError('Use n / p / seq NUMBER / play / pause / rate NUMBER / status / q')
        with self.condition:
            action = self.controller.command(text)
            if action == 'quit':
                self.stopped = True
            elif action in ('forward', 'backward', 'unchanged'):
                self.controller.playing = False
                self.requests.append((self.controller.position, action))
            self.condition.notify_all()
        return action, self.snapshot()

    def stop(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()

    def join(self, timeout=3.):
        self.thread.join(timeout)
        return not self.thread.is_alive()

    def _next(self):
        with self.condition:
            while not self.stopped:
                if self.requests:
                    self.busy = True
                    return self.requests.popleft()
                now = time.monotonic()
                c = self.controller
                interval = 1. / c.rate if c.playing else (1. / self.refresh_hz if self.refresh_hz else None)
                wait = None if interval is None else max(0., self.last_finished + interval - now)
                if wait is None or wait > 0:
                    self.condition.wait(wait)
                    continue
                if c.playing:
                    old = c.position
                    c.command('n')
                    if c.position == old:
                        c.playing = False
                        continue
                    reason = 'autoplay'
                else:
                    reason = 'paused_refresh'
                self.busy = True
                return c.position, reason
        return None

    def _run(self):
        try:
            with self.condition:
                self.condition.wait_for(lambda: self.stopped, timeout=self.start_delay)
            while True:
                request = self._next()
                if request is None:
                    break
                position, reason = request
                self.publish(position, reason)
                with self.condition:
                    self.last_published = self.controller.frames[position]['seq']
                    self.last_finished = time.monotonic()
                    self.busy = False
                self.first_published.set()
        except Exception as exc:
            self.error = exc
            self.event('publisher_error', error=type(exc).__name__ + ': ' + str(exc))
            self.stop()
        finally:
            with self.condition:
                self.busy = False
