#!/usr/bin/env python3

import os
import socket
import threading
import time

import lib.snowboy_training as training_service
import logger
import utils


class MDTServer(threading.Thread):
    def __init__(self, cfg, log, play, terminal, die_in, stt):
        super().__init__(name='MDTServer')
        self.MDAPI = {
            'hi': self._api_voice,
            'voice': self._api_voice,
            'home': self._api_home,
            'url': self._api_url,
            'play': self._api_play,
            'pause': self._api_pause,
            'tts': self._api_tts,
            'ask': self._api_ask,
            'rtsp': self._api_rtsp,
            'run': self._api_run,
        }
        self.MTAPI = {
            'settings': self._api_settings,
            'rec': self._api_rec,
        }

        self._cfg = cfg
        self.log = log
        self._play = play
        self._terminal = terminal
        self._die_in = die_in
        self._stt = stt

        self.work = False
        self._socket = socket.socket()

    def join(self, timeout=None):
        self.work = False
        self.log('stopping...')
        super().join(timeout)
        self.log('stop.', logger.INFO)

    def start(self):
        self.work = True
        super().start()
        self.log('start', logger.INFO)

    def _open_socket(self) -> bool:
        ip = ''
        port = 7999
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.settimeout(1)
        try:
            self._socket.bind((ip, port))
        except OSError as e:
            say = 'Ошибка запуска сервера{}.'.format(' - адрес уже используется' if e.errno == 98 else '')
            self.log('Ошибка запуска сервера на {}:{}: {}'.format(ip, port, e), logger.CRIT)
            self._play.say(say)
            return False
        self._socket.listen(1)
        return True

    def run(self):
        if not self._open_socket():
            return
        while self.work:
            try:
                conn, ip_info = self._socket.accept()
                conn.settimeout(5.0)
            except socket.timeout:
                continue
            allow = self._cfg.allow_connect(ip_info[0])
            msg = '{} new connection from {}'.format('Allow' if allow else 'Ignore', ip_info[0])
            self.log(msg, logger.DEBUG if allow else logger.WARN)
            try:
                if allow:
                    self._parse(self._socket_reader(conn))
            finally:
                conn.close()
        self._socket.close()

    def _parse(self, data: str):
        if not data:
            return self.log('Нет данных')
        else:
            self.log('Получены данные: {}'.format(data))

        cmd = data.split(':', maxsplit=1)
        if len(cmd) != 2:
            cmd.append('')
        if cmd[0] in self.MDAPI:
            self.MDAPI[cmd[0]](cmd[1])
        elif cmd[0] in self.MTAPI:
            self.MTAPI[cmd[0]](cmd[1])
        else:
            self.log('Неизвестная комманда: {}'.format(cmd[0]), logger.WARN)

    def _api_voice(self, cmd: str):
        self._terminal.external_detect('voice', cmd)

    def _api_home(self, cmd: str):
        self.log('Not implemented yet - home:{}'.format(cmd), logger.WARN)

    def _api_url(self, cmd: str):
        self.log('Not implemented yet - url:{}'.format(cmd), logger.WARN)

    def _api_play(self, cmd: str):
        self._play.mpd.play(cmd)

    def _api_pause(self, _):
        self._play.mpd.pause()

    def _api_tts(self, cmd: str):
        self._play.say(cmd, lvl=0)

    def _api_ask(self, cmd: str):
        self._terminal.external_detect('ask', cmd)

    def _api_rtsp(self, cmd: str):
        self.log('Not implemented yet - rtsp:{}'.format(cmd), logger.WARN)

    def _api_run(self, cmd: str):
        self.log('Not implemented yet - run:{}'.format(cmd), logger.WARN)

    def _api_settings(self, cmd: str or dict) -> bool:
        if self._cfg.json_to_cfg(cmd):
            self._cfg.config_save()
            self._terminal.reload()
            self.log('Конфиг обновлен: {}'.format(self._cfg), logger.DEBUG)
            self.log('Конфиг обновлен', logger.INFO)
            return True
        else:
            self.log('Конфиг не изменился', logger.DEBUG)
            return False

    def _api_rec(self, cmd: str):
        param = cmd.split('_')  # должно быть вида rec_1_1, play_2_1, compile_5_1
        if len(param) != 3 or sum([1 if len(x) else 0 for x in param]) != 3:
            self.log('Ошибка разбора параметров для \'rec\': {}'.format(param), logger.ERROR)
            return
        # a = param[0]  # rec, play или compile
        # b = param[1]  # 1-6
        # c = param[2]  # 1-3
        if param[0] == 'play':
            self._rec_play(param)
        elif param[0] == 'save':
            self._die_in(3, True)
        elif param[0] == 'rec':
            self._rec_rec(param)
        elif param[0] == 'compile':
            self._rec_compile(param)
        else:
            self.log('Неизвестная комманда для rec: '.format(param[0]), logger.ERROR)

    def _rec_play(self, param: list):
        file = os.path.join(self._cfg.path['tmp'], param[1] + param[2] + '.wav')
        if os.path.isfile(file):
            self._play.say(file, is_file=True)
        else:
            self._play.say('Ошибка воспроизведения - файл {} не найден'.format(param[1] + param[2] + '.wav'))
            self.log('Файл {} не найден'.format(file), logger.WARN)

    def _rec_rec(self, param: list):
        nums = {'1': 'первого', '2': 'второго', '3': 'третьего'}
        if param[2] not in nums:
            self.log('SERVER: Ошибка записи - недопустимый параметр: {}'.format(param[2]), logger.ERROR)
            self._play.say('Ошибка записи - недопустимый параметр')
            return

        self._terminal.paused(True)

        hello = 'Запись {} образца на 5 секунд начнется после звукового сигнала'.format(nums[param[2]])
        save_to = os.path.join(self._cfg.path['tmp'], param[1] + param[2] + '.wav')
        self.log(hello, logger.INFO)

        err = self._stt.voice_record(hello=hello, save_to=save_to, convert_rate=16000, convert_width=2)
        self._terminal.paused(False)
        if err is None:
            bye = 'Запись {} образца завершена. Вы можете прослушать свою запись.'.format(nums[param[2]])
            self._play.say(bye)
            self.log(bye, logger.INFO)
        else:
            err = 'Ошибка сохранения образца {}: {}'.format(nums[param[2]], err)
            self.log(err, logger.ERROR)
            self._play.say(err)

    def _rec_compile(self, param: list):
        models = [os.path.join(self._cfg.path['tmp'], param[1] + x + '.wav') for x in ['1', '2', '3']]
        miss = False
        for x in models:
            if not os.path.isfile(x):
                miss = True
                err = 'Ошибка компиляции - файл {} не найден.'
                self.log(err.format(x), logger.ERROR)
                self._play.say(err.format(os.path.basename(x)))
        if miss:
            return
        pmdl_name = 'model' + param[1] + self._cfg.path['model_ext']
        pmdl_path = os.path.join(self._cfg.path['models'], pmdl_name)
        self.log('Компилирую {}'.format(pmdl_path), logger.INFO)
        work_time = time.time()
        try:
            snowboy = training_service.Training(*models)
        except RuntimeError as e:
            self.log('Ошибка компиляции модели {}: {}'.format(pmdl_path, e), logger.ERROR)
            self._play.say('Ошибка компиляции модели номер {}'.format(param[1]))
        else:
            work_time = utils.pretty_time(time.time() - work_time)
            snowboy.save(pmdl_path)
            phrase = self._stt.phrase_from_files(models)
            msg = ', "{}",'.format(phrase) if phrase else ''
            self.log('Модель{} скомпилирована успешно за {}: {}'.format(msg, work_time, pmdl_path), logger.INFO)
            self._play.say('Модель{} номер {} скомпилирована успешно за {}'.format(msg, param[1], work_time))
            self._cfg.models_load()
            if not self._api_settings({'models': {pmdl_name: phrase}}):
                self._terminal.reload()
            # Удаляем временные файлы
            for x in models:
                os.remove(x)

    @staticmethod
    def _socket_reader(conn) -> str:
        data = b''
        while b'\r\n' not in data:  # ждём первую строку
            try:
                tmp = conn.recv(1024)
            except (BrokenPipeError, socket.timeout):
                break
            if not tmp:  # сокет закрыли, пустой объект
                break
            data += tmp
        return data.decode().split('\r\n', 1)[0]
