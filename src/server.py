#!/usr/bin/env python3

import os
import socket
import subprocess
import threading
import time

import logger
import stts
import utils
from config import ConfigHandler
from terminal import MDTerminal
import player


class MDTServer:

    def __init__(self, init_cfg: dict, home: str, die_in):
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
        self._die_in = die_in
        self.reload = False
        self._cfg = ConfigHandler(cfg=init_cfg, path={}, home=home)

        self._logger = logger.Logger(self._cfg['log'])
        self._cfg.configure(self._logger.add('CFG'))

        self.log = self._logger.add('SERVER')

        self._play = player.Player(cfg=self._cfg, logger_=self._logger)

        self._stt = stts.SpeechToText(cfg=self._cfg, play_=self._play, log=self._logger.add('STT'))

        self._terminal = MDTerminal(
            cfg=self._cfg, play_=self._play, stt=self._stt,
            die_in=die_in, log=self._logger.add('Terminal')
        )
        self._death_time = 0
        self._thread = threading.Thread(target=self._loop)
        self.work = False
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.settimeout(1)

    def stop(self):
        self.work = False
        self._play.quiet()
        self._play.say('Голосовой терминал мажордомо завершает свою работу.')
        self.log('stopping...')
        self._terminal.stop()
        self._stt.stop()
        self._play.stop()
        self._thread.join()
        self.log('stop.', logger.INFO)

    def start(self):
        self.work = True
        self._play.start()
        self._play.say('Приветствую. Голосовой терминал Мажордомо настраивается, три... два... один...', 0, wait=0.5)
        self._stt.start()
        self._cfg.join_low_say(self._play.say)
        self._terminal.start()
        self.log('start', logger.INFO)
        self._thread.start()

    def _loop(self):
        self._socket.bind(('', 7999))
        self._socket.listen(1)
        while self.work:
            try:
                conn, _ = self._socket.accept()
                conn.settimeout(5.0)
            except socket.timeout:
                continue
            self.log('New connection from {}'.format(_[0]))
            try:
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

    def _api_settings(self, cmd: str):
        if self._cfg.json_to_cfg(cmd):
            self._cfg.config_save()
            self._terminal.reload()
            self.log('Конфиг обновлен: {}'.format(self._cfg), logger.DEBUG)
            self.log('Конфиг обновлен', logger.INFO)
        else:
            self.log('Конфиг не изменился', logger.DEBUG)

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
            self.reload = True
            self._die_in(3)
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

        err = self._stt.voice_record(hello=hello, save_to=save_to)
        if err is None:
            bye = 'Запись {} образца завершена. Вы можете прослушать свою запись.'.format(nums[param[2]])
            self._play.say(bye)
            self.log(bye, logger.INFO)
        else:
            err = 'Ошибка сохранения образца {}: {}'.format(nums[param[2]], err)
            self.log(err, logger.ERROR)
            self._play.say(err)

        self._terminal.paused(False)

        # self._play.quiet()
        # self._play.say('Запись {} образца на 5 секунд начнется после звукового сигнала'.format(nums[param[2]]))
        # self.log('Запись {} образца на 5 секунд начнется после звукового сигнала'.format(nums[param[2]]), logger.INFO)
        # self._play.play(self._cfg.path['ding'])
        # cmd = ['rec', '-q', os.path.join(self._cfg.path['tmp'], param[1] + param[2] + '.wav')]
        # self.log(cmd)
        # try:
        #     subprocess.run(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        # except subprocess.TimeoutExpired:
        #     # self._play.play(self._cfg.path['ding'])
        #     self._play.say('Запись {} образца завершена. Вы можете прослушать свою запись.'.format(nums[param[2]]))
        #     self.log('Запись {} образца завершена.'.format(nums[param[2]]), logger.INFO)
        # else:
        #     # self._play.play(self._cfg.path['ding'])
        #     err = 'Ошибка записи образца {}. Возможно ваша аудиосистема не работает или настроена неправильно'.format(
        #             nums[param[2]])
        #     self.log(err, logger.ERROR)
        #     self._play.say(err)
        # finally:
        #     self._terminal.paused(False)

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
        pmdl = os.path.join(self._cfg.path['models'], 'model' + param[1] + self._cfg.path['model_ext'])
        cmd = [self._cfg.path['training_service'], ]
        cmd.extend(models)
        cmd.append(pmdl)
        wtime = time.time()
        self.log('Компилирую {}'.format(pmdl), logger.INFO)
        try:
            # TODO: Переделать на питоне
            subprocess.run(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
        except (subprocess.SubprocessError, subprocess.TimeoutExpired):
            self.log('Ошибка компиляции модели: {}'.format(pmdl), logger.ERROR)
            self._play.say('Ошибка компиляции модели номер {}'.format(param[1]))
        else:
            ctime = utils.pretty_time(time.time() - wtime)
            self.log('Модель скомпилирована успешно за {}: {}'.format(ctime, pmdl), logger.INFO)
            self._play.say('Модель номер {} скомпилирована успешно за {}'.format(param[1], ctime))
            self._cfg.models_load()
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