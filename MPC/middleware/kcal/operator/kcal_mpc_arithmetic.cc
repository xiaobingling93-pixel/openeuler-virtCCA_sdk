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

#include "kcal/operator/kcal_mpc_arithmetic.h"

namespace kcal {

// ===========================
//   Add operator impl
// ===========================

int Add::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, ADD, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Sub operator impl
// ===========================

int Sub::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, SUB, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Mul operator impl
// ===========================

int Mul::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, MULTI, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Div operator impl
// ===========================

int Div::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, DIV, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Less operator impl
// ===========================

int Less::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, LT, shareSet.Get(), &outShare->Get());
}

// ===========================
//   LessEqual operator impl
// ===========================

int LessEqual::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, LT_EQ, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Greater operator impl
// ===========================

int Greater::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, GT, shareSet.Get(), &outShare->Get());
}

// ===========================
//   GreaterEqual operator impl
// ===========================

int GreaterEqual::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, GT_EQ, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Equal operator impl
// ===========================

int Equal::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, EQ, shareSet.Get(), &outShare->Get());
}

// ===========================
//   NoEqual operator impl
// ===========================

int NoEqual::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    return opts_->calculate(dgTeeCtx_, NEQ, shareSet.Get(), &outShare->Get());
}

// ===========================
//   Avg operator impl
// ===========================

int Avg::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    int ret = opts_->calculate(dgTeeCtx_, AVG, shareSet.Get(), &outShare->Get());
    if (ret != DG_SUCCESS) {
        return ret;
    }
    outShare->Get()->size = 1;
    return DG_SUCCESS;
}

// ===========================
//   Max operator impl
// ===========================

int Max::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    int ret = opts_->calculate(dgTeeCtx_, MAX, shareSet.Get(), &outShare->Get());
    if (ret == DG_SUCCESS) {
        outShare->Get()->size = 1;
    }
    return ret;
}

int Min::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    int ret = opts_->calculate(dgTeeCtx_, MIN, shareSet.Get(), &outShare->Get());
    if (ret == DG_SUCCESS) {
        outShare->Get()->size = 1;
    }
    return ret;
}

// ===========================
//   Sum operator impl
// ===========================

int Sum::Run(const io::MpcShareSet &shareSet, io::MpcShare *&outShare)
{
    int ret = opts_->calculate(dgTeeCtx_, SUM, shareSet.Get(), &outShare->Get());
    if (ret != DG_SUCCESS) {
        return ret;
    }
    outShare->Get()->size = 1;
    return DG_SUCCESS;
}

} // namespace kcal
