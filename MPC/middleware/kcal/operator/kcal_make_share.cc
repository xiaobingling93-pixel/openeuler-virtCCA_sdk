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

#include "kcal/operator/kcal_make_share.h"

namespace kcal {

int MakeShare::GetTeeCtx(const std::shared_ptr<Context> &context)
{
    return Arithmetic::GetTeeCtx(context);
}

int MakeShare::Run(io::KcalInput &input, int isRecvShare, io::KcalMpcShare *&share)
{
    return opts_->makeShare(dgTeeCtx_, isRecvShare, input.Get(), &share->Get());
}

} // namespace kcal
