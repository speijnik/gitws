#!/usr/bin/env python

import logging
import os
import sys

from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler
try:
    from gitws.server import GitWSApp
except ImportError:
    # Try harder...
    sys.path.insert(0, 
                    os.path.join(os.path.abspath(
                os.path.dirname(__file__)), '..'))
    from gitws.server import GitWSApp

logging.basicConfig(level=logging.DEBUG)
App = GitWSApp(os.getcwd(), prefix='/gitws/')

def application(environ, start_response):
    return App(environ, start_response)

LOG = logging.getLogger('gitws.serve')

if __name__ == '__main__':
    LOG.info('Serving repository in %s via gitws.', os.getcwd())
    server = pywsgi.WSGIServer(('127.0.0.1', 8000), application,
                               handler_class=WebSocketHandler)
    server.serve_forever()
