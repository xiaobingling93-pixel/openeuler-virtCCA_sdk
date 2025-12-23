# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

"""
KCAL Python bindings.
"""
from __future__ import annotations
import collections.abc
import enum
from typing import List, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod

__all__: list[str] = [
    'AlgorithmsType',
    'TeeMode',
    'ShareType',
    'DummyMode',
    'Config',
    'Context',
    'Psi',
    'create_psi',
    'Pir',
    'create_pir',
    'MpcShare',
    'MakeShare',
    'create_make_share',
    'RevealShare',
    'create_reveal_share',
    'MpcOperatorBase',
    'create_mpc',
]


class AlgorithmsType(enum.IntEnum):
    ADD = 1
    SUB = 2
    MUL = 3
    DIV = 4
    LESS = 5
    LESS_EQUAL = 6
    GREATER = 7
    GREATER_EQUAL = 8
    EQUAL = 9
    NO_EQUAL = 10
    SUM = 11
    AVG = 12
    MAX = 13
    MIN = 14


class TeeMode(enum.IntEnum):
    OUTPUT_STRING = 0
    OUTPUT_INDEX = 1


class ShareType(enum.IntEnum):
    FIX_POINT = 0
    NON_FIX_POINT = 1


class DummyMode(enum.IntEnum):
    NORMAL = 0
    DUMMY = 1


@dataclass
class Config:
    useSMAlg: bool = False
    fixBits: int = 2
    nodeId: int = 0
    threadCount: int = 16
    worldSize: int = 2


class Context:
    @staticmethod
    def create(config: Config, send_func: collections.abc.Callable, recv_func: collections.abc.Callable) -> Context: ...


class Psi:
    def __init__(self, ctx: Context) -> None: ...

    def run(self, input: List[str], output: List[Any], tee_mode: TeeMode) -> int: ...


def create_psi(ctx: Context) -> Psi: ...


class Pir:
    def __init__(self, ctx: Context) -> None: ...

    def ServerPreProcess(self, keys: List[str], out_value: List[str]) -> int: ...

    def ClientQuery(self, input: List[str], out_value: List[str], dummy_mode: DummyMode) -> int: ...

    def ServerAnswer(self) -> int: ...


def create_pir(ctx: Context) -> Pir: ...


class MpcShare:
    def __init__(self) -> None: ...

    def size(self) -> int: ...

    def type(self) -> ShareType: ...


class MakeShare:
    def __init__(self, ctx: Context) -> None: ...

    def run(self, input: List[Any], is_recv_share: int, out_share: MpcShare) -> int: ...


def create_make_share(ctx: Context) -> MakeShare: ...


class RevealShare:
    def __init__(self, ctx: Context) -> None: ...

    def run(self, input_share: MpcShare, output: List[Any]) -> int: ...


def create_reveal_share(ctx: Context) -> RevealShare: ...


class MpcOperatorBase(ABC):
    def GetType(self) -> AlgorithmsType: ...

    @abstractmethod
    def run(self, shares: List[MpcShare], out_share: MpcShare) -> int: ...


def create_mpc(ctx: Context, type: AlgorithmsType) -> MpcOperatorBase: ...
