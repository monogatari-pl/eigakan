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
import threading
import argparse
import cgi
import urlparse

import Queue
import commands
from multiprocessing.pool import ThreadPool

import signal

_id = '2018'
_output = 'c:/ffmpeg/test/htdocs/' + _id
_output_file = 'play.m3u8'
_input = 'c:/ffmpeg/test/1.mkv'
cmd2 = 'ffmpeg -hide_banner -i ' + _input
cmd2 += ' -c:v libx264 -x264opts keyint=500:no-scenecut -s 1280x720 -r 25 -b:v 3000000 -profile:v main -c:a aac'
cmd2 += ' -sws_flags bilinear -hls_time 10 -hls_segment_type mpegts -hls_allow_cache 0 -hls_list_size 0'
cmd2 += ' -live_start_index 0 -hls_flags +temp_file+program_date_time -hls_playlist_type event'
cmd2 += ' -hls_start_number_source generic -start_number 0 ' + _output + '/' + _output_file


class FFMPegRunner(object):

    re_duration = re.compile('Duration: (\d{2}):(\d{2}):(\d{2}).(\d{2})[^\d]*', re.U)
    re_position = re.compile('time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})\d*', re.U | re.I)
    pipe = None

    def __init__(self, output):
        self.cmd = ''
        self._stop = False
        self._output = output
        if not os.path.exists(self._output):
            os.makedirs(self._output)

    def run_session(self, command, status_handler=None):
        self.pipe = subprocess.Popen(command + self._output, shell=True,
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
        # percent = int(percent)
        # print(percent)
        return 100 if percent > 100 else percent

    def time2sec(self, search):
        x1 = int(search.group(3))
        x2 = int(search.group(2))
        x3 = int(search.group(1))
        x = x1 + (x2*60) + (x3*3600)
        return float(x)
        # time.sleep(10)

    bar = progressbar.ProgressBar()

    def status_handler(self, pos, dur):
        pos = int(pos)
        dur = int(dur)
        self.bar.max_value = dur
        self.bar.maxvalue = dur
        self.bar.update(pos)
        time.sleep(0.3)

    def run(self, _cmd):
        print('run')
        self.cmd = _cmd
        self.run_session(self.cmd, status_handler=self.status_handler)

    def shutdown(self):
        self._stop = True

    def status(self):
        if self.pipe is not None:
            return self.pipe.poll()


class LocalData(object):
    records = {}


class HTTPRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if re.search('/api/transode/*', self.path) is not None:
            ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
            if ctype == 'application/json':
                length = int(self.headers.getheader('content-length'))
                data = urlparse.parse_qs(self.rfile.read(length), keep_blank_values=1)
                record_id = self.path.split('/')[-1]
                if 'file' in data:
                    if os.path.exists(data['file'][0]):
                        output3 = 'c:/ffmpeg/test/htdocs/' + record_id
                        cmd3 = 'ffmpeg -hide_banner -i ' + data['file'][0]
                        cmd3 += ' -c:v libx264 -x264opts keyint=500:no-scenecut -s 1280x720 -r 25 -b:v 3000000 -profile:v main -c:a aac'
                        cmd3 += ' -sws_flags bilinear -hls_time 10 -hls_segment_type mpegts -hls_allow_cache 0 -hls_list_size 0'
                        cmd3 += ' -live_start_index 0 -hls_flags +temp_file+program_date_time -hls_playlist_type event'
                        cmd3 += ' -hls_start_number_source generic -start_number 0 '

                        output_file = os.path.join(output3, _output_file)
                        worker = Worker(cmd3, output_file)
                        worker.start()
                        # worker.join()

                        while not os.path.exists(output_file):
                            time.sleep(2)

                        LocalData.records[record_id] = output_file
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
        if re.search('/api/transode/*', self.path) is not None:
            record_id = self.path.split('/')[-1]
            if record_id in LocalData.records:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write("{\"file\":\"" + LocalData.records[record_id] + "\"}")
            else:
                self.send_response(400, 'Bad Request: record does not exist')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
        else:
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            return


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True

    def shutdown(self):
        self.socket.close()
        HTTPServer.shutdown(self)


class SimpleHttpServer:
    def __init__(self, ip, port):
        self.server = ThreadedHTTPServer((ip, port), HTTPRequestHandler)
        self.server_thread = None

    def start(self):
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()

    def waitForThread(self):
        self.server_thread.join()

    def addRecord(self, recordID, jsonEncodedRecord):
        LocalData.records[recordID] = jsonEncodedRecord

    def stop(self):
        self.server.shutdown()
        self.waitForThread()


class Worker(threading.Thread):
    def __init__(self, _cmd, _output):  # , queue):
        threading.Thread.__init__(self)
        self.server_thread = None
        self.cmd = _cmd
        # self.queue = queue
        self.runner = FFMPegRunner(_output)

    def run(self):
        self.server_thread = threading.Thread(target=self.runner.run(self.cmd))
        # self.queue.put((self.cmd, self.server_thread))
        self.server_thread.daemon = False
        self.server_thread.start()

    def waitForThread(self):
        self.server_thread.join()

    def stop(self):
        self.runner.shutdown()
        # self.waitForThread()

    def status(self):
        self.runner.status()


# result_queue = Queue.Queue()

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
