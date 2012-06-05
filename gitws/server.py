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

import logging
import os
import os.path
import select
import subprocess
import fcntl

LOG = logging.getLogger('gitws.server')

def ws_send_error(ws, error):
    ws.send('%.4x\x02%s\n' % (len(error)+1, error))
    ws.close()

class RepositoryWSHandler(object):
    def __init__(self, environ, start_response, repo_path, ws, method):
        self._repo_path = repo_path
        self._ws = ws
        self._method = method
        self._environ = environ
        self._start_response = start_response

    def handle(self):
        if self._method == 'upload-pack':
            self.handleDownload()
        elif self._method == 'receive-pack':
            self.handleUpload()
        else:
            ws_send_error(self._ws, 'Unknown method %s.' % (self._method))

    def _setNonblocking(self, fd):
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        

    def handleDownload(self):
        p = subprocess.Popen(['git-upload-pack', self._repo_path], 
                             stdin=subprocess.PIPE, 
                             stdout=subprocess.PIPE, 
                             stderr=subprocess.PIPE,
                             close_fds=True)
        self._setNonblocking(p.stdout.fileno())
        self._setNonblocking(p.stderr.fileno())
        flags = fcntl.fcntl(self._ws.fobj.fileno(), fcntl.F_GETFL)
        fcntl.fcntl(self._ws.fobj.fileno(), fcntl.F_SETFL, 
                    flags | os.O_NONBLOCK)
        LOG.debug('[DOWNLOAD] Process spawned.')
        initial = True
        poller = select.poll()
        ws_fd = self._ws.fobj.fileno()
        poller.register(p.stdout.fileno(), select.POLLIN)
        poller.register(p.stderr.fileno(), select.POLLIN)
        poller.register(ws_fd, select.POLLIN|select.POLLHUP)
        exit_loop = False
        stdoutbuf = ''
        stderrbuf = ''
        while not exit_loop:
            for (fd, evmask) in poller.poll(100):
                if fd == p.stdout.fileno():
                    LOG.debug('Data on stdout...')
                    again = True
                    while again:
                        try:
                            data = p.stdout.read()
                            LOG.debug('Read from stdin: "%s"', data)
                            if not data:
                                again = False
                            else:
                                self._ws.send(data)
                        except IOError:
                            again = False
                elif fd == p.stderr.fileno():
                    LOG.debug('Data on stderr...')
                    stderrbuf += p.stderr.read()
                    while '\n' in stderrbuf:
                        data, stderrbuf = stderrbuf.split('\n', 1)
                        self._ws.send(data)
                        LOG.debug('Read from stderr: "%s"', data)
                elif fd == ws_fd:
                    LOG.debug('Event on WebSocket: %d (POLLIN=%d,POLLHUP=%d)',
                              evmask, select.POLLIN, select.POLLHUP)
                    if (evmask & select.POLLIN) > 0:
                        data = self._ws.receive()
                        LOG.debug('Received via WebSocket: "%s"', data)
                        if not data:
                            LOG.debug('Received empty datum from WebSocket.')
                            exit_loop = True
                            break
                        p.stdin.write(data)
                    elif (evmask & select.POLLHUP) > 0:
                        LOG.debug('WebSocket: HUP.')
                        exit_loop = True
                        break

            if p.poll() is not None:
                LOG.debug('Process exited (%d)', p.returncode)
                break

        LOG.debug('[DOWNLOAD] complete.')
        if not p.poll():
            try:
                p.terminate()
            except OSError:
                pass

    def handleUpload(self):
        ws_send_error(self._ws, 'Upload not implemented.')

class GitWSApp(object):
    def __init__(self, base_dir, prefix='/'):
        self._base_dir = os.path.abspath(base_dir)
        self._prefix = prefix
        LOG.debug(
            'GitWSApp initialized base_dir=%s, prefix=%s',
            self._base_dir, self._prefix)

    def __call__(self, environ, start_response):
        path = environ['PATH_INFO']
        if not path.startswith(self._prefix):
            LOG.error('Cannot handle path %s, prefix mismatch.',
                      path)
            start_response('501 Not implemented', 
                           [('context-type', 'text/plain')])
            return ['',]
        path = path[len(self._prefix):]
            
        if not environ.has_key('wsgi.websocket') or \
                not environ['wsgi.websocket']:
            # No websocket -> this won't work...
            LOG.error('Called without websocket active.')
            start_response('501 Not Implemented', 
                           [('content-type', 'text/plain')])
            return ['',]

        ws = environ['wsgi.websocket']

        repository = path
        LOG.debug('Access to repository %s requested.',
                  repository)

        if not ':' in repository:
            LOG.error('":" missing in path')
            ws_send_error(ws, '":" missing in path.')
            return

        repository, method = repository.split(':', 1)
        if method not in ('upload-pack', 'receive-pack'):
            LOG.error('Invalid method %s in path.',
                      method)
            ws_send_error(ws, 'Invalid method %s.' % (method))
            return

        # Norm path so one cannot escape the base dir
        repo_path = os.path.normpath(repository)
        LOG.debug('Repository path (normalized): %s', repo_path)

        repo_abspath = os.path.join(self._base_dir, repo_path)
        LOG.debug('Repository path (absolute): %s', repo_abspath)
        
        if os.path.exists(repo_abspath) and os.path.isdir(repo_abspath):
            # Everything fine, we are operating on a directory
            handler = RepositoryWSHandler(environ, start_response,
                                          repo_abspath, ws, method)
            handler.handle()
                                          
        else:
            LOG.error('Repository "%s" not found.', repo_path)
            ws_send_error(ws, 'Repository "%s" not found.' % (repo_path))
        


