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

std::unique_ptr<MakeShare> MakeShare::Create(std::shared_ptr<Context> context)
{
    auto op = std::make_unique<MakeShare>(std::move(context));

    op->opts_ = std::make_unique<DG_Arithmetic_Opts>();
    *op->opts_ = DG_InitArithmeticOpts();

    if (op->Initialize() != 0) {
        return nullptr;
    }

    return op;
}

int MakeShare::Initialize()
{
    if (!context_ || !context_->IsValid()) {
        return DG_ERR_MPC_INVALID_PARAM;
    }

    dgTeeCtx_ = context_->GetTeeCtx(KCAL_AlgorithmsType::ARITHMETIC);
    if (!dgTeeCtx_) {
        return DG_ERR_MPC_INVALID_PARAM;
    }

    initialized_ = true;
    return DG_SUCCESS;
}

int MakeShare::Run(const io::Input &input, int isRecvShare, io::MpcShare *share)
{
    return opts_->makeShare(dgTeeCtx_, isRecvShare, input.Get(), &share->Get());
}

} // namespace kcal
