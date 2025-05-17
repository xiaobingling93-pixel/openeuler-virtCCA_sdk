#!/bin/bash
CUR_DIR=$(pwd)

ulimit -v $((8 * 1024 * 1024))
./src/build/mpc_demo 19009 19010 1 ./data/client.csv 1 127.0.0.1 127.0.0.1
echo $?
