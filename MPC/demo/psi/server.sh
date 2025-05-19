#!/bin/bash

ulimit -v $((8 * 1024 * 1024))
./src/build/mpc_demo 19010 19009 0 ./data/server.csv 0 127.0.0.1 127.0.0.1
echo $?



