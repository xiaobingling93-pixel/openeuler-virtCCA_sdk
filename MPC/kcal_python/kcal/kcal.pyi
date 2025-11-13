# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

"""
KCAL Python bindings.
"""
from __future__ import annotations
import collections.abc
import typing

__all__: list[str] = ['ADD', 'AVG', 'Add', 'AlgorithmsType', 'Arithmetic', 'Avg', 'BuildDgString', 'Config', 'Context',
                      'ContextBase', 'DIV', 'DUMMY', 'Div', 'DummyMode', 'EQUAL', 'Equal', 'FIX_POINT', 'GREATER',
                      'GREATER_EQUAL', 'Greater', 'GreaterEqual', 'Input', 'IsOperatorRegistered', 'LESS', 'LESS_EQUAL',
                      'Less', 'LessEqual', 'MAKE_SHARE', 'MAX', 'MIN', 'MUL', 'MakeShare', 'Max', 'Min', 'MpcShare',
                      'MpcShareSet', 'Mul', 'NON_FIX_POINT', 'NORMAL', 'NO_EQUAL', 'NoEqual', 'OUTPUT_INDEX',
                      'OUTPUT_STRING', 'OperatorBase', 'Output', 'PIR', 'PSI', 'Pir', 'Psi', 'REVEAL_SHARE',
                      'RegisterAllOps', 'ReleaseMpcShare', 'ReleaseOutput', 'RevealShare', 'SUB', 'SUM', 'ShareType', 'Sub',
                      'Sum', 'TeeMode', 'TeeNodeInfo', 'create_operator']


class Add(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class AlgorithmsType:
    """
    Members:
    
      PSI
    
      PIR
    
      MAKE_SHARE
    
      REVEAL_SHARE
    
      ADD
    
      SUB
    
      MUL
    
      DIV
    
      LESS
    
      LESS_EQUAL
    
      GREATER
    
      GREATER_EQUAL
    
      EQUAL
    
      NO_EQUAL
    
      SUM
    
      AVG
    
      MAX
    
      MIN
    """
    ADD: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.ADD: 5>
    AVG: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.AVG: 16>
    DIV: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.DIV: 8>
    EQUAL: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.EQUAL: 13>
    GREATER: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.GREATER: 11>
    GREATER_EQUAL: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.GREATER_EQUAL: 12>
    LESS: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.LESS: 9>
    LESS_EQUAL: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.LESS_EQUAL: 10>
    MAKE_SHARE: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.MAKE_SHARE: 3>
    MAX: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.MAX: 17>
    MIN: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.MIN: 18>
    MUL: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.MUL: 7>
    NO_EQUAL: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.NO_EQUAL: 14>
    PIR: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.PIR: 1>
    PSI: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.PSI: 0>
    REVEAL_SHARE: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.REVEAL_SHARE: 4>
    SUB: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.SUB: 6>
    SUM: typing.ClassVar[AlgorithmsType]  # value = <AlgorithmsType.SUM: 15>
    __members__: typing.ClassVar[dict[
        str, AlgorithmsType]]  # value = {'PSI': <AlgorithmsType.PSI: 0>, 'PIR': <AlgorithmsType.PIR: 1>, 'MAKE_SHARE': <AlgorithmsType.MAKE_SHARE: 3>, 'REVEAL_SHARE': <AlgorithmsType.REVEAL_SHARE: 4>, 'ADD': <AlgorithmsType.ADD: 5>, 'SUB': <AlgorithmsType.SUB: 6>, 'MUL': <AlgorithmsType.MUL: 7>, 'DIV': <AlgorithmsType.DIV: 8>, 'LESS': <AlgorithmsType.LESS: 9>, 'LESS_EQUAL': <AlgorithmsType.LESS_EQUAL: 10>, 'GREATER': <AlgorithmsType.GREATER: 11>, 'GREATER_EQUAL': <AlgorithmsType.GREATER_EQUAL: 12>, 'EQUAL': <AlgorithmsType.EQUAL: 13>, 'NO_EQUAL': <AlgorithmsType.NO_EQUAL: 14>, 'SUM': <AlgorithmsType.SUM: 15>, 'AVG': <AlgorithmsType.AVG: 16>, 'MAX': <AlgorithmsType.MAX: 17>, 'MIN': <AlgorithmsType.MIN: 18>}

    def __eq__(self, other: typing.Any) -> bool:
        ...

    def __getstate__(self) -> int:
        ...

    def __hash__(self) -> int:
        ...

    def __index__(self) -> int:
        ...

    def __init__(self, value: typing.SupportsInt) -> None:
        ...

    def __int__(self) -> int:
        ...

    def __ne__(self, other: typing.Any) -> bool:
        ...

    def __repr__(self) -> str:
        ...

    def __setstate__(self, state: typing.SupportsInt) -> None:
        ...

    def __str__(self) -> str:
        ...

    @property
    def name(self) -> str:
        ...

    @property
    def value(self) -> int:
        ...


class Arithmetic(OperatorBase):
    pass


class Avg(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class Config:
    useSMAlg: bool

    def __init__(self) -> None:
        ...

    @property
    def fixBits(self) -> int:
        ...

    @fixBits.setter
    def fixBits(self, arg0: typing.SupportsInt) -> None:
        ...

    @property
    def nodeId(self) -> int:
        ...

    @nodeId.setter
    def nodeId(self, arg0: typing.SupportsInt) -> None:
        ...

    @property
    def threadCount(self) -> int:
        ...

    @threadCount.setter
    def threadCount(self, arg0: typing.SupportsInt) -> None:
        ...

    @property
    def worldSize(self) -> int:
        ...

    @worldSize.setter
    def worldSize(self, arg0: typing.SupportsInt) -> None:
        ...


class Context:
    @staticmethod
    def Create(arg0: Config, arg1: collections.abc.Callable, arg2: collections.abc.Callable) -> Context:
        ...

    def __init__(self) -> None:
        ...


class ContextBase:
    def GetConfig(self) -> Config:
        ...

    def GetWorldSize(self) -> int:
        ...

    def IsValid(self) -> bool:
        ...

    def NodeId(self) -> int:
        ...

    def __init__(self) -> None:
        ...


class Div(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class DummyMode:
    """
    Members:
    
      NORMAL
    
      DUMMY
    """
    DUMMY: typing.ClassVar[DummyMode]  # value = <DummyMode.DUMMY: 1>
    NORMAL: typing.ClassVar[DummyMode]  # value = <DummyMode.NORMAL: 0>
    __members__: typing.ClassVar[
        dict[str, DummyMode]]  # value = {'NORMAL': <DummyMode.NORMAL: 0>, 'DUMMY': <DummyMode.DUMMY: 1>}

    def __eq__(self, other: typing.Any) -> bool:
        ...

    def __getstate__(self) -> int:
        ...

    def __hash__(self) -> int:
        ...

    def __index__(self) -> int:
        ...

    def __init__(self, value: typing.SupportsInt) -> None:
        ...

    def __int__(self) -> int:
        ...

    def __ne__(self, other: typing.Any) -> bool:
        ...

    def __repr__(self) -> str:
        ...

    def __setstate__(self, state: typing.SupportsInt) -> None:
        ...

    def __str__(self) -> str:
        ...

    @property
    def name(self) -> str:
        ...

    @property
    def value(self) -> int:
        ...


class Equal(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class Greater(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class GreaterEqual(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class Input:
    @staticmethod
    def Create() -> Input:
        ...

    def Fill(self, arg0: collections.abc.Sequence[str]) -> None:
        ...

    def Get(self) -> DG_TeeInput:
        ...

    def Set(self, arg0: DG_TeeInput) -> None:
        ...

    def Size(self) -> int:
        ...

    @typing.overload
    def __init__(self) -> None:
        ...

    @typing.overload
    def __init__(self, arg0: DG_TeeInput) -> None:
        ...


class Less(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class LessEqual(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class MakeShare(Arithmetic):
    def Run(self, arg0: Input, arg1: typing.SupportsInt, arg2: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class Max(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class Min(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class MpcShare:
    @staticmethod
    def Create() -> MpcShare:
        ...

    def Get(self) -> DG_MpcShare:
        ...

    def Set(self, arg0: DG_MpcShare) -> None:
        ...

    def Size(self) -> int:
        ...

    def Type(self) -> ShareType:
        ...

    @typing.overload
    def __init__(self) -> None:
        ...

    @typing.overload
    def __init__(self, arg0: DG_MpcShare) -> None:
        ...


class MpcShareSet:
    @staticmethod
    def Create(arg0: collections.abc.Sequence[MpcShare]) -> MpcShareSet:
        ...

    def Get(self) -> DG_MpcShareSet:
        ...

    def __init__(self) -> None:
        ...


class Mul(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class NoEqual(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class OperatorBase:
    def GetType(self) -> AlgorithmsType:
        ...


class Pir(OperatorBase):
    def ClientQuery(self, arg0: Input, arg1: Input, arg2: DummyMode) -> int:
        ...

    def ServerAnswer(self) -> int:
        ...

    def ServerPreProcess(self, arg0: DG_PairList) -> int:
        ...

    def __init__(self) -> None:
        ...


class Psi(OperatorBase):
    def Run(self, arg0: Input, arg1: Input, arg2: TeeMode) -> int:
        ...

    def __init__(self) -> None:
        ...


class RevealShare(Arithmetic):
    def Run(self, arg0: MpcShare, arg1: Input) -> int:
        ...

    def __init__(self) -> None:
        ...


class ShareType:
    """
    Members:
    
      FIX_POINT
    
      NON_FIX_POINT
    """
    FIX_POINT: typing.ClassVar[ShareType]  # value = <ShareType.FIX_POINT: 0>
    NON_FIX_POINT: typing.ClassVar[ShareType]  # value = <ShareType.NON_FIX_POINT: 1>
    __members__: typing.ClassVar[dict[
        str, ShareType]]  # value = {'FIX_POINT': <ShareType.FIX_POINT: 0>, 'NON_FIX_POINT': <ShareType.NON_FIX_POINT: 1>}

    def __eq__(self, other: typing.Any) -> bool:
        ...

    def __getstate__(self) -> int:
        ...

    def __hash__(self) -> int:
        ...

    def __index__(self) -> int:
        ...

    def __init__(self, value: typing.SupportsInt) -> None:
        ...

    def __int__(self) -> int:
        ...

    def __ne__(self, other: typing.Any) -> bool:
        ...

    def __repr__(self) -> str:
        ...

    def __setstate__(self, state: typing.SupportsInt) -> None:
        ...

    def __str__(self) -> str:
        ...

    @property
    def name(self) -> str:
        ...

    @property
    def value(self) -> int:
        ...


class Sub(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class Sum(Arithmetic):
    def Run(self, arg0: MpcShareSet, arg1: MpcShare) -> int:
        ...

    def __init__(self) -> None:
        ...


class TeeMode:
    """
    Members:
    
      OUTPUT_INDEX
    
      OUTPUT_STRING
    """
    OUTPUT_INDEX: typing.ClassVar[TeeMode]  # value = <TeeMode.OUTPUT_INDEX: 1>
    OUTPUT_STRING: typing.ClassVar[TeeMode]  # value = <TeeMode.OUTPUT_STRING: 0>
    __members__: typing.ClassVar[dict[
        str, TeeMode]]  # value = {'OUTPUT_INDEX': <TeeMode.OUTPUT_INDEX: 1>, 'OUTPUT_STRING': <TeeMode.OUTPUT_STRING: 0>}

    def __eq__(self, other: typing.Any) -> bool:
        ...

    def __getstate__(self) -> int:
        ...

    def __hash__(self) -> int:
        ...

    def __index__(self) -> int:
        ...

    def __init__(self, value: typing.SupportsInt) -> None:
        ...

    def __int__(self) -> int:
        ...

    def __ne__(self, other: typing.Any) -> bool:
        ...

    def __repr__(self) -> str:
        ...

    def __setstate__(self, state: typing.SupportsInt) -> None:
        ...

    def __str__(self) -> str:
        ...

    @property
    def name(self) -> str:
        ...

    @property
    def value(self) -> int:
        ...


class TeeNodeInfo:
    def __init__(self) -> None:
        ...

    @property
    def nodeId(self) -> int:
        ...

    @nodeId.setter
    def nodeId(self, arg0: typing.SupportsInt) -> None:
        ...


def BuildDgString(arg0: collections.abc.Sequence[str]) -> typing.Any:
    ...


def IsOperatorRegistered(arg0: AlgorithmsType) -> bool:
    ...


def RegisterAllOps() -> None:
    ...


def ReleaseMpcShare(arg0: DG_MpcShare) -> None:
    ...


def ReleaseOutput(arg0: DG_TeeInput) -> None:
    ...


def create_operator(arg0: ContextBase, arg1: AlgorithmsType) -> OperatorBase:
    ...


ADD: AlgorithmsType  # value = <AlgorithmsType.ADD: 5>
AVG: AlgorithmsType  # value = <AlgorithmsType.AVG: 16>
DIV: AlgorithmsType  # value = <AlgorithmsType.DIV: 8>
DUMMY: DummyMode  # value = <DummyMode.DUMMY: 1>
EQUAL: AlgorithmsType  # value = <AlgorithmsType.EQUAL: 13>
FIX_POINT: ShareType  # value = <ShareType.FIX_POINT: 0>
GREATER: AlgorithmsType  # value = <AlgorithmsType.GREATER: 11>
GREATER_EQUAL: AlgorithmsType  # value = <AlgorithmsType.GREATER_EQUAL: 12>
LESS: AlgorithmsType  # value = <AlgorithmsType.LESS: 9>
LESS_EQUAL: AlgorithmsType  # value = <AlgorithmsType.LESS_EQUAL: 10>
MAKE_SHARE: AlgorithmsType  # value = <AlgorithmsType.MAKE_SHARE: 3>
MAX: AlgorithmsType  # value = <AlgorithmsType.MAX: 17>
MIN: AlgorithmsType  # value = <AlgorithmsType.MIN: 18>
MUL: AlgorithmsType  # value = <AlgorithmsType.MUL: 7>
NON_FIX_POINT: ShareType  # value = <ShareType.NON_FIX_POINT: 1>
NORMAL: DummyMode  # value = <DummyMode.NORMAL: 0>
NO_EQUAL: AlgorithmsType  # value = <AlgorithmsType.NO_EQUAL: 14>
OUTPUT_INDEX: TeeMode  # value = <TeeMode.OUTPUT_INDEX: 1>
OUTPUT_STRING: TeeMode  # value = <TeeMode.OUTPUT_STRING: 0>
PIR: AlgorithmsType  # value = <AlgorithmsType.PIR: 1>
PSI: AlgorithmsType  # value = <AlgorithmsType.PSI: 0>
REVEAL_SHARE: AlgorithmsType  # value = <AlgorithmsType.REVEAL_SHARE: 4>
SUB: AlgorithmsType  # value = <AlgorithmsType.SUB: 6>
SUM: AlgorithmsType  # value = <AlgorithmsType.SUM: 15>
Output = Input
