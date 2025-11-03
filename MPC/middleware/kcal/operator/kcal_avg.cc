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

#include "kcal/operator/kcal_avg.h"

namespace kcal {

int Avg::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int Avg::Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare)
{
    int ret = opts_->calculate(dgTeeCtx_, DG_AlgorithmsType::AVG, shareSet.Get(), &outShare->Get());
    if (ret != DG_SUCCESS) {
        return ret;
    }
    outShare->Get()->size = 1;
    return DG_SUCCESS;
}

} // namespace kcal
