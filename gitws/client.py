# Copyright (C) 2012 Stephan Peijnik
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import fcntl
import logging
import os
import select
import socket
import sys

SUPPORTED_PROTOCOLS = ('ws', 'wss')
EXIT_OK = 0
EXIT_PROTO_UNSUPPORTED = 1
EXIT_SERVICE_UNSUPPORTED = 2
EXIT_CONNECTION_FAILED = 3
EXIT_INTERNAL_ERROR = 255

def writeError(msg, *args):
    message = msg % args
    sys.stderr.write('fatal: %s\n' % (message))
    sys.stderr.flush()

try:
    import websocket
except ImportError:
    writeError('websocket Python package is missing.')
    sys.exit(EXIT_INTERNAL_ERROR)

LOG = logging.getLogger('gitws.client')

class Client(object):
    def __init__(self, uri):
        self._uri = uri
        self._protocol, unused = self._uri.split('://', 1)

    def getServiceMethod(self):
        if not os.environ.has_key('GIT_EXT_SERVICE_NOPREFIX'):
            writeError('GIT_EXT_SERVICE_NOPREFIX environment variable not set.')
            sys.exit(EXIT_SERVICE_UNSUPPORTED)
        serviceName = os.environ['GIT_EXT_SERVICE_NOPREFIX']
        serviceName = serviceName[0].upper() + serviceName[1:]
        while '-' in serviceName:
            idx = serviceName.index('-')
            serviceName = serviceName[0:idx] + serviceName[idx+1:]
            serviceName = serviceName[0:idx] + serviceName[idx].upper() \
                + serviceName[idx+1:]
        methodName = 'handle%s' % (serviceName)
        LOG.debug('Service handler method name: %s.', methodName)
        method = getattr(self, methodName, None)
        if not method or not callable(method):
            writeError('Service %s is not supported.', 
                       os.environ['GIT_EXT_SERVICE_NOPREFIX'])
            sys.exit(EXIT_SERVICE_UNSUPPORTED)
        return method

    def run(self):
        if self._protocol not in SUPPORTED_PROTOCOLS:
            writeError('Unsupported protocol "%s".', self._protocol)
            writeError('argv: %r', sys.argv)
            return EXIT_PROTO_UNSUPPORTED
        method = self.getServiceMethod()
        LOG.debug('Service handler method: %r.', method)
        return method(self._protocol, self._uri)

    def setNonblocking(self, fd):
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def handleUploadPack(self, protocol, uri):
        full_uri = uri + ':upload-pack'
        poll = select.poll()
        self.setNonblocking(sys.stdin.fileno())
        self.ws = None
        try:
            LOG.debug('Connecting to %s...', full_uri)
            self.ws = websocket.create_connection(full_uri)
        except socket.error, e:
            LOG.error('Connection failed: %s', e)
            writeError('Connection failed: %s', e)
            return EXIT_CONNECTION_FAILED
        LOG.debug('websocket connection established.')
        self.setNonblocking(self.ws.sock.fileno())
        LOG.debug('stdin and websocket set nonblocking.')

        fdHandlers = {sys.stdin.fileno(): self.stdinHandler,
                      self.ws.sock.fileno(): self.websocketHandler}
        poll.register(sys.stdin.fileno(), select.POLLIN|select.POLLHUP)
        poll.register(self.ws.sock.fileno(), select.POLLIN|select.POLLHUP)
        
        connection_closed = False
        while not connection_closed:
            for (fd, event) in poll.poll(200):
                if not fdHandlers[fd](event):
                    LOG.debug('Connection closed by FD handler %r.',
                              fdHandlers[fd])
                    connection_closed = True
        
        return EXIT_OK

    def stdinHandler(self, event):
        if (event & select.POLLIN) > 0:
            data = sys.stdin.read()
            if not data:
                LOG.debug('[STDIN] Received empty data, possibly closed.')
                return False
            LOG.debug('[STDIN] "%s"', data)
            self.ws.send(data)

        if (event & select.POLLHUP) > 0:
            LOG.debug('[STDIN] closed. Closing websocket connection.')
            self.ws.close()
            return False
        
        if (event & (select.POLLHUP|select.POLLIN)) == 0:
            LOG.debug('[STDIN] Unknown event %s.', event)
            return False

        return True

    def websocketHandler(self, event):
        if (event & select.POLLIN) > 0:
            try:
                data = self.ws.recv()
                if not data:
                    LOG.debug('[WebSocket] Received empty data, connection closed.')
                    return False
                LOG.debug('[WebSocket] "%s"', data)
                sys.stdout.write(data)
                sys.stdout.flush()
            except websocket.WebSocketException:
                LOG.debug('[WebSocket] Exception during recv, assuming connection closed.')
                return False

        if (event & select.POLLHUP) > 0:
            LOG.debug('WebSocket closed. Closing stdin.')
            sys.stdin.close()
            return False

        if (event & (select.POLLIN|select.POLLHUP)) == 0:
            LOG.debug('[WebSocket] Unknown event %s.', event)
            return False
        return True
        
