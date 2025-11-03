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

#ifndef KCAL_MIDDLEWARE_KCAL_ARITHMETIC_H
#define KCAL_MIDDLEWARE_KCAL_ARITHMETIC_H

#include <memory>
#include "kcal/core/operator_base.h"
#include "kcal/core/context.h"
#include "kcal/enumeration/kcal_enum.h"
#include "kcal/utils/io.h"

namespace kcal {

class Arithmetic : public OperatorBase {
public:
    Arithmetic();
    ~Arithmetic() override;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::ARITHMETIC; }

protected:
    DG_TeeCtx *dgTeeCtx_ = nullptr;
    std::unique_ptr<DG_Arithmetic_Opts> opts_;
};

class Add : public Arithmetic {
public:
    Add() = default;
    ~Add() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::ADD; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

class Sub : public Arithmetic {
public:
    Sub() = default;
    ~Sub() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::SUB; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

class Mul : public Arithmetic {
public:
    Mul() = default;
    ~Mul() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::MUL; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

class Div : public Arithmetic {
public:
    Div() = default;
    ~Div() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::DIV; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

class Less : public Arithmetic {
public:
    Less() = default;
    ~Less() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::LESS; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

class LessEqual : public Arithmetic {
public:
    LessEqual() = default;
    ~LessEqual() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::LESS_EQUAL; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

class Greater : public Arithmetic {
public:
    Greater() = default;
    ~Greater() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::GREATER; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

class GreaterEqual : public Arithmetic {
public:
    GreaterEqual() = default;
    ~GreaterEqual() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::GREATER_EQUAL; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

class Equal : public Arithmetic {
public:
    Equal() = default;
    ~Equal() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::EQUAL; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

class NoEqual : public Arithmetic {
public:
    NoEqual() = default;
    ~NoEqual() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::NO_EQUAL; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

} // namespace kcal

#endif // KCAL_MIDDLEWARE_KCAL_ARITHMETIC_H
