#!/usr/bin/env python3

import os
import random
import threading
import time

import wikipedia

import logger
import player
import stts
from lib import snowboydecoder

wikipedia.set_lang('ru')


class MDTerminal(threading.Thread):
    def __init__(self, cfg, play_: player.Player, stt: stts.SpeechToText, log, handler):
        super().__init__(name='MDTerminal')
        self.log = log
        self._cfg = cfg
        self._play = play_
        self._stt = stt
        self._handler = handler
        self.work = False
        self._paused = False
        self._is_paused = False
        self._snowboy = None
        self._callbacks = []
        self.reload()
        self._api = ''
        self._api_cmd = ''
        self._api_time = 0

    def reload(self):
        self.paused(True)
        if len(self._cfg.path['models_list']) and self._stt.max_mic_index != -2:
            self._snowboy = snowboydecoder.HotwordDetector(
                decoder_model=self._cfg.path['models_list'], sensitivity=[self._cfg['sensitivity']]
            )
            self._callbacks = [self._detected for _ in self._cfg.path['models_list']]
        else:
            self._snowboy = None
        self.paused(False)

    def join(self, timeout=None):
        self.work = False
        self.log('stopping...', logger.DEBUG)
        super().join()
        self.log('stop.', logger.INFO)

    def start(self):
        self.work = True
        super().start()
        self.log('start', logger.INFO)

    def paused(self, paused: bool):
        if self._paused == paused or self._snowboy is None:
            return
        self._paused = paused
        while self._is_paused != paused and self.work:
            time.sleep(0.1)

    def _interrupt_callback(self):
        return not self.work or self._paused or self._api

    def run(self):
        while self.work:
            self._is_paused = self._paused
            if self._paused:
                time.sleep(0.1)
                continue
            self._listen()
            self._external_check()

    def _listen(self):
        if self._snowboy is None:
            time.sleep(0.5)
        else:
            self._snowboy.start(detected_callback=self._callbacks,
                                interrupt_check=self._interrupt_callback,
                                sleep_time=0.03)
            self._snowboy.terminate()

    def _external_check(self):
        if self._api:
            cmd = self._api
            self._api = ''
            txt = self._api_cmd
            time_ = int(time.time()) - self._api_time
            if time_ > 10:
                self.log('Получена {}:{} опоздание {} секунд. Игнорирую.'.format(cmd, txt, time_), logger.WARN)
                return
            else:
                self.log('Получена {}:{} опоздание {} секунд'.format(cmd, txt, time_), logger.DEBUG)
            if cmd == 'ask' and txt:
                self.detected(txt)
            elif cmd == 'voice':
                self.detected(voice=True)
            else:
                self.log('Не верный вызов \'{}:{}\''.format(cmd, txt), logger.ERROR)

    def external_detect(self, cmd, txt: str =''):
        self._api = cmd
        self._api_cmd = txt
        self._api_time = int(time.time())

    def _detected(self, model: int=0):
        phrase = ''
        if not model:
            self.log('Очень странный вызов от сновбоя. Это нужно исправить', logger.CRIT)
        else:
            model -= 1
            if model < len(self._cfg.path['models_list']):
                model_name = os.path.split(self._cfg.path['models_list'][model])[1]
                phrase = self._cfg['models'].get(model_name)
                msg = '' if not phrase else ': "{}"'.format(phrase)
            else:
                model_name = str(model)
                msg = ''
            self.log('Голосовая активация по {}{}'.format(model_name, msg), logger.INFO)
        self.detected('{} слушает'.format(phrase) if phrase and not random.SystemRandom().randrange(0, 4) else '')

    def detected(self, hello: str = '', voice=False):
        if self._snowboy is not None:
            self._snowboy.terminate()

        caller = False
        reply = self._stt.listen(hello, voice=voice)
        if reply or voice:
            while caller is not None:
                reply, caller = self._handler(reply, caller)
                if caller:
                    reply = self._stt.listen(reply or '', voice=not reply)
        if reply:
            self._play.say(reply, lvl=1)
        self._listen()
