# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from __future__ import annotations

import socket
import sys

import kcal
import argparse

import socket_util

_client_socket = None
_server_socket = None

"""
server:
    nodeId: 0
    socket: _client_socket
client:
    nodeId: 1
    socket: _server_socket
"""


def get_fd(node_info: dict) -> socket.socket:
    return _server_socket if node_info['nodeId'] == 0 else _client_socket


def on_send_data(node_info: dict, data_buffer: memoryview) -> int:
    s = get_fd(node_info)
    return socket_util.send_data(s, data_buffer)


def on_recv_data(node_info: dict, buffer: memoryview) -> int:
    s = get_fd(node_info)
    return socket_util.recv_data(s, buffer)


def psi_demo(is_server: bool):
    config = kcal.Config()
    config.nodeId = 0 if is_server else 1
    config.worldSize = 2
    config.fixBits = 2
    config.threadCount = 32
    config.useSMAlg = False

    context = kcal.Context.create(config, on_send_data, on_recv_data)

    op = kcal.create_psi(context)

    input0 = ["4", "3", "2", "1"]
    input1 = ["1", "3", "4", "5"]
    output = []
    import time
    start_time = time.time()
    if is_server:
        op.run(input0, output, kcal.TeeMode.OUTPUT_STRING)
    else:
        op.run(input1, output, kcal.TeeMode.OUTPUT_STRING)
    print(output)
    end_time = time.time()
    duration_ms = (end_time - start_time) * 1000  # ms
    print(f"run cost: {duration_ms:.2f} ms")


def main(argv=None):
    parser = argparse.ArgumentParser(description="KCAL python wrapper demo.")
    try:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--server", action="store_true", default=False, help="start server")
        group.add_argument("--client", action="store_true", default=False, help="start client")
        parser.add_argument("--host", type=str, default="127.0.0.1")
        parser.add_argument("-p", "--port", type=int, required=True)
        args = parser.parse_args(argv)
    except argparse.ArgumentParser:
        parser.print_help()
        sys.exit(1)

    global _client_socket, _server_socket
    if args.server:
        _client_socket = socket_util.init_server(args.host, args.port)
        psi_demo(True)
        _client_socket.close()
    elif args.client:
        _server_socket = socket_util.init_client(args.host, args.port)
        psi_demo(False)
        _server_socket.close()


if __name__ == "__main__":
    main()
