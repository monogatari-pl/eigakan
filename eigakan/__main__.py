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

import urllib2


class FFMPegRunner(object):

    re_duration = re.compile('Duration: (\d{2}):(\d{2}):(\d{2}).(\d{2})[^\d]*', re.U)
    re_position = re.compile('time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})\d*', re.U | re.I)
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
                                     stdin=subprocess.PIPE)

        duration = None
        position = None
        percents = 0

        while True:
            if self._stop:
                if self.pipe is not None:
                    self.pipe.communicate(input=b'q')
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

    def shutdown(self):
        self._stop = True

    def status(self):
        if self.pipe is not None:
            return self.pipe.poll()


class LocalData(object):
    records = {}


local_data = LocalData
app = Flask(__name__, static_url_path='')
worker = None


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


@app.route('/api/video/<path:path>')
def do_get(path):
    return send_from_directory(args.root_dir, path)


@app.route('/api/transcode/<path:path>', methods=['GET', 'POST'])
def transcode(path):
    if request.method == 'POST':
        data = request.get_json(silent=True)
        record_id = path
        process_file = False
        if 'file' in data:
            file_place = data['file']
            if "http:" in file_place:
                try:
                    urllib2.urlopen(file_place)
                    process_file = True
                except urllib2.HTTPError, e:
                    print(e.code)
                except urllib2.URLError, e:
                    print(e.args)
            else:
                if os.path.exists(file_place):
                    process_file = True
                else:
                    print "file 404"
                    print(str(data))

            if process_file:
                cmd3 = 'ffmpeg -hide_banner -i ' + '"' + file_place + '"'
                cmd3 += ' -c:v libx264 -x264opts keyint=500:no-scenecut -s 1280x720 -r 25 -b:v 3000000 -profile:v main -c:a aac'
                cmd3 += ' -sws_flags bilinear -hls_time 10 -hls_segment_type mpegts -hls_allow_cache 0 -hls_list_size 0'
                cmd3 += ' -live_start_index 0 -hls_flags +temp_file+program_date_time -hls_playlist_type event'
                cmd3 += ' -hls_start_number_source generic -hls_base_url ' + request.host_url + 'api/video/' + str(record_id) + '/ -start_number 0 '

                output3 = args.root_dir + record_id
                output_file = os.path.join(output3, 'play.m3u8')

                if os.path.exists(output3):
                    shutil.rmtree(output3)

                worker = Worker(cmd3, output_file)
                worker.start()

                while not os.path.exists(output_file):
                    time.sleep(2)

                local_data.records[record_id] = output_file
                print "record %s is added successfully" % record_id
                return jsonify(record_id=record_id)
        else:
            print "no file in json"

    elif request.method == 'GET':
        if path in local_data.records:
            return jsonify(file=local_data.records[path])


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
    args = parser.parse_args()

    # http-server
    app.run(host=args.ip, port=str(args.port), threaded=True)

# TODO support stoping transcode via GET/POST
# TODO resolve: socket.py", line 307, in flush self._sock.sendall(view[write_offset:write_offset+buffer_size])