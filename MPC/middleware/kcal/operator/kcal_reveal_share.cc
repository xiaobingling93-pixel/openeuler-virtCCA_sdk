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

#include "kcal/operator/kcal_reveal_share.h"

namespace kcal {

std::unique_ptr<RevealShare> RevealShare::Create(std::shared_ptr<Context> context)
{
    auto op = std::make_unique<RevealShare>(std::move(context));

    op->opts_ = std::make_unique<DG_Arithmetic_Opts>();
    *op->opts_ = DG_InitArithmeticOpts();

    if (op->Initialize() != 0) {
        return nullptr;
    }

    return op;
}

int RevealShare::Initialize()
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

int RevealShare::Run(const io::MpcShare *share, io::Output &output)
{
    DG_TeeOutput *rawOutput = nullptr;
    int ret = opts_->revealShare(dgTeeCtx_, share->Get(), &rawOutput);
    if (ret == DG_SUCCESS) {
        output.Reset(rawOutput);
    }
    return ret;
}

} // namespace kcal
