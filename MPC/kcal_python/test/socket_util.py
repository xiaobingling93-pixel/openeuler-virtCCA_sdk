# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import socket
import struct


def init_server(host: str, port: int) -> socket.socket:
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(1)
    print(f"Server listening on {host}:{port}")
    c, addr = server_socket.accept()
    print(f"{addr} connected")
    return c


def init_client(host: str, port: int) -> socket.socket:
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect((host, port))
    print(f"Connected to server {host}:{port}")
    return client_socket


def send_data(sock: socket.socket, data: memoryview) -> int:
    total_sent = 0
    data_len = len(data)

    sock.sendall(struct.pack('!I', data_len))

    while total_sent < data_len:
        sent = sock.send(data[total_sent:])
        if sent == 0:
            raise RuntimeError("Socket connection broken")
        total_sent += sent

    return 0


def recv_data(sock: socket.socket, buffer: memoryview) -> int:
    len_data = sock.recv(4)
    if not len_data:
        return 0

    data_len = struct.unpack('!I', len_data)[0]

    if data_len > len(buffer):
        raise ValueError(f"Buffer too small: {len(buffer)} < {data_len}")

    total_received = 0
    while total_received < data_len:
        remaining = data_len - total_received
        chunk = sock.recv(min(4096, remaining))
        if not chunk:
            raise RuntimeError("Socket connection broken")

        buffer[total_received:total_received + len(chunk)] = chunk
        total_received += len(chunk)

    return 0
