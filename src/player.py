#!/usr/bin/env python3


import os
import queue
import subprocess
import threading
import time

import logger


class Player:
    PLAY = {
        '.mp3': ['mpg123', '-q'],
        '.wav': ['aplay', '-q'],
    }
    MAX_BUSY_WAIT = 60  # Макс время блокировки, потом отлуп. Поможет от возможных зависаний

    def __init__(self, cfg, log, tts):
        self._cfg = cfg
        self.log = log
        # 0 - играем в фоне, до 5 снимаем блокировку автоматически. 5 - монопольный режим, нужно снять блокировку руками
        self._lvl = 0
        self._only_one = threading.Lock()
        self._work = False
        self._popen = None
        self._last_activity = time.time()
        self._tts = tts

        self.mpd = None
        self._lp_play = LowPrioritySay(self.really_busy, self.say, self.play)

    def start(self, mpd):
        self._work = True
        self.mpd = mpd
        self._lp_play.start()
        self.log('start.', logger.INFO)

    def stop(self):
        self._work = False
        self.log('stopping...', logger.DEBUG)
        self._lvl = 100500
        self._lp_play.stop()

        count = 0
        while (self.popen_work()) and count < 1000:
            time.sleep(0.01)
            count += 1
        self.quiet()
        self.kill_popen()

        self._last_activity = 0  # Отжим паузы

        self.log('stop.', logger.INFO)

    def set_lvl(self, lvl):
        if lvl > 1:
            self._lp_play.clear()

        start_time = time.time()
        if lvl <= self.get_lvl():
                while self.busy() and time.time() - start_time < self.MAX_BUSY_WAIT:
                    pass
        if lvl >= self.get_lvl():
            self._lvl = lvl
            self.quiet()
            return True
        self._only_one.release()
        return False

    def get_lvl(self):
        if self._lvl < 5:
            if self.busy():
                return self._lvl
        else:
            return self._lvl
        return 0

    def clear_lvl(self):
        self._lvl = 0

    def busy(self):
        return self.popen_work() and self._work

    def really_busy(self):
        return self._only_one.locked() or self.busy()

    def kill_popen(self):
        if self.popen_work():
            self._popen.kill()
            self.log('Stop playing', logger.DEBUG)

    def quiet(self):
        if self.popen_work():
            self._lp_play.clear()

    def last_activity(self):
        if self.popen_work():
            self._last_activity = time.time()
        return self._last_activity

    def popen_work(self):
        return self._popen is not None and self._popen.poll() is None

    def play(self, file, lvl: int=2, wait=0):
        if not lvl:
            self.log('low play \'{}\' pause {}'.format(file, wait), logger.DEBUG)
            return self._lp_play.play(file, wait)
        self._only_one.acquire()

        if not self.set_lvl(lvl):
            return

        self._last_activity = time.time() + 3
        self.mpd.pause(True)

        time.sleep(0.01)
        self._play(file)
        self._only_one.release()

        self._last_activity = time.time() + wait
        if wait:
            time.sleep(wait)

    def say(self, msg: str, lvl: int=2, alarm=None, wait=0, is_file: bool = False):
        if not lvl:
            self.log('low say \'{}\' pause {}'.format(msg, wait), logger.DEBUG)
            return self._lp_play.say(msg, wait, is_file)
        self._only_one.acquire()

        if not self.set_lvl(lvl):
            return

        if alarm is None:
            alarm = self._cfg.get('alarmtts', 0)

        file = self._tts(msg) if not is_file else msg
        self._last_activity = time.time() + 3
        self.mpd.pause(True)

        time.sleep(0.01)
        if alarm:
            self._play(self._cfg.path['dong'])
            try:
                self._popen.wait(2)
            except subprocess.TimeoutExpired:
                pass
        self._play(file)
        self._only_one.release()

        self._last_activity = time.time() + wait
        if wait:
            time.sleep(wait)

    def _play(self, obj):
        (path, stream, ext) = obj() if callable(obj) else (obj, None, None) if isinstance(obj, str) else obj
        self.kill_popen()
        ext = ext or os.path.splitext(path)[1]
        if not stream and not os.path.isfile(path):
            return self.log('Файл {} не найден'.format(path), logger.ERROR)
        if ext not in self.PLAY:
            return self.log('Неизвестный тип файла: {}'.format(ext), logger.CRIT)
        cmd = self.PLAY[ext].copy()
        if stream is None:
            cmd.append(path)
            self.log('Играю {} ...'.format(path, logger.DEBUG))
            self._popen = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            cmd.append('-')
            self.log('Стримлю {} ...'.format(path, logger.DEBUG))
            # noinspection PyCallingNonCallable
            self._popen = stream(cmd)


class LowPrioritySay(threading.Thread):
    TIMEOUT = 300

    def __init__(self, is_busy, say, play):
        super().__init__(name='LowPrioritySay')
        self._play = play
        self._say = say
        self._is_busy = is_busy
        self._queue_in = queue.Queue()
        self._quiet = False
        self._work = False

    def start(self):
        self._work = True
        super().start()

    def stop(self):
        self._work = False
        self._queue_in.put_nowait(None)
        self.join()

    def clear(self):
        self._quiet = True
        while not self._queue_in.empty():
            try:
                self._queue_in.get_nowait()
            except queue.Empty:
                pass

    def say(self, msg: str, wait: float or int=0, is_file: bool = False):
        self._put(1 if not is_file else 3, msg, wait)

    def play(self, file: str, wait: float or int=0):
        self._put(2, file, wait)

    def _put(self, action, target, wait):
        self._queue_in.put_nowait([action, target, wait])

    def run(self):
        while self._work:
            say = self._queue_in.get()
            while self._is_busy() and self._work:
                time.sleep(0.01)
            if say is None or not self._work:
                break
            if say[0] in [1, 3]:
                self._say(msg=say[1], lvl=1, wait=say[2], is_file=say[0] == 3)
            elif say[0] == 2:
                self._play(file=say[1], lvl=1, wait=say[2])



