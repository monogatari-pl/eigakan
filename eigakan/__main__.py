#!/usr/bin/env python
# -*- coding: utf-8 -*-

from flask import Flask, request, send_from_directory, jsonify

import subprocess
import re
import time
import math
import progressbar
import os

import mimetypes

import threading
import argparse

import shutil

import urllib3


__version__ = 0.8


class GenerateM3U8(object):
    def __init__(self):
        self._stop = False

    def run_session(self, m3u8_path):
        # new m3u8
        m3u8 = os.path.join(m3u8_path, 'play_me.m3u8')
        index = 0
        make_file = True
        while True:
            if self._stop:
                break

            # new m3u8
            if make_file:
                f = open(m3u8, 'a')
                lines = [
                        '#EXTM3U\r',
                        '#EXT-X-VERSION:7\r',
                        '#EXT-X-ALLOW-CACHE:NO\r',
                        '#EXT-X-TARGETDURATION:20\r',
                        #'#EXT-X-MEDIA-SEQUENCE:0\r',
                        #'#EXT-X-PLAYLIST-TYPE:EVENT\r',
                        '#EXT-X-INDEPENDENT-SEGMENTS\r',
                        '#EXT-X-START:TIME-OFFSET=20.0,PRECISE=YES\r'
                ]
                f.writelines(lines)
                f.close()
                make_file = False

            if os.path.exists(os.path.join(m3u8_path, 'play' + str(index) + '.ts')):
                f = open(m3u8, 'a')
                lines = [
                        '#EXTINF:20.000000,\r',
                        'http://127.0.0.1:8000/api/video/15137/play' + str(index) + '.ts\r'
                        ]
                f.writelines(lines)
                f.close()
                index += 1
            else:
                time.sleep(1)

    def run(self, m3u8_path):
        self.run_session(m3u8_path)
        print('running m38u')

    def stop(self):
        self._stop = True

    def shutdown(self):
        self._stop = True

    def status(self):
        if self._stop:
            print('stopped')
        else:
            print('running strong')


class FFMPegRunner(object):
    re_duration = re.compile('Duration: (\\d{2}):(\\d{2}):(\\d{2}).(\\d{2})[^\\d]*', re.U)
    re_position = re.compile('time=(\\d{2}):(\\d{2}):(\\d{2}).(\\d{2})\\d*', re.U | re.I)
    pipe = None

    def __init__(self, command, output):
        self.cmd = command
        self._stop = False
        self._output = output
        basepath = os.path.dirname(self._output)
        if not os.path.exists(basepath):
            os.makedirs(basepath)

    def run_session(self, command, status_handler=None):
        ffmpeg_command = command + self._output
        ffmpeg_command = str(ffmpeg_command).replace('\\', '/')
        print(ffmpeg_command)
        self.pipe = subprocess.Popen(ffmpeg_command, shell=True,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT,
                                     universal_newlines=True,
                                     encoding="utf-8",
                                     errors='ignore',
                                     stdin=subprocess.PIPE)
        duration = None
        position = None
        percents = 0

        while True:
            if self._stop:
                if self.pipe is not None:
                    self.pipe.communicate(input='q')
                    time.sleep(2)
                    break

            line = self.pipe.stdout.readline().strip()

            if line == '' and self.pipe.poll() is not None:
                break

            if duration is None:
                duration_match = self.re_duration.match(line)
                if duration_match:
                    duration = self.time2sec(duration_match)

            if duration:
                position_match = self.re_position.search(line)
                if position_match:
                    position = self.time2sec(position_match)

            new_percents = self.get_percent(position, duration)

            if new_percents != percents:
                if callable(status_handler):
                    status_handler(position, duration)
                percents = new_percents

    def get_percent(self, position, duration):
        if not position or not duration:
            return 0
        percent = 100 * position / duration
        percent = math.floor(percent*1000)
        percent = percent / 1000
        return 100 if percent > 100 else percent

    def time2sec(self, search):
        x1 = int(search.group(3))
        x2 = int(search.group(2))
        x3 = int(search.group(1))
        x = x1 + (x2*60) + (x3*3600)
        return float(x)

    bar = progressbar.ProgressBar()

    def status_handler(self, pos, dur):
        pos = int(pos)
        dur = int(dur)
        self.bar.max_value = dur
        self.bar.maxvalue = dur
        self.bar.update(pos)
        time.sleep(0.3)

    def run(self, _cmd):
        self.cmd = _cmd
        self.run_session(self.cmd, status_handler=self.status_handler)
        print('running')

    def stop(self):
        self._stop = True

    def shutdown(self):
        self._stop = True

    def status(self):
        if self.pipe is not None:
            return self.pipe.poll()


class LocalData(object):
    records = {}


local_data = LocalData
app = Flask(__name__, static_url_path='')


class WorkerM3U8(threading.Thread):
    def __init__(self, _path):  # , queue):
        threading.Thread.__init__(self)
        self._path = _path
        self.server_thread = None
        self.runner = GenerateM3U8()

    def run(self):
        self.server_thread = threading.Thread(target=self.runner.run(self._path))
        self.server_thread.daemon = False
        self.server_thread.start()

    def waitForThread(self):
        self.server_thread.join()

    def stop(self):
        self.runner.shutdown()

    def status(self):
        self.runner.status()


class Worker(threading.Thread):
    def __init__(self, _cmd, _output):  # , queue):
        threading.Thread.__init__(self)
        self.server_thread = None
        self.cmd = _cmd
        self.runner = FFMPegRunner(_cmd, _output)

    def run(self):
        self.server_thread = threading.Thread(target=self.runner.run(self.cmd))
        self.server_thread.daemon = False
        self.server_thread.start()

    def waitForThread(self):
        self.server_thread.join()

    def stop(self):
        self.runner.shutdown()

    def status(self):
        self.runner.status()


@app.route('/api/version')
def get_version():
    return jsonify(eigakan=__version__)


@app.route('/api/video/<path:path>')
def do_get(path):
    return send_from_directory(args.root_dir, path)


@app.route('/api/transcode/<path:path>', methods=['GET', 'POST'])
def transcode(path):
    if request.method == 'POST':
        data = request.get_json(silent=True)
        record_id = path
        process_file = False

        resolution = '1280x720'
        audio_coded = 'aac'
        video_bitrate = '3000000'
        x264_profile = 'main'
        audio_stream = '-1'
        subtitles_stream = '-1'

        if 'resolution' in data:
            resolution = data['resolution']
        if 'audio_coded' in data:
            audio_coded = data['audio_coded']
        if 'video_bitrate' in data:
            video_bitrate = data['video_bitrate']
        if 'x264_profile' in data:
            x264_profile = data['x264_profile']
        if 'audio_stream' in data:
            audio_stream = data['audio_stream']
        if 'subtitles_stream' in data:
            subtitles_stream = data['subtitles_stream']

        if 'file' in data:
            file_place = data['file']
            if "http:" in file_place:
                http = urllib3.PoolManager()
                try:
                    http.request('HEAD', file_place)
                    process_file = True
                except urllib3.exceptions.HTTPError as e:
                    print(e)
            else:
                if os.path.exists(file_place):
                    process_file = True
                else:
                    print("file 404")
                    print(str(data))

            if process_file:
                cmd3 = args.ffmpeg_path
                cmd3 += ' -hide_banner -i ' + '"' + file_place + '"'
                # this will only work with bitmap subttiles, other should use -subtitles
                # but subtitles don't like http:// url for subtitles embeded inside file
                if subtitles_stream != '-1':
                    cmd3 += ' -filter_complex "[0:v][0:s:' + subtitles_stream + ']overlay[v]" -map "[v]"'
                if audio_stream != '-1':
                    cmd3 += ' -map 0:a:' + audio_stream
                cmd3 += ' -c:v libx264 -x264opts keyint=500:no-scenecut -s ' + resolution
                cmd3 += ' -r 25 -b:v ' + video_bitrate + ' -profile:v ' + x264_profile + ' -c:a ' + audio_coded
                cmd3 += ' -sws_flags bilinear'
                # HLS settings
                cmd3 += ' -hls_time 10'
                cmd3 += ' -hls_segment_type mpegts'
                # cmd3 += ' -hls_segment_type fmp4'  # hls v7 add info about version from 3 to 7 # wont play
                cmd3 += ' -hls_allow_cache 0'
                cmd3 += ' -hls_list_size 0'
                # cmd3 += ' -live_start_index '  # demuxer option
                cmd3 += ' -hls_flags +temp_file'
                # cmd3 += '+program_date_time'
                cmd3 += '+append_list'
                cmd3 += '+independent_segments'  # boost version to 6 !
                # cmd3 += '+round_durations'
                # cmd3 += '+omit_endlist'
                cmd3 += ' -hls_playlist_type event'
                # cmd3 += ' -hls_playlist_type vod'
                cmd3 += ' -hls_start_number_source generic'
                cmd3 += ' -start_number 0'
                cmd3 += ' -hls_base_url ' + request.host_url + 'api/video/' + str(record_id) + '/ '

                output3 = args.root_dir + '/' + record_id
                output_file = os.path.join(output3, 'play.m3u8')

                if os.path.exists(output3):
                    try:
                        shutil.rmtree(output3)
                    except:
                        print('we didnt not clean {}, something use it while we tried'.format(output3))
                else:
                    os.mkdir(output3)

                worker = Worker(cmd3, output_file)
                worker.start()

                worker2 = WorkerM3U8(output3)
                worker2.start()

                while not os.path.exists(output_file):
                    time.sleep(2)

                local_data.records[record_id] = worker
                print("record %s is added successfully" % record_id)

                while not os.path.exists(output_file):
                    time.sleep(1)

                return jsonify(record_id=record_id)
        else:
            print("no file in json")

    elif request.method == 'GET':
        if path in local_data.records:
            return jsonify(file=local_data.records[path])


@app.route('/api/transcode/<path:path>/cancel', methods=['GET'])
def cancel_transcode(path):
    if path in local_data.records:
        worker = local_data.records[path]
        worker.stop()
        # worker.waitForThread()
        local_data.records.pop(path, None)
        return jsonify(action='cancel')


if __name__ == "__main__":
    print('eigakan')

    # mime support
    mimetypes.init()
    mimetypes.add_type('application/x-mpegurl', '.m3u8', strict=False)
    mimetypes.add_type('video/mp2t ', '.ts', strict=False)
    mimetypes.add_type('text/vtt', '.vtt', strict=False)

    # arguments
    parser = argparse.ArgumentParser(description='HTTP Server')
    parser.add_argument('port', type=int, help='Listening port for HTTP Server')
    parser.add_argument('ip', help='HTTP Server IP')
    parser.add_argument('root_dir', help='Directory to serve inside http server')
    parser.add_argument('ffmpeg_path', help='Path to ffmpeg')
    args = parser.parse_args()

    if shutil.which('ffmpeg') or os.path.exists(args.ffmpeg_path)is not None:
        # http-server
        app.run(host=args.ip, port=str(args.port), threaded=True)
    else:
        print("ffmpeg cannot be found")

# TODO resolve: socket.py", line 307, in flush self._sock.sendall(view[write_offset:write_offset+buffer_size])
# TODO add support to hardsubing with parameter of which subs to pick based on metadata from external source (nakamori -> shoko)
