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

#include "kcal/operator/kcal_psi.h"
#include "kcal/utils/node_info_helper.h"

namespace kcal {

Psi::Psi(std::shared_ptr<Context> context) : context_(std::move(context)) {}

std::unique_ptr<Psi> Psi::Create(std::shared_ptr<Context> context)
{
    auto op = std::make_unique<Psi>(std::move(context));

    op->opts_ = std::make_unique<DG_PrivateSet_Opts>();
    *op->opts_ = DG_InitPsiOpts();

    int ret = op->Initialize();
    if (ret != 0) {
        return nullptr;
    }

    return op;
}

int Psi::Initialize()
{
    if (!context_ || !context_->IsValid()) {
        return DG_ERR_MPC_INVALID_PARAM;
    }

    dgTeeCtx_ = context_->GetTeeCtx(KCAL_AlgorithmsType::PSI);
    if (!dgTeeCtx_) {
        return DG_ERR_MPC_INVALID_PARAM;
    }

    initialized_ = true;
    return DG_SUCCESS;
}

Psi::~Psi()
{
    if (initialized_) {
        dgTeeCtx_ = nullptr;
        context_.reset();
        initialized_ = false;
    }
}

int Psi::Run(const io::Input &input, io::Output &output, DG_TeeMode outputMode)
{
    if (!initialized_ || !dgTeeCtx_) {
        return DG_ERR_MPC_INVALID_PARAM;
    }

    if (!input.Valid()) {
        return DG_ERR_MPC_INVALID_PARAM;
    }

    DG_TeeOutput *rawOutput = nullptr;
    int ret = opts_->calculate(dgTeeCtx_, PSI, input.Get(), &rawOutput, outputMode);
    if (ret == DG_SUCCESS) {
        output.Reset(rawOutput);
    }
    return ret;
}

} // namespace kcal
