#!/usr/bin/env python
# -*- coding: utf-8 -*-

import subprocess
import re
import time
import math
import progressbar
import os

from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from SocketServer import ThreadingMixIn
import mimetypes as memetypes

import threading
import argparse
import cgi
import json

import shutil

_output_file = 'play.m3u8'
_output_dir = 'c:/ffmpeg/test/htdocs/'


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
        ffmpeg_command = str(ffmpeg_command).replace('\\','/')
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


class HTTPRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if re.search('/api/transcode/*', self.path) is not None:
            ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
            if ctype == 'application/json' or ctype == 'text/json':
                length = int(self.headers.getheader('content-length'))
                # data = urlparse.parse_qs(self.rfile.read(length), keep_blank_values=1)
                json_body = self.rfile.read(length)
                data = json.loads(json_body)
                record_id = self.path.split('/')[-1]
                if 'file' in data:
                    file_place = data['file']
                    if os.path.exists(file_place):
                        cmd3 = 'ffmpeg -hide_banner -i ' + '"' + file_place + '"'
                        cmd3 += ' -c:v libx264 -x264opts keyint=500:no-scenecut -s 1280x720 -r 25 -b:v 3000000 -profile:v main -c:a aac'
                        cmd3 += ' -sws_flags bilinear -hls_time 10 -hls_segment_type mpegts -hls_allow_cache 0 -hls_list_size 0'
                        cmd3 += ' -live_start_index 0 -hls_flags +temp_file+program_date_time -hls_playlist_type event'
                        cmd3 += ' -hls_start_number_source generic -start_number 0 '

                        output3 = _output_dir + record_id
                        output_file = os.path.join(output3, _output_file)

                        if os.path.exists(output3):
                            shutil.rmtree(output3)

                        worker = Worker(cmd3, output_file)
                        worker.start()

                        while not os.path.exists(output_file):
                            time.sleep(2)

                        local_data.records[record_id] = output_file
                        print "record %s is added successfully" % record_id

                        self.send_response(200)
                        self.end_headers()
                    else:
                        print "file 404"
                else:
                    print "no file in json"
            else:
                data = {}
                self.send_response(200)
                self.end_headers()
        else:
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            return

    def do_GET(self):
        print("get:" + str(self.path))
        if re.search('/api/transcode/*', self.path) is not None:
            record_id = self.path.split('/')[-1]
            if record_id in local_data.records:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write("{\"file\":\"" + LocalData.records[record_id] + "\"}")
            else:
                self.send_response(400, 'Bad Request: record does not exist')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
        elif re.search('/api/video/*', self.path) is not None:
            record_id = self.path.split('/')[-2]
            file = self.path.split('/')[-1]
            if self.path.endswith(".m3u8") or self.path.endswith(".ts") or self.path.endswith(".vtt"):
                file_path = os.path.join(os.path.join(_output_dir, record_id), file)
                content, encoding = memetypes.MimeTypes().guess_type(file_path)
                if content is None:
                    content = "application/octet-stream"
                f = open(file_path, 'rb')
                self.send_response(200)
                self.send_header('Content-type', content)
                self.end_headers()
                shutil.copyfileobj(f, self.wfile)
                f.close()
        else:
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            return

    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("content-type", "text/plain;charset=utf-8")
        self.end_headers()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True

    def shutdown(self):
        self.socket.close()
        HTTPServer.shutdown(self)


class SimpleHttpServer:
    def __init__(self, ip, port):
        self.server = ThreadedHTTPServer((ip, port), HTTPRequestHandler)
        # self.server = HTTPServer((ip, port), HTTPRequestHandler)
        self.server_thread = None

    def start(self):
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()

    def waitForThread(self):
        self.server_thread.join()

    # def addRecord(self, recordID, jsonEncodedRecord):
    #    LocalData.records[recordID] = jsonEncodedRecord

    def stop(self):
        self.server.shutdown()
        self.waitForThread()


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


if __name__ == "__main__":
    print('eigakan')

    # http-server
    parser = argparse.ArgumentParser(description='HTTP Server')
    parser.add_argument('port', type=int, help='Listening port for HTTP Server')
    parser.add_argument('ip', help='HTTP Server IP')
    args = parser.parse_args()

    server = SimpleHttpServer(args.ip, args.port)
    print 'HTTP Server Running...........'

    server.start()
    server.waitForThread()
