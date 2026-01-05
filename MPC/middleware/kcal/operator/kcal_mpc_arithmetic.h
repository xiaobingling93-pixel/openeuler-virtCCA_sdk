/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024. All rights reserved.
 * virtCCA_sdk is licensed under the Mulan PSL v2.
 * You can use this software according to the terms and conditions of the Mulan PSL v2.
 * You may obtain a copy of Mulan PSL v2 at:
 *     http://license.coscl.org.cn/MulanPSL2
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
 * PURPOSE.
 * See the Mulan PSL v2 for more details.
 */

#ifndef KCAL_MIDDLEWARE_KCAL_MPC_OPERATOR_BASE_H
#define KCAL_MIDDLEWARE_KCAL_MPC_OPERATOR_BASE_H

#include "kcal/core/mpc_operator_base.h"
#include "kcal/enumeration/kcal_enum.h"
#include "kcal/utils/io.h"

namespace kcal {

class Add : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::ADD; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class Sub : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::SUB; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class Mul : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::MUL; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class Div : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::DIV; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class Less : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::LESS; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class LessEqual : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::LESS_EQUAL; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class Greater : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::GREATER; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class GreaterEqual : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::GREATER_EQUAL; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class Equal : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::EQUAL; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class NoEqual : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::NO_EQUAL; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class Avg : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::AVG; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class Max : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::MAX; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class Min : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::MIN; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

class Sum : public MpcOperatorBase {
public:
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::SUM; }

    int Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare) override;
};

} // namespace kcal

#endif // KCAL_MIDDLEWARE_KCAL_MPC_OPERATOR_BASE_H
