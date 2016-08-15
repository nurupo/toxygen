import pyaudio
import time
import threading
import settings
from toxav_enums import *
import cv2
# TODO: play sound until outgoing call will be started or cancelled and add timeout


class Call:

    def __init__(self, out_audio, out_video, in_audio=False, in_video=False):
        self._in_audio = in_audio
        self._in_video = in_video
        self._out_audio = out_audio
        self._out_video = out_video
        # TODO: add widget for call

    # -----------------------------------------------------------------------------------------------------------------
    # Audio
    # -----------------------------------------------------------------------------------------------------------------

    def get_in_audio(self):
        return self._in_audio

    def set_in_audio(self, value):
        self._in_audio = value

    in_audio = property(get_in_audio, set_in_audio)

    def get_out_audio(self):
        return self._out_audio

    def set_out_audio(self, value):
        self._out_audio = value

    out_audio = property(get_out_audio, set_out_audio)

    # -----------------------------------------------------------------------------------------------------------------
    # Video
    # -----------------------------------------------------------------------------------------------------------------

    def get_in_video(self):
        return self._in_video

    def set_in_video(self, value):
        self._in_video = value

    in_video = property(get_in_video, set_in_video)

    def get_out_video(self):
        return self._out_video

    def set_out_video(self, value):
        self._in_video = value

    out_video = property(get_out_video, set_out_video)


class AV:

    def __init__(self, toxav):
        self._toxav = toxav
        self._running = True

        self._calls = {}  # dict: key - friend number, value - Call instance

        self._audio = None
        self._audio_stream = None
        self._audio_thread = None
        self._audio_running = False
        self._out_stream = None

        self._audio_rate = 8000
        self._audio_channels = 1
        self._audio_duration = 60
        self._audio_sample_count = self._audio_rate * self._audio_channels * self._audio_duration // 1000

        self._video = None
        self._video_thread = None
        self._video_running = False

    def stop(self):
        self._running = False
        self.stop_audio_thread()
        self.stop_video_thread()

    def __contains__(self, friend_number):
        return friend_number in self._calls

    # -----------------------------------------------------------------------------------------------------------------
    # Calls
    # -----------------------------------------------------------------------------------------------------------------

    def __call__(self, friend_number, audio, video):
        """Call friend with specified number"""
        self.start_audio_thread()
        if video:
            self.start_video_thread()
        self._calls[friend_number] = Call(audio, video)
        self._toxav.call(friend_number, 32 if audio else 0, 5000 if video else 0)

    def accept_call(self, friend_number, audio_enabled, video_enabled):

        if self._running:
            self._calls[friend_number] = Call(audio_enabled, video_enabled)
            self._toxav.answer(friend_number, 32 if audio_enabled else 0, 5000 if video_enabled else 0)
            if audio_enabled:
                self.start_audio_thread()
            if video_enabled:
                self.start_video_thread()

    def finish_call(self, friend_number, by_friend=False):

        if not by_friend:
            self._toxav.call_control(friend_number, TOXAV_CALL_CONTROL['CANCEL'])
        if friend_number in self._calls:
            del self._calls[friend_number]
        if not len(self._calls):
            self.stop_audio_thread()
            self.stop_video_thread()

    def toxav_call_state_cb(self, friend_number, state):
        """
        New call state
        """
        call = self._calls[friend_number]
        call.in_audio = state | TOXAV_FRIEND_CALL_STATE['SENDING_A']
        call.in_video = state | TOXAV_FRIEND_CALL_STATE['SENDING_V']
        # TODO: disable sending?

    # -----------------------------------------------------------------------------------------------------------------
    # Threads
    # -----------------------------------------------------------------------------------------------------------------

    def start_audio_thread(self):
        """
        Start audio sending
        """
        if self._audio_thread is not None:
            return

        self._audio_running = True

        self._audio = pyaudio.PyAudio()
        self._audio_stream = self._audio.open(format=pyaudio.paInt16,
                                              rate=self._audio_rate,
                                              channels=self._audio_channels,
                                              input=True,
                                              input_device_index=settings.Settings.get_instance().audio['input'],
                                              frames_per_buffer=self._audio_sample_count * 10)

        self._audio_thread = threading.Thread(target=self.send_audio)
        self._audio_thread.start()

    def stop_audio_thread(self):

        if self._audio_thread is None:
            return

        self._audio_running = False

        self._audio_thread.join()

        self._audio_thread = None
        self._audio_stream = None
        self._audio = None

        if self._out_stream is not None:
            self._out_stream.stop_stream()
            self._out_stream.close()
            self._out_stream = None

    def start_video_thread(self):
        if self._video_thread is not None:
            return
        self._video_running = True

        self._video = cv2.VideoCapture(0)
        self._video.set(cv2.CAP_PROP_FPS, 25)
        self._video.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._video.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._video_thread = threading.Thread(target=self.send_video)
        self._video_thread.start()

    def stop_video_thread(self):
        if self._video_thread is None:
            return

        self._video_running = False
        self._video_thread.join()
        self._video_thread = None
        self._video = None

    # -----------------------------------------------------------------------------------------------------------------
    # Incoming chunks
    # -----------------------------------------------------------------------------------------------------------------

    def audio_chunk(self, samples, channels_count, rate):
        """
        Incoming chunk
        """

        if self._out_stream is None:
            self._out_stream = self._audio.open(format=pyaudio.paInt16,
                                                channels=channels_count,
                                                rate=rate,
                                                output_device_index=settings.Settings.get_instance().audio['output'],
                                                output=True)
        self._out_stream.write(samples)

    def video_chunk(self):
        pass

    # -----------------------------------------------------------------------------------------------------------------
    # AV sending
    # -----------------------------------------------------------------------------------------------------------------

    def send_audio(self):
        """
        This method sends audio to friends
        """

        while self._audio_running:
            try:
                pcm = self._audio_stream.read(self._audio_sample_count)
                if pcm:
                    for friend_num in self._calls:
                        if self._calls[friend_num].out_audio:
                            try:
                                self._toxav.audio_send_frame(friend_num, pcm, self._audio_sample_count,
                                                             self._audio_channels, self._audio_rate)
                            except:
                                pass
            except:
                pass

            time.sleep(0.01)

    def send_video(self):
        # TODO: fix sending on windows and record video
        while self._video_running:
            try:
                # result, frame = self._video.read()
                # if result:
                #     height, width, channels = frame.shape
                for friend_num in self._calls:
                    if self._calls[friend_num].out_video:
                        try:
                            self._toxav.video_send_frame(friend_num, 4, 2, bytes([1] * 8),
                                                         bytes([50] * 2),
                                                         bytes([2] * 2))
                        except Exception as e:
                            print('Exc0', e)
            except Exception as e:
                print('Exc:', e)

            time.sleep(0.04)


def convert_bgr_to_yuv(frame, width, height):
    # TODO: bgr => yuv
    return bytes([0]), bytes([0]), bytes([0])
