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

#include "kcal/operator/kcal_maximum.h"

namespace kcal {

// ===========================
//   Max operator impl
// ===========================

int Max::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int Max::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    int ret = opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::MAX, shareSet.Get(), &outShare->Get());
    if (ret == DG_SUCCESS) {
        outShare->Get()->size = 1;
    }
    return ret;
}

// ===========================
//   Min operator impl
// ===========================

int Min::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int Min::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    int ret = opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::MIN, shareSet.Get(), &outShare->Get());
    if (ret == DG_SUCCESS) {
        outShare->Get()->size = 1;
    }
    return ret;
}

} // namespace kcal
