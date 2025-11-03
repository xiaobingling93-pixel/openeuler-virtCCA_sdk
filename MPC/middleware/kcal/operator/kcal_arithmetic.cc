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

#include "kcal/operator/kcal_arithmetic.h"

namespace kcal {

Arithmetic::Arithmetic()
{
    opts_ = std::make_unique<DG_Arithmetic_Opts>();
    *opts_ = DG_InitArithmeticOpts();
}

Arithmetic::~Arithmetic()
{
    if (initialized_) {
        dgTeeCtx_ = nullptr;
        context_.reset();
        initialized_ = false;
    }
}

int Arithmetic::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    dgTeeCtx_ = context->GetTeeCtx(KCAL_AlgorithmsType::ARITHMETIC);
    if (!dgTeeCtx_) {
        return DG_ERR_MPC_INVALID_PARAM;
    }
    return DG_SUCCESS;
}

// ===========================
//   Add operator impl
// ===========================

int Add::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int Add::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::ADD, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Sub operator impl
// ===========================

int Sub::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int Sub::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::SUB, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Mul operator impl
// ===========================

int Mul::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int Mul::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::MULTI, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Div operator impl
// ===========================

int Div::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int Div::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::DIV, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Less operator impl
// ===========================

int Less::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int Less::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::LT, shareSet.Get(), &outShare->Get());
}

// ===========================
//   LessEqual operator impl
// ===========================

int LessEqual::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int LessEqual::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::LT_EQ, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Greater operator impl
// ===========================

int Greater::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int Greater::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::GT, shareSet.Get(), &outShare->Get());
}

// ===========================
//   GreaterEqual operator impl
// ===========================

int GreaterEqual::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int GreaterEqual::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::GT_EQ, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Equal operator impl
// ===========================

int Equal::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int Equal::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::EQ, shareSet.Get(), &outShare->Get());
}

// ===========================
//   NoEqual operator impl
// ===========================

int NoEqual::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int NoEqual::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::NEQ, shareSet.Get(), &outShare->Get());
}

} // namespace kcal
