#!/usr/bin/env python

import sys
import fcntl
import os
import logging
import select
import websocket
import threading

HELPER=os.path.join(os.path.abspath(os.path.dirname(__file__)), 'helper.py')

LOG = logging.getLogger('gitws.client')

class WSClient(websocket.WebSocketApp):
    def __init__(self, uri, method):
        if not uri.endswith('/'):
            uri = uri + '/'
        self._uri = uri
        self._method = method
        if method not in ('download', 'upload'):
            raise Exception('Invalid method %s.' % (method))
            
        self._uri_full = uri + ':' + method
        self._closed = False
        websocket.WebSocketApp.__init__(self, self._uri_full,
                                        on_error = self._on_error,
                                        on_close = self._on_close,
                                        on_message = self._on_message)
        LOG.debug('Client created, full uri is %s.', self._uri_full)

    def run(self):
        if self._method == 'download':
            return self.run_download()
        elif self._method == 'upload':
            return self.run_upload()

    def run_download(self):
        self.on_open = self.on_open_download
        self.run_forever()

    def run_upload(self):
        raise NotImplementedError
        #self.on_open = self.on_open_download
        #self.run_forever()

    def _on_message(self, ws, message):
        if not message:
            message = ''
        LOG.debug('WebSocket: "%s"', message)
        sys.stdout.write(message)
        sys.stdout.flush()

    def _on_error(self, ws, error):
        LOG.error('WebSocket error: %s', error)
        ws.close()

    def _on_close(self, ws):
        LOG.debug('Connection to %s closed.', self._uri_full)
        self._closed = True

    def on_open_download(self, ws):
        LOG.debug('Connection to %s opened, DOWNLOAD mode.', self._uri_full)
        self._closed = False
        t = threading.Thread(target=self.reader_main)
        t.start()
    
    def reader_main(self):
        LOG.debug('Reader thread has started...')
        flags = fcntl.fcntl(sys.stdin.fileno(), fcntl.F_GETFL)
        fcntl.fcntl(sys.stdin.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)
        while not self._closed:
            try:
                data = sys.stdin.read()
                LOG.debug('Data on stdin: "%s"', data)
                if data:
                    self.send(data)
                else:
                    break
            except IOError:
                pass
        LOG.debug('Connection closed.')
        if self.sock:
            self.close()
    

class Client(object):
    def __init__(self, uri):
        LOG.debug('Client for initialized (uri=%s).', uri)
        self._uri = uri

    def download(self):
        c = WSClient(self._uri, 'download')
        c.run()

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, filename='client.log')
    host = sys.argv[1]
    port = 8000
    if '@' in host:
        port, host = host.split('@', 1)
    repo_data = sys.argv[2].split(' ')
    repo = repo_data[1][1:-1]
    LOG.debug('Config: %r' % sys.argv)
    method = None
    if repo_data[0] == 'git-upload-pack':
        method = 'download'
    else:
        sys.stderr.write('fatal: Cannot detect method from %s.' \
                             % (repo_data[0]))
        sys.exit(1)
        
    c = Client('ws://%s:%s/%s' % (host, port, repo))
    meth = getattr(c, method, None)
    if meth and callable(meth):
        meth()
    else:
        sys.stderr.write('fatal: Method %s not supported.', method)
        sys.exit(2)
    
