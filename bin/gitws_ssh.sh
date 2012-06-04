#!/bin/bash

PTH=`dirname $0`/../gitws/
exec python "$PTH/client.py" "$@"
