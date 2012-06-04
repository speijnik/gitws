#!/bin/bash

PTH=`dirname $0`
exec python "$PTH/client.py" "$@"
